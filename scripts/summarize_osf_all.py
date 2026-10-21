#!/usr/bin/env python3
"""Summarize every staged OSF case from path and verifier artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


def bool_text(value: Any) -> str:
    if value in (True, "True", "true", "1", 1):
        return "True"
    if value in (False, "False", "false", "0", 0):
        return "False"
    return ""


def normalize_source_case(value: str) -> str:
    value = value.replace("\\", "/")
    for marker in ("/benchmarks_typed/", "/benchmarks/"):
        if marker in value:
            value = value.split(marker, 1)[1]
            break
    return value.strip("/").lower()


def localize_artifact_path(
    value: str,
    *,
    path_root: Path,
    repo_root: Path | None = None,
) -> Path:
    """Translate container-absolute artifact paths to the current checkout.

    Merged manifests intentionally store paths under the Linux container root
    so that ``run_evaluation.py`` can consume them.  When the same manifest is
    audited from the Windows host, those paths are not meaningful there.
    """
    normalized = value.replace("\\", "/")
    container_root = "/workspace/symbolic_analysis"
    if normalized == container_root or normalized.startswith(container_root + "/"):
        if repo_root is None:
            repo_root = Path(__file__).resolve().parents[1]
        relative = normalized[len(container_root) :].lstrip("/")
        return repo_root / relative
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return path_root / candidate


def path_evidence_from_dir(paths_dir: Path, *, case_exists: bool) -> dict[str, Any]:
    old_paths = sorted(paths_dir.glob("symbolic_oldV_path_*.txt")) if paths_dir.is_dir() else []
    new_paths = sorted(paths_dir.glob("symbolic_newV_path_*.txt")) if paths_dir.is_dir() else []
    exploration: dict[str, bool] = {}
    failures: list[str] = []
    for prefix in ("symbolic_oldV", "symbolic_newV"):
        manifest = paths_dir / f"{prefix}_exploration.json"
        if manifest.is_file():
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                exploration[prefix] = bool(payload.get("complete", False))
            except (OSError, json.JSONDecodeError):
                exploration[prefix] = False
        failure = paths_dir / f"{prefix}_failure.json"
        if failure.is_file():
            try:
                payload = json.loads(failure.read_text(encoding="utf-8"))
                failures.append(str(payload.get("error") or payload.get("status") or "failure"))
            except (OSError, json.JSONDecodeError):
                failures.append("unreadable_failure_marker")
    if old_paths and new_paths:
        status = "complete"
    elif old_paths or new_paths:
        status = "partial"
    elif failures:
        status = "failed"
    elif case_exists:
        status = "not_started"
    else:
        status = "not_attempted"
    return {
        "path_status": status,
        "old_path_count": len(old_paths),
        "new_path_count": len(new_paths),
        "old_exploration_complete": bool_text(exploration.get("symbolic_oldV")),
        "new_exploration_complete": bool_text(exploration.get("symbolic_newV")),
        "path_failure": " | ".join(dict.fromkeys(failures)),
        "path_dir": str(paths_dir) if paths_dir.is_dir() else "",
    }


def path_evidence(path_root: Path, source_case: str) -> dict[str, Any]:
    case_dir = path_root / "cases" / source_case
    return path_evidence_from_dir(case_dir / "paths", case_exists=case_dir.is_dir())


def manifest_paths(
    path_root: Path,
    *,
    repo_root: Path | None = None,
) -> dict[str, Path]:
    manifest = path_root / "manifest.json"
    if not manifest.is_file():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, Path] = {}
    for pair in data.get("pairs", []):
        source = str(pair.get("source_case") or "")
        paths_dir = pair.get("paths_dir")
        if source and paths_dir:
            out[normalize_source_case(source)] = localize_artifact_path(
                str(paths_dir),
                path_root=path_root,
                repo_root=repo_root,
            )
    return out


def manifest_failures(path_root: Path) -> dict[str, str]:
    manifest = path_root / "manifest.json"
    if not manifest.is_file():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for failure in data.get("failures", []):
        case = failure.get("case")
        if case:
            out[normalize_source_case(str(case))] = str(failure.get("error") or "failure")
    return out


def failed_path_evidence(error: str) -> dict[str, Any]:
    return {
        "path_status": "failed",
        "old_path_count": 0,
        "new_path_count": 0,
        "old_exploration_complete": "",
        "new_exploration_complete": "",
        "path_failure": error,
        "path_dir": "",
    }


def path_evidence_priority(
    evidence: dict[str, Any],
    root_index: int,
    *,
    prefer_later_root: bool,
) -> tuple[bool, int, int]:
    """Rank complete evidence, optionally treating later roots as overrides."""
    complete = evidence["path_status"] == "complete"
    path_count = int(evidence["old_path_count"]) + int(evidence["new_path_count"])
    if prefer_later_root:
        return complete, root_index, path_count
    return complete, path_count, root_index


def load_results(
    roots: list[Path],
    *,
    result_group: str | None = None,
) -> dict[str, dict[str, str]]:
    by_pair: dict[str, dict[str, str]] = {}
    priority = {"ok": 2, "failed": 1}
    report_group = {
        "naive_report.json": "naive",
        "veribin_report.json": "veribin_align",
        "verification_report.json": "fmcad_align",
    }
    for root in roots:
        if not root.is_dir():
            continue
        raw_root = root / "raw"
        if raw_root.is_dir():
            for report_file in sorted(raw_root.rglob("*.json")):
                group = report_group.get(report_file.name)
                if group is None or (
                    result_group is not None and group != result_group
                ):
                    continue
                try:
                    report = json.loads(report_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(report, dict) or "verdict" not in report:
                    continue
                relative = report_file.relative_to(raw_root)
                parts = relative.parts
                if report_file.name == "verification_report.json" and parts[-2] == "fmcad":
                    pair_parts = parts[:-2]
                else:
                    pair_parts = parts[:-1]
                if len(pair_parts) < 2:
                    continue
                pair_id = "/".join(pair_parts)
                lowered = pair_id.lower()
                if lowered.endswith("_eq"):
                    ground_truth = "True"
                elif lowered.endswith("_neq"):
                    ground_truth = "False"
                else:
                    continue
                prediction = report.get("prediction")
                by_pair[pair_id] = {
                    "pair_id": pair_id,
                    "group": group,
                    "status": "ok",
                    "ground_truth": ground_truth,
                    "prediction": (
                        "True"
                        if prediction is True
                        else "False"
                        if prediction is False
                        else ""
                    ),
                    "result_file": str(report_file),
                }
        for result_file in sorted(root.rglob("results.csv")):
            with result_file.open(encoding="utf-8", newline="") as stream:
                for row in csv.DictReader(stream):
                    if result_group is not None and row.get("group") != result_group:
                        continue
                    pair_id = row.get("pair_id", "")
                    if not pair_id:
                        continue
                    existing = by_pair.get(pair_id)
                    if existing and priority.get(existing.get("status", ""), 0) > priority.get(
                        row.get("status", ""), 0
                    ):
                        continue
                    enriched = dict(row)
                    enriched["result_file"] = str(result_file)
                    by_pair[pair_id] = enriched
    return by_pair


def classify(row: dict[str, Any], evaluation: dict[str, str] | None) -> tuple[str, str]:
    if not evaluation:
        return "not_attempted", ""
    status = evaluation.get("status", "")
    truth = bool_text(evaluation.get("ground_truth"))
    prediction = bool_text(evaluation.get("prediction"))
    if status != "ok":
        return "failed", ""
    if not prediction:
        return "unk", ""
    if truth == prediction:
        return ("correct_eq" if truth == "True" else "correct_neq"), "yes"
    return ("wrong_eq" if prediction == "True" else "wrong_neq"), "no"


def load_label_overrides(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    with path.open(encoding="utf-8", newline="") as stream:
        return {
            row["case_id"].lower(): row["outcome_override"].strip()
            for row in csv.DictReader(stream)
            if row.get("case_id") and row.get("outcome_override", "").strip()
        }


def apply_label_override(
    outcome: str,
    evaluated_correct: str,
    override: str,
) -> tuple[str, str]:
    if override and outcome in {"wrong_eq", "wrong_neq"}:
        return override, ""
    return outcome, evaluated_correct


def percent(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "NA"
    return f"{100.0 * numerator / denominator:.2f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--path-root", type=Path, action="append", default=[])
    parser.add_argument("--eval-root", type=Path, action="append", default=[])
    parser.add_argument(
        "--result-group",
        default=None,
        help="Keep only rows produced by this evaluator method group.",
    )
    parser.add_argument(
        "--prefer-later-path-root",
        action="store_true",
        help="Let a later complete --path-root override an earlier one.",
    )
    parser.add_argument(
        "--label-audit-csv",
        type=Path,
        help="Apply explicit audited label classifications to matching cases.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    with args.manifest.open(encoding="utf-8", newline="") as stream:
        manifest = list(csv.DictReader(stream))
    label_overrides = load_label_overrides(args.label_audit_csv)
    evaluations = load_results(args.eval_root, result_group=args.result_group)
    manifest_indexes = {root: manifest_paths(root) for root in args.path_root}
    failure_indexes = {root: manifest_failures(root) for root in args.path_root}
    rows: list[dict[str, Any]] = []
    for item in manifest:
        normalized_source = normalize_source_case(item["source_case"])
        evidence_candidates = []
        for index, root in enumerate(args.path_root):
            if normalized_source in manifest_indexes[root]:
                candidate = path_evidence_from_dir(
                    manifest_indexes[root][normalized_source],
                    case_exists=True,
                )
            elif normalized_source in failure_indexes[root]:
                candidate = failed_path_evidence(
                    failure_indexes[root][normalized_source]
                )
            else:
                candidate = path_evidence(root, item["source_case"])
            if candidate["path_status"] != "not_attempted":
                evidence_candidates.append((index, candidate))
        if evidence_candidates:
            _index, evidence = max(
                evidence_candidates,
                key=lambda pair: path_evidence_priority(
                    pair[1],
                    pair[0],
                    prefer_later_root=args.prefer_later_path_root,
                ),
            )
        else:
            evidence = {
                "path_status": "not_attempted",
                "old_path_count": 0,
                "new_path_count": 0,
                "old_exploration_complete": "",
                "new_exploration_complete": "",
                "path_failure": "",
                "path_dir": "",
            }
        source_parts = item["source_case"].split("/")
        pair_id = f"{source_parts[0]}/{item['program']}_{source_parts[-1]}"
        evaluation = evaluations.get(pair_id)
        if evaluation is None:
            lowered = pair_id.lower()
            evaluation = next(
                (value for key, value in evaluations.items() if key.lower() == lowered),
                None,
            )
        osf_outcome, evaluated_correct = classify(item, evaluation)
        label_audit_override = label_overrides.get(item["case_id"].lower(), "")
        osf_outcome, evaluated_correct = apply_label_override(
            osf_outcome,
            evaluated_correct,
            label_audit_override,
        )
        rows.append(
            {
                **item,
                "pair_id": pair_id,
                **evidence,
                "evaluation_status": evaluation.get("status", "") if evaluation else "",
                "evaluation_prediction": evaluation.get("prediction", "") if evaluation else "",
                "evaluation_ground_truth": evaluation.get("ground_truth", "") if evaluation else "",
                "evaluated_correct": evaluated_correct,
                "osf_outcome": osf_outcome,
                "label_audit_override": label_audit_override,
                "evaluation_result_file": evaluation.get("result_file", "") if evaluation else "",
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.output_dir / "results.csv"
    with results_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    upstream = [row for row in rows if row["upstream_ardiff_pair"]]
    with (args.output_dir / "upstream_142_results.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(upstream)

    preparation = Counter(row["support_status"] for row in rows)
    paths = Counter(row["path_status"] for row in rows if row["support_status"] != "unsupported")
    fully_explored = sum(
        row["path_status"] == "complete"
        and row["old_exploration_complete"] == "True"
        and row["new_exploration_complete"] == "True"
        for row in rows
    )
    incomplete_exploration = sum(
        row["path_status"] == "complete"
        and not (
            row["old_exploration_complete"] == "True"
            and row["new_exploration_complete"] == "True"
        )
        for row in rows
    )
    outcomes = Counter(row["osf_outcome"] for row in rows)
    outcomes_upstream = Counter(row["osf_outcome"] for row in upstream)
    evaluated = [
        row
        for row in rows
        if row["osf_outcome"] not in {"", "not_attempted"}
    ]
    correct = sum(
        row["osf_outcome"] in {"correct_eq", "correct_neq"} for row in evaluated
    )
    lines = [
        "# OSF all-case summary",
        "",
        f"- Cases in source archive: {len(rows)}",
        f"- Scalar/global-observable cases staged: "
        f"{sum(count for key, count in preparation.items() if key != 'unsupported')}",
        f"- Unsupported entry-level cases: {preparation['unsupported']}",
        f"- Upstream ARDiff 142-case population matched: {len(upstream)}",
        "",
        "## Path generation",
        "",
        f"- Complete exploration on both sides: {fully_explored}",
        f"- Path artifacts with incomplete exploration: {incomplete_exploration}",
        "",
        "| Status | Cases |",
        "|---|---:|",
    ]
    for key in ("complete", "partial", "failed", "not_started", "not_attempted"):
        lines.append(f"| {key} | {paths.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## Evaluation outcomes",
            "",
            "| Outcome | All OSF | Upstream 142 |",
            "|---|---:|---:|",
        ]
    )
    for key in (
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
    ):
        lines.append(f"| {key} | {outcomes.get(key, 0)} | {outcomes_upstream.get(key, 0)} |")

    family_rows = []
    for family in sorted({row["family"] for row in rows}):
        family_items = [row for row in rows if row["family"] == family]
        family_outcomes = Counter(row["osf_outcome"] for row in family_items)
        family_rows.append(
            {
                "family": family,
                "cases": len(family_items),
                "supported": sum(
                    row["support_status"] != "unsupported"
                    for row in family_items
                ),
                "complete_paths": sum(
                    row["path_status"] == "complete"
                    for row in family_items
                ),
                "correct_eq": family_outcomes.get("correct_eq", 0),
                "correct_neq": family_outcomes.get("correct_neq", 0),
                "wrong_eq": family_outcomes.get("wrong_eq", 0),
                "wrong_neq": family_outcomes.get("wrong_neq", 0),
                "label_inconsistent": family_outcomes.get(
                    "label_inconsistent", 0
                ),
                "undefined_behavior": family_outcomes.get(
                    "undefined_behavior", 0
                ),
                "harness_invalid": family_outcomes.get("harness_invalid", 0),
                "unk": family_outcomes.get("unk", 0),
                "failed": family_outcomes.get("failed", 0),
                "not_attempted": family_outcomes.get("not_attempted", 0),
            }
        )
    family_fields = list(family_rows[0]) if family_rows else []
    with (args.output_dir / "family_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=family_fields)
        writer.writeheader()
        writer.writerows(family_rows)
    lines.extend(
        [
            "",
            "## Per-family results",
            "",
            "| Family | Cases | Supported | Complete paths | Correct EQ | "
            "Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | "
            "Undefined behavior | UNK | Failed | Not attempted |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in family_rows:
        lines.append(
            "| {family} | {cases} | {supported} | {complete_paths} | "
            "{correct_eq} | {correct_neq} | {wrong_eq} | {wrong_neq} | "
            "{label_inconsistent} | {undefined_behavior} | {unk} | "
            "{failed} | {not_attempted} |".format(**row)
        )
    lines.extend(
        [
            "",
            f"Evaluated cases: {len(evaluated)}; correct determinate: {correct}; "
            f"raw correct rate: {percent(correct, len(evaluated))}.",
            "",
            "`not_attempted` preserves cases for which no verifier artifact exists. "
            "It is not counted as correct, UNK, or an incorrect verdict.",
        ]
    )
    (args.output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
