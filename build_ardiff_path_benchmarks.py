#!/usr/bin/env python3
"""Build a path-matching benchmark from ARDiff comparison cases.

The script discovers symbolic_oldV/symbolic_newV cases, optionally compiles and
runs symbolic execution, then emits a run_evaluation.py-compatible manifest with
Naive, VeriBin-style, and FMCAD-style ranking files.
"""

from __future__ import annotations

import argparse
import ast
import csv
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SYMBOLIC_SRC = ROOT / "src"
sys.path.insert(0, str(SYMBOLIC_SRC))
sys.path.insert(0, str(ROOT / "scripts"))

from symbolic_analysis.analysis.path_constraint_features import (  # noqa: E402
    FEATURE_NAMES,
    FEATURE_RANGES,
    FEATURE_SCHEMA,
    cosine_with_validity,
    extract_feature_record,
    normalize_features,
)
from symbolic_analysis.analysis.hybrid_path_matching import (  # noqa: E402
    HybridConfig,
    hybrid_rank_paths,
)
from symbolic_analysis.analysis.basic_block_mapping import build_structural_block_map  # noqa: E402
from symbolic_analysis.analysis.bindiff_backend import (  # noqa: E402
    build_bindiff_mapping,
)
from symbolic_analysis.profile import (  # noqa: E402
    FULL_INPUT_SPACE,
    LOOP_BOUND,
    MAX_PATHS,
    PAPER_PROFILE_ID,
    SEMANTIC_CONTRACT,
    profile_for_input_domains,
)
from generate_path_truth import compute_pair_truth  # noqa: E402


PATH_RE = re.compile(r"^(?P<prefix>symbolic_(?:old|new)V)_path_(?P<idx>\d+)\.txt$")
_SYMBOLIC_EXEC_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


