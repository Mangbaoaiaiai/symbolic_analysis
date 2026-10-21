#!/usr/bin/env python3
"""Audit a complete OSF run with strict exploration and verifier evidence.

Unlike ``summarize_osf_all.py``, this audit never treats path-file presence as
proof that exploration completed. An EQ is accepted only when both exploration
manifests and the matching verifier report record complete exploration.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
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

FAILURE_CATEGORY_KEYS = (
    "unsupported_harness",
    "sigkill_or_oom",
    "symbolic_timeout",
    "no_complete_paths",
    "other_symbolic_execution_failure",
    "incomplete_symbolic_exploration",
    "verifier_or_semantic_unknown",
    "unclassified_failure",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        fields.extend(key for key in row if key not in fields)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_case(value: str) -> str:
    normalized = value.replace("\\", "/").strip().strip('"')
    normalized = re.sub(r"/paths/?$", "", normalized, flags=re.IGNORECASE)
    for marker in (
        "/benchmarks_typed/", "benchmarks_typed/", "/benchmarks/", "benchmarks/",
        "/paths/cases/", "paths/cases/", "/cases/", "cases/",
    ):
        position = normalized.find(marker)
        if position >= 0:
            normalized = normalized[position + len(marker) :]
            break
    return normalized.strip("/").lower()


def localize_artifact(value: str, path_root: Path) -> Path:
    normalized = value.replace("\\", "/")
    for marker in (
        "/workspace/repo/",
        "/workspace/symbolic_analysis/",
        "/workspace/symbolicana/",
    ):
        if normalized.startswith(marker):
            candidate = Path(__file__).resolve().parents[1] / normalized[len(marker) :]
            if candidate.exists():
                return candidate
    candidate = Path(value)
    return candidate if candidate.is_absolute() else path_root / candidate


def failure_paths_dir(failure: dict[str, Any], path_root: Path) -> Path | None:
    """Recover the generated paths directory from a failure record."""
    raw = str(failure.get("paths_dir") or "")
    if not raw:
        match = re.search(r"\bsee\s+([^;]+?\.log)\b", str(failure.get("error") or ""))
        raw = match.group(1).strip() if match else ""
    if not raw:
        return None
    candidate = localize_artifact(raw, path_root)
    if candidate.suffix == ".log":
        candidate = candidate.parent
    return candidate if candidate.is_dir() else None


def path_index(path_root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    manifest = read_json(path_root / "manifest.json")
    if not manifest.get("pairs"):
        manifest = read_json(path_root / "manifest.partial.json")
    for pair in manifest.get("pairs", []):
        source = str(pair.get("source_case") or pair.get("pair_id") or "")
        paths_dir = localize_artifact(str(pair.get("paths_dir") or ""), path_root)
        normalized = normalize_case(source)
        if normalized:
            out[normalized] = {
                "paths_dir": paths_dir if paths_dir.is_dir() else None,
                "generation_failure": "",
            }
    generation = read_json(path_root / "generation_summary.json")
    failures: Iterable[dict[str, Any]] = (
        manifest.get("failures", []) + generation.get("failures", [])
    )
    for failure in failures:
        normalized = normalize_case(
            str(failure.get("case") or failure.get("source_case") or "")
        )
        if normalized:
            entry = out.setdefault(
                normalized, {"paths_dir": None, "generation_failure": ""}
            )
            entry["generation_failure"] = str(
                failure.get("error") or failure.get("status") or "generation failed"
            )
            recovered = failure_paths_dir(failure, path_root)
            if recovered is not None:
                entry["paths_dir"] = recovered
    return out


def evaluation_index(eval_root: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    results = eval_root / "results.csv"
    if not results.is_file():
        return out
    for row in read_csv(results):
        if row.get("group") == "fmcad_align" and row.get("pair_id"):
            out[row["pair_id"].lower()] = row
    return out


def bool_value(value: Any) -> bool:
    return value is True or str(value).lower() in {"true", "1"}


def target_names(item: dict[str, str]) -> list[str]:
    """Return stable target labels for a jointly wrapped all-methods case."""
    if item.get("support_status") != "supported_targets":
        return []
    names = [
        value.strip()
        for value in str(item.get("entry_name") or "").split("|")
        if value.strip()
    ]
    return list(dict.fromkeys(names))


def extract_target_stdout(stdout: Any, names: Iterable[str]) -> dict[str, str]:
    """Partition wrapper output into target-local blocks without guessing."""
    ordered_names = list(names)
    prefixes = {name: f"Target {name}:" for name in ordered_names}
    blocks: dict[str, list[str]] = {}
    active: str | None = None
    for raw_line in str(stdout or "").splitlines():
        matched = next(
            (
                name
                for name in ordered_names
                if raw_line.startswith(prefixes[name])
            ),
            None,
        )
        if matched is not None:
            active = matched
            blocks.setdefault(active, []).append(raw_line)
            continue
        if raw_line.startswith("Target ") or raw_line.startswith("Result:"):
            active = None
            continue
        if active is not None:
            blocks[active].append(raw_line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def report_target_replay_events(
    report: dict[str, Any],
    names: list[str],
) -> list[dict[str, Any]]:
    """Extract compact, target-partitioned observations from replay evidence."""
    events: list[dict[str, Any]] = []
    mismatches = report.get("confirmed_mismatches", [])
    if not isinstance(mismatches, list):
        return events
    for mismatch in mismatches:
        if not isinstance(mismatch, dict):
            continue
        replay = mismatch.get("replay") or {}
        if not isinstance(replay, dict):
            continue
        left = replay.get("left") or {}
        right = replay.get("right") or {}
        left_blocks = extract_target_stdout(left.get("stdout"), names)
        right_blocks = extract_target_stdout(right.get("stdout"), names)
        stdin = str(replay.get("stdin") or "")
        for name in names:
            left_text = left_blocks.get(name)
            right_text = right_blocks.get(name)
            events.append(
                {
                    "target": name,
                    "source": str(mismatch.get("source") or ""),
                    "target_path": str(mismatch.get("target") or ""),
                    "classification": str(replay.get("classification") or ""),
                    "reason": str(replay.get("reason") or ""),
                    "stdin_sha256": (
                        hashlib.sha256(stdin.encode("utf-8")).hexdigest()
                        if stdin
                        else ""
                    ),
                    "left_stdout": left_text,
                    "right_stdout": right_text,
                    "observable_output_diff": (
                        left_text is not None
                        and right_text is not None
                        and left_text != right_text
                    ),
                    "return_observation": (
                        "encoded_in_target_stdout"
                        if left_text is not None or right_text is not None
                        else "unavailable"
                    ),
                    "global_state_observation": "process_level_aggregate",
                }
            )
    return events


def target_audit(
    item: dict[str, str],
    events: list[dict[str, Any]],
    verdict: str,
) -> list[dict[str, Any]]:
    """Derive target verdicts without attributing whole-process differences."""
    names = target_names(item)
    rows: list[dict[str, Any]] = []
    for name in names:
        target_events = [event for event in events if event.get("target") == name]
        differing = [
            event for event in target_events if event.get("observable_output_diff")
        ]
        witness = differing[0] if differing else (target_events[0] if target_events else {})
        if verdict == "EQ":
            status = "EQ"
            reason = "complete_case_semantic_cover_proof"
        elif differing:
            status = "NEQ"
            reason = "target_local_observable_difference"
        else:
            status = "UNK"
            reason = (
                "confirmed_case_neq_not_localized_to_target"
                if verdict == "NEQ"
                else "case_level_semantic_unknown"
            )
        rows.append(
            {
                "case_id": item["case_id"],
                "target": name,
                "status": status,
                "reason": reason,
                "evidence_source": witness.get("source", ""),
                "evidence_target_path": witness.get("target_path", ""),
                "definedness_classification": witness.get("classification", ""),
                "stdin_sha256": witness.get("stdin_sha256", ""),
                "left_stdout": witness.get("left_stdout") or "",
                "right_stdout": witness.get("right_stdout") or "",
                "observable_output_diff": bool(
                    witness.get("observable_output_diff", False)
                ),
                "return_observation": witness.get(
                    "return_observation", "unavailable"
                ),
                "global_state_observation": witness.get(
                    "global_state_observation", "process_level_aggregate"
                ),
            }
        )
    return rows


def aggregate_target_verdict(rows: list[dict[str, Any]]) -> str:
    """Aggregate target evidence: any NEQ, else all EQ, otherwise UNK."""
    if not rows:
        return ""
    statuses = [row["status"] for row in rows]
    if "NEQ" in statuses:
        return "NEQ"
    if statuses and all(status == "EQ" for status in statuses):
        return "EQ"
    return "UNK"


def public_message(value: Any) -> str:
    """Keep a failure cause while removing generated filesystem paths."""
    text = str(value or "")
    # Preserve an appended diagnostic such as ``(SIGKILL/OOM)`` while removing
    # the generated binary and log paths that precede it.
    text = re.sub(
        r"\s+for\s+[^;]+;\s*see\s+[^;]+?(?=\s+\(|\s+\||$)", "", text
    )
    text = re.sub(r"/workspace/[^;,\s]+", "<generated-path>", text)
    text = re.sub(r"[A-Za-z]:\\[^;,\s]+", "<generated-path>", text)
    return text.strip()


def execution_failure_detail(paths_dir: Path, prefix: str) -> str:
    """Recover a concise process-level cause omitted by failure.json."""
    log_path = paths_dir / f"{prefix}_symbolic_execution.log"
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if re.search(r"returncode\s*=\s*-9\b", text):
        return "symbolic executor terminated by SIGKILL (typically OOM)"
    return ""


def path_evidence(paths_dir: Path | None, generation_failure: str) -> dict[str, Any]:
    if paths_dir is None:
        return {
            "artifact_status": "failed" if generation_failure else "not_attempted",
            "old_path_count": 0,
            "new_path_count": 0,
            "old_complete": False,
            "new_complete": False,
            "both_complete": False,
            "incomplete_reasons": public_message(generation_failure),
            "failure": public_message(generation_failure),
        }
    counts: dict[str, int] = {}
    complete: dict[str, bool] = {}
    incomplete_reasons: list[str] = []
    failures: list[str] = []
    for prefix in ("symbolic_oldV", "symbolic_newV"):
        counts[prefix] = len(list(paths_dir.glob(f"{prefix}_path_*.txt")))
        exploration = read_json(paths_dir / f"{prefix}_exploration.json")
        complete[prefix] = exploration.get("complete") is True
        reasons = exploration.get("incomplete_reasons", [])
        if isinstance(reasons, list):
            incomplete_reasons.extend(f"{prefix}: {reason}" for reason in reasons)
        failure = read_json(paths_dir / f"{prefix}_failure.json")
        if failure:
            detail = execution_failure_detail(paths_dir, prefix)
            failures.append(
                f"{prefix}: "
                f"{failure.get('error') or failure.get('status') or 'failure'}"
                f"{f' ({detail})' if detail else ''}"
            )
    if counts["symbolic_oldV"] and counts["symbolic_newV"]:
        artifact_status = "both_sides"
    elif counts["symbolic_oldV"] or counts["symbolic_newV"]:
        artifact_status = "partial"
    elif complete or failures:
        artifact_status = "failed"
    else:
        artifact_status = "not_attempted"
    both_complete = (
        complete["symbolic_oldV"]
        and complete["symbolic_newV"]
        and counts["symbolic_oldV"] > 0
        and counts["symbolic_newV"] > 0
        and not failures
    )
    for prefix in ("symbolic_oldV", "symbolic_newV"):
        has_reason = any(reason.startswith(f"{prefix}:") for reason in incomplete_reasons)
        if not complete[prefix] and not has_reason:
            incomplete_reasons.append(f"{prefix}: marker missing or incomplete")
    return {
        "artifact_status": artifact_status,
        "old_path_count": counts["symbolic_oldV"],
        "new_path_count": counts["symbolic_newV"],
        "old_complete": complete["symbolic_oldV"],
        "new_complete": complete["symbolic_newV"],
        "both_complete": both_complete,
        "incomplete_reasons": " | ".join(dict.fromkeys(incomplete_reasons)),
        "failure": public_message(" | ".join(failures) or generation_failure),
    }


def report_exploration_complete(report: dict[str, Any]) -> tuple[bool, bool]:
    exploration = report.get("exploration", {})
    if not isinstance(exploration, dict):
        return False, False
    return (
        bool_value((exploration.get("symbolic_oldV") or {}).get("complete")),
        bool_value((exploration.get("symbolic_newV") or {}).get("complete")),
    )


def direct_report(eval_root: Path, pair_id: str) -> dict[str, Any]:
    standard = eval_root / "raw" / pair_id / "fmcad" / "verification_report.json"
    if standard.is_file():
        return read_json(standard)
    return read_json(eval_root / pair_id / "fmcad.json")


def stage_evidence(
    name: str,
    path_root: Path,
    eval_root: Path,
    item: dict[str, str],
    paths: dict[str, dict[str, Any]],
    evaluations: dict[str, dict[str, str]],
) -> dict[str, Any]:
    source = normalize_case(item.get("source_case", ""))
    indexed = paths.get(source, {})
    path = path_evidence(
        indexed.get("paths_dir"), str(indexed.get("generation_failure") or "")
    )
    pair_id = item.get("case_id") or item.get("pair_id") or ""
    evaluation = evaluations.get(pair_id.lower(), {})
    report = direct_report(eval_root, pair_id)
    if not evaluation and report:
        # A fully written verifier report is itself atomic evidence.  Support
        # targeted/manual reruns that intentionally skip results.csv.
        prediction = report.get("prediction")
        evaluation = {
            "status": "ok",
            "prediction": "" if prediction is None else str(prediction).lower(),
        }
    report_old, report_new = report_exploration_complete(report)
    verdict = str(report.get("verdict") or "").upper()
    prediction = evaluation.get("prediction", "")
    names = target_names(item)
    target_events = report_target_replay_events(report, names) if names else []
    if verdict not in {"EQ", "NEQ", "UNK"}:
        if bool_value(prediction):
            verdict = "EQ"
        elif prediction not in (None, "", "None"):
            verdict = "NEQ"
        elif evaluation:
            verdict = "UNK"
    return {
        "attempt": name,
        "pair_id": pair_id,
        **path,
        "evaluation_status": evaluation.get("status", ""),
        "verdict": verdict,
        "prediction": prediction,
        "evaluation_error": public_message(evaluation.get("error", "")),
        "wall_seconds": evaluation.get("evaluation_wall_seconds", ""),
        "t_se": report.get("t_se", ""),
        "t_align": report.get("t_align", ""),
        "t_smt": report.get("t_smt", ""),
        "t_total": report.get("t_total", ""),
        "candidate_pairs": report.get("candidate_pairs", ""),
        "aligned_pairs": report.get("aligned_pairs", ""),
        "smt_calls": report.get("smt_calls", ""),
        "unknowns": report.get("unknowns", ""),
        "report_old_complete": report_old,
        "report_new_complete": report_new,
        "report_confirms_both_complete": report_old and report_new,
        "definedness_audit": report.get("definedness_audit", {}) or {},
        "target_replay_events": target_events,
    }


def valid_verdict(stage: dict[str, Any]) -> str:
    if stage["evaluation_status"] != "ok":
        return ""
    verdict = stage["verdict"]
    if verdict == "NEQ":
        return "NEQ"
    if (
        verdict == "EQ"
        and stage["both_complete"]
        and stage["report_confirms_both_complete"]
    ):
        return "EQ"
    return ""


def select_stage(stages: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """Prefer a later complete EQ, otherwise a later successful NEQ."""
    if not stages:
        return None, ""
    trustworthy = [(stage, valid_verdict(stage)) for stage in stages]
    eq_stages = [(stage, value) for stage, value in trustworthy if value == "EQ"]
    neq_exists = any(value == "NEQ" for _, value in trustworthy)
    if eq_stages:
        selected, _ = eq_stages[-1]
        return (
            (selected, "conflicting_stage_verdicts")
            if neq_exists
            else (selected, "EQ")
        )
    neq_stages = [(stage, value) for stage, value in trustworthy if value == "NEQ"]
    if neq_stages:
        selected, _ = neq_stages[-1]
        return selected, "NEQ"
    attempted = [
        stage
        for stage in stages
        if stage["evaluation_status"] or stage["artifact_status"] != "not_attempted"
    ]
    if not attempted:
        return None, "UNK"
    selected = max(
        enumerate(attempted),
        key=lambda item: (
            item[1]["both_complete"],
            int(item[1]["old_path_count"] or 0)
            + int(item[1]["new_path_count"] or 0),
            item[0],
        ),
    )[1]
    return selected, "UNK"


def load_overrides(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    return {
        row["case_id"].lower(): row["outcome_override"].strip()
        for row in read_csv(path)
        if row.get("case_id") and row.get("outcome_override", "").strip()
    }


def classify(
    verdict: str,
    ground_truth: str,
    override: str,
    *,
    supported: bool,
    attempted: bool,
) -> tuple[str, str]:
    if not supported:
        return "not_attempted", ""
    if verdict in {"EQ", "NEQ"}:
        correct = verdict == ground_truth
        outcome = (
            f"correct_{verdict.lower()}" if correct else f"wrong_{verdict.lower()}"
        )
        return (
            (override if not correct and override else outcome),
            "" if not correct and override else str(correct).lower(),
        )
    return ("unk" if attempted else "failed"), ""


def baseline_index(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    return {row["case_id"].lower(): row for row in read_csv(path)}


def failure_category(row: dict[str, Any]) -> str:
    """Classify each case that did not reach a determinate audited outcome."""
    if row.get("support_status") == "unsupported":
        return "unsupported_harness"
    if row.get("outcome") not in {"failed", "unk"}:
        return ""
    failure = str(row.get("path_failure") or "").lower()
    incomplete = str(row.get("incomplete_reasons") or "").lower()
    old_paths = int(row.get("old_path_count", 0) or 0)
    new_paths = int(row.get("new_path_count", 0) or 0)
    if "sigkill" in failure or "oom" in failure:
        return "sigkill_or_oom"
    if (
        "timeout" in failure
        or "timed out" in failure
        or "timeout" in incomplete
    ):
        return "symbolic_timeout"
    if old_paths + new_paths == 0:
        if "no complete paths" in failure:
            return "no_complete_paths"
        if failure:
            return "other_symbolic_execution_failure"
        return "unclassified_failure"
    if not bool_value(row.get("both_complete")):
        return "incomplete_symbolic_exploration"
    return "verifier_or_semantic_unknown"


def metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = Counter(row["outcome"] for row in rows)
    failure_categories = Counter(row.get("failure_category") or "" for row in rows)
    failure_categories.pop("", None)
    supported = [row for row in rows if row["support_status"] != "unsupported"]
    target_cases = [row for row in rows if int(row.get("target_count", 0) or 0) > 0]
    target_verdicts = Counter(
        row.get("target_verdict") or "" for row in target_cases
    )
    target_verdicts.pop("", None)
    target_statuses: Counter[str] = Counter()
    for row in target_cases:
        try:
            target_statuses.update(
                json.loads(row.get("target_statuses") or "{}").values()
            )
        except (AttributeError, TypeError, json.JSONDecodeError):
            continue
    definedness: Counter[str] = Counter()
    for row in rows:
        try:
            definedness.update(json.loads(row.get("definedness_classifications") or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
    return {
        "total": len(rows),
        "supported": len(supported),
        "unsupported": len(rows) - len(supported),
        "entered_symbolic_execution": sum(
            int(row["old_path_count"]) + int(row["new_path_count"]) > 0
            for row in supported
        ),
        "both_sides_path_artifacts": sum(
            row["artifact_status"] == "both_sides" for row in supported
        ),
        "both_sides_complete": sum(row["both_complete"] for row in supported),
        "incomplete_exploration": sum(
            int(row["old_path_count"]) + int(row["new_path_count"]) > 0
            and not row["both_complete"]
            for row in supported
        ),
        "no_path_artifact": sum(
            int(row["old_path_count"]) + int(row["new_path_count"]) == 0
            for row in supported
        ),
        "target_cases": len(target_cases),
        "target_observations": sum(
            int(row.get("target_count", 0) or 0) for row in target_cases
        ),
        "target_verdicts": dict(sorted(target_verdicts.items())),
        "target_statuses": dict(sorted(target_statuses.items())),
        "target_inconsistent_cases": sum(
            row.get("target_audit_consistent") is False for row in target_cases
        ),
        "correct": outcomes["correct_eq"] + outcomes["correct_neq"],
        "determinate": sum(
            outcomes[key]
            for key in ("correct_eq", "correct_neq", "wrong_eq", "wrong_neq")
        ),
        "unknown_as_neq_witnesses": sum(
            int(row.get("unknown_as_neq", 0) or 0) for row in rows
        ),
        "definedness_classifications": dict(sorted(definedness.items())),
        "failure_categories": dict(sorted(failure_categories.items())),
        "outcomes": {key: outcomes[key] for key in OUTCOME_KEYS},
    }


def write_summary(
    summary: dict[str, Any],
    family_rows: list[dict[str, Any]],
    output_dir: Path,
    *,
    title: str,
    conflicts: list[str],
    upstream_summary: dict[str, Any],
) -> None:
    lines = [
        f"# {title}",
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
        "An EQ is accepted only when both exploration manifests and the",
        "matching verifier report are complete. A NEQ remains valid when a",
        "verified, replayable observable difference exists.",
        "",
        "## Target-level audit",
        "",
        "Jointly wrapped cases are partitioned by their `Target <name>:`",
        "stdout blocks. A target is reported as NEQ only when that block",
        "differs on the same replayed input; a whole-process difference is",
        "never attributed to every target.",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Multi-target cases | {summary['target_cases']} |",
        f"| Target observations | {summary['target_observations']} |",
        f"| Target EQ | {summary['target_statuses'].get('EQ', 0)} |",
        f"| Target NEQ | {summary['target_statuses'].get('NEQ', 0)} |",
        f"| Target UNK | {summary['target_statuses'].get('UNK', 0)} |",
        f"| Case/target verdict inconsistencies | "
        f"{summary['target_inconsistent_cases']} |",
        "",
        "## Outcomes",
        "",
        "| Outcome | Cases |",
        "|---|---:|",
        *[f"| {key} | {summary['outcomes'][key]} |" for key in OUTCOME_KEYS],
        f"| **Correct determinate** | **{summary['correct']}** |",
        f"| UB status unknown, treated as NEQ | {summary['unknown_as_neq_witnesses']} |",
        "",
        "### Definedness classifications",
        "",
        "| Classification | Witnesses |",
        "|---|---:|",
        *[
            f"| `{key}` | {value} |"
            for key, value in summary["definedness_classifications"].items()
        ],
        "",
        "## Failure categories",
        "",
        "| Category | Cases |",
        "|---|---:|",
        *[
            f"| `{key}` | {summary['failure_categories'].get(key, 0)} |"
            for key in FAILURE_CATEGORY_KEYS
        ],
        *[
            f"| `{key}` | {value} |"
            for key, value in summary["failure_categories"].items()
            if key not in FAILURE_CATEGORY_KEYS
        ],
        "",
    ]
    if conflicts:
        lines.extend(
            ["## Conflicting attempts", "", *[f"- `{case}`" for case in conflicts], ""]
        )
    lines.extend(
        [
            "## Family table",
            "",
            "| Family | Cases | Supported | Complete | Correct EQ | Correct NEQ | "
            "Wrong EQ | Wrong NEQ | Label inconsistent | Undefined behavior | UNK | "
            "Failed | Not attempted |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in family_rows:
        lines.append(
            "| {family} | {cases} | {supported} | {both_sides_complete} | "
            "{correct_eq} | {correct_neq} | {wrong_eq} | {wrong_neq} | "
            "{label_inconsistent} | {undefined_behavior} | {unk} | {failed} | "
            "{not_attempted} |".format(**row)
        )
    lines.extend(
        [
            "",
            "## Upstream ARDiff 142",
            "",
            "| Cases | Supported | Entered SE | Complete | Correct EQ | "
            "Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | "
            "Undefined behavior | UNK | Failed | Not attempted |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            "| {total} | {supported} | {entered_symbolic_execution} | "
            "{both_sides_complete} | {correct_eq} | {correct_neq} | {wrong_eq} | "
            "{wrong_neq} | {label_inconsistent} | {undefined_behavior} | {unk} | "
            "{failed} | {not_attempted} |".format(
                **{
                    "total": upstream_summary["total"],
                    "supported": upstream_summary["supported"],
                    "entered_symbolic_execution": upstream_summary[
                        "entered_symbolic_execution"
                    ],
                    "both_sides_complete": upstream_summary["both_sides_complete"],
                    **upstream_summary["outcomes"],
                }
            ),
            "",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--attempt-name", action="append", required=True)
    parser.add_argument("--path-root", type=Path, action="append", required=True)
    parser.add_argument("--eval-root", type=Path, action="append", required=True)
    parser.add_argument("--label-audit-csv", type=Path)
    parser.add_argument("--baseline-cases", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--title",
        default="Complete OSF strict audit",
        help="Markdown report title.",
    )
    args = parser.parse_args()

    if not (len(args.attempt_name) == len(args.path_root) == len(args.eval_root)):
        parser.error("attempt names, path roots, and eval roots must have equal counts")
    manifest = read_csv(args.manifest)
    case_ids = [row["case_id"].lower() for row in manifest]
    if len(manifest) != 272 or len(set(case_ids)) != len(manifest):
        parser.error("OSF manifest must contain exactly 272 unique case_id values")

    path_indexes = [path_index(root) for root in args.path_root]
    eval_indexes = [evaluation_index(root) for root in args.eval_root]
    overrides = load_overrides(args.label_audit_csv)
    baseline = baseline_index(args.baseline_cases)
    rows: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []
    target_case_rows: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for item in manifest:
        stages = [
            stage_evidence(name, path_root, eval_root, item, paths, evaluations)
            for name, path_root, eval_root, paths, evaluations in zip(
                args.attempt_name,
                args.path_root,
                args.eval_root,
                path_indexes,
                eval_indexes,
            )
        ]
        selected, verdict = select_stage(stages)
        if verdict == "conflicting_stage_verdicts":
            conflicts.append(item["case_id"])
            verdict = "UNK"
        supported = item.get("support_status") != "unsupported"
        attempted = any(
            int(stage["old_path_count"]) + int(stage["new_path_count"]) > 0
            or stage["evaluation_status"]
            for stage in stages
        )
        outcome, correctness = classify(
            verdict,
            item.get("label", "").upper(),
            overrides.get(item["case_id"].lower(), ""),
            supported=supported,
            attempted=attempted,
        )
        chosen = selected or {}
        case_target_rows = target_audit(
            item,
            chosen.get("target_replay_events", []) or [],
            verdict,
        )
        target_rows.extend(case_target_rows)
        case_target_verdict = aggregate_target_verdict(case_target_rows)
        if case_target_rows:
            target_case_rows.append(
                {
                    "case_id": item["case_id"],
                    "case_verdict": verdict,
                    "target_verdict": case_target_verdict,
                    "target_count": len(case_target_rows),
                    "target_statuses": json.dumps(
                        [
                            {
                                "target": target_row["target"],
                                "status": target_row["status"],
                                "reason": target_row["reason"],
                            }
                            for target_row in case_target_rows
                        ],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "consistent": case_target_verdict == verdict,
                }
            )
        prior = baseline.get(item["case_id"].lower(), {})
        rows.append(
            {
                "case_id": item["case_id"],
                "family": item["family"],
                "program": item["program"],
                "label": item["label"],
                "support_status": item["support_status"],
                "support_reason": public_message(item.get("reason", "")),
                "entry_name": item.get("entry_name", ""),
                "entry_signature": item.get("entry_signature", ""),
                "selection_rule": item.get("selection_rule", ""),
                "upstream_ardiff_pair": item.get("upstream_ardiff_pair", ""),
                "attempt": chosen.get("attempt", ""),
                "artifact_status": chosen.get("artifact_status", "not_attempted"),
                "old_path_count": chosen.get("old_path_count", 0),
                "new_path_count": chosen.get("new_path_count", 0),
                "old_complete": chosen.get("old_complete", False),
                "new_complete": chosen.get("new_complete", False),
                "both_complete": chosen.get("both_complete", False),
                "incomplete_reasons": chosen.get("incomplete_reasons", ""),
                "path_failure": chosen.get("failure", ""),
                "evaluation_status": chosen.get("evaluation_status", ""),
                "verdict": verdict,
                "evaluation_error": chosen.get("evaluation_error", ""),
                "evaluation_wall_seconds": chosen.get("wall_seconds", ""),
                "t_se": chosen.get("t_se", ""),
                "t_align": chosen.get("t_align", ""),
                "t_smt": chosen.get("t_smt", ""),
                "t_total": chosen.get("t_total", ""),
                "candidate_pairs": chosen.get("candidate_pairs", ""),
                "aligned_pairs": chosen.get("aligned_pairs", ""),
                "smt_calls": chosen.get("smt_calls", ""),
                "unknowns": chosen.get("unknowns", ""),
                "target_count": len(case_target_rows),
                "target_verdict": case_target_verdict,
                "target_audit_consistent": (
                    case_target_verdict == verdict if case_target_rows else ""
                ),
                "target_statuses": json.dumps(
                    {
                        target_row["target"]: target_row["status"]
                        for target_row in case_target_rows
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "outcome": outcome,
                "evaluated_correct": correctness,
                "label_audit_override": overrides.get(item["case_id"].lower(), ""),
                "definedness_checks": int(
                    (chosen.get("definedness_audit") or {}).get("checks", 0) or 0
                ),
                "rejected_witnesses": int(
                    (chosen.get("definedness_audit") or {}).get("rejected_witnesses", 0)
                    or 0
                ),
                "unknown_as_neq": int(
                    (chosen.get("definedness_audit") or {}).get("unknown_as_neq", 0)
                    or 0
                ),
                "definedness_classifications": json.dumps(
                    (chosen.get("definedness_audit") or {}).get(
                        "classification_counts", {}
                    ),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "baseline_outcome": prior.get("osf_outcome", ""),
                "baseline_both_complete": (
                    bool_value(prior.get("old_exploration_complete"))
                    and bool_value(prior.get("new_exploration_complete"))
                ),
                "stage_trace": json.dumps(
                    [
                        {
                            key: stage[key]
                            for key in (
                                "attempt", "artifact_status", "old_path_count",
                                "new_path_count", "both_complete",
                                "evaluation_status", "verdict",
                            )
                        }
                        for stage in stages
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )

    for row in rows:
        row["failure_category"] = failure_category(row)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "cases.csv", rows)
    write_csv(output_dir / "targets.csv", target_rows)
    write_csv(output_dir / "target_cases.csv", target_case_rows)
    summary = metric_summary(rows)
    with (output_dir / "outcomes.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("outcome", "cases"))
        writer.writerows((key, summary["outcomes"][key]) for key in OUTCOME_KEYS)
    write_csv(
        output_dir / "failure_summary.csv",
        [
            {"category": category, "cases": count}
            for category, count in summary["failure_categories"].items()
        ],
    )
    write_csv(
        output_dir / "failure_cases.csv",
        [
            {
                key: row[key]
                for key in (
                    "case_id", "family", "label", "support_status",
                    "failure_category", "artifact_status", "old_path_count",
                    "new_path_count", "both_complete", "path_failure",
                    "evaluation_status", "evaluation_error", "outcome",
                )
            }
            for row in rows
            if row["failure_category"]
        ],
    )

    family_rows: list[dict[str, Any]] = []
    for family in sorted({row["family"] for row in rows}):
        family_items = [row for row in rows if row["family"] == family]
        family_summary = metric_summary(family_items)
        family_rows.append(
            {
                "family": family,
                "cases": len(family_items),
                "supported": family_summary["supported"],
                "both_sides_complete": family_summary["both_sides_complete"],
                **family_summary["outcomes"],
            }
        )
    write_csv(output_dir / "family_summary.csv", family_rows)
    upstream_rows = [row for row in rows if row["upstream_ardiff_pair"]]
    upstream_summary = metric_summary(upstream_rows)
    write_csv(output_dir / "upstream_142_cases.csv", upstream_rows)
    write_csv(
        output_dir / "upstream_142_summary.csv",
        [
            {
                "cases": upstream_summary["total"],
                "supported": upstream_summary["supported"],
                "entered_symbolic_execution": upstream_summary[
                    "entered_symbolic_execution"
                ],
                "both_sides_complete": upstream_summary["both_sides_complete"],
                "correct": upstream_summary["correct"],
                **upstream_summary["outcomes"],
            }
        ],
    )
    write_csv(
        output_dir / "ub_cases.csv",
        [
            {
                key: row[key]
                for key in (
                    "case_id", "family", "label", "verdict", "outcome",
                    "definedness_checks", "rejected_witnesses", "unknown_as_neq",
                    "definedness_classifications",
                )
            }
            for row in rows
            if int(row["definedness_checks"])
            or int(row["unknown_as_neq"])
        ],
    )

    comparison_rows: list[dict[str, Any]] = []
    for row in rows:
        before = row["baseline_outcome"] or "not_attempted"
        if before != row["outcome"]:
            comparison_rows.append(
                {
                    "case_id": row["case_id"],
                    "previous_outcome": before,
                    "current_outcome": row["outcome"],
                    "previous_both_complete": row["baseline_both_complete"],
                    "current_both_complete": row["both_complete"],
                }
            )
    write_csv(output_dir / "baseline_changes.csv", comparison_rows)
    if baseline:
        old = metric_summary(
            [
                {
                    **row,
                    "outcome": row["baseline_outcome"] or "not_attempted",
                    "support_status": baseline.get(row["case_id"].lower(), {}).get(
                        "support_status", ""
                    ),
                    "artifact_status": {
                        "complete": "both_sides",
                        "partial": "partial",
                        "failed": "failed",
                    }.get(
                        baseline.get(row["case_id"].lower(), {}).get(
                            "path_status", ""
                        ),
                        "not_attempted",
                    ),
                    "old_path_count": baseline.get(row["case_id"].lower(), {}).get(
                        "old_path_count", 0
                    ),
                    "new_path_count": baseline.get(row["case_id"].lower(), {}).get(
                        "new_path_count", 0
                    ),
                    "both_complete": row["baseline_both_complete"],
                }
                for row in rows
            ]
        )
        summary["baseline"] = old
        summary["delta"] = {
            key: summary[key] - old[key]
            for key in (
                "correct",
                "determinate",
                "both_sides_complete",
                "entered_symbolic_execution",
                "both_sides_path_artifacts",
            )
        }
        summary["delta"]["supported"] = summary["supported"] - old["supported"]
    summary["conflicting_attempts"] = conflicts
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_summary(
        summary,
        family_rows,
        output_dir,
        title=args.title,
        conflicts=conflicts,
        upstream_summary=upstream_summary,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
