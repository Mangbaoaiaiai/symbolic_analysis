#!/usr/bin/env python3
"""Merge targeted OSF support results into the prior complete-suite audit.

This produces an explicitly marked provisional table.  It is only used until a
fresh full-suite run has replaced every reused case row.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


OUTCOME_KEYS = (
    "correct_eq",
    "correct_neq",
    "wrong_eq",
    "wrong_neq",
    "label_inconsistent",
    "undefined_behavior",
    "harness_invalid",
    "unk",
    "failed",
    "not_attempted",
)
FAILURE_KEYS = (
    "unsupported_harness",
    "sigkill_or_oom",
    "symbolic_timeout",
    "no_complete_paths",
    "other_symbolic_execution_failure",
    "incomplete_symbolic_exploration",
    "verifier_or_semantic_unknown",
    "unclassified_failure",
)
PATH_SOURCE_FIELDS = {
    "path_dir",
    "typed_old",
    "typed_new",
    "report_path",
    "evaluation_result_file",
    "artifact_path",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_rows(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    materialized = list(rows)
    fields: list[str] = []
    for row in materialized:
        fields.extend(key for key in row if key not in fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def bool_value(value: Any) -> bool:
    return value is True or str(value).lower() in {"true", "1"}


def normalize_case_key(value: str) -> str:
    """Match targeted result IDs case-insensitively (``Neq`` vs ``NEq``)."""
    return value.strip().casefold()


def json_counter(row: dict[str, Any], field: str) -> Counter[str]:
    try:
        value = json.loads(str(row.get(field) or "{}"))
    except (TypeError, json.JSONDecodeError):
        return Counter()
    if not isinstance(value, dict):
        return Counter()
    return Counter({str(key): int(item) for key, item in value.items()})


def update_manifest_fields(
    row: dict[str, Any],
    manifest: dict[str, str],
) -> None:
    for key in (
        "family",
        "program",
        "label",
        "support_status",
        "reason",
        "entry_name",
        "entry_signature",
        "selection_rule",
        "upstream_ardiff_pair",
    ):
        row[key] = manifest.get(key, "")
    row["support_reason"] = manifest.get("reason", "")


def override_outcome(
    verdict: str,
    label: str,
    override: str,
) -> tuple[str, str]:
    verdict = verdict.upper()
    label = label.upper()
    if verdict not in {"EQ", "NEQ"}:
        return "unk", ""
    correct = verdict == label
    outcome = (
        f"correct_{verdict.lower()}"
        if correct
        else f"wrong_{verdict.lower()}"
    )
    if not correct and override:
        return override, ""
    return outcome, str(correct).lower()


def custom_row(
    base: dict[str, str],
    manifest: dict[str, str],
    result: dict[str, str],
    reports_root: Path,
    overrides: dict[str, str],
) -> dict[str, Any]:
    pair_id = result["pair_id"]
    report_path = reports_root / pair_id / "fmcad" / "verification_report.json"
    report = read_json(report_path)
    if not report:
        raise SystemExit(f"missing verification report for {pair_id}: {report_path}")
    old_count = int(report.get("old_path_count") or 0)
    new_count = int(report.get("new_path_count") or 0)
    exploration = report.get("exploration", {})
    old_complete = bool_value(
        (exploration.get("symbolic_oldV") or {}).get("complete")
        if isinstance(exploration, dict)
        else False
    )
    new_complete = bool_value(
        (exploration.get("symbolic_newV") or {}).get("complete")
        if isinstance(exploration, dict)
        else False
    )
    both_complete = old_complete and new_complete and old_count > 0 and new_count > 0
    if old_count and new_count:
        artifact_status = "both_sides"
    elif old_count or new_count:
        artifact_status = "partial"
    else:
        artifact_status = "failed"
    verdict = str(report.get("verdict") or "UNK").upper()
    outcome, evaluated_correct = override_outcome(
        verdict,
        manifest["label"],
        overrides.get(pair_id.lower(), ""),
    )
    if outcome == "unk":
        failure = (
            "verifier_or_semantic_unknown"
            if both_complete
            else "incomplete_symbolic_exploration"
            if old_count or new_count
            else "no_complete_paths"
        )
    else:
        failure = ""
    row = dict(base)
    update_manifest_fields(row, manifest)
    row.update(
        {
            "attempt": "small_osf_complex_type_regression",
            "artifact_status": artifact_status,
            "old_path_count": str(old_count),
            "new_path_count": str(new_count),
            "old_complete": str(old_complete),
            "new_complete": str(new_complete),
            "both_complete": str(both_complete),
            "incomplete_reasons": (
                "" if both_complete else "small-run evidence incomplete"
            ),
            "path_failure": "",
            "evaluation_status": result.get("status", ""),
            "verdict": verdict,
            "evaluation_error": result.get("error", ""),
            "evaluation_wall_seconds": "",
            "t_align": report.get("t_align", ""),
            "t_smt": report.get("t_smt", ""),
            "t_total": report.get("t_total", ""),
            "candidate_pairs": report.get("candidate_pairs", ""),
            "aligned_pairs": report.get("aligned_pairs", ""),
            "smt_calls": report.get("smt_calls", ""),
            "unknowns": report.get("unknowns", ""),
            "outcome": outcome,
            "evaluated_correct": evaluated_correct,
            "label_audit_override": overrides.get(pair_id.lower(), ""),
            "definedness_checks": str(
                (report.get("definedness_audit") or {}).get("checks", 0)
            ),
            "rejected_witnesses": str(
                (report.get("definedness_audit") or {}).get(
                    "rejected_witnesses", 0
                )
            ),
            "unknown_as_neq": str(
                (report.get("definedness_audit") or {}).get(
                    "unknown_as_neq", 0
                )
            ),
            "definedness_classifications": json.dumps(
                (report.get("definedness_audit") or {}).get(
                    "classification_counts", {}
                ),
                sort_keys=True,
                separators=(",", ":"),
            ),
            "baseline_outcome": base.get("outcome", ""),
            "baseline_both_complete": base.get("both_complete", "False"),
            "stage_trace": json.dumps(
                [
                    {
                        "attempt": "small_osf_entry_regression",
                        "artifact_status": artifact_status,
                        "old_path_count": old_count,
                        "new_path_count": new_count,
                        "both_complete": both_complete,
                        "evaluation_status": result.get("status", ""),
                        "verdict": verdict,
                    }
                ],
                sort_keys=True,
                separators=(",", ":"),
            ),
            "failure_category": failure,
            "provisional_merge_source": "small_osf_complex_type_regression",
        }
    )
    return row


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = Counter(str(row.get("outcome") or "") for row in rows)
    failures = Counter(
        str(row.get("failure_category") or "")
        for row in rows
        if row.get("failure_category")
    )
    supported = [
        row for row in rows if row.get("support_status") != "unsupported"
    ]
    classifications: Counter[str] = Counter()
    for row in rows:
        classifications.update(json_counter(row, "definedness_classifications"))
    both_complete = [row for row in supported if bool_value(row.get("both_complete"))]
    entered = [
        row
        for row in supported
        if int(row.get("old_path_count", 0) or 0)
        + int(row.get("new_path_count", 0) or 0)
        > 0
    ]
    return {
        "total": len(rows),
        "supported": len(supported),
        "unsupported": len(rows) - len(supported),
        "entered_symbolic_execution": len(entered),
        "both_sides_path_artifacts": sum(
            row.get("artifact_status") == "both_sides" for row in supported
        ),
        "both_sides_complete": len(both_complete),
        "incomplete_exploration": sum(
            int(row.get("old_path_count", 0) or 0)
            + int(row.get("new_path_count", 0) or 0)
            > 0
            and not bool_value(row.get("both_complete"))
            for row in supported
        ),
        "no_path_artifact": sum(
            int(row.get("old_path_count", 0) or 0)
            + int(row.get("new_path_count", 0) or 0)
            == 0
            for row in supported
        ),
        "correct": outcomes["correct_eq"] + outcomes["correct_neq"],
        "determinate": sum(
            outcomes[key]
            for key in ("correct_eq", "correct_neq", "wrong_eq", "wrong_neq")
        ),
        "unknown_as_neq_witnesses": sum(
            int(row.get("unknown_as_neq", 0) or 0) for row in rows
        ),
        "definedness_classifications": dict(sorted(classifications.items())),
        "failure_categories": dict(sorted(failures.items())),
        "outcomes": {key: outcomes[key] for key in OUTCOME_KEYS},
    }


def family_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for family in sorted({str(row.get("family") or "") for row in rows}):
        subset = [row for row in rows if row.get("family") == family]
        summary = metrics(subset)
        outcomes = summary["outcomes"]
        output.append(
            {
                "family": family,
                "cases": len(subset),
                "supported": summary["supported"],
                "both_sides_complete": summary["both_sides_complete"],
                "correct_eq": outcomes["correct_eq"],
                "correct_neq": outcomes["correct_neq"],
                "wrong_eq": outcomes["wrong_eq"],
                "wrong_neq": outcomes["wrong_neq"],
                "label_inconsistent": outcomes["label_inconsistent"],
                "undefined_behavior": outcomes["undefined_behavior"],
                "harness_invalid": outcomes["harness_invalid"],
                "unk": outcomes["unk"],
                "failed": outcomes["failed"],
                "not_attempted": outcomes["not_attempted"],
            }
        )
    return output


def summary_markdown(
    summary: dict[str, Any],
    family_data: list[dict[str, Any]],
    upstream: dict[str, Any],
    provisional_count: int,
) -> str:
    outcomes = summary["outcomes"]
    lines = [
        "# Provisional complete OSF audit",
        "",
        "> This table combines the previous 272-case full audit with targeted",
        f"> results for {provisional_count} newly supported cases. It is not a",
        "> fresh end-to-end run and is retained only until the final full-suite",
        "> replacement completes.",
        "",
        "## Coverage",
        "",
        "| Metric | Cases |",
        "|---|---:|",
        f"| Official entries | {summary['total']} |",
        f"| Supported / staged | {summary['supported']} |",
        f"| Unsupported by harness | {summary['unsupported']} |",
        f"| Entered symbolic execution | {summary['entered_symbolic_execution']} |",
        f"| Both-side path artifacts | {summary['both_sides_path_artifacts']} |",
        f"| Both-side complete exploration | {summary['both_sides_complete']} |",
        f"| Incomplete exploration | {summary['incomplete_exploration']} |",
        f"| No path artifact | {summary['no_path_artifact']} |",
        "",
        "## Outcomes",
        "",
        "| Outcome | Cases |",
        "|---|---:|",
        *[f"| {key} | {outcomes[key]} |" for key in OUTCOME_KEYS],
        f"| **Correct determinate** | **{summary['correct']}** |",
        f"| UB status unknown treated as NEQ | "
        f"{summary['unknown_as_neq_witnesses']} |",
        "",
        "## Failure categories",
        "",
        "| Category | Cases |",
        "|---|---:|",
        *[
            f"| {key} | {summary['failure_categories'].get(key, 0)} |"
            for key in FAILURE_KEYS
        ],
        "",
        "## Family table",
        "",
        "| Family | Cases | Supported | Complete | Correct EQ | Correct NEQ | "
        "Wrong EQ | Wrong NEQ | Label inconsistent | UB | UNK | Failed | "
        "Not attempted |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in family_data:
        lines.append(
            "| {family} | {cases} | {supported} | {both_sides_complete} | "
            "{correct_eq} | {correct_neq} | {wrong_eq} | {wrong_neq} | "
            "{label_inconsistent} | {undefined_behavior} | {unk} | {failed} | "
            "{not_attempted} |".format(**row)
        )
    upstream_outcomes = upstream["outcomes"]
    lines.extend(
        [
            "",
            "## Upstream ARDiff 142",
            "",
            "| Cases | Supported | Entered SE | Complete | Correct EQ | "
            "Correct NEQ | Wrong | Label inconsistent | UB | UNK | Failed |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            f"| {upstream['total']} | {upstream['supported']} | "
            f"{upstream['entered_symbolic_execution']} | "
            f"{upstream['both_sides_complete']} | "
            f"{upstream_outcomes['correct_eq']} | "
            f"{upstream_outcomes['correct_neq']} | "
            f"{upstream_outcomes['wrong_eq'] + upstream_outcomes['wrong_neq']} | "
            f"{upstream_outcomes['label_inconsistent']} | "
            f"{upstream_outcomes['undefined_behavior']} | "
            f"{upstream_outcomes['unk']} | {upstream_outcomes['failed']} |",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-cases", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--all-methods-manifest", type=Path, required=True)
    parser.add_argument("--support-audit", type=Path, required=True)
    parser.add_argument("--custom-results", type=Path, required=True)
    parser.add_argument("--custom-reports-root", type=Path, required=True)
    parser.add_argument("--label-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    base_rows = read_rows(args.base_cases)
    base = {row["case_id"]: row for row in base_rows}
    manifests = {
        row["case_id"]: row for row in read_rows(args.manifest)
    }
    all_methods_ids = {
        normalize_case_key(row["case_id"])
        for row in read_rows(args.all_methods_manifest)
    }
    audit_rows = {
        normalize_case_key(row["case_id"]): row
        for row in read_rows(args.support_audit)
    }
    custom_results = {
        normalize_case_key(row["pair_id"]): row
        for row in read_rows(args.custom_results)
    }
    overrides = {
        row["case_id"].lower(): row["outcome_override"].strip()
        for row in read_rows(args.label_audit)
        if row.get("outcome_override", "").strip()
    }

    merged: dict[str, dict[str, Any]] = {}
    provisional_ids: set[str] = set()
    for case_id, base_row in base.items():
        manifest = manifests[case_id]
        old_supported = base_row.get("support_status") != "unsupported"
        new_supported = manifest.get("support_status") != "unsupported"
        if not old_supported and new_supported:
            case_key = normalize_case_key(case_id)
            if case_key in custom_results:
                row = custom_row(
                    base_row,
                    manifest,
                    custom_results[case_key],
                    args.custom_reports_root,
                    overrides,
                )
            elif case_key in all_methods_ids and case_key in audit_rows:
                row = dict(audit_rows[case_key])
                update_manifest_fields(row, manifest)
                row["attempt"] = "small_osf_all_methods_regression"
                row["provisional_merge_source"] = "small_osf_all_methods_regression"
            else:
                raise SystemExit(f"missing targeted result for newly supported {case_id}")
            row["baseline_outcome"] = base_row.get("outcome", "")
            row["baseline_both_complete"] = base_row.get("both_complete", "False")
            provisional_ids.add(case_id)
        else:
            row = dict(base_row)
            update_manifest_fields(row, manifest)
        merged[case_id] = row

    rows = [merged[case_id] for case_id in manifests]
    for row in rows:
        for field in PATH_SOURCE_FIELDS:
            row.pop(field, None)

    summary = metrics(rows)
    summary.update(
        {
            "provisional": True,
            "full_osf_rerun_complete": False,
            "provisional_replaced_cases": len(provisional_ids),
            "provisional_case_ids": sorted(provisional_ids),
        }
    )
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    write_rows(output / "cases.csv", rows)
    with (output / "summary.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    with (output / "outcomes.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("outcome", "cases"))
        writer.writerows((key, summary["outcomes"][key]) for key in OUTCOME_KEYS)

    families = family_rows(rows)
    write_rows(output / "family_summary.csv", families)
    write_rows(
        output / "failure_summary.csv",
        [
            {"category": key, "cases": summary["failure_categories"].get(key, 0)}
            for key in FAILURE_KEYS
            if summary["failure_categories"].get(key, 0)
        ],
    )
    write_rows(
        output / "failure_cases.csv",
        [
            {
                key: row.get(key, "")
                for key in (
                    "case_id",
                    "family",
                    "label",
                    "support_status",
                    "failure_category",
                    "artifact_status",
                    "old_path_count",
                    "new_path_count",
                    "both_complete",
                    "path_failure",
                    "evaluation_status",
                    "evaluation_error",
                    "outcome",
                )
            }
            for row in rows
            if row.get("failure_category")
        ],
    )
    write_rows(
        output / "ub_cases.csv",
        [
            {
                key: row.get(key, "")
                for key in (
                    "case_id",
                    "family",
                    "label",
                    "verdict",
                    "outcome",
                    "definedness_checks",
                    "rejected_witnesses",
                    "unknown_as_neq",
                    "definedness_classifications",
                )
            }
            for row in rows
            if int(row.get("definedness_checks", 0) or 0)
            or row.get("definedness_classifications") not in ("", "{}")
        ],
    )
    write_rows(
        output / "baseline_changes.csv",
        [
            {
                "case_id": row["case_id"],
                "previous_outcome": base[row["case_id"]].get("outcome", ""),
                "current_outcome": row.get("outcome", ""),
                "previous_both_complete": base[row["case_id"]].get(
                    "both_complete", "False"
                ),
                "current_both_complete": row.get("both_complete", "False"),
            }
            for row in rows
            if base[row["case_id"]].get("outcome", "")
            != row.get("outcome", "")
            or bool_value(base[row["case_id"]].get("both_complete"))
            != bool_value(row.get("both_complete"))
        ],
    )

    upstream_rows = [
        row for row in rows if row.get("upstream_ardiff_pair")
    ]
    upstream = metrics(upstream_rows)
    write_rows(output / "upstream_142_cases.csv", upstream_rows)
    write_rows(
        output / "upstream_142_summary.csv",
        [
            {
                "cases": upstream["total"],
                "supported": upstream["supported"],
                "entered_symbolic_execution": upstream["entered_symbolic_execution"],
                "both_sides_complete": upstream["both_sides_complete"],
                **upstream["outcomes"],
            }
        ],
    )
    (output / "label_audit.csv").write_text(
        args.label_audit.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (output / "summary.md").write_text(
        summary_markdown(summary, families, upstream, len(provisional_ids)),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "supported": summary["supported"],
                "entered_symbolic_execution": summary["entered_symbolic_execution"],
                "both_sides_complete": summary["both_sides_complete"],
                "correct": summary["correct"],
                "provisional_replaced_cases": len(provisional_ids),
                "outcomes": summary["outcomes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