@dataclass(frozen=True)
class Case:
    case_dir: Path
    rel: Path
    subset: str
    program: str
    truth_label: str
    equivalent: bool


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ARDiff path-matching benchmark artifacts.")
    parser.add_argument(
        "--benchmarks",
        type=Path,
        default=Path("experiments/ardiff_comparison/benchmarks"),
    )
    parser.add_argument(
        "--int-min",
        type=int,
        default=None,
        help="Lower signed integer bound; omit both integer bounds for the full domain.",
    )
    parser.add_argument(
        "--int-max",
        type=int,
        default=None,
        help="Upper signed integer bound; omit both integer bounds for the full domain.",
    )
    parser.add_argument(
        "--case-domains",
        type=Path,
        help=(
            "Optional CSV of per-family input domains with scope/int_min/int_max/"
            "float_min/float_max columns. The 'default' row is the fallback."
        ),
    )
    parser.add_argument(
        "--float-min",
        type=float,
        default=None,
        help="Lower floating-point bound; omit both floating bounds for the full domain.",
    )
    parser.add_argument(
        "--float-max",
        type=float,
        default=None,
        help="Upper floating-point bound; omit both floating bounds for the full domain.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("benchmarks/ardiff_paths"))
    parser.add_argument("--eval-output-dir", type=Path, default=Path("evaluation_results_ardiff"))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--max-paths",
        type=int,
        default=MAX_PATHS,
        help="Reject path-exploding binaries instead of materializing an unbounded artifact set.",
    )
    parser.add_argument(
        "--concrete-global-initializers",
        action="store_true",
        help=(
            "Preserve ELF data/BSS initial values instead of symbolizing global "
            "objects as additional inputs."
        ),
    )
    parser.add_argument(
        "--loop-bound",
        type=int,
        default=LOOP_BOUND,
        help="Maximum completed iterations per symbolic loop.",
    )
    parser.add_argument(
        "--profile-id",
        default=PAPER_PROFILE_ID,
        help="Auditable symbolic-execution profile identifier.",
    )
    parser.add_argument(
        "--ranking-candidates",
        type=int,
        default=None,
        help="Retain only the highest-ranked N candidates per source path.",
    )
    parser.add_argument(
        "--skip-control-rankings",
        action="store_true",
        help="Do not materialize the optional Naive and VeriBin control rankings.",
    )
    parser.add_argument(
        "--optimization",
        choices=("O0", "O1", "O2", "O3"),
        default="O3",
        help="Compiler optimization level (paper main configuration: O3).",
    )
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument(
        "--bindiff-mode",
        choices=("auto", "structural", "off"),
        default="auto",
        help="Use real BinDiff, the explicit structural fallback, or feature-only.",
    )
    parser.add_argument("--bindiff-binary", default=None)
    parser.add_argument("--ghidra-headless", default=None)
    parser.add_argument("--java-home", default=None)
    parser.add_argument("--bindiff-output-dir", type=Path, default=None)
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Only run cases whose POSIX relative path contains one of these strings.",
    )
    parser.add_argument(
        "--family",
        action="append",
        default=[],
        help="Only run cases whose first relative path component exactly matches.",
    )
    parser.add_argument(
        "--exclude-family",
        action="append",
        default=[],
        help="Exclude cases whose first relative path component exactly matches.",
    )
    parser.add_argument(
        "--exclude-case",
        action="append",
        default=[],
        help="Exclude cases whose POSIX relative path contains one of these strings.",
    )
    parser.add_argument(
        "--case-manifest",
        type=Path,
        help="CSV manifest whose source_case column selects an exact case set.",
    )
    parser.add_argument("--force-symbolic-exec", action="store_true")
    parser.add_argument("--skip-symbolic-exec", action="store_true")
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument("--skip-semantic-truth", action="store_true")
    parser.add_argument(
        "--skip-ranking-truth",
        action="store_true",
        help=(
            "Defer independent SAT-overlap truth to "
            "scripts/annotate_path_truth.py."
        ),
    )
    parser.add_argument("--python", default=os.environ.get("PYTHON", "python3"))
    args = parser.parse_args()
    if args.case_domains is not None:
        args.case_domains = load_case_domains(args.case_domains)
    else:
        args.case_domains = {}

    explicit_benchmarks = any(
        arg == "--benchmarks" or arg.startswith("--benchmarks=") for arg in sys.argv[1:]
    )
    if (
        not explicit_benchmarks
        and "typed" in str(args.out_dir).lower()
        and args.benchmarks == Path("experiments/ardiff_comparison/benchmarks")
    ):
        args.benchmarks = Path("experiments/ardiff_comparison/benchmarks_typed")

    benchmarks = (ROOT / args.benchmarks).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    eval_output_dir = (ROOT / args.eval_output_dir).resolve()
    args.python = resolve_python_command(args.python)
    if not args.skip_symbolic_exec:
        verify_symbolic_python(args.python)

    cases = discover_cases(benchmarks)
    if args.family:
        families = set(args.family)
        cases = [case for case in cases if case.rel.parts[0] in families]
    if args.exclude_family:
        excluded_families = set(args.exclude_family)
        cases = [case for case in cases if case.rel.parts[0] not in excluded_families]
    if args.case:
        cases = [
            case
            for case in cases
            if any(selector in case.rel.as_posix() for selector in args.case)
        ]
    if args.exclude_case:
        cases = [
            case
            for case in cases
            if not any(selector in case.rel.as_posix() for selector in args.exclude_case)
        ]
    if args.case_manifest:
        with args.case_manifest.open(encoding="utf-8", newline="") as stream:
            selected = set()
            for row in csv.DictReader(stream):
                raw = (row.get("source_case") or row.get("osf_source_case") or "").replace(
                    "\\", "/"
                )
                if not raw:
                    continue
                if "/benchmarks/" in raw:
                    raw = raw.split("/benchmarks/", 1)[1]
                selected.add(raw.lower())
        cases = [case for case in cases if case.rel.as_posix().lower() in selected]
    if args.max_cases is not None:
        cases = cases[: args.max_cases]
    if not cases:
        raise SystemExit(f"No ARDiff cases found under {benchmarks}")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, Any]] = []
    truth_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case.rel}")
        try:
            row, truth = process_case(case, out_dir, args)
            if row:
                manifest_rows.append(row)
                truth_rows.append(truth)
        except Exception as exc:  # noqa: BLE001
            failures.append({"case": str(case.rel), "error": str(exc)})
            print(f"  failed: {exc}")
        write_incremental_snapshots(
            out_dir,
            manifest_rows,
            truth_rows,
            failures,
            cases_discovered=len(cases),
            cases_processed=i,
        )

    (out_dir / "manifest.json").write_text(
        json.dumps({"pairs": manifest_rows, "failures": failures}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "groundtruth.json").write_text(
        json.dumps({"pairs": truth_rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    ground_truth_path = out_dir / "groundtruth.json"
    (out_dir / "generation_summary.json").write_text(
        json.dumps(
            {
                "cases_discovered": len(cases),
                "cases_generated": len(manifest_rows),
                "failures": failures,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(manifest_rows)} generated cases to {out_dir}")
    if failures:
        print(f"Failures: {len(failures)}; see {out_dir / 'generation_summary.json'}")

    if manifest_rows and not args.skip_evaluation:
        cmd = [
            args.python,
            str(ROOT / "run_evaluation.py"),
            "--benchmarks",
            str(out_dir),
            "--ground-truth",
            str(ground_truth_path),
            "--output-dir",
            str(eval_output_dir),
            "--python",
            args.python,
            "--execute",
            "--timeout",
            "86400",
            "--require-manifest",
            "--smt-timeout-ms",
            "60000",
        ]
        print("Running evaluation:")
        print("  " + " ".join(cmd))
        subprocess.run(cmd, cwd=str(ROOT), check=False)

    return 0


def write_incremental_snapshots(
    out_dir: Path,
    manifest_rows: list[dict[str, Any]],
    truth_rows: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    *,
    cases_discovered: int,
    cases_processed: int,
) -> None:
    """Persist progress after every case so an interrupted run remains recoverable."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "manifest.partial.json": {
            "pairs": manifest_rows,
            "failures": failures,
            "cases_discovered": cases_discovered,
            "cases_processed": cases_processed,
        },
        "groundtruth.partial.json": {"pairs": truth_rows},
        "generation_summary.partial.json": {
            "cases_discovered": cases_discovered,
            "cases_processed": cases_processed,
            "cases_generated": len(manifest_rows),
            "failures": failures,
        },
    }
    for name, payload in payloads.items():
        target = out_dir / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)


def discover_cases(root: Path) -> list[Case]:
    cases: list[Case] = []
    for old_src in sorted(root.rglob("symbolic_oldV.c")):
        case_dir = old_src.parent
        if not (case_dir / "symbolic_newV.c").is_file():
            continue
        rel = case_dir.relative_to(root)
        if "instrumented" in {part.lower() for part in rel.parts}:
            continue
        parsed = parse_case_rel(rel)
        if parsed is None:
            continue
        subset, program, truth_label, equivalent = parsed
        cases.append(Case(case_dir, rel, subset, program, truth_label, equivalent))
    return cases


def resolve_python_command(raw: str) -> str:
    if "/" not in raw and "\\" not in raw:
        return raw
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.absolute()
    if not path.exists():
        raise SystemExit(
            f"Python interpreter not found: {path}\n"
            "Pass a working interpreter with angr installed, e.g. --python /abs/path/to/python."
        )
    return str(path)


def verify_symbolic_python(python_cmd: str) -> None:
    completed = subprocess.run(
        [python_cmd, "-c", "import angr, claripy; print('angr ok')"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "The selected Python cannot import angr/claripy.\n"
            f"Python: {python_cmd}\n"
            f"stderr:\n{completed.stderr.strip()}\n"
            "Install/fix angr first, or run with --skip-symbolic-exec if path files already exist."
        )


def parse_case_rel(rel: Path) -> tuple[str, str, str, bool] | None:
    parts = rel.parts
    if len(parts) < 3:
        return None
    if parts[0].lower() == "moddiff":
        truth = parts[1]
        func = "/".join(parts[2:])
        program = f"{func}_{truth}"
        return "ModDiff", program, truth, truth.lower() == "eq"
    truth = parts[-1]
    subset = parts[0]
    func = "/".join(parts[1:-1])
    program = f"{func}_{truth}"
    return subset, program, truth, truth.lower() == "eq"


def load_case_domains(path: Path) -> dict[str, dict[str, int | float | None]]:
    domains: dict[str, dict[str, int | float | None]] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            scope = (row.get("scope") or "").strip().lower()
            if not scope:
                continue
            raw_int_min = (row.get("int_min") or "").strip()
            raw_int_max = (row.get("int_max") or "").strip()
            raw_float_min = (row.get("float_min") or "").strip()
            raw_float_max = (row.get("float_max") or "").strip()
            domains[scope] = {
                "int_min": int(raw_int_min) if raw_int_min else None,
                "int_max": int(raw_int_max) if raw_int_max else None,
                "float_min": float(raw_float_min) if raw_float_min else None,
                "float_max": float(raw_float_max) if raw_float_max else None,
            }
    return domains


def case_domain_args(args: argparse.Namespace, subset: str) -> argparse.Namespace:
    domains = getattr(args, "case_domains", {}) or {}
    domain = domains.get(subset.lower()) or domains.get("default")
    if not domain:
        return args
    resolved = argparse.Namespace(**vars(args))
    for key, value in domain.items():
        setattr(resolved, key, value)
    return resolved


def process_case(case: Case, out_dir: Path, args: argparse.Namespace) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    args = case_domain_args(args, case.subset)
    case_out = out_dir / "cases" / case.rel
    bin_out = case_out / "bin"
    paths_out = case_out / "paths"
    rankings_out = out_dir / "rankings" / case.subset / sanitize(case.program)
    bin_out.mkdir(parents=True, exist_ok=True)
    paths_out.mkdir(parents=True, exist_ok=True)
    rankings_out.mkdir(parents=True, exist_ok=True)

    old_bin = ensure_binary(
        case.case_dir / "symbolic_oldV.c", bin_out / "symbolic_oldV", args.optimization
    )
    new_bin = ensure_binary(
        case.case_dir / "symbolic_newV.c", bin_out / "symbolic_newV", args.optimization
    )

    if not args.skip_symbolic_exec:
        maybe_run_symbolic_exec(old_bin, paths_out, "symbolic_oldV", args, case.case_dir / "symbolic_oldV.c")
        if not collect_path_files(paths_out, "symbolic_oldV"):
            raise RuntimeError("missing generated path files for oldV")
        maybe_run_symbolic_exec(new_bin, paths_out, "symbolic_newV", args, case.case_dir / "symbolic_newV.c")

    old_paths = collect_path_files(paths_out, "symbolic_oldV")
    new_paths = collect_path_files(paths_out, "symbolic_newV")
    if not old_paths or not new_paths:
        raise RuntimeError("missing generated path files for oldV or newV")

    pair_id = f"{case.subset}/{sanitize(case.program)}"
    old_ids = [p.stem for _, p in old_paths]
    new_ids = [p.stem for _, p in new_paths]
    if args.skip_ranking_truth:
        truth_pairs: dict[str, list[str]] = {}
        path_truth: dict[str, Any] = {
            "schema": "symbolicana.path_truth.v1",
            "semantics": "sat_input_overlap",
            "status": "pending",
            "queries": [],
        }
    else:
        path_truth_sets, path_truth = compute_pair_truth(
            [path for _index, path in old_paths],
            [path for _index, path in new_paths],
            timeout_ms=60_000,
        )
        truth_pairs = {
            query: sorted(targets)
            for query, targets in path_truth_sets.items()
        }

    naive_path = rankings_out / "naive.json"
    veribin_path = rankings_out / "veribin.json"
    fmcad_path = rankings_out / "fmcad.json"
    if not args.skip_control_rankings:
        naive_path.write_text(
            json.dumps(
                timed_ranking(build_naive_ranking, pair_id, old_paths, new_paths),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        veribin_path.write_text(
            json.dumps(
                timed_ranking(
                    build_veribin_ranking,
                    pair_id,
                    old_paths,
                    new_paths,
                    preprocess_seconds=veribin_preprocess_seconds(paths_out),
                ),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    trace_required = not args.skip_control_rankings or args.bindiff_mode != "off"
    old_traces = (
        [
            parse_execution_trace(path.read_text(encoding="utf-8", errors="replace"))
            for _, path in old_paths
        ]
        if trace_required
        else []
    )
    new_traces = (
        [
            parse_execution_trace(path.read_text(encoding="utf-8", errors="replace"))
            for _, path in new_paths
        ]
        if trace_required
        else []
    )
    bb_map_path = rankings_out / "basic_block_map.json"
    graph_state: dict[str, Any] = {
        "map": None,
        "metadata": {
            "status": "not_requested",
            "backend": "feature_only_not_requested",
        },
    }

    def graph_provider():
        if graph_state["map"] is not None:
            return graph_state["map"], graph_state["metadata"]
        if args.bindiff_mode == "off":
            graph_state["metadata"] = {
                "status": "disabled",
                "backend": "feature_only",
            }
            return None, graph_state["metadata"]
        started = time.perf_counter()
        if args.bindiff_mode == "structural":
            bb_map, stats = build_structural_block_map(
                old_bin, new_bin, old_traces, new_traces
            )
            graph_state["map"] = bb_map
            graph_state["metadata"] = {
                "status": "ok",
                "backend": "structural_fallback",
                "statistics": stats,
                "elapsed": time.perf_counter() - started,
            }
            return bb_map, graph_state["metadata"]
        bindiff_out = (
            args.bindiff_output_dir / case.rel
            if args.bindiff_output_dir is not None
            else out_dir / "bindiff" / case.rel
        )
        result = build_bindiff_mapping(
            old_bin,
            new_bin,
            bindiff_out,
            old_traces=old_traces,
            new_traces=new_traces,
            bindiff_binary=args.bindiff_binary,
            ghidra_headless=args.ghidra_headless,
            java_home=args.java_home,
        )
        if result.get("status") == "ok" and result.get("mapping") is not None:
            graph_state["map"] = result["mapping"]
            graph_state["metadata"] = {
                key: value for key, value in result.items() if key != "mapping"
            }
            return result["mapping"], graph_state["metadata"]
        bb_map, stats = build_structural_block_map(
            old_bin, new_bin, old_traces, new_traces
        )
        graph_state["map"] = bb_map
        graph_state["metadata"] = {
            **{key: value for key, value in result.items() if key != "mapping"},
            "status": "fallback",
            "backend": "structural_fallback",
            "fallback_reason": result.get("reason", "bindiff_unavailable"),
            "statistics": stats,
            "elapsed": time.perf_counter() - started,
        }
        return bb_map, graph_state["metadata"]

    experiment_profile = profile_for_input_domains(
        args.int_min,
        args.int_max,
        args.float_min,
        args.float_max,
        loop_bound=args.loop_bound,
        max_paths=args.max_paths,
        timeout_seconds=args.timeout,
        profile_id=args.profile_id,
    )
    experiment_profile["symbolic_execution"]["global_initialization"] = (
        "loaded_elf_memory"
        if args.concrete_global_initializers
        else "symbolic_first_16_words"
    )
    fmcad_path.write_text(
        json.dumps(
            timed_ranking(
                lambda pid, old, new: build_hybrid_fmcad_ranking(
                    pid,
                    old,
                    new,
                    graph_provider=graph_provider,
                    profile_id=args.profile_id,
                    profile=experiment_profile,
                    max_results_per_query=args.ranking_candidates,
                ),
                pair_id,
                old_paths,
                new_paths,
            ),
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    bb_map = graph_state["map"] or {}
    bb_map_path.write_text(
        json.dumps(
            {
                "matching_bb_addrs": {hex(k): hex(v) for k, v in bb_map.items()},
                "backend": graph_state["metadata"].get("backend", "feature_only"),
                "status": graph_state["metadata"].get("status", "not_requested"),
                "metadata": graph_state["metadata"],
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    base = {
        "pair_id": pair_id,
        "subset": case.subset,
        "program": sanitize(case.program),
        "ground_truth": case.equivalent,
        "original_path_count": len(old_paths),
        "patched_path_count": len(new_paths),
        "ground_truth_pairs": truth_pairs,
        "path_truth": path_truth,
    }
    truth = {**base, "path_truth": path_truth}
    (case_out / "path_truth.json").write_text(
        json.dumps(path_truth, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    row = {
        **base,
        "left": rel_to(old_paths[0][1], out_dir),
        "right": rel_to(new_paths[0][1], out_dir),
        "paths_dir": rel_to(paths_out, out_dir),
        "naive_ranking_path": (
            rel_to(naive_path, out_dir) if not args.skip_control_rankings else ""
        ),
        "veribin_ranking_path": (
            rel_to(veribin_path, out_dir) if not args.skip_control_rankings else ""
        ),
        "fmcad_ranking_path": rel_to(fmcad_path, out_dir),
        "basic_block_map_path": rel_to(bb_map_path, out_dir),
        "source_case": rel_to(case.case_dir, out_dir),
        "old_binary": rel_to(old_bin, out_dir),
        "new_binary": rel_to(new_bin, out_dir),
        "compiler": "gcc",
        "optimization": args.optimization,
        "symbolic_timeout_seconds": args.timeout,
        "loop_bound": args.loop_bound,
        "max_paths": args.max_paths,
        "input_ranges": {
            "integer": (
                [args.int_min, args.int_max]
                if args.int_min is not None or args.int_max is not None
                else FULL_INPUT_SPACE
            ),
            "floating_point": (
                [args.float_min, args.float_max]
                if args.float_min is not None or args.float_max is not None
                else FULL_INPUT_SPACE
            ),
        },
        "profile_id": args.profile_id,
        "profile": experiment_profile,
        "global_initialization": experiment_profile["symbolic_execution"][
            "global_initialization"
        ],
        "semantic_contract": dict(SEMANTIC_CONTRACT),
    }
    return row, truth


def ensure_binary(src: Path, out_bin: Path, optimization: str = "O3") -> Path:
    if (
        out_bin.is_file()
        and is_native_binary(out_bin)
        and out_bin.stat().st_mtime >= src.stat().st_mtime
    ):
        return out_bin
    gcc = find_gcc()
    cmd = [gcc, f"-{optimization}", "-g", "-o", str(out_bin), str(src), "-lm"]
    env = os.environ.copy()
    gcc_dir = str(Path(gcc).parent) if Path(gcc).is_file() else ""
    if gcc_dir:
        env["PATH"] = gcc_dir + os.pathsep + env.get("PATH", "")
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(f"{gcc} failed for {src}: {completed.stderr.strip()}")
    exe_out = out_bin.with_name(out_bin.name + ".exe")
    if exe_out.is_file() and not is_windows_pe(out_bin):
        shutil.move(str(exe_out), str(out_bin))
    return out_bin


def find_gcc() -> str:
    for candidate in (
        os.environ.get("CC"),
        shutil.which("gcc"),
        r"C:\msys64\mingw64\bin\gcc.exe",
        r"C:\msys64\ucrt64\bin\gcc.exe",
        r"C:\msys64\clang64\bin\gcc.exe",
    ):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return "gcc"


def is_windows_pe(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def is_native_binary(path: Path) -> bool:
    return is_windows_pe(path) if os.name == "nt" else is_elf(path)


def maybe_run_symbolic_exec(
    binary: Path,
    paths_out: Path,
    prefix: str,
    args: argparse.Namespace,
    source: Path | None = None,
) -> None:
    cache_material = source.read_bytes() if source and source.is_file() else binary.read_bytes()
    signature = extract_c_snippet_signature(source) if source else None
    loop_bound = getattr(args, "loop_bound", LOOP_BOUND)
    profile_id = getattr(args, "profile_id", PAPER_PROFILE_ID)
    concrete_global_initializers = bool(
        getattr(args, "concrete_global_initializers", False)
    )
    cache_key = (
        hashlib.sha256(cache_material).hexdigest(),
        args.optimization,
        args.timeout,
        args.max_paths,
        loop_bound,
        profile_id,
        args.int_min,
        args.int_max,
        args.float_min,
        args.float_max,
        concrete_global_initializers,
        signature,
    )
    failure_marker = paths_out / f"{prefix}_failure.json"
    exploration_manifest = paths_out / f"{prefix}_exploration.json"
    if not args.force_symbolic_exec and collect_path_files(paths_out, prefix):
        _SYMBOLIC_EXEC_CACHE[cache_key] = {
            "status": "success", "paths_dir": paths_out, "prefix": prefix
        }
        return
    if not args.force_symbolic_exec and failure_marker.is_file():
        failure = json.loads(failure_marker.read_text(encoding="utf-8"))
        _SYMBOLIC_EXEC_CACHE[cache_key] = {"status": "failure", "failure": failure}
        raise RuntimeError(failure.get("error", "cached symbolic-execution failure"))
    if not args.force_symbolic_exec and exploration_manifest.is_file():
        exploration = json.loads(exploration_manifest.read_text(encoding="utf-8"))
        if not exploration.get("complete", False):
            reasons = ", ".join(exploration.get("incomplete_reasons", [])) or "incomplete"
            error = f"symbolic execution incomplete for {binary}: {reasons}"
            failure = {"status": "incomplete", "error": error, "exploration": exploration}
            failure_marker.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
            raise RuntimeError(error)
    cached = None if args.force_symbolic_exec else _SYMBOLIC_EXEC_CACHE.get(cache_key)
    if cached and cached["status"] == "success":
        copy_cached_symbolic_artifacts(
            Path(cached["paths_dir"]), str(cached["prefix"]), paths_out, prefix
        )
        return
    for _, old_path in collect_path_files(paths_out, prefix):
        old_path.unlink()
    script = ROOT / "scripts" / "se_script_improved.py"
    cmd = [
        args.python,
        str(script),
        "--binary",
        str(binary),
        "--output-prefix",
        prefix,
        "--timeout",
        str(args.timeout),
        "--max-paths",
        str(args.max_paths),
        "--loop-bound",
        str(loop_bound),
        "--profile-id",
        profile_id,
        "--stream-path-output",
    ]
    for flag, value in (
        ("--int-min", args.int_min),
        ("--int-max", args.int_max),
        ("--float-min", args.float_min),
        ("--float-max", args.float_max),
    ):
        if value is not None:
            cmd.extend([flag, str(value)])
    if signature:
        cmd.extend(["--signature", signature])
    if concrete_global_initializers:
        cmd.append("--concrete-global-initializers")
    start = time.perf_counter()
    log = paths_out / f"{prefix}_symbolic_execution.log"
    timeout_seconds = args.timeout + 30
    with log.open("w", encoding="utf-8") as log_f:
        log_f.write("Command: " + " ".join(cmd) + "\n\n")
        log_f.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(paths_out),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            text=True,
        )
        while proc.poll() is None:
            if time.perf_counter() - start > timeout_seconds:
                proc.kill()
                proc.wait()
                elapsed = time.perf_counter() - start
                log_f.write(f"\n\nelapsed={elapsed:.6f}\nreturncode=timeout\n")
                error = f"symbolic execution timed out for {binary}; see {log}"
                failure = {"status": "timeout", "error": error, "elapsed": elapsed}
                failure_marker.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
                raise RuntimeError(error)
            time.sleep(0.25)
        elapsed = time.perf_counter() - start
        log_f.write(f"\n\nelapsed={elapsed:.6f}\nreturncode={proc.returncode}\n")
        returncode = proc.returncode
    if returncode != 0:
        error = f"symbolic execution failed for {binary}; see {log}"
        failure = {"status": "error", "error": error, "elapsed": elapsed}
        failure_marker.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(error)
    if not collect_path_files(paths_out, prefix):
        error = f"symbolic execution produced no complete paths for {binary}; see {log}"
        failure = {"status": "incomplete", "error": error, "elapsed": elapsed}
        if exploration_manifest.is_file():
            failure["exploration"] = json.loads(exploration_manifest.read_text(encoding="utf-8"))
        failure_marker.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(error)
    _SYMBOLIC_EXEC_CACHE[cache_key] = {
        "status": "success", "paths_dir": paths_out, "prefix": prefix
    }


def copy_cached_symbolic_artifacts(source_dir: Path, source_prefix: str, target_dir: Path, target_prefix: str) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.glob(f"{source_prefix}_path_*.txt"):
        suffix = source_path.name[len(source_prefix):]
        shutil.copy2(source_path, target_dir / f"{target_prefix}{suffix}")
    for suffix in ("_exploration.json", "_symbolic_execution.log"):
        source_path = source_dir / f"{source_prefix}{suffix}"
        if source_path.is_file():
            shutil.copy2(source_path, target_dir / f"{target_prefix}{suffix}")


def extract_c_snippet_signature(source: Path | None) -> str | None:
    if not source or not source.is_file():
        return None
    text = source.read_text(encoding="utf-8", errors="replace")
    scalar_types = ("bool", "char", "short", "int", "long", "double", "float", "void")
    type_pattern = "|".join(sorted(scalar_types, key=len, reverse=True))
    match = re.search(
        rf"\b(?:const\s+)?(?P<ret>{type_pattern})\s+snippet\s*\((?P<args>[^)]*)\)",
        text,
    )
    if not match:
        return None
    arg_types = []
    for raw_arg in match.group("args").split(","):
        raw_arg = raw_arg.strip()
        if not raw_arg or raw_arg == "void":
            continue
        parts = raw_arg.replace("*", " * ").split()
        arg_type = next((token for token in parts if token in scalar_types), None)
        if arg_type is None or arg_type == "void":
            raise ValueError(f"unsupported snippet argument declaration: {raw_arg}")
        arg_types.append(arg_type)
    return f"{match.group('ret')}({','.join(arg_types)})"


def collect_path_files(paths_dir: Path, prefix: str) -> list[tuple[int, Path]]:
    out = []
    for path in paths_dir.glob(f"{prefix}_path_*.txt"):
        match = PATH_RE.match(path.name)
        if match:
            out.append((int(match.group("idx")), path))
    return sorted(out, key=lambda item: item[0])


def force_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def build_naive_ranking(pair_id: str, old_paths: list[tuple[int, Path]], new_paths: list[tuple[int, Path]]) -> dict[str, Any]:
    ranking = [{"path_id": path.stem, "similarity": 0.0} for _, path in new_paths]
    return {
        "pair_id": pair_id,
        "method": "naive_candidate_order",
        "queries": [{"query": old.stem, "ranking": ranking} for _, old in old_paths],
    }


def timed_ranking(
    builder: Any,
    pair_id: str,
    old_paths: list[tuple[int, Path]],
    new_paths: list[tuple[int, Path]],
    preprocess_seconds: float = 0.0,
) -> dict[str, Any]:
    start = time.perf_counter()
    data = builder(pair_id, old_paths, new_paths)
    rank_elapsed = time.perf_counter() - start
    data["timing"] = {
        "t_align": preprocess_seconds + rank_elapsed,
        "t_preprocess": preprocess_seconds,
        "t_align_rank": rank_elapsed,
        "old_path_count": len(old_paths),
        "new_path_count": len(new_paths),
        "candidate_pairs": len(old_paths) * len(new_paths),
    }
    return data


def veribin_preprocess_seconds(paths_out: Path) -> float:
    """Approximate VeriBin preprocessing with the old/new trace-generation pass.

    In this ARDiff path-only benchmark we do not invoke IDA/BinDiff directly.
    The VeriBin-style ranker consumes basic-block traces emitted during the
    symbolic execution pass, so this folds the trace-producing preprocessing
    logs into VERIBIN's alignment cost.
    """
    return (
        read_elapsed_from_log(paths_out / "symbolic_oldV_symbolic_execution.log")
        + read_elapsed_from_log(paths_out / "symbolic_newV_symbolic_execution.log")
    )


def read_elapsed_from_log(path: Path) -> float:
    if not path.is_file():
        return 0.0
    match = re.search(r"(?m)^elapsed=([0-9.]+)\s*$", path.read_text(encoding="utf-8", errors="replace"))
    return float(match.group(1)) if match else 0.0


def build_fmcad_ranking(pair_id: str, old_paths: list[tuple[int, Path]], new_paths: list[tuple[int, Path]]) -> dict[str, Any]:
    all_paths = [p for _, p in old_paths + new_paths]
    records = {
        p.stem: extract_feature_record(
            p.read_text(encoding="utf-8", errors="replace")
        )
        for p in all_paths
    }
    min_max = compute_feature_min_max(records)
    vectors = {
        pid: normalize_features(record.raw, min_max)
        for pid, record in records.items()
    }
    validity = {
        pid: [record.valid[name] for name in FEATURE_NAMES]
        for pid, record in records.items()
    }
    queries = []
    for _, old in old_paths:
        ranked = []
        for _, new in new_paths:
            score = cosine_with_validity(
                vectors[old.stem],
                vectors[new.stem],
                validity[old.stem],
                validity[new.stem],
            )
            ranked.append({"path_id": new.stem, "similarity": round(score, 6)})
        ranked.sort(key=lambda item: (-item["similarity"], path_numeric_suffix(item["path_id"])))
        queries.append({"query": old.stem, "ranking": ranked})
    return {
        "pair_id": pair_id,
        "method": "fmcad_11d_cosine",
        "feature_schema": FEATURE_SCHEMA,
        "queries": queries,
    }


def build_hybrid_fmcad_ranking(
    pair_id: str,
    old_paths: list[tuple[int, Path]],
    new_paths: list[tuple[int, Path]],
    matching_bb_map: dict[int, int] | None = None,
    graph_provider=None,
    profile_id: str = PAPER_PROFILE_ID,
    profile: dict[str, Any] | None = None,
    max_results_per_query: int | None = None,
) -> dict[str, Any]:
    data = hybrid_rank_paths(
        [p for _, p in old_paths],
        [p for _, p in new_paths],
        config=HybridConfig(
            high_threshold=0.70,
            margin_threshold=0.05,
            graph_min_score=0.01,
            graph_weight=1.0,
            feature_weight=0.0,
        ),
        matching_bb_map=matching_bb_map,
        graph_provider=graph_provider,
        profile_id=profile_id,
        profile=profile,
        max_results_per_query=max_results_per_query,
    )
    data["pair_id"] = pair_id
    return data


def build_veribin_ranking(pair_id: str, old_paths: list[tuple[int, Path]], new_paths: list[tuple[int, Path]]) -> dict[str, Any]:
    old_info = {p.stem: path_match_info(p) for _, p in old_paths}
    new_info = {p.stem: path_match_info(p) for _, p in new_paths}
    queries = []
    scoring = "basic_block_trace_overlap"
    if not any(info["trace"] for info in old_info.values()) or not any(info["trace"] for info in new_info.values()):
        scoring = "path_constraint_string_similarity"
    for _, old in old_paths:
        ranked = []
        for _, new in new_paths:
            sim = veribin_score(old_info[old.stem], new_info[new.stem], scoring)
            ranked.append({"path_id": new.stem, "similarity": round(sim, 6)})
        ranked.sort(key=lambda item: (-item["similarity"], path_numeric_suffix(item["path_id"])))
        queries.append({"query": old.stem, "ranking": ranked})
    return {"pair_id": pair_id, "method": f"veribin_{scoring}", "queries": queries}


def path_match_info(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8", errors="replace")
    body = content.split("; Path signature:")[0]
    return {"constraint": body, "trace": parse_execution_trace(content)}


def parse_execution_trace(content: str) -> list[int]:
    match = re.search(r";\s*Execution trace:\s*(.*)", content)
    if not match:
        return []
    text = match.group(1).strip()
    try:
        value = ast.literal_eval(text)
    except Exception:
        value = []
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            pass
    return out


def veribin_score(old: dict[str, Any], new: dict[str, Any], scoring: str) -> float:
    if scoring == "basic_block_trace_overlap":
        old_trace = old["trace"]
        new_trace = new["trace"]
        if not old_trace or not new_trace:
            return 0.0
        old_set = set(old_trace)
        new_set = set(new_trace)
        return 2.0 * len(old_set & new_set) / (len(old_set) + len(new_set))
    return difflib.SequenceMatcher(None, old["constraint"], new["constraint"]).ratio()


def compute_feature_min_max(records: dict[str, Any]) -> dict[str, tuple[float, float]]:
    names = list(FEATURE_RANGES.keys())
    if not records:
        return dict(FEATURE_RANGES)
    result = {}
    for index, name in enumerate(names):
        values = [
            record.raw[index]
            for record in records.values()
            if record.valid[name]
        ]
        if values:
            result[name] = (min(values), max(values))
    return result


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def path_numeric_suffix(path_id: str) -> int:
    match = re.search(r"_path_(\d+)$", path_id)
    return int(match.group(1)) if match else 0


def sanitize(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")


def rel_to(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path.resolve(), base.resolve())).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
