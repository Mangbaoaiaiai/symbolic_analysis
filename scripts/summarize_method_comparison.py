#!/usr/bin/env python3
"""Aggregate correctness and ranking metrics across evaluation shards."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class MethodInput:
    name: str
    root: Path
    group: str | None = None


def parse_method_input(value: str) -> MethodInput:
    if "=" not in value:
        raise argparse.ArgumentTypeError("method input must be NAME=DIRECTORY")
    method_spec, raw_path = value.rsplit("=", 1)
    name, separator, group = method_spec.partition(":")
    name = name.strip()
    group = group.strip() if separator else None
    raw_path = raw_path.strip()
    if not name or not raw_path or (separator and not group):
        raise argparse.ArgumentTypeError(
            "method input must be NAME=DIRECTORY or NAME:GROUP=DIRECTORY"
        )
    return MethodInput(name=name, root=Path(raw_path), group=group)


def result_files(root: Path) -> Iterable[Path]:
    direct = root / "results.csv"
    if direct.is_file():
        yield direct
        return
    yield from sorted(root.rglob("results.csv"))


def load_method_rows(item: MethodInput) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in result_files(item.root):
        with path.open(encoding="utf-8", newline="") as stream:
            for raw in csv.DictReader(stream):
                pair_id = raw.get("pair_id", "")
                if not pair_id:
                    continue
                if item.group is not None and raw.get("group") != item.group:
                    continue
                if pair_id in seen:
                    raise ValueError(
                        f"duplicate pair {pair_id!r} for method {item.name!r}"
                    )
                seen.add(pair_id)
                row = dict(raw)
                row["method"] = item.name
                row["result_file"] = str(path)
                rows.append(row)
    return rows


def exclude_case_prefixes(
    rows: list[dict[str, str]],
    prefixes: list[str],
) -> list[dict[str, str]]:
    if not prefixes:
        return rows
    return [
        row
        for row in rows
        if not any(row.get("pair_id", "").startswith(prefix) for prefix in prefixes)
    ]


def prefer_successful_attempts(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Collapse retries, preferring an `ok` attempt over a process failure."""
    selected: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for row in rows:
        pair_id = row.get("pair_id", "")
        if not pair_id:
            continue
        existing = selected.get(pair_id)
        if existing is None:
            selected[pair_id] = row
            order.append(pair_id)
            continue
        if existing.get("status") != "ok" and row.get("status") == "ok":
            selected[pair_id] = row
    return [selected[pair_id] for pair_id in order]


def as_bool(value: str | None) -> bool | None:
    lowered = str(value or "").strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def as_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def weighted_metric(
    rows: list[dict[str, str]],
    field: str,
    *,
    percent: bool,
) -> float | None:
    queries = 0
    total = 0.0
    for row in rows:
        count = int(as_float(row.get("ranking_queries")) or 0)
        value = as_float(row.get(field))
        if count <= 0 or value is None:
            continue
        queries += count
        total += count * (value / 100.0 if percent else value)
    if queries == 0:
        return None
    average = total / queries
    return 100.0 * average if percent else average


REPORT_NAMES_BY_GROUP = {
    "naive": {"naive_report.json"},
    "veribin_align": {"veribin_report.json"},
    "fmcad_align": {"verification_report.json"},
}


def match_type_counts(root: Path, group: str | None = None) -> Counter[str]:
    counts: Counter[str] = Counter()
    allowed_names = REPORT_NAMES_BY_GROUP.get(group)
    for report_path in sorted(root.rglob("*.json")):
        if allowed_names is None:
            if report_path.name not in {
                "naive_report.json",
                "veribin_report.json",
                "verification_report.json",
            }:
                continue
        elif report_path.name not in allowed_names:
            continue
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(report, dict) or "matches" not in report:
            continue
        for directional_key in ("matches", "reverse_matches"):
            for record in report.get(directional_key, []) or []:
                match_type = str(record.get("match_type") or "")
                if match_type and match_type != "unmatched":
                    counts[match_type] += 1
    return counts


