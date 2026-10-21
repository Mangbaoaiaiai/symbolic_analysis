#!/usr/bin/env python3
"""Run the paper benchmark or the complete OSF benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from symbolic_analysis.profile import (  # noqa: E402
    DEFAULT_FLOAT_MAX,
    DEFAULT_FLOAT_MIN,
    DEFAULT_INT_MAX,
    DEFAULT_INT_MIN,
    LOOP_BOUND,
    MAX_PATHS,
    OSF_PROFILE_ID,
    RANKING_TRUTH_TIMEOUT_MS,
    SMT_TIMEOUT_MS,
    SYMBOLIC_EXECUTION_TIMEOUT_SECONDS,
    VERIFIER_WALL_TIMEOUT_SECONDS,
)

PYTHON = sys.executable
BENCHMARKS_ARCHIVE = ROOT / "benchmark" / "osf_benchmarks.zip"
BENCHMARKS_EXTRACTED = ROOT / "work" / "benchmark_sources"
BENCHMARKS_SOURCE = BENCHMARKS_EXTRACTED / "benchmarks"
PREPARED_ROOT = ROOT / "work" / "osf_prepared"
PREPARED_CASES = PREPARED_ROOT / "benchmarks_typed"
PAPER_INT_MIN = str(DEFAULT_INT_MIN)
PAPER_INT_MAX = str(DEFAULT_INT_MAX)
PAPER_FLOAT_MIN = str(DEFAULT_FLOAT_MIN)
PAPER_FLOAT_MAX = str(DEFAULT_FLOAT_MAX)
OSF_STAGE1_MAX_PATHS = 2048
OSF_STAGE1_LOOP_BOUND = LOOP_BOUND
OSF_STAGE2_MAX_PATHS = 8192
OSF_STAGE2_LOOP_BOUND = 128
OSF_SYMBOLIC_TIMEOUT_SECONDS = 600
OSF_RETRY_SYMBOLIC_TIMEOUT_SECONDS = 1200
OSF_VERIFIER_TIMEOUT_SECONDS = 600


def resolve_run_names(
    suite: str,
    requested: str | None,
) -> tuple[str, str]:
    """Return collision-free paper and OSF run labels for a suite."""
    if suite == "all":
        if requested:
            return f"{requested}_paper", f"{requested}_osf"
        return "paper", "osf"
    label = requested or suite
    return label, label


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
    int_min: str | None = None,
    int_max: str | None = None,
    float_min: str | None = None,
    float_max: str | None = None,
    case_domains: Path | None = None,
    families: list[str] | None = None,
    exclude_families: list[str] | None = None,
    max_cases: int | None = None,
    fresh: bool = False,
    run_controls: bool = True,
    max_paths: int = MAX_PATHS,
    loop_bound: int = LOOP_BOUND,
    symbolic_timeout: int = SYMBOLIC_EXECUTION_TIMEOUT_SECONDS,
    verifier_timeout: int = VERIFIER_WALL_TIMEOUT_SECONDS,
    profile_id: str = "paper.v3-20261020",
    annotate_path_truth: bool = True,
    ranking_candidates: int | None = None,
    skip_control_rankings: bool = False,
    bindiff_mode: str = "auto",
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
        str(symbolic_timeout),
        "--max-paths",
        str(max_paths),
        "--loop-bound",
        str(loop_bound),
        "--profile-id",
        profile_id,
        "--optimization",
        "O3",
        "--bindiff-mode",
        bindiff_mode,
        "--skip-semantic-truth",
        "--skip-ranking-truth",
        "--skip-evaluation",
    ]
    if ranking_candidates is not None:
        command.extend(["--ranking-candidates", str(ranking_candidates)])
    if skip_control_rankings:
        command.append("--skip-control-rankings")
    if case_domains is not None:
        command.extend(["--case-domains", str(case_domains)])
    command.extend(domain_arguments(int_min, int_max, float_min, float_max))
    for family in families or []:
        command.extend(["--family", family])
    for family in exclude_families or []:
        command.extend(["--exclude-family", family])
    if fresh:
        command.append("--force-symbolic-exec")
    if max_cases is not None:
        command.extend(["--max-cases", str(max_cases)])
    run(command)
    if annotate_path_truth:
        run(
            [
                PYTHON,
                "scripts/annotate_path_truth.py",
                "--benchmarks",
                str(path_root),
                "--timeout-ms",
                str(RANKING_TRUTH_TIMEOUT_MS),
            ]
        )
    groups = ["fmcad_align"]
    if run_controls:
        groups = ["naive", "veribin_align", "fmcad_align"]
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
            str(verifier_timeout),
            "--smt-timeout-ms",
            str(SMT_TIMEOUT_MS),
            "--require-manifest",
            "--groups",
            *groups,
        ]
    )
    if run_controls:
        run(
            [
                PYTHON,
                "run_evaluation.py",
                "--benchmarks",
                str(path_root),
                "--ground-truth",
                str(path_root / "groundtruth.json"),
                "--output-dir",
                str(eval_root.parent / "evaluation_one_to_one"),
                "--python",
                PYTHON,
                "--execute",
                "--timeout",
            str(verifier_timeout),
                "--smt-timeout-ms",
                str(SMT_TIMEOUT_MS),
                "--require-manifest",
                "--groups",
                "fmcad_align",
                "--one-to-one-only",
            ]
        )
    return path_root, eval_root


def domain_arguments(
    int_min: str | None,
    int_max: str | None,
    float_min: str | None,
    float_max: str | None,
) -> list[str]:
    """Translate explicit bounds into SE arguments; omit them for full domains."""
    command: list[str] = []
    for flag, value in (
        ("--int-min", int_min),
        ("--int-max", int_max),
        ("--float-min", float_min),
        ("--float-max", float_max),
    ):
        if value is not None:
            command.extend([flag, value])
    return command


def run_paper(
    max_cases: int | None = None,
    fresh: bool = False,
    run_name: str = "paper",
    paper_manifest: Path = Path("configs/paper_62.csv"),
) -> None:
    prepare_osf()
    full_run = max_cases is None
    fixed_manifest = ROOT / paper_manifest
    paths, eval_root = build_paths(
        run_name,
        fixed_manifest,
        int_min=PAPER_INT_MIN,
        int_max=PAPER_INT_MAX,
        float_min=PAPER_FLOAT_MIN,
        float_max=PAPER_FLOAT_MAX,
        case_domains=ROOT / "configs" / "paper_62_domains.csv",
        max_cases=max_cases,
        fresh=fresh,
        run_controls=full_run,
    )
    if not full_run:
        print(
            "Smoke mode: skipping fixed-62 cross-shard summaries and audit.",
            flush=True,
        )
        return
    run(
        [
            PYTHON,
            "scripts/summarize_paper_eval.py",
            "--paper-manifest",
            str(paper_manifest),
            "--benchmarks",
            str(paths),
            "--eval-root",
            str(eval_root),
            "--output-dir",
            f"results/rerun/{run_name}",
        ]
    )
    one_to_one = eval_root.parent / "evaluation_one_to_one"
    run(
        [
            PYTHON,
            "scripts/summarize_method_comparison.py",
            "--input",
            f"hybrid:fmcad_align={eval_root}",
            "--input",
            f"naive:naive={eval_root}",
            "--input",
            f"veribin_internal:veribin_align={eval_root}",
            "--input",
            f"hybrid_one_to_one:fmcad_align={one_to_one}",
            "--expected-cases",
            "62",
            "--include-case-manifest",
            str(paper_manifest),
            "--output-dir",
            f"results/rerun/{run_name}/method_comparison",
        ]
    )
    run(
        [
            PYTHON,
            "scripts/audit_paper_eval.py",
            "--paper-manifest",
            str(paper_manifest),
            "--benchmarks",
            str(paths),
            "--method",
            f"hybrid:fmcad_align={eval_root}",
            "--method",
            f"naive:naive={eval_root}",
            "--method",
            f"veribin_internal:veribin_align={eval_root}",
            "--method",
            f"hybrid_one_to_one:fmcad_align={one_to_one}",
            "--output-dir",
            f"results/rerun/{run_name}/audit",
        ]
    )
    run(
        [
            PYTHON,
            "scripts/audit_ub_full62.py",
            "--paper-cases",
            f"results/rerun/{run_name}/paper_cases.csv",
            "--eval-root",
            str(eval_root),
            "--output-dir",
            f"results/rerun/{run_name}/ub_audit",
        ]
    )
    run(
        [
            PYTHON,
            "scripts/write_run_metadata.py",
            "--output",
            f"results/rerun/{run_name}/run_metadata.json",
            "--image",
            os.environ.get("SYMBOLICANA_IMAGE", "unspecified"),
            "--command",
            (
                f"scripts/run_suite.py --suite paper --run-name {run_name} "
                f"--paper-manifest {paper_manifest}"
            ),
        ]
    )


def normalize_case_path(value: str) -> str:
    """Return the OSF-relative case path for manifests and artifact paths."""
    normalized = value.replace("\\", "/").strip("/")
    for marker in ("benchmarks_typed/", "benchmarks/", "paths/cases/", "cases/"):
        position = normalized.find(marker)
        if position >= 0:
            normalized = normalized[position + len(marker) :]
            break
    if normalized.endswith("/paths"):
        normalized = normalized[: -len("/paths")]
    return normalized.strip("/").lower()


def generation_failures(path_root: Path) -> set[str]:
    summary = path_root / "generation_summary.json"
    if not summary.is_file():
        return set()
    payload = json.loads(summary.read_text(encoding="utf-8"))
    return {
        normalize_case_path(str(item.get("case", "")))
        for item in payload.get("failures", [])
        if item.get("case")
    }


def artifact_path(path_root: Path, value: str) -> Path:
    """Resolve a path written by either the host or the Linux container."""
    normalized = value.replace("\\", "/")
    for marker in ("/workspace/repo/", "/workspace/symbolic_analysis/"):
        if normalized.startswith(marker):
            return ROOT / normalized[len(marker) :]
    candidate = Path(value)
    return candidate if candidate.is_absolute() else path_root / candidate


def retry_reasons(path_root: Path) -> dict[str, list[str]]:
    """Find cases without complete, auditable symbolic exploration evidence."""
    reasons: dict[str, set[str]] = {}

    def add(case: str, reason: str) -> None:
        normalized = normalize_case_path(case)
        if normalized:
            reasons.setdefault(normalized, set()).add(reason)

    for case in generation_failures(path_root):
        add(case, "generation_failed")

    manifest = path_root / "manifest.json"
    if not manifest.is_file():
        return {case: sorted(values) for case, values in reasons.items()}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {case: sorted(values) for case, values in reasons.items()}

    for failure in payload.get("failures", []):
        case = str(failure.get("case") or "")
        if case:
            add(case, "generation_failed")

    for pair in payload.get("pairs", []):
        raw_paths_dir = str(pair.get("paths_dir") or "")
        case = str(pair.get("source_case") or raw_paths_dir)
        if not case:
            continue
        paths_dir = artifact_path(path_root, raw_paths_dir) if raw_paths_dir else path_root
        for prefix in ("symbolic_oldV", "symbolic_newV"):
            exploration_path = paths_dir / f"{prefix}_exploration.json"
            if not exploration_path.is_file():
                add(case, f"missing_{prefix}_exploration")
            else:
                try:
                    exploration = json.loads(
                        exploration_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    add(case, f"unreadable_{prefix}_exploration")
                else:
                    if exploration.get("complete") is not True:
                        add(case, f"incomplete_{prefix}_exploration")
            if (paths_dir / f"{prefix}_failure.json").is_file():
                add(case, f"{prefix}_failure_marker")
            if not list(paths_dir.glob(f"{prefix}_path_*.txt")):
                add(case, f"missing_{prefix}_paths")

    return {case: sorted(values) for case, values in reasons.items()}


def write_retry_manifest(
    source: Path,
    failures: set[str],
    target: Path,
) -> int:
    with source.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = list(reader.fieldnames or [])
        rows = [
            row
            for row in reader
            if normalize_case_path(row.get("source_case", "")) in failures
        ]
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def staged_attempt_record(
    name: str,
    path_root: Path,
    *,
    max_paths: int,
    loop_bound: int,
    symbolic_timeout: int,
) -> dict[str, object]:
    failures = generation_failures(path_root)
    retry = retry_reasons(path_root)
    manifest = path_root / "manifest.json"
    generated = 0
    if manifest.is_file():
        generated = len(json.loads(manifest.read_text(encoding="utf-8")).get("pairs", []))
    return {
        "name": name,
        "path_root": path_root.as_posix(),
        "generated_cases": generated,
        "failed_cases": len(failures),
        "failed_case_ids": sorted(failures),
        "retry_required_cases": len(retry),
        "retry_reasons": retry,
        "configuration": {
            "profile_id": OSF_PROFILE_ID,
            "max_paths": max_paths,
            "loop_bound": loop_bound,
            "symbolic_timeout_seconds": symbolic_timeout,
            "verifier_timeout_seconds": OSF_VERIFIER_TIMEOUT_SECONDS,
            "input_domain": "full_representable_input_space",
        },
    }


def run_osf(
    max_cases: int | None = None,
    fresh: bool = False,
    run_name: str = "osf",
    case_manifest: Path | None = None,
    prepare: bool = True,
) -> None:
    if prepare:
        prepare_osf()
    manifest = case_manifest or (PREPARED_ROOT / "manifest_all.csv")
    path_roots: list[Path] = []
    eval_roots: list[Path] = []
    attempts: list[dict[str, object]] = []

    stage1_paths, stage1_eval = build_paths(
        f"{run_name}_stage1",
        manifest,
        max_cases=max_cases,
        fresh=fresh,
        run_controls=False,
        max_paths=OSF_STAGE1_MAX_PATHS,
        loop_bound=OSF_STAGE1_LOOP_BOUND,
        symbolic_timeout=OSF_SYMBOLIC_TIMEOUT_SECONDS,
        verifier_timeout=OSF_VERIFIER_TIMEOUT_SECONDS,
        profile_id=OSF_PROFILE_ID,
        annotate_path_truth=False,
        ranking_candidates=64,
        skip_control_rankings=True,
        bindiff_mode="off",
    )
    path_roots.append(stage1_paths)
    eval_roots.append(stage1_eval)
    attempts.append(
        staged_attempt_record(
            "stage1",
            stage1_paths,
            max_paths=OSF_STAGE1_MAX_PATHS,
            loop_bound=OSF_STAGE1_LOOP_BOUND,
            symbolic_timeout=OSF_SYMBOLIC_TIMEOUT_SECONDS,
        )
    )

    retry = retry_reasons(stage1_paths)
    retry_cases = set(retry)
    retry_manifest = ROOT / "work" / run_name / "stage2_retry_manifest.csv"
    retry_count = write_retry_manifest(manifest, retry_cases, retry_manifest)
    if retry_count:
        stage2_paths, stage2_eval = build_paths(
            f"{run_name}_stage2",
            retry_manifest,
            max_cases=max_cases,
            fresh=True,
            run_controls=False,
            max_paths=OSF_STAGE2_MAX_PATHS,
            loop_bound=OSF_STAGE2_LOOP_BOUND,
            symbolic_timeout=OSF_RETRY_SYMBOLIC_TIMEOUT_SECONDS,
            verifier_timeout=OSF_VERIFIER_TIMEOUT_SECONDS,
            profile_id=OSF_PROFILE_ID,
            annotate_path_truth=False,
            ranking_candidates=64,
            skip_control_rankings=True,
            bindiff_mode="off",
        )
        path_roots.append(stage2_paths)
        eval_roots.append(stage2_eval)
        attempts.append(
            staged_attempt_record(
                "stage2",
                stage2_paths,
                max_paths=OSF_STAGE2_MAX_PATHS,
                loop_bound=OSF_STAGE2_LOOP_BOUND,
                symbolic_timeout=OSF_RETRY_SYMBOLIC_TIMEOUT_SECONDS,
            )
        )

    summary_command = [
        PYTHON,
        "scripts/summarize_osf_all.py",
        "--manifest",
        str(manifest),
        "--result-group",
        "fmcad_align",
        "--label-audit-csv",
        "configs/osf_label_audit.csv",
        "--prefer-later-path-root",
        "--output-dir",
        f"results/rerun/{run_name}",
    ]
    for path_root in path_roots:
        summary_command.extend(["--path-root", str(path_root)])
    for eval_root in eval_roots:
        summary_command.extend(["--eval-root", str(eval_root)])
    run(summary_command)

    output_root = ROOT / "results" / "rerun" / run_name
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "attempts.json").write_text(
        json.dumps(
            {
                "schema": "symbolicana.osf_staged_attempts.v1",
                "run_name": run_name,
                "attempts": attempts,
                "retry_manifest": retry_manifest.as_posix(),
                "retry_cases": retry_count,
                "stage2_retry_reasons": retry,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    audit_command = [
        PYTHON,
        "scripts/audit_osf_full.py",
        "--manifest",
        str(manifest),
        "--label-audit-csv",
        "configs/osf_label_audit.csv",
        "--output-dir",
        f"results/rerun/{run_name}/audit",
    ]
    for attempt, path_root, eval_root in zip(attempts, path_roots, eval_roots):
        audit_command.extend(
            [
                "--attempt-name",
                str(attempt["name"]),
                "--path-root",
                str(path_root),
                "--eval-root",
                str(eval_root),
            ]
        )
    run(audit_command)


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
    parser.add_argument(
        "--run-name",
        help=(
            "Run label. Defaults to the suite name; --suite all writes separate "
            "paper and OSF result directories."
        ),
    )
    parser.add_argument(
        "--paper-manifest",
        type=Path,
        default=Path("configs/paper_62.csv"),
    )
    parser.add_argument(
        "--osf-manifest",
        type=Path,
        help="Optional OSF case manifest, used for balanced sharded execution.",
    )
    parser.add_argument(
        "--skip-prepare",
        action="store_true",
        help="Reuse an already prepared OSF benchmark in a shard run.",
    )
    args = parser.parse_args()

    run_tests()
    paper_run_name, osf_run_name = resolve_run_names(args.suite, args.run_name)
    if args.suite in {"paper", "all"}:
        run_paper(
            args.max_cases,
            args.fresh,
            paper_run_name,
            args.paper_manifest,
        )
    if args.suite in {"osf", "all"}:
        run_osf(
            args.max_cases,
            args.fresh,
            osf_run_name,
            args.osf_manifest,
            not args.skip_prepare,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
