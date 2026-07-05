#!/usr/bin/env python3
"""Legacy benchmark automation entry point.

This script is kept for older TSVC-style experiments. The maintained ARDiff
artifact pipeline is implemented by ``build_ardiff_path_benchmarks.py`` and
``run_evaluation.py``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and show progress."""
    print(f"\n{'=' * 60}")
    print(f"Running: {description}")
    print("Command:", " ".join(cmd))
    print(f"{'=' * 60}")

    start_time = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start_time
    print(f"Elapsed: {elapsed:.2f} seconds")

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Legacy benchmark analysis automation tool")
    parser.add_argument("benchmark_dir", help="Path to benchmark directory")
    parser.add_argument("--timeout", type=int, default=120, help="Symbolic-execution timeout in seconds")
    parser.add_argument(
        "--step",
        choices=["se", "equiv", "all"],
        default="all",
        help="Step to run: symbolic execution, equivalence, or all",
    )
    parser.add_argument("--use-original", action="store_true", help="Use the compatibility symbolic-execution wrapper")
    args = parser.parse_args()

    se_script = "se_script.py" if args.use_original else "se_script_improved.py"

    if args.step in {"se", "all"}:
        if not run_command(["python", se_script, "--benchmark", args.benchmark_dir, "--timeout", str(args.timeout)], "symbolic execution"):
            return 1

    if args.step in {"equiv", "all"}:
        if not run_command(["python", "semantic_equivalence_analyzer.py", "--benchmark", args.benchmark_dir], "semantic equivalence"):
            return 1

    summary_file = os.path.join(args.benchmark_dir, "optimization_equivalence_summary.txt")
    if os.path.exists(summary_file):
        print(f"\nAnalysis complete. Summary: {summary_file}")
    else:
        print("\nAnalysis complete. No legacy summary file was produced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
