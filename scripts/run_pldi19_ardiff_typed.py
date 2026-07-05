#!/usr/bin/env python3
"""Prepare and run PLDI19/STOKE checks for typed ARDiff benchmarks.

The generated ``benchmarks/ardiff_paths_typed`` directory contains path-level
SMT files. The PLDI19 checker works at the x86-64 assembly level, so this
script maps each manifest row back to the typed C source pair under
``experiments/ardiff_comparison/benchmarks_typed``, builds a PLDI19-style
benchmark directory, and optionally executes STOKE there.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARKS = ROOT / "benchmarks" / "ardiff_paths_typed"
DEFAULT_SOURCES = ROOT / "experiments" / "ardiff_comparison" / "benchmarks_typed"
DEFAULT_PLDI19 = ROOT.parent / "pldi19-equivalence-checker"
DEFAULT_OUTPUT = ROOT / "evaluation_results_pldi19_ardiff_typed"

INT_ARG_REGS = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]
FP_ARG_REGS = ["%xmm0", "%xmm1", "%xmm2", "%xmm3", "%xmm4", "%xmm5", "%xmm6", "%xmm7"]
PAPER_EXTRA_DEF_INS = ["%rbp", "%rsp", "%rbx", "%r12", "%r13", "%r14", "%r15", "%xmm0", "%xmm1", "%xmm2", "%xmm3", "%xmm4"]
PAPER_EXTRA_LIVE_OUTS = ["%rbx", "%rsp", "%rbp", "%r12", "%r13", "%r14", "%r15"]


@dataclass(frozen=True)
class Case:
    pair_id: str
    subset: str
    program: str
    ground_truth: bool | None
    source_dir: Path
    work_dir: Path


@dataclass(frozen=True)
class Signature:
    return_type: str
    arg_types: list[str]

    @property
    def def_ins(self) -> list[str]:
        int_idx = 0
        fp_idx = 0
        regs: list[str] = []
        for arg_type in self.arg_types:
            if is_fp_type(arg_type):
                if fp_idx < len(FP_ARG_REGS):
                    regs.append(FP_ARG_REGS[fp_idx])
                fp_idx += 1
            elif arg_type != "void":
                if int_idx < len(INT_ARG_REGS):
                    regs.append(INT_ARG_REGS[int_idx])
                int_idx += 1
        return regs

    @property
    def live_outs(self) -> list[str]:
        if self.return_type == "void":
            return []
        if is_fp_type(self.return_type):
            return ["%xmm0"]
        return ["%rax"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--pldi19-dir", type=Path, default=DEFAULT_PLDI19)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--only", action="append", default=[], help="Substring filter for pair_id, repeatable.")
    parser.add_argument("--execute", action="store_true", help="Run make/tcgen/demo.sh after preparing work dirs.")
    parser.add_argument("--force", action="store_true", help="Regenerate existing per-case work directories.")
    parser.add_argument("--timeout", type=int, default=600, help="Seconds per STOKE verification command.")
    parser.add_argument("--config", choices=["baseline", "paper"], default="baseline")
    parser.add_argument("--target-bound", type=int)
    parser.add_argument("--rewrite-bound", type=int)
    parser.add_argument("--stoke-strategy", default="ddec")
    parser.add_argument("--solver")
    parser.add_argument("--max-jumps", type=int)
    parser.add_argument("--training-set-size", type=int)
    parser.add_argument("--assume", default="")
    parser.add_argument("--vector-invariants", action="store_true")
    args = parser.parse_args()

    if args.target_bound is None:
        args.target_bound = 30 if args.config == "paper" else 8
    if args.rewrite_bound is None:
        args.rewrite_bound = 30 if args.config == "paper" else 8
    if args.config == "paper":
        args.solver = args.solver or "z3"
        args.max_jumps = args.max_jumps or 129000
        args.vector_invariants = True

    benchmarks = resolve_path(args.benchmarks)
    sources = resolve_path(args.sources)
    pldi19_dir = resolve_path(args.pldi19_dir)
    output_dir = resolve_path(args.output_dir)
    work_root = output_dir / "work"
    logs_root = output_dir / "logs"

    rows = load_manifest(benchmarks / "manifest.json")
    cases = discover_cases(rows, benchmarks, sources, work_root, args.only)
    if args.max_cases is not None:
        cases = cases[: args.max_cases]
    if not cases:
        raise SystemExit("No matching typed ARDiff cases found.")

    output_dir.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)

    env_status = check_environment(pldi19_dir)
    results: list[dict[str, Any]] = []
    if args.execute and not env_status["ready"]:
        print(
            "PLDI19/STOKE environment is not ready; preparing cases only. "
            "See pldi19_summary.md for missing commands."
        )
    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case.pair_id}")
        prepared = prepare_case(
            case,
            pldi19_dir=pldi19_dir,
            force=args.force,
            target_bound=args.target_bound,
            rewrite_bound=args.rewrite_bound,
            strategy=args.stoke_strategy,
            timeout=args.timeout,
            config=args.config,
            solver=args.solver,
            max_jumps=args.max_jumps,
            training_set_size=args.training_set_size,
            assume=args.assume,
            vector_invariants=args.vector_invariants,
        )
        result = {
            "pair_id": case.pair_id,
            "subset": case.subset,
            "program": case.program,
            "ground_truth": case.ground_truth,
            "source_dir": str(case.source_dir),
            "work_dir": str(case.work_dir),
            "signature": prepared["signature"],
            "def_in": prepared["def_in"],
            "live_out": prepared["live_out"],
            "status": "prepared",
            "prediction": None,
            "elapsed": 0.0,
            "error": None,
        }
        if args.execute and env_status["ready"]:
            run_result = run_case(case, logs_root / safe_name(case.pair_id), env_status["env"], args.timeout)
            result.update(run_result)
        results.append(result)

    payload = {
        "execute": args.execute,
        "benchmarks": str(benchmarks),
        "sources": str(sources),
        "pldi19_dir": str(pldi19_dir),
        "config": args.config,
        "target_bound": args.target_bound,
        "rewrite_bound": args.rewrite_bound,
        "solver": args.solver,
        "max_jumps": args.max_jumps,
        "training_set_size": args.training_set_size,
        "assume": args.assume,
        "vector_invariants": args.vector_invariants,
        "environment": env_status["summary"],
        "cases": results,
    }
    (output_dir / "pldi19_results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_summary(output_dir / "pldi19_summary.md", payload)

    print(f"Wrote PLDI19 run artifacts to {output_dir}")
    if args.execute and not env_status["ready"]:
        print("Environment is missing required PLDI19/STOKE commands; see pldi19_summary.md.")
        return 2
    return 0


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else (ROOT / path).resolve()


def load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("pairs", [])
    if not isinstance(rows, list):
        raise SystemExit(f"Manifest has no list-valued 'pairs': {path}")
    return rows


def discover_cases(
    rows: list[dict[str, Any]],
    benchmarks: Path,
    sources: Path,
    work_root: Path,
    filters: list[str],
) -> list[Case]:
    by_rel: dict[str, dict[str, Any]] = {}
    for row in rows:
        rel = source_rel_from_row(row)
        if rel is not None:
            by_rel[rel_key(rel)] = row

    cases: list[Case] = []
    rels = manifest_rels(rows)
    scanned_rels = benchmark_case_rels(benchmarks)
    for rel in sorted(set(rels) | set(scanned_rels), key=lambda p: tuple(p.parts)):
        row = by_rel.get(rel_key(rel), {})
        pair_id = str(row.get("pair_id") or pair_id_from_rel(rel))
        if filters and not any(item in pair_id for item in filters):
            continue
        source_dir = sources / rel
        if not (source_dir / "symbolic_oldV.c").is_file() or not (source_dir / "symbolic_newV.c").is_file():
            print(f"skip {pair_id}: missing typed source under {source_dir}")
            continue
        cases.append(
            Case(
                pair_id=pair_id,
                subset=str(row.get("subset") or rel.parts[0]),
                program=str(row.get("program") or rel.name),
                ground_truth=row.get("ground_truth", ground_truth_from_rel(rel)),
                source_dir=source_dir,
                work_dir=work_root / safe_name(pair_id),
            )
        )
    return cases


def manifest_rels(rows: list[dict[str, Any]]) -> list[Path]:
    rels: list[Path] = []
    for row in rows:
        rel = source_rel_from_row(row)
        if rel is not None:
            rels.append(rel)
    return rels


def benchmark_case_rels(benchmarks: Path) -> list[Path]:
    cases_root = benchmarks / "cases"
    if not cases_root.is_dir():
        return []
    rels: list[Path] = []
    for paths_dir in sorted(cases_root.rglob("paths")):
        if not paths_dir.is_dir():
            continue
        has_old = any(paths_dir.glob("symbolic_oldV_path_*.txt"))
        has_new = any(paths_dir.glob("symbolic_newV_path_*.txt"))
        if has_old and has_new:
            rels.append(paths_dir.parent.relative_to(cases_root))
    return rels


def pair_id_from_rel(rel: Path) -> str:
    parts = rel.parts
    if len(parts) < 3:
        return rel.as_posix()
    subset = parts[0]
    if subset.lower() == "moddiff":
        truth = parts[1]
        program = "_".join(["/".join(parts[2:]), truth])
        return f"{subset}/{program}"
    truth = parts[-1]
    program = "_".join(["/".join(parts[1:-1]), truth])
    return f"{subset}/{program}"


def ground_truth_from_rel(rel: Path) -> bool | None:
    if not rel.parts:
        return None
    if rel.parts[0].lower() == "moddiff" and len(rel.parts) >= 2:
        truth = rel.parts[1].lower()
    else:
        truth = rel.parts[-1].lower()
    if truth == "eq":
        return True
    if truth == "neq":
        return False
    return None


def rel_key(rel: Path) -> str:
    return rel.as_posix().lower()


def source_rel_from_row(row: dict[str, Any]) -> Path | None:
    paths_dir = row.get("paths_dir")
    if paths_dir:
        parts = Path(str(paths_dir).replace("\\", "/")).parts
        if len(parts) >= 4 and parts[0] == "cases" and parts[-1] == "paths":
            return Path(*parts[1:-1])
    pair_id = str(row.get("pair_id") or "")
    if "/" not in pair_id:
        return None
    subset, program = pair_id.split("/", 1)
    if "_" not in program:
        return None
    func, truth = program.rsplit("_", 1)
    return Path(subset) / func / truth


def prepare_case(
    case: Case,
    pldi19_dir: Path,
    force: bool,
    target_bound: int,
    rewrite_bound: int,
    strategy: str,
    timeout: int,
    config: str,
    solver: str | None,
    max_jumps: int | None,
    training_set_size: int | None,
    assume: str,
    vector_invariants: bool,
) -> dict[str, Any]:
    if force and case.work_dir.exists():
        shutil.rmtree(case.work_dir)
    case.work_dir.mkdir(parents=True, exist_ok=True)

    old_src = case.source_dir / "symbolic_oldV.c"
    new_src = case.source_dir / "symbolic_newV.c"
    shutil.copy2(old_src, case.work_dir / "symbolic_oldV.c")
    shutil.copy2(new_src, case.work_dir / "symbolic_newV.c")

    signature = parse_signature(old_src)
    new_signature = parse_signature(new_src)
    if signature != new_signature:
        raise RuntimeError(f"signature mismatch in {case.source_dir}: {signature} vs {new_signature}")

    write_text_lf(case.work_dir / "source.c", render_source())
    def_ins = configured_def_ins(signature, config)
    live_outs = configured_live_outs(signature, config)

    write_text_lf(case.work_dir / "variables", render_variables(case, signature, target_bound, rewrite_bound, def_ins, live_outs))
    write_text_lf(case.work_dir / "Makefile", render_makefile())
    demo = case.work_dir / "demo.sh"
    write_text_lf(demo, render_demo(strategy, timeout, solver, max_jumps, training_set_size, assume, vector_invariants))
    try:
        demo.chmod(demo.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass
    return {
        "signature": f"{signature.return_type}({','.join(signature.arg_types)})",
        "def_in": def_ins,
        "live_out": live_outs,
        "pldi19_dir": str(pldi19_dir),
    }


def parse_signature(source: Path) -> Signature:
    text = strip_comments(source.read_text(encoding="utf-8", errors="replace"))
    match = re.search(
        r"\b(?P<ret>(?:unsigned\s+)?(?:long\s+long|long|int|double|float|void))\s+"
        r"snippet\s*\((?P<args>[^)]*)\)",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"cannot find snippet signature in {source}")
    return_type = normalize_c_type(match.group("ret"))
    arg_text = match.group("args").strip()
    arg_types = [] if not arg_text or arg_text == "void" else [arg_type(part) for part in split_args(arg_text)]
    return Signature(return_type=return_type, arg_types=arg_types)


def write_text_lf(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//.*", "", text)


def split_args(arg_text: str) -> list[str]:
    return [part.strip() for part in arg_text.split(",") if part.strip()]


def arg_type(arg: str) -> str:
    arg = arg.replace("*", " * ")
    tokens = [token for token in arg.split() if token not in {"const", "volatile", "restrict"}]
    if "*" in tokens:
        return "pointer"
    if len(tokens) >= 2 and tokens[0] == "unsigned" and tokens[1] in {"int", "long"}:
        return f"unsigned {tokens[1]}"
    if len(tokens) >= 2 and tokens[0] == "long" and tokens[1] == "long":
        return "long long"
    for token in tokens:
        if token in {"int", "long", "double", "float", "void"}:
            return token
    raise RuntimeError(f"unsupported snippet argument: {arg}")


def normalize_c_type(raw: str) -> str:
    return " ".join(raw.split())


def is_fp_type(c_type: str) -> bool:
    return c_type in {"float", "double"}


def render_source() -> str:
    return """#define snippet symbolic_oldV_snippet
