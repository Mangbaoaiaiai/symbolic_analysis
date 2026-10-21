#!/usr/bin/env python3
"""Audit the full 62-case UB-heuristic run from per-case verifier reports."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize_reason(value: str) -> str:
    """Keep failure semantics while removing local artifact paths."""
    value = value or ""
    value = re.sub(r"\s+for\s+(?:[A-Za-z]:\\|/workspace/)[^;]+;.*$", "", value)
    value = re.sub(r"(?:[A-Za-z]:\\|/workspace/|/home/|/tmp/)[^\s;,]+", "", value)
    return value.strip()


def resolve_report_path(value: str) -> Path:
    """Resolve a host or container path emitted by a suite run."""
    normalized = value.replace("\\", "/")
    marker = "/workspace/symbolicana/"
    if normalized.startswith(marker):
        return ROOT / normalized[len(marker) :]
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-cases", type=Path, required=True)
    parser.add_argument("--eval-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    with args.paper_cases.open(encoding="utf-8", newline="") as stream:
        source_rows = list(csv.DictReader(stream))

    rows: list[dict[str, Any]] = []
    classification_counts: Counter[str] = Counter()
    for source in source_rows:
        expected = source["ground_truth"]
        verdict = source.get("verdict", "")
        path_status = source.get("path_status", "")
        path_failure = source.get("path_failure", "")
        report_path = source.get("report_path", "")
        audit: dict[str, Any] = {}
        resolved_report = resolve_report_path(report_path) if report_path else None
        if resolved_report is not None and resolved_report.is_file():
            report = load_json(resolved_report)
            verdict = str(report.get("verdict") or verdict).upper()
            audit = report.get("definedness_audit", {}) or {}

        if path_status != "complete" or not report_path:
            final_status = "UNK"
            reason = path_failure or "missing verifier report"
        elif verdict == "UNK":
            final_status = "UNK"
            reason = source.get("result_error") or "verifier returned UNK"
        elif verdict in {"EQ", "NEQ"}:
            final_status = "CORRECT" if verdict == expected else "WRONG"
            reason = ""
        else:
            final_status = "UNK"
            reason = "missing or invalid verdict"

        counts = audit.get("classification_counts", {}) or {}
        classification_counts.update(counts)
        rows.append(
            {
                "case_id": source["case_id"],
                "family": source["family"],
                "ground_truth": expected,
                "verdict": verdict or "UNK",
                "final_status": final_status,
                "reason": sanitize_reason(reason),
                "definedness_checks": int(audit.get("checks", 0) or 0),
                "rejected_witnesses": int(
                    audit.get("rejected_witnesses", 0) or 0
                ),
                "unknown_as_neq": int(audit.get("unknown_as_neq", 0) or 0),
                "classification_counts": json.dumps(
                    counts, sort_keys=True, separators=(",", ":")
                ),
                "report_available": bool(
                    resolved_report is not None and resolved_report.is_file()
                ),
            }
        )

    status_counts = Counter(row["final_status"] for row in rows)
    eq_rows = [row for row in rows if row["ground_truth"] == "EQ"]
    neq_rows = [row for row in rows if row["ground_truth"] == "NEQ"]
    summary = {
        "total": len(rows),
        "correct": status_counts["CORRECT"],
        "wrong": status_counts["WRONG"],
        "unk": status_counts["UNK"],
        "eq_correct": sum(row["final_status"] == "CORRECT" for row in eq_rows),
        "eq_total": len(eq_rows),
        "neq_correct": sum(
            row["final_status"] == "CORRECT" for row in neq_rows
        ),
        "neq_total": len(neq_rows),
        "conditional_eq_cases": [
            row["case_id"]
            for row in rows
            if row["final_status"] == "CORRECT"
            and row["verdict"] == "EQ"
            and row["rejected_witnesses"] > 0
        ],
        "classification_counts": dict(sorted(classification_counts.items())),
        "unknown_as_neq": sum(row["unknown_as_neq"] for row in rows),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "cases.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# UB heuristic audit",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Correct | {summary['correct']}/{summary['total']} |",
        f"| Correct EQ | {summary['eq_correct']}/{summary['eq_total']} |",
        f"| Correct NEQ | {summary['neq_correct']}/{summary['neq_total']} |",
        f"| Wrong | {summary['wrong']} |",
        f"| UNK | {summary['unk']} |",
        f"| Unknown status treated as NEQ | {summary['unknown_as_neq']} |",
        "",
        "## Definedness events",
        "",
        "| Classification | Logical witnesses |",
        "|---|---:|",
        *[
            f"| `{name}` | {count} |"
            for name, count in summary["classification_counts"].items()
        ],
        "",
        "## Per-case outcomes",
        "",
        "| Case | Label | Verdict | Status | Audit checks | Rejected | Reason |",
        "|---|---|---|---|---:|---:|---|",
        *[
            (
                f"| `{row['case_id']}` | {row['ground_truth']} | "
                f"{row['verdict']} | {row['final_status']} | "
                f"{row['definedness_checks']} | "
                f"{row['rejected_witnesses']} | {row['reason']} |"
            )
            for row in rows
        ],
        "",
    ]
    (args.output_dir / "summary.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
