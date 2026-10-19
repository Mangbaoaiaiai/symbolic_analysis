#!/usr/bin/env python3
"""Run the paper benchmark or the complete OSF benchmark."""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
BENCHMARKS_ARCHIVE = ROOT / "benchmark" / "osf_benchmarks.zip"
BENCHMARKS_EXTRACTED = ROOT / "work" / "benchmark_sources"
BENCHMARKS_SOURCE = BENCHMARKS_EXTRACTED / "benchmarks"
PREPARED_ROOT = ROOT / "work" / "osf_prepared"
PREPARED_CASES = PREPARED_ROOT / "benchmarks_typed"


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def prepare_osf() -> None:
    BENCHMARKS_EXTRACTED.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BENCHMARKS_ARCHIVE) as archive:
        archive.extractall(BENCHMARKS_EXTRACTED)
    run(
        [
            PYTHON,
            "scripts/prepare_osf_all.py",
            "--osf-root",
            str(BENCHMARKS_SOURCE),
            "--output-root",
            str(PREPARED_ROOT),
            "--ardiff-script",
            str(ROOT / "benchmark" / "ardiff" / "RunningBenchmarksOnLinux.sh"),
        ]
    )


def build_paths(
    name: str,
    case_manifest: Path,
    *,
    int_min: str = "-100",
    int_max: str = "100",
    float_min: str = "-100.0",
    float_max: str = "100.0",
    max_cases: int | None = None,
    fresh: bool = False,
) -> tuple[Path, Path]:
    path_root = ROOT / "work" / name / "paths"
    eval_root = ROOT / "work" / name / "evaluation"
    command = [
        PYTHON,
        "build_ardiff_path_benchmarks.py",
        "--benchmarks",
        str(PREPARED_CASES),
        "--case-manifest",
        str(case_manifest),
        "--out-dir",
        str(path_root),
        "--eval-output-dir",
        str(eval_root),
        "--python",
        PYTHON,
        "--timeout",
        "600",
        "--max-paths",
        "128",
        "--optimization",
        "O3",
        "--int-min",
        int_min,
        "--int-max",
        int_max,
        f"--float-min={float_min}",
        f"--float-max={float_max}",
        "--skip-semantic-truth",
        "--skip-evaluation",
    ]
    if fresh:
        command.append("--force-symbolic-exec")
    if max_cases is not None:
        command.extend(["--max-cases", str(max_cases)])
    run(command)
    run(
        [
            PYTHON,
            "run_evaluation.py",
            "--benchmarks",
            str(path_root),
            "--ground-truth",
            str(path_root / "groundtruth.json"),
            "--output-dir",
            str(eval_root),
            "--python",
            PYTHON,
            "--execute",
            "--timeout",
            "86400",
            "--smt-timeout-ms",
            "60000",
            "--require-manifest",
            "--groups",
            "fmcad_align",
        ]
    )
    return path_root, eval_root


def run_paper(max_cases: int | None = None, fresh: bool = False) -> None:
    prepare_osf()
    default_paths, default_eval = build_paths(
        "paper_default",
        ROOT / "configs" / "paper_candidates.csv",
        max_cases=max_cases,
        fresh=fresh,
    )
    ell_paths, ell_eval = build_paths(
        "paper_ell_bounded10",
        ROOT / "configs" / "ell_cases.csv",
        int_min="0",
        int_max="10",
        float_min="-10.0",
        float_max="10.0",
        max_cases=max_cases,
        fresh=fresh,
    )
    run(
        [
            PYTHON,
            "scripts/summarize_paper_eval.py",
            "--paper-manifest",
            "configs/paper_candidates.csv",
            "--benchmarks",
            str(default_paths),
            "--supplemental-benchmarks",
            str(ell_paths),
            "--eval-root",
            str(default_eval),
            "--eval-root",
            str(ell_eval),
            "--output-dir",
            "results/rerun/paper",
        ]
    )


def run_osf(max_cases: int | None = None, fresh: bool = False) -> None:
    prepare_osf()
    default_paths, default_eval = build_paths(
        "osf_default",
        PREPARED_ROOT / "manifest_all.csv",
        max_cases=max_cases,
        fresh=fresh,
    )
    ell_paths, ell_eval = build_paths(
        "osf_ell_bounded10",
        ROOT / "configs" / "ell_cases.csv",
        int_min="0",
        int_max="10",
        float_min="-10.0",
        float_max="10.0",
        max_cases=max_cases,
        fresh=fresh,
    )
    tcas_paths, tcas_eval = build_paths(
        "osf_tcas_full32",
        ROOT / "configs" / "tcas_cases.csv",
        int_min="-2147483648",
        int_max="2147483647",
        max_cases=max_cases,
        fresh=fresh,
    )
    command = [
        PYTHON,
        "scripts/summarize_osf_all.py",
        "--manifest",
        str(PREPARED_ROOT / "manifest_all.csv"),
        "--path-root",
        str(default_paths),
        "--path-root",
        str(ell_paths),
        "--path-root",
        str(tcas_paths),
        "--prefer-later-path-root",
        "--eval-root",
        str(default_eval),
        "--eval-root",
        str(ell_eval),
        "--eval-root",
        str(tcas_eval),
        "--result-group",
        "fmcad_align",
        "--label-audit-csv",
        "configs/osf_label_audit.csv",
        "--output-dir",
        "results/rerun/osf",
    ]
    run(command)


def run_tests() -> None:
    run([PYTHON, "-m", "unittest", "discover", "-s", "tests", "-v"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("tests", "paper", "osf", "all"),
        default="paper",
    )
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    run_tests()
    if args.suite in {"paper", "all"}:
        run_paper(args.max_cases, args.fresh)
    if args.suite in {"osf", "all"}:
        run_osf(args.max_cases, args.fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