#define main symbolic_oldV_main
#include "symbolic_oldV.c"
#undef snippet
#undef main

#define snippet symbolic_newV_snippet
#define main symbolic_newV_main
#include "symbolic_newV.c"
#undef snippet
#undef main

int main(int argc, char **argv) {
  (void)argc;
  (void)argv;
  return 0;
}
"""


def configured_def_ins(signature: Signature, config: str) -> list[str]:
    if config != "paper":
        return signature.def_ins
    return unique_regs(signature.def_ins + PAPER_EXTRA_DEF_INS)


def configured_live_outs(signature: Signature, config: str) -> list[str]:
    if config != "paper":
        return signature.live_outs
    return unique_regs(signature.live_outs + PAPER_EXTRA_LIVE_OUTS)


def unique_regs(regs: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for reg in regs:
        if reg not in seen:
            result.append(reg)
            seen.add(reg)
    return result


def render_variables(
    case: Case,
    signature: Signature,
    target_bound: int,
    rewrite_bound: int,
    def_ins: list[str],
    live_outs: list[str],
) -> str:
    return f"""TARGET_BOUND={target_bound}
REWRITE_BOUND={rewrite_bound}
NAME={safe_name(case.pair_id)}
TARGET=opt1/symbolic_oldV_snippet.s
REWRITE=opt1/symbolic_newV_snippet.s
DEF_INS="{brace_regs(def_ins)}"
LIVE_OUTS="{brace_regs(live_outs)}"
GROUND_TRUTH={str(case.ground_truth).lower() if case.ground_truth is not None else "unknown"}
"""


def brace_regs(regs: list[str]) -> str:
    return "{ " + " ".join(regs) + " }"


def render_makefile() -> str:
    return """include variables

