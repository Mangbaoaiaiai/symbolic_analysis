#!/usr/bin/env python3
"""Aggregate paper-candidate verifier reports across independent eval runs."""

from __future__ import annotations

import argparse
import csv
import json
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


def failure_case_id(case: str) -> str:
    parts = case.replace("\\", "/").strip("/").split("/")
    if len(parts) < 3:
        return canonical_case_id(case)
    return canonical_case_id(f"{parts[0]}/{parts[-2]}_{parts[-1]}")


def classify(verdict: str, truth: bool | None) -> str:
    if verdict == "UNK":
        return "unk"
    if verdict not in {"EQ", "NEQ"}:
        return "verifier_failed"
    if truth is None:
        return "undetermined"
    prediction = verdict == "EQ"
    if prediction == truth:
        return "correct_eq" if truth else "correct_neq"
    return "wrong_eq" if prediction else "wrong_neq"


def summarize_variant(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["outcome"] for row in rows)
    final_count = sum(row["path_status"] == "complete" for row in rows)
    denominator = len(rows)
    correct = counts["correct_eq"] + counts["correct_neq"]
    return {
        "variant": name,
        "candidate_cases": denominator,
        "correct_rate_denominator": denominator,
        "path_complete": final_count,
        "correct_determinate": correct,
        "wrong_determinate": counts["wrong_eq"] + counts["wrong_neq"],
        "unk": counts["unk"],
        "verifier_failed": counts["verifier_failed"],
        "path_failed": counts["path_failed"],
        "correct_rate_percent": (
            100.0 * correct / denominator if denominator else None
        ),
    }


def load_generated_and_failures(
    manifest_paths: list[Path],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    generated: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for path in manifest_paths:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        for pair in manifest.get("pairs", []):
            generated.setdefault(canonical_case_id(str(pair["pair_id"])), pair)
        for item in manifest.get("failures", []):
            failures.setdefault(
                failure_case_id(str(item.get("case", ""))),
                str(item.get("error") or "failure"),
            )
    return generated, failures


def load_eval_rows(eval_roots: list[Path]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for root in eval_roots:
        path = root / "results.csv"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("group") != "fmcad_align":
                    continue
                key = canonical_case_id(str(row.get("pair_id") or ""))
                rows.setdefault(key, row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-manifest", type=Path, required=True)
    parser.add_argument("--benchmarks", type=Path, required=True)
    parser.add_argument(
        "--supplemental-benchmarks",
        type=Path,
        action="append",
        default=[],
        help="Fill missing pair IDs from an additional path-artifact manifest.",
    )
    parser.add_argument("--eval-root", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest_paths = [args.benchmarks, *args.supplemental_benchmarks]
    generated, failures = load_generated_and_failures(manifest_paths)
    eval_rows = load_eval_rows(args.eval_root)
    with args.paper_manifest.open(encoding="utf-8", newline="") as stream:
        candidates = list(csv.DictReader(stream))

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        key = canonical_case_id(candidate["case_id"])
        pair = generated.get(key)
        truth = candidate["ground_truth"] == "EQ"
        verdict = ""
        report_path = ""
        path_status = "path_failed" if key in failures else "not_found"
        result_status = ""
        result_error = ""
        if pair is not None:
            path_status = "complete"
            report = (
                args.eval_root[0]
                / "raw"
                / str(pair["subset"])
                / str(pair["program"])
                / "fmcad"
                / "verification_report.json"
            )
            for root in args.eval_root:
                candidate_path = (
                    root
                    / "raw"
                    / str(pair["subset"])
                    / str(pair["program"])
                    / "fmcad"
                    / "verification_report.json"
                )
                if candidate_path.is_file():
                    report = candidate_path
                    break
            if report.is_file():
                try:
                    data = json.loads(report.read_text(encoding="utf-8"))
                    verdict = str(data.get("verdict") or "").upper()
                    report_path = str(report)
                except (OSError, json.JSONDecodeError):
                    verdict = ""
            if not report_path and key in eval_rows:
                eval_row = eval_rows[key]
                result_status = str(eval_row.get("status") or "")
                result_error = str(eval_row.get("error") or "")
                if result_status == "ok" and str(
                    eval_row.get("prediction") or ""
                ).strip().lower() in {"", "none", "null"}:
                    verdict = "UNK"
        if path_status == "path_failed":
            outcome = "path_failed"
        elif verdict == "UNK":
            outcome = classify(verdict, truth)
        elif not report_path:
            outcome = "verifier_failed"
        else:
            outcome = classify(verdict, truth)
        rows.append(
            {
                "case_id": candidate["case_id"],
                "family": candidate["family"],
                "ground_truth": candidate["ground_truth"],
                "path_status": path_status,
                "verdict": verdict,
                "outcome": outcome,
                "path_failure": failures.get(key, ""),
                "result_status": result_status,
                "result_error": result_error,
                "report_path": report_path,
            }
        )

    variants = {"fixed_62": rows}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "paper_cases.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summaries = []
    for name, variant in variants.items():
        summaries.append(summarize_variant(name, variant))
    with (args.output_dir / "variant_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    lines = [
        "# Paper evaluation summary",
        "",
        "Primary manifest: `" + str(args.benchmarks) + "`",
        "",
    ]
    if args.supplemental_benchmarks:
        lines.extend(
            [
                "Supplemental manifests fill only pair IDs absent from the primary "
                "manifest:",
                "",
                *[
                    f"- `{path}`"
                    for path in args.supplemental_benchmarks
                ],
                "",
            ]
        )
    lines.extend(
        [
        "| Variant | Candidates | Correct-rate denominator | Path complete | Correct | Wrong | UNK | Verifier failed | Path failed | Correct rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in summaries:
        rate = (
            "NA"
            if item["correct_rate_percent"] is None
            else f"{item['correct_rate_percent']:.2f}%"
        )
        lines.append(
            f"| {item['variant']} | {item['candidate_cases']} | "
            f"{item['correct_rate_denominator']} | {item['path_complete']} | "
            f"{item['correct_determinate']} | "
            f"{item['wrong_determinate']} | {item['unk']} | "
            f"{item['verifier_failed']} | {item['path_failed']} | {rate} |"
        )
    (args.output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.output_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
