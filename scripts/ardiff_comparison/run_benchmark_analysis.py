#!/usr/bin/env python3
"""Run the ARDiff benchmark pipeline over a selected set of cases."""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BENCH_ROOT = REPO_ROOT / "experiments" / "ardiff_comparison" / "benchmarks"
RUN_ONE_SCRIPT = REPO_ROOT / "experiments" / "ardiff_comparison" / "run_one_benchmark.sh"

TARGET_CASES = {
    "Airy/MAX/Eq",
    "Airy/MAX/NEq",
    "Airy/Sign/Eq",
    "Airy/Sign/NEq",
    "Bess/SIGN/Eq",
    "Bess/SIGN/NEq",
    "Bess/SQR/Eq",
    "Bess/SQR/NEq",
    "Bess/bessi0/Eq",
    "Bess/bessi0/NEq",
    "Bess/bessi1/Eq",
    "Bess/bessi1/NEq",
    "Bess/probks/Eq",
    "Bess/probks/NEq",
    "Ell/rc/Eq",
    "Ell/rc/NEq",
    "ModDiff/Add/Eq",
    "ModDiff/Comp/Eq",
    "ModDiff/Const/Eq",
    "ModDiff/LoopMult10/Eq",
    "ModDiff/LoopMult10/NEq",
    "ModDiff/LoopMult15/Eq",
    "ModDiff/LoopMult15/NEq",
    "ModDiff/LoopMult20/Eq",
    "ModDiff/LoopMult20/NEq",
    "ModDiff/LoopMult5/Eq",
    "ModDiff/LoopMult5/NEq",
    "ModDiff/LoopSub/Eq",
    "ModDiff/LoopSub/NEq",
    "ModDiff/LoopUnreach10/Eq",
    "ModDiff/LoopUnreach10/NEq",
    "ModDiff/LoopUnreach15/Eq",
    "ModDiff/LoopUnreach15/NEq",
    "ModDiff/LoopUnreach2/Eq",
    "ModDiff/LoopUnreach2/NEq",
    "ModDiff/LoopUnreach20/Eq",
    "ModDiff/LoopUnreach20/NEq",
    "ModDiff/LoopUnreach5/Eq",
    "ModDiff/LoopUnreach5/NEq",
    "ModDiff/Sub/Eq",
    "Ran/gammln/Eq",
    "Ran/gammln/NEq",
    "Ran/ranzero/Eq",
    "Ran/ranzero/NEq",
    "caldat/julday/Eq",
    "caldat/julday/NEq",
    "dart/test/Eq",
    "dart/test/NEq",
    "gam/ei/Eq",
    "gam/ei/NEq",
    "gam/erfcc/Eq",
    "gam/erfcc/NEq",
    "power/test/Eq",
    "power/test/NEq",
}


def run_command(cmd: list[str], description: str, timeout_seconds: int | None = None) -> bool:
    """Run a command from the repository root and show progress."""
    print(f"\n{'=' * 60}")
    print(f"Running: {description}")
    print("Command:", " ".join(str(part) for part in cmd))
    if timeout_seconds:
        print(f"Timeout: {timeout_seconds} seconds")
    print(f"{'=' * 60}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - start
        print(f"Elapsed time: {elapsed:.2f} seconds")
        print("Status: timeout; skipping this case")
        stdout_text = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr_text = exc.stderr.decode("utf-8", errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        if stdout_text.strip():
            print("stdout before timeout:")
            print(stdout_text)
        if stderr_text.strip():
            print("stderr before timeout:")
            print(stderr_text)
        return False

    elapsed = time.time() - start
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


def canonical_case_rel(rel: str) -> str:
    """Normalize case paths to Family/Method/Eq|NEq."""
    rel = rel.replace("\\", "/")
    parts = [part for part in rel.split("/") if part and part != "."]
    if len(parts) == 3 and parts[1] in {"Eq", "NEq"}:
        return f"{parts[0]}/{parts[2]}/{parts[1]}"
    return rel


def discover_cases(bench_root: Path, case_type: str = "all", target_only: bool = True) -> list[Path]:
    """Find benchmark case directories containing old/new C sources."""
    cases: list[Path] = []
    for root, _, files in os.walk(bench_root):
        if "symbolic_oldV.c" not in files or "symbolic_newV.c" not in files:
            continue
        root_path = Path(root)
        last = root_path.name
        parent = root_path.parent.name
        if last in {"Eq", "NEq"}:
            eqneq = last
        elif parent in {"Eq", "NEq"}:
            eqneq = parent
        else:
            continue
        if case_type in {"Eq", "NEq"} and eqneq != case_type:
            continue
        if target_only and canonical_case_rel(os.path.relpath(root_path, bench_root)) not in TARGET_CASES:
            continue
        cases.append(root_path)
    return sorted(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch ARDiff analysis: compile, symbolically execute, and compare.")
    parser.add_argument("--bench-root", type=Path, default=DEFAULT_BENCH_ROOT, help="Benchmark root directory")
    parser.add_argument("--type", choices=["Eq", "NEq", "all"], default="all", help="Case type filter")
    parser.add_argument("--case-timeout", type=int, default=600, help="Maximum seconds per case")
    parser.add_argument("--all-cases", action="store_true", help="Disable the target-case allowlist")
    args = parser.parse_args()

    bench_root = args.bench_root if args.bench_root.is_absolute() else REPO_ROOT / args.bench_root
    if not bench_root.is_dir():
        print(f"Benchmark root does not exist: {bench_root}")
        return 1
    if not RUN_ONE_SCRIPT.is_file():
        print(f"Single-case runner not found: {RUN_ONE_SCRIPT}")
        return 1

    print(f"Repository root: {REPO_ROOT}")
    print(f"Benchmark root: {bench_root}")
    print(f"Single-case runner: {RUN_ONE_SCRIPT}")

    cases = discover_cases(bench_root, args.type, target_only=not args.all_cases)
    if not cases:
        print("No benchmark cases were found under the selected root.")
        return 1

    print(f"\nDiscovered {len(cases)} cases:")
    for case in cases:
        print(f"  - {os.path.relpath(case, bench_root)}")

    success = 0
    failed = 0
    for idx, case_dir in enumerate(cases, 1):
        rel = os.path.relpath(case_dir, bench_root)
        cmd = [str(RUN_ONE_SCRIPT), str(case_dir)]
        if run_command(cmd, f"[{idx}/{len(cases)}] {rel}", timeout_seconds=args.case_timeout):
            success += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print("Batch analysis completed")
    print(f"  Success: {success}")
    print(f"  Failed: {failed}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