all:
\tgcc -O1 -std=c99 source.c -c -o opt1.o
\tstoke extract -i opt1.o -o opt1

tcgen:
\trm -rf tcs
\tmkdir -p tcs
\tstoke_tcgen --target $(TARGET) --bound $(TARGET_BOUND) --def_in $(DEF_INS) --live_out $(LIVE_OUTS) --output tcs/tcgen1 --mutants 0
\tstoke_tcgen --target $(REWRITE) --bound $(REWRITE_BOUND) --def_in $(DEF_INS) --live_out $(LIVE_OUTS) --output tcs/tcgen2 --mutants 0
\ttouch tcs/tcgen1 tcs/tcgen2
\tcat tcs/tcgen1 tcs/tcgen2 > testcases
\trm -rf tcs

clean:
\trm -rf opt1 opt1.o tcs testcases *.time trace *.tmp sage* stoke_sage* state*
"""


def render_demo(
    strategy: str,
    timeout: int,
    solver: str | None,
    max_jumps: int | None,
    training_set_size: int | None,
    assume: str,
    vector_invariants: bool,
) -> str:
    extra_args: list[str] = []
    if solver:
        extra_args.append(f"    --solver {solver} \\")
    if vector_invariants:
        extra_args.append("    --vector_invariants \\")
    if max_jumps is not None:
        extra_args.append(f"    --max_jumps {max_jumps} \\")
    if training_set_size is not None:
        extra_args.append(f"    --training_set_size {training_set_size} \\")
    if assume:
        escaped_assume = assume.replace('"', '\\"')
        extra_args.append(f'    --assume "{escaped_assume}" \\')
    extra = "\n".join(extra_args)
    if extra:
        extra += "\n"
    return f"""#!/usr/bin/env bash
