#!/usr/bin/env python3
"""Annotate a generated benchmark with independent SAT-overlap path truth."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from generate_path_truth import compute_pair_truth


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def path_files(paths_dir: Path, prefix: str) -> list[Path]:
    files = sorted(paths_dir.glob(f"{prefix}_path_*.txt"))
    if not files:
        raise ValueError(f"no {prefix} path files in {paths_dir}")
    return files


def annotate(
    benchmark_root: Path,
    *,
    timeout_ms: int,
    force: bool,
    old_prefix: str,
    new_prefix: str,
) -> dict[str, Any]:
    manifest_path = benchmark_root / "manifest.json"
    groundtruth_path = benchmark_root / "groundtruth.json"
    manifest = load_json(manifest_path)
    groundtruth = load_json(groundtruth_path)
    pairs = manifest.get("pairs") or []
    truth_by_pair = {
        str(pair.get("pair_id")): pair
        for pair in groundtruth.get("pairs") or []
        if pair.get("pair_id")
    }
    started = time.perf_counter()
    annotated = 0
    reused = 0
    failures: list[dict[str, str]] = []
    case_timings: list[dict[str, Any]] = []

    for pair in pairs:
        pair_id = str(pair.get("pair_id") or "")
        try:
            paths_dir = (benchmark_root / str(pair["paths_dir"])).resolve()
            old_paths = path_files(paths_dir, old_prefix)
            new_paths = path_files(paths_dir, new_prefix)
            expected_queries = {path.stem for path in old_paths}
            expected_targets = {path.stem for path in new_paths}
            existing = pair.get("path_truth")
            reusable = (
                not force
                and isinstance(existing, dict)
                and existing.get("status", "complete") == "complete"
                and {
                    str(item.get("query"))
                    for item in existing.get("queries", [])
                    if isinstance(item, dict)
                }
                == expected_queries
                and all(
                    {
                        str(target.get("target"))
                        for target in item.get("targets", [])
                        if isinstance(target, dict)
                    }
                    == expected_targets
                    for item in existing.get("queries", [])
                    if isinstance(item, dict)
                )
            )
            if reusable:
                path_truth = existing
                related = {
                    str(item["query"]): set(item.get("related_targets") or [])
                    for item in path_truth.get("queries", [])
                }
                case_seconds = 0.0
                reused += 1
            else:
                case_started = time.perf_counter()
                related, path_truth = compute_pair_truth(
                    old_paths,
                    new_paths,
                    timeout_ms,
                )
                path_truth["status"] = "complete"
                case_seconds = time.perf_counter() - case_started
                pair["path_truth"] = path_truth
                pair["ground_truth_pairs"] = {
                    query: sorted(targets)
                    for query, targets in related.items()
                }
                truth_pair = truth_by_pair.get(pair_id)
                if truth_pair is not None:
                    truth_pair["path_truth"] = path_truth
                    truth_pair["ground_truth_pairs"] = pair["ground_truth_pairs"]
                write_json(paths_dir.parent / "path_truth.json", path_truth)
                annotated += 1
                write_json(manifest_path, manifest)
                write_json(groundtruth_path, groundtruth)
            case_timings.append(
                {
                    "pair_id": pair_id,
                    "status": "reused" if reusable else "computed",
                    "seconds": case_seconds,
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"pair_id": pair_id, "error": str(exc)})
            print(f"path truth failed for {pair_id}: {exc}", flush=True)

    write_json(manifest_path, manifest)
    write_json(groundtruth_path, groundtruth)
    summary = {
        "schema": "symbolicana.path_truth_annotation.v1",
        "benchmark_root": str(benchmark_root),
        "timeout_ms": timeout_ms,
        "cases_total": len(pairs),
        "cases_annotated": annotated,
        "cases_reused": reused,
        "failures": failures,
        "elapsed_seconds": time.perf_counter() - started,
        "case_timings": case_timings,
    }
    write_json(benchmark_root / "path_truth_summary.json", summary)
    if failures:
        raise RuntimeError(
            f"path truth failed for {len(failures)} of {len(pairs)} cases"
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmarks",
        type=Path,
        required=True,
        help="Benchmark root containing manifest.json and groundtruth.json.",
    )
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--old-prefix", default="symbolic_oldV")
    parser.add_argument("--new-prefix", default="symbolic_newV")
    args = parser.parse_args()
    summary = annotate(
        args.benchmarks.resolve(),
        timeout_ms=args.timeout_ms,
        force=args.force,
        old_prefix=args.old_prefix,
        new_prefix=args.new_prefix,
    )
    print(
        f"annotated {summary['cases_annotated']} cases "
        f"({summary['cases_reused']} reused) in "
        f"{summary['elapsed_seconds']:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