def summarize(
    item: MethodInput,
    rows: list[dict[str, str]],
    *,
    expected_cases: int | None,
    matches: Counter[str] | None = None,
) -> dict[str, Any]:
    correct = 0
    wrong = 0
    unk = 0
    failed = 0
    for row in rows:
        truth = as_bool(row.get("ground_truth"))
        prediction = as_bool(row.get("prediction"))
        status = str(row.get("status") or "")
        if status != "ok":
            failed += 1
        elif prediction is None:
            unk += 1
        elif truth is None:
            failed += 1
        elif prediction == truth:
            correct += 1
        else:
            wrong += 1
    matches = matches if matches is not None else Counter()
    one_to_many = sum(
        count for kind, count in matches.items() if kind.startswith("one_to_many_")
    )
    return {
        "method": item.name,
        "cases_run": len(rows),
        "expected_cases": expected_cases,
        "missing_cases": (
            max(0, expected_cases - len(rows)) if expected_cases is not None else None
        ),
        "correct_determinate": correct,
        "wrong_determinate": wrong,
        "unk": unk,
        "failed": failed,
        "hit_at_1_percent": weighted_metric(rows, "hit_at_1", percent=True),
        "hit_at_3_percent": weighted_metric(rows, "hit_at_3", percent=True),
        "mrr": weighted_metric(rows, "mrr", percent=False),
        "ranking_queries": sum(
            int(as_float(row.get("ranking_queries")) or 0) for row in rows
        ),
        "match_records": sum(matches.values()),
        "one_to_many_records": one_to_many,
        **{f"match_{kind}": count for kind, count in sorted(matches.items())},
    }


def fmt_percent(value: float | None) -> str:
    return "NA" if value is None else f"{value:.2f}%"


def fmt_float(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4f}"


def write_reports(
    output_dir: Path,
    summaries: list[dict[str, Any]],
    case_rows: list[dict[str, str]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_fields = [
        "method",
        "cases_run",
        "expected_cases",
        "missing_cases",
        "correct_determinate",
        "wrong_determinate",
        "unk",
        "failed",
        "hit_at_1_percent",
        "hit_at_3_percent",
        "mrr",
        "ranking_queries",
        "match_records",
        "one_to_many_records",
    ]
    extra_fields = sorted(
        {
            key
            for summary in summaries
            for key in summary
            if key.startswith("match_") and key != "match_records"
        }
        - set(summary_fields)
    )
    with (output_dir / "summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=summary_fields + extra_fields)
        writer.writeheader()
        writer.writerows(summaries)

    case_fields = [
        "method",
        "pair_id",
        "subset",
        "status",
        "ground_truth",
        "prediction",
        "confusion",
        "hit_at_1",
        "hit_at_3",
        "mrr",
        "ranking_queries",
        "result_file",
    ]
    with (output_dir / "cases.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=case_fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(case_rows)

    lines = [
        "# Method comparison",
        "",
        "| Method | Cases | Correct | Wrong | UNK | Failed | Hit@1 | Hit@3 | MRR | One-to-many records |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        lines.append(
            f"| {summary['method']} | {summary['cases_run']} | "
            f"{summary['correct_determinate']} | {summary['wrong_determinate']} | "
            f"{summary['unk']} | {summary['failed']} | "
            f"{fmt_percent(summary['hit_at_1_percent'])} | "
            f"{fmt_percent(summary['hit_at_3_percent'])} | "
            f"{fmt_float(summary['mrr'])} | "
            f"{summary['one_to_many_records']} |"
        )
    lines.extend(
        [
            "",
            "Counts are computed from verified per-case CSV rows. Missing rows are",
            "reported only when `expected_cases` is supplied; they are never treated",
            "as correct, UNK, or wrong.",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        type=parse_method_input,
        metavar="NAME[:GROUP]=DIRECTORY",
        help="Method result directory; repeat to merge disjoint shards.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-cases", type=int)
    parser.add_argument(
        "--exclude-case-prefix",
        action="append",
        default=[],
        help="Exclude pair IDs beginning with this prefix after merging shards.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    grouped: dict[str, list[dict[str, str]]] = {}
    inputs: dict[str, list[MethodInput]] = {}
    for item in args.input:
        inputs.setdefault(item.name, []).append(item)
        grouped.setdefault(item.name, []).extend(load_method_rows(item))
    if args.exclude_case_prefix:
        for name, rows in grouped.items():
            grouped[name] = exclude_case_prefixes(rows, args.exclude_case_prefix)
    for name, rows in grouped.items():
        grouped[name] = prefer_successful_attempts(rows)
    summaries = [
        summarize(
            MethodInput(name=name, root=Path(".")),
            rows,
            expected_cases=args.expected_cases,
        )
        for name, rows in grouped.items()
    ]
    # Match-type reports may live in different shard roots than the rows.
    for summary in summaries:
        counts: Counter[str] = Counter()
        for item in inputs[summary["method"]]:
            counts.update(match_type_counts(item.root, item.group))
        summary["match_records"] = sum(counts.values())
        summary["one_to_many_records"] = sum(
            count for kind, count in counts.items() if kind.startswith("one_to_many_")
        )
        for kind, count in sorted(counts.items()):
            summary[f"match_{kind}"] = count
    write_reports(args.output_dir, summaries, [row for rows in grouped.values() for row in rows])
    print(f"wrote {args.output_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