set -euo pipefail

source variables

if [ -s testcases ]; then
  timeout {timeout}s stoke_debug_verify \\
    --strategy {strategy} \\
    --target "$TARGET" \\
    --rewrite "$REWRITE" \\
    --testcases testcases \\
{extra}\
    --heap_out \\
    --stack_out \\
    --live_out "$LIVE_OUTS" \\
    --def_in "$DEF_INS" \\
    --target_bound "$TARGET_BOUND" \\
    --rewrite_bound "$REWRITE_BOUND" \\
    --alias_strategy flat
else
  timeout {timeout}s stoke_debug_verify \\
    --strategy {strategy} \\
    --target "$TARGET" \\
    --rewrite "$REWRITE" \\
{extra}\
    --heap_out \\
    --stack_out \\
    --live_out "$LIVE_OUTS" \\
    --def_in "$DEF_INS" \\
    --target_bound "$TARGET_BOUND" \\
    --rewrite_bound "$REWRITE_BOUND" \\
    --alias_strategy flat
fi
"""


def check_environment(pldi19_dir: Path) -> dict[str, Any]:
    env = os.environ.copy()
    path_parts = []
    if (pldi19_dir / "bin").is_dir():
        path_parts.append(str(pldi19_dir / "bin"))
    path_parts.append(env.get("PATH", ""))
    env["PATH"] = os.pathsep.join(path_parts)

    required = ["gcc", "make", "stoke", "stoke_debug_verify", "stoke_tcgen"]
    found = {name: shutil.which(name, path=env["PATH"]) for name in required}
    ready = all(found.values())
    summary = {
        "ready": ready,
        "pldi19_dir_exists": pldi19_dir.is_dir(),
        "commands": found,
        "missing": [name for name, path in found.items() if not path],
    }
    return {"ready": ready, "summary": summary, "env": env}


def run_case(case: Case, log_dir: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    for step, command in (
        ("make", ["make"]),
        ("tcgen", ["make", "tcgen"]),
        ("verify", ["bash", "demo.sh"]),
    ):
        completed = subprocess.run(
            command,
            cwd=case.work_dir,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout + 30,
            check=False,
        )
        (log_dir / f"{step}.stdout.txt").write_text(completed.stdout, encoding="utf-8", errors="replace")
        (log_dir / f"{step}.stderr.txt").write_text(completed.stderr, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            return {
                "status": "failed",
                "prediction": parse_prediction(completed.stdout + "\n" + completed.stderr),
                "elapsed": time.perf_counter() - start,
                "error": f"{step} failed with exit code {completed.returncode}",
            }
    verify_out = (log_dir / "verify.stdout.txt").read_text(encoding="utf-8", errors="replace")
    return {
        "status": "ok",
        "prediction": parse_prediction(verify_out),
        "elapsed": time.perf_counter() - start,
        "error": None,
    }


def parse_prediction(output: str) -> bool | None:
    if re.search(r"Equivalent:\s*yes", output, flags=re.IGNORECASE):
        return True
    if re.search(r"Equivalent:\s*no", output, flags=re.IGNORECASE):
        return False
    return None


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    cases = payload["cases"]
    ok = sum(1 for row in cases if row["status"] == "ok")
    failed = sum(1 for row in cases if row["status"] == "failed")
    prepared = sum(1 for row in cases if row["status"] == "prepared")
    env = payload["environment"]
    lines = [
        "# PLDI19 ARDiff Typed Run Summary",
        "",
        f"- Execute mode: {payload['execute']}",
        f"- Cases: {len(cases)}",
        f"- OK: {ok}",
        f"- Failed: {failed}",
        f"- Prepared only: {prepared}",
        f"- Environment ready: {env['ready']}",
    ]
    if env["missing"]:
        lines.append(f"- Missing commands: {', '.join(env['missing'])}")
    lines.extend(
        [
            "",
            "| Pair | Truth | Status | Prediction | Elapsed s | Work Dir |",
            "|---|---:|---|---:|---:|---|",
        ]
    )
    for row in cases:
        lines.append(
            "| {pair} | {truth} | {status} | {pred} | {elapsed:.3f} | {work} |".format(
                pair=row["pair_id"],
                truth=row["ground_truth"],
                status=row["status"],
                pred=row["prediction"],
                elapsed=float(row["elapsed"] or 0.0),
                work=row["work_dir"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def safe_name(text: str) -> str:
    text = text.replace("\\", "/")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "case"


if __name__ == "__main__":
    raise SystemExit(main())
