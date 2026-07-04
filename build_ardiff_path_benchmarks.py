#!/usr/bin/env python3
"""Build a path-matching benchmark from ARDiff comparison cases.

The script discovers symbolic_oldV/symbolic_newV cases, optionally compiles and
runs symbolic execution, then emits a run_evaluation.py-compatible manifest with
Naive, VeriBin-style, and FMCAD-style ranking files.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SYMBOLIC_SRC = ROOT / "src"
sys.path.insert(0, str(SYMBOLIC_SRC))

from symbolic_analysis.analysis.path_constraint_features import (  # noqa: E402
    FEATURE_RANGES,
    extract_features,
    normalize_features,
)
from symbolic_analysis.analysis.hybrid_path_matching import (  # noqa: E402
    HybridConfig,
    hybrid_rank_paths,
)


PATH_RE = re.compile(r"^(?P<prefix>symbolic_(?:old|new)V)_path_(?P<idx>\d+)\.txt$")


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
    parser.add_argument("--out-dir", type=Path, default=Path("benchmarks/ardiff_paths"))
    parser.add_argument("--eval-output-dir", type=Path, default=Path("evaluation_results_ardiff"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--force-symbolic-exec", action="store_true")
    parser.add_argument("--skip-symbolic-exec", action="store_true")
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument("--python", default=os.environ.get("PYTHON", "python3"))
    args = parser.parse_args()

    benchmarks = (ROOT / args.benchmarks).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    eval_output_dir = (ROOT / args.eval_output_dir).resolve()
    args.python = resolve_python_command(args.python)
    if not args.skip_symbolic_exec:
        verify_symbolic_python(args.python)

    cases = discover_cases(benchmarks)
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

    (out_dir / "manifest.json").write_text(
        json.dumps({"pairs": manifest_rows, "failures": failures}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "groundtruth.json").write_text(
        json.dumps({"pairs": truth_rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
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
            str(out_dir / "groundtruth.json"),
            "--output-dir",
            str(eval_output_dir),
            "--python",
            args.python,
            "--execute",
        ]
        print("Running evaluation:")
        print("  " + " ".join(cmd))
        subprocess.run(cmd, cwd=str(ROOT), check=False)

    return 0


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


def process_case(case: Case, out_dir: Path, args: argparse.Namespace) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    case_out = out_dir / "cases" / case.rel
    bin_out = case_out / "bin"
    paths_out = case_out / "paths"
    rankings_out = out_dir / "rankings" / case.subset / sanitize(case.program)
    bin_out.mkdir(parents=True, exist_ok=True)
    paths_out.mkdir(parents=True, exist_ok=True)
    rankings_out.mkdir(parents=True, exist_ok=True)

    old_bin = ensure_binary(case.case_dir / "symbolic_oldV.c", bin_out / "symbolic_oldV")
    new_bin = ensure_binary(case.case_dir / "symbolic_newV.c", bin_out / "symbolic_newV")

    if not args.skip_symbolic_exec:
        maybe_run_symbolic_exec(old_bin, paths_out, "symbolic_oldV", args, case.case_dir / "symbolic_oldV.c")
        maybe_run_symbolic_exec(new_bin, paths_out, "symbolic_newV", args, case.case_dir / "symbolic_newV.c")

    old_paths = collect_path_files(paths_out, "symbolic_oldV")
    new_paths = collect_path_files(paths_out, "symbolic_newV")
    if not old_paths or not new_paths:
        raise RuntimeError("missing generated path files for oldV or newV")

    pair_id = f"{case.subset}/{sanitize(case.program)}"
    old_ids = [p.stem for _, p in old_paths]
    new_ids = [p.stem for _, p in new_paths]
    truth_pairs = {
        old.stem: new.stem
        for (old_idx, old), (new_idx, new) in zip(old_paths, new_paths)
        if old_idx == new_idx
    }
    if not truth_pairs:
        truth_pairs = dict(zip(old_ids, new_ids))

    naive_path = rankings_out / "naive.json"
    veribin_path = rankings_out / "veribin.json"
    fmcad_path = rankings_out / "fmcad.json"
    naive_path.write_text(
        json.dumps(timed_ranking(build_naive_ranking, pair_id, old_paths, new_paths), indent=2) + "\n",
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
    fmcad_path.write_text(
        json.dumps(timed_ranking(build_hybrid_fmcad_ranking, pair_id, old_paths, new_paths), indent=2) + "\n",
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
    }
    truth = dict(base)
    row = {
        **base,
        "left": rel_to(old_paths[0][1], out_dir),
        "right": rel_to(new_paths[0][1], out_dir),
        "paths_dir": rel_to(paths_out, out_dir),
        "naive_ranking_path": rel_to(naive_path, out_dir),
        "veribin_ranking_path": rel_to(veribin_path, out_dir),
        "fmcad_ranking_path": rel_to(fmcad_path, out_dir),
        "source_case": rel_to(case.case_dir, out_dir),
        "old_binary": rel_to(old_bin, out_dir),
        "new_binary": rel_to(new_bin, out_dir),
    }
    return row, truth


def ensure_binary(src: Path, out_bin: Path) -> Path:
    if out_bin.is_file():
        return out_bin
    cmd = ["gcc", "-O0", "-g", "-o", str(out_bin), str(src), "-lm"]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"gcc failed for {src}: {completed.stderr.strip()}")
    return out_bin


def maybe_run_symbolic_exec(
    binary: Path,
    paths_out: Path,
    prefix: str,
    args: argparse.Namespace,
    source: Path | None = None,
) -> None:
    if not args.force_symbolic_exec and collect_path_files(paths_out, prefix):
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
    ]
    signature = extract_c_snippet_signature(source) if source else None
    if signature:
        cmd.extend(["--signature", signature])
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
                raise RuntimeError(f"symbolic execution timed out for {binary}; see {log}")
            time.sleep(0.25)
        elapsed = time.perf_counter() - start
        log_f.write(f"\n\nelapsed={elapsed:.6f}\nreturncode={proc.returncode}\n")
        returncode = proc.returncode
    if returncode != 0:
        raise RuntimeError(f"symbolic execution failed for {binary}; see {log}")


def extract_c_snippet_signature(source: Path | None) -> str | None:
    if not source or not source.is_file():
        return None
    text = source.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"\b(?P<ret>int|double|float|long)\s+snippet\s*\((?P<args>[^)]*)\)", text)
    if not match:
        return None
    arg_types = []
    for raw_arg in match.group("args").split(","):
        raw_arg = raw_arg.strip()
        if not raw_arg or raw_arg == "void":
            continue
        parts = raw_arg.replace("*", " * ").split()
        for token in parts:
            if token in {"int", "double", "float", "long"}:
                arg_types.append(token)
                break
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
    raw = {p.stem: extract_features(p.read_text(encoding="utf-8", errors="replace"))[0] for p in all_paths}
    min_max = compute_min_max(raw)
    vectors = {pid: normalize_features(vec, min_max) for pid, vec in raw.items()}
    queries = []
    for _, old in old_paths:
        ranked = []
        for _, new in new_paths:
            ranked.append({"path_id": new.stem, "similarity": round(cosine(vectors[old.stem], vectors[new.stem]), 6)})
        ranked.sort(key=lambda item: (-item["similarity"], path_numeric_suffix(item["path_id"])))
        queries.append({"query": old.stem, "ranking": ranked})
    return {"pair_id": pair_id, "method": "fmcad_11d_cosine", "queries": queries}


def build_hybrid_fmcad_ranking(pair_id: str, old_paths: list[tuple[int, Path]], new_paths: list[tuple[int, Path]]) -> dict[str, Any]:
    data = hybrid_rank_paths(
        [p for _, p in old_paths],
        [p for _, p in new_paths],
        config=HybridConfig(
            high_threshold=0.80,
            margin_threshold=0.05,
            graph_min_score=0.01,
            graph_weight=1.0,
            feature_weight=0.0,
        ),
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


def compute_min_max(raw: dict[str, list[float]]) -> dict[str, tuple[float, float]]:
    names = list(FEATURE_RANGES.keys())
    values = list(raw.values())
    if not values:
        return dict(FEATURE_RANGES)
    return {
        name: (min(vec[i] for vec in values), max(vec[i] for vec in values))
        for i, name in enumerate(names)
    }


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
    return os.path.relpath(path.resolve(), base.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
