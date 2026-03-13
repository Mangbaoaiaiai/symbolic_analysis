#!/usr/bin/env python3
"""
Save a complete ARDiff experiment log snapshot.

Collects benchmark outputs, key scripts, optional terminal logs,
and writes both a folder snapshot and a tar.gz archive.
"""

import argparse
import datetime
import json
import os
import shutil
import tarfile
from pathlib import Path


def now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def rel_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def copy_file(src: Path, dst_root: Path, repo_root: Path, copied: list[str]) -> None:
    if not src.is_file():
        return
    rel = rel_to_repo(src, repo_root)
    dst = dst_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied.append(rel)


def collect_by_patterns(repo_root: Path, out_root: Path, patterns: list[str], copied: list[str]) -> None:
    for pattern in patterns:
        for src in repo_root.glob(pattern):
            if src.is_file():
                copy_file(src, out_root, repo_root, copied)


def collect_terminal_logs(terminals_dir: Path | None, out_root: Path, copied: list[str]) -> None:
    if terminals_dir is None or not terminals_dir.is_dir():
        return
    target_dir = out_root / "external_logs" / "terminals"
    target_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(terminals_dir.glob("*.txt")):
        dst = target_dir / src.name
        shutil.copy2(src, dst)
        copied.append(f"external_logs/terminals/{src.name}")


def create_archive(snapshot_dir: Path) -> Path:
    archive_path = snapshot_dir.with_suffix(".tar.gz")
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(snapshot_dir, arcname=snapshot_dir.name)
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Save complete ARDiff experiment logs.")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root directory (default: current directory).",
    )
    parser.add_argument(
        "--out-dir",
        default="experiments/ardiff_comparison/experiment_logs",
        help="Output parent directory for snapshots.",
    )
    parser.add_argument(
        "--terminals-dir",
        default=None,
        help="Optional terminals directory (e.g. /root/.cursor/projects/.../terminals).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    out_parent = (repo_root / args.out_dir).resolve()
    stamp = now_stamp()
    snapshot_dir = out_parent / f"snapshot_{stamp}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []

    # 1) Main summary reports
    key_files = [
        repo_root / "experiments/ardiff_comparison/benchmark_summary.md",
    ]
    for f in key_files:
        copy_file(f, snapshot_dir, repo_root, copied)

    # 2) Benchmark outputs (full)
    collect_by_patterns(
        repo_root,
        snapshot_dir,
        patterns=[
            "experiments/ardiff_comparison/benchmarks/**/enhanced_equivalence_report.txt",
            "experiments/ardiff_comparison/benchmarks/**/*_timing_report.txt",
            "experiments/ardiff_comparison/benchmarks/**/*_path_*.txt",
            "experiments/ardiff_comparison/benchmarks/**/symbolic_oldV",
            "experiments/ardiff_comparison/benchmarks/**/symbolic_newV",
        ],
        copied=copied,
    )

    # 3) Key scripts/config used in experiment
    script_files = [
        "scripts/se_script.py",
        "scripts/ardiff_comparison/run_benchmark_analysis.py",
        "scripts/ardiff_comparison/semantic_equivalence_analyzer_enhanced.py",
        "experiments/ardiff_comparison/run_one_benchmark.py",
        "experiments/ardiff_comparison/run_one_benchmark.sh",
    ]
    for rel in script_files:
        copy_file(repo_root / rel, snapshot_dir, repo_root, copied)

    # 4) Optional terminal logs
    terminals_dir = Path(args.terminals_dir).resolve() if args.terminals_dir else None
    collect_terminal_logs(terminals_dir, snapshot_dir, copied)

    # 5) Manifest
    manifest = {
        "created_at": datetime.datetime.now().isoformat(),
        "repo_root": str(repo_root),
        "snapshot_dir": str(snapshot_dir),
        "total_files": len(copied),
        "files": sorted(copied),
    }
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # 6) Tar.gz archive
    archive_path = create_archive(snapshot_dir)

    print(f"Snapshot saved: {snapshot_dir}")
    print(f"Archive saved:  {archive_path}")
    print(f"Files copied:   {len(copied)} (+ manifest.json)")


if __name__ == "__main__":
    main()

