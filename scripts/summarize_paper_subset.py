#!/usr/bin/env python3
"""Compare the reconstructed paper candidate set with the exhaustive OSF run."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from typing import Any


def canonical_case_id(case_id: str) -> str:
    family, rest = case_id.split("/", 1)
    family = family.lower()
    if family == "clever":
        family = "moddiff"
    elif family == "pow":
        family = "power"
    return f"{family}/{rest}".lower()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def summarize(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["paper_outcome"] for row in rows)
    path_complete = sum(row["path_status"] == "complete" for row in rows)
    correct = counts["correct_eq"] + counts["correct_neq"]
    wrong = counts["wrong_eq"] + counts["wrong_neq"]
    unknown = counts["unk"]
    verifier_failed = counts["verifier_failed"]
    evaluated = correct + wrong + unknown + verifier_failed
    correct_rate = 100.0 * correct / evaluated if evaluated else None
    return {
        "variant": name,
        "candidate_cases": len(rows),
        "path_complete": path_complete,
        "evaluated": evaluated,
        "correct_determinate": correct,
        "wrong_determinate": wrong,
        "unk": unknown,
        "verifier_failed": verifier_failed,
        "not_attempted": counts["not_attempted"],
        "path_failed": counts["path_failed"],
        "correct_rate_percent": correct_rate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-manifest", type=Path, required=True)
    parser.add_argument("--all-results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    paper_rows = load_rows(args.paper_manifest)
    all_rows = load_rows(args.all_results)
    indexed = {canonical_case_id(row["case_id"]): row for row in all_rows}
    rows: list[dict[str, Any]] = []
    for paper in paper_rows:
        key = canonical_case_id(paper["case_id"])
        osf = indexed.get(key)
        outcome = "not_attempted"
        if osf is not None:
            if osf["path_status"] == "failed":
                outcome = "path_failed"
            elif osf["osf_outcome"] == "failed":
                outcome = "verifier_failed"
            elif osf["osf_outcome"] != "not_attempted":
                outcome = osf["osf_outcome"]
        rows.append(
            {
                "paper_case_id": paper["case_id"],
                "osf_case_id": osf["case_id"] if osf else "",
                "osf_pair_id": osf["pair_id"] if osf else "",
                "paper_family": paper["family"],
                "canonical_ground_truth": paper["ground_truth"],
                "paper_outcome": outcome,
                "path_status": osf["path_status"] if osf else "not_found",
                "entry_name": osf["entry_name"] if osf else "",
                "entry_signature": osf["entry_signature"] if osf else "",
                "path_dir": osf["path_dir"] if osf else "",
                "path_failure": osf["path_failure"] if osf else "",
                "evaluation_result_file": osf["evaluation_result_file"] if osf else "",
            }
        )

    variants = {
        "all_72": rows,
        "exclude_gam_erfcc": [
            row for row in rows if row["paper_case_id"] != "gam/erfcc_Eq"
            and row["paper_case_id"] != "gam/erfcc_NEq"
        ],
        "exclude_gam_gcf": [
            row for row in rows if row["paper_case_id"] != "gam/gcf_Eq"
            and row["paper_case_id"] != "gam/gcf_NEq"
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "paper_candidates.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summaries = [summarize(name, variant) for name, variant in variants.items()]
    with (args.output_dir / "variant_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    lines = [
        "# Paper-subset comparison",
        "",
        "The exact 62-case list is not public. The two local 62-case variants use",
        "the same paper family envelope and differ only in which two-case gam",
        "program is removed.",
        "",
        "| Variant | Candidates | Path complete | Evaluated | Correct | Wrong | UNK | Verifier failed | Path failed | Correct rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        rate = (
            "NA"
            if item["correct_rate_percent"] is None
            else f"{item['correct_rate_percent']:.2f}%"
        )
        lines.append(
            f"| {item['variant']} | {item['candidate_cases']} | "
            f"{item['path_complete']} | {item['evaluated']} | "
            f"{item['correct_determinate']} | {item['wrong_determinate']} | "
            f"{item['unk']} | {item['verifier_failed']} | "
            f"{item['path_failed']} | {rate} |"
        )
    (args.output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.output_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
