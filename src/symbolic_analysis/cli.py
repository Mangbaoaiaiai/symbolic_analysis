"""Command-line entry point for the Symbolicana toolkit."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from symbolic_analysis.analysis.hybrid_path_matching import (
    HybridConfig,
    hybrid_rank_paths,
    load_matching_bb_map,
)
from symbolic_analysis.analysis.path_constraint_features import (
    FEATURE_RANGES,
    extract_features,
    normalize_features,
)


FEATURE_NAMES = [
    "assert_count",
    "variable_count",
    "main_bv_width",
    "operator_type_count",
    "comparison_ratio",
    "nest_depth",
    "dominant_constant_type",
    "variable_range_span",
    "shift_coefficient",
    "extend_count",
    "extract_count",
]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    return args.handler(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="symbolicana",
        description="Symbolic execution, path ranking, and path equivalence verification.",
    )
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check-deps", help="Check optional runtime dependencies.")
    check.set_defaults(handler=cmd_check_deps)

    se = sub.add_parser("symbolic-exec", help="Generate path constraints for one binary.")
    se.add_argument("--binary", type=Path, required=True)
    se.add_argument("--output-prefix", required=True)
    se.add_argument("--timeout", type=int, default=120)
    se.add_argument("--signature", help="Snippet signature, e.g. double(double,int)")
    se.set_defaults(handler=cmd_symbolic_exec)

    vectors = sub.add_parser("vectors", help="Generate 11-dimensional path feature vectors.")
    vectors.add_argument("--paths-dir", type=Path)
    vectors.add_argument("--path-file", type=Path)
    vectors.add_argument("--out", type=Path, default=Path("path_feature_vectors.json"))
    vectors.add_argument("--normalize", action="store_true")
    vectors.add_argument("--include-min-max", action="store_true")
    vectors.set_defaults(handler=cmd_vectors)

    rank = sub.add_parser("rank", help="Rank old/new path candidates with hybrid matching.")
    rank.add_argument("--old-paths-dir", type=Path)
    rank.add_argument("--new-paths-dir", type=Path)
    rank.add_argument("--old-prefix")
    rank.add_argument("--new-prefix")
    rank.add_argument("--old-path", type=Path, action="append", default=[])
    rank.add_argument("--new-path", type=Path, action="append", default=[])
    rank.add_argument("--matching-bb-map", type=Path)
    rank.add_argument("--high-threshold", type=float, default=0.80)
    rank.add_argument("--margin-threshold", type=float, default=0.05)
    rank.add_argument("--graph-min-score", type=float, default=0.01)
    rank.add_argument("--graph-weight", type=float, default=1.0)
    rank.add_argument("--feature-weight", type=float, default=0.0)
    rank.add_argument("--out", type=Path, default=Path("hybrid_path_ranking.json"))
    rank.set_defaults(handler=cmd_rank)

    verify = sub.add_parser("verify", help="Verify path equivalence using a ranked queue.")
    verify.add_argument("--paths-dir", type=Path, required=True)
    verify.add_argument("--ranking", type=Path)
    verify.add_argument("--out", type=Path, required=True)
    verify.add_argument("--timeout-ms", type=int, default=30_000)
    verify.add_argument("--naive", action="store_true")
    verify.add_argument("--truth-pairs-json")
    verify.add_argument("--program-ground-truth")
    verify.set_defaults(handler=cmd_verify)

    return parser


def cmd_check_deps(_args: argparse.Namespace) -> int:
    deps = ["angr", "claripy", "z3"]
    ok = True
    for name in deps:
        available = importlib.util.find_spec(name) is not None
        ok = ok and available
        print(f"{name}: {'ok' if available else 'missing'}")
    return 0 if ok else 1


def cmd_symbolic_exec(args: argparse.Namespace) -> int:
    script = project_root() / "scripts" / "se_script_improved.py"
    command = [
        sys.executable,
        str(script),
        "--binary",
        str(args.binary),
        "--output-prefix",
        args.output_prefix,
        "--timeout",
        str(args.timeout),
    ]
    if args.signature:
        command.extend(["--signature", args.signature])
    return subprocess.call(command, cwd=Path.cwd())


def cmd_vectors(args: argparse.Namespace) -> int:
    if (args.paths_dir is None) == (args.path_file is None):
        raise SystemExit("Provide exactly one of --paths-dir or --path-file.")
    files = [(args.path_file.stem, args.path_file)] if args.path_file else collect_paths(args.paths_dir)
    for _, path in files:
        if not path.is_file():
            raise SystemExit(f"Path file not found: {path}")

    records = []
    for path_id, path in files:
        raw, _ = extract_features(path.read_text(encoding="utf-8", errors="replace"))
        records.append({"path_id": path_id, "raw": raw})

    min_max = None
    if args.include_min_max or args.normalize:
        min_max = compute_dataset_min_max(records)
    if args.normalize and min_max:
        for record in records:
            record["normalized"] = normalize_features(record["raw"], min_max)

    out_data = {
        "feature_names": FEATURE_NAMES,
        "vectors": {r["path_id"]: r["raw"] for r in records},
        "vectors_by_path": records,
    }
    if min_max:
        out_data["min_max"] = {k: [lo, hi] for k, (lo, hi) in min_max.items()}
    if args.normalize and min_max:
        out_data["normalized_vectors"] = {r["path_id"]: r["normalized"] for r in records}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(records)} path vectors to {args.out}")
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    old_paths = list(args.old_path)
    new_paths = list(args.new_path)
    if args.old_paths_dir:
        old_paths.extend(path for _, path in collect_paths(args.old_paths_dir, args.old_prefix))
    if args.new_paths_dir:
        new_paths.extend(path for _, path in collect_paths(args.new_paths_dir, args.new_prefix))
    old_paths = sorted(set(old_paths))
    new_paths = sorted(set(new_paths))
    if not old_paths or not new_paths:
        raise SystemExit("Provide non-empty old and new path inputs.")
    for path in old_paths + new_paths:
        if not path.is_file():
            raise SystemExit(f"Path file not found: {path}")

    config = HybridConfig(
        high_threshold=args.high_threshold,
        margin_threshold=args.margin_threshold,
        graph_min_score=args.graph_min_score,
        graph_weight=args.graph_weight,
        feature_weight=args.feature_weight,
    )
    result = hybrid_rank_paths(
        old_paths,
        new_paths,
        config=config,
        matching_bb_map=load_matching_bb_map(args.matching_bb_map),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote hybrid ranking for {len(result['queries'])} queries to {args.out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    script = project_root() / "scripts" / "verify_ranked_path_equivalence.py"
    command = [
        sys.executable,
        str(script),
        "--paths-dir",
        str(args.paths_dir),
        "--out",
        str(args.out),
        "--timeout-ms",
        str(args.timeout_ms),
    ]
    if args.ranking:
        command.extend(["--ranking", str(args.ranking)])
    if args.naive:
        command.append("--naive")
    if args.truth_pairs_json:
        command.extend(["--truth-pairs-json", args.truth_pairs_json])
    if args.program_ground_truth:
        command.extend(["--program-ground-truth", args.program_ground_truth])
    return subprocess.call(command, cwd=Path.cwd())


def collect_paths(paths_dir: Path, prefix: str | None = None) -> list[tuple[str, Path]]:
    if not paths_dir or not paths_dir.is_dir():
        raise SystemExit(f"Directory not found: {paths_dir}")
    out = []
    for path in sorted(paths_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".txt" or "path" not in path.stem.lower():
            continue
        if prefix and not path.name.startswith(prefix):
            continue
        out.append((path.stem, path))
    return out


def compute_dataset_min_max(records: list[dict]) -> dict[str, tuple[float, float]]:
    if not records:
        return dict(FEATURE_RANGES)
    names = list(FEATURE_RANGES.keys())
    mins = [min(r["raw"][i] for r in records) for i in range(len(records[0]["raw"]))]
    maxs = [max(r["raw"][i] for r in records) for i in range(len(records[0]["raw"]))]
    return {names[i]: (mins[i], maxs[i]) for i in range(len(names))}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    raise SystemExit(main())
