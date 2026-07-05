#!/usr/bin/env python3
"""Run symbolic execution and equivalence analysis for one ARDiff case."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SE_SCRIPT = SCRIPTS_DIR / "se_script_improved.py"
EQUIV_SCRIPT = SCRIPTS_DIR / "ardiff_comparison" / "semantic_equivalence_analyzer_enhanced.py"


def run_command(cmd: list[str], description: str, cwd: Path | None = None) -> bool:
    """Run a command and print a compact progress report."""
    print(f"\n{'=' * 60}")
    print(f"Running: {description}")
    print("Command:", " ".join(str(part) for part in cmd))
    print(f"{'=' * 60}")

    start_time = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd or REPO_ROOT))
    elapsed = time.time() - start_time

    print(f"Elapsed time: {elapsed:.2f} seconds")
    if result.returncode == 0:
        print("Status: success")
        if result.stdout:
            print(result.stdout)
        return True

    print("Status: failed")
    if result.stdout:
        print("stdout:")
        print(result.stdout)
    if result.stderr:
        print("stderr:")
        print(result.stderr)
    return False


def resolve_benchmark_dir(path_text: str) -> Path | None:
    """Resolve absolute, repository-relative, or benchmark-relative case paths."""
    candidates = [
        Path(path_text),
        REPO_ROOT / path_text,
        SCRIPT_DIR / "benchmarks" / path_text,
        SCRIPT_DIR / "benchmarks_typed" / path_text,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def extract_total_time_from_timing_report(report_path: Path) -> float:
    """Read total symbolic-execution time from a timing report if available."""
    if not report_path.is_file():
        return 0.0
    for line in report_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Total time:"):
            try:
                return float(line.split(":", 1)[1].strip().split()[0])
            except (IndexError, ValueError):
                return 0.0
    return 0.0


def compile_case_if_needed(benchmark_dir: Path) -> bool:
    """Compile symbolic_oldV.c and symbolic_newV.c when they are present."""
    old_c = benchmark_dir / "symbolic_oldV.c"
    new_c = benchmark_dir / "symbolic_newV.c"
    if not (old_c.is_file() and new_c.is_file()):
        return True

    commands = [
        (["gcc", "-o", "symbolic_oldV", "symbolic_oldV.c", "-lm"], "compile symbolic_oldV"),
        (["gcc", "-o", "symbolic_newV", "symbolic_newV.c", "-lm"], "compile symbolic_newV"),
    ]
    return all(run_command(cmd, label, cwd=benchmark_dir) for cmd, label in commands)


def run_symbolic_execution_for_case(benchmark_dir: Path, timeout: int) -> bool:
    """Run symbolic execution for oldV and newV in a single case."""
    old_bin = benchmark_dir / "symbolic_oldV"
    new_bin = benchmark_dir / "symbolic_newV"

    if not (old_bin.is_file() and new_bin.is_file()):
        cmd = [sys.executable, str(SE_SCRIPT), "--benchmark", str(benchmark_dir), "--timeout", str(timeout)]
        return run_command(cmd, "symbolic execution for benchmark directory", cwd=REPO_ROOT)

    old_cmd = [sys.executable, str(SE_SCRIPT), "--binary", str(old_bin), "--timeout", str(timeout)]
    new_cmd = [sys.executable, str(SE_SCRIPT), "--binary", str(new_bin), "--timeout", str(timeout)]
    return run_command(old_cmd, "symbolic execution for oldV", cwd=benchmark_dir) and run_command(
        new_cmd, "symbolic execution for newV", cwd=benchmark_dir
    )


def run_equivalence_for_benchmarks(benchmark_dir: Path, timeout: int = 120) -> bool:
    """Run equivalence analysis for directories containing old/new path files."""
    if not benchmark_dir.is_dir():
        print(f"Benchmark directory does not exist: {benchmark_dir}")
        return False

    cases: list[Path] = []
    for root, _, files in os.walk(benchmark_dir):
        has_old = any(name.startswith("symbolic_oldV_path") and name.endswith(".txt") for name in files)
        has_new = any(name.startswith("symbolic_newV_path") and name.endswith(".txt") for name in files)
        if has_old and has_new:
            cases.append(Path(root))

    if not cases:
        print("No paired symbolic_oldV_path_*.txt and symbolic_newV_path_*.txt files found.")
        return True

    all_ok = True
    for case_dir in sorted(cases):
        case_name = os.path.relpath(case_dir, benchmark_dir)
        prefix_old = case_dir / "symbolic_oldV_path"
        prefix_new = case_dir / "symbolic_newV_path"
        output_file = case_dir / "enhanced_equivalence_report.txt"
        se_time = extract_total_time_from_timing_report(case_dir / "symbolic_oldV_timing_report.txt")
        se_time += extract_total_time_from_timing_report(case_dir / "symbolic_newV_timing_report.txt")

        cmd = [
            sys.executable,
            str(EQUIV_SCRIPT),
            str(prefix_old),
            str(prefix_new),
            "--output",
            str(output_file),
            "--timeout",
            str(timeout * 1000),
            "--se-time",
            str(se_time),
        ]
        if not run_command(cmd, f"equivalence analysis for {case_name}", cwd=REPO_ROOT):
            all_ok = False
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one ARDiff benchmark case.")
    parser.add_argument("benchmark_dir", help="Case directory, repo-relative path, or benchmark-relative path")
    parser.add_argument("--timeout", type=int, default=120, help="Symbolic-execution timeout in seconds")
    parser.add_argument(
        "--step",
        choices=["se", "equiv", "all"],
        default="all",
        help="Run only symbolic execution, only equivalence analysis, or the full pipeline",
    )
    parser.add_argument("--use-original", action="store_true", help="Deprecated compatibility flag; ignored")
    args = parser.parse_args()

    benchmark_dir = resolve_benchmark_dir(args.benchmark_dir)
    if benchmark_dir is None:
        print(f"Benchmark directory does not exist: {args.benchmark_dir}")
        return 1

    if args.step in {"se", "all"}:
        if not compile_case_if_needed(benchmark_dir):
            return 1
        if not run_symbolic_execution_for_case(benchmark_dir, args.timeout):
            return 1

    if args.step in {"equiv", "all"} and not run_equivalence_for_benchmarks(benchmark_dir, args.timeout):
        return 1

    print(f"\nAnalysis completed: {benchmark_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
