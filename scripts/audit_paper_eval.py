#!/usr/bin/env python3
"""Audit the fixed 62-case paper experiment from raw per-case artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from summarize_paper_eval import canonical_case_id


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@dataclass(frozen=True)
class MethodInput:
    name: str
    group: str
    root: Path


def parse_method_input(value: str) -> MethodInput:
    method_spec, raw_path = value.rsplit("=", 1)
    name, separator, group = method_spec.partition(":")
    if not name or not separator or not group or not raw_path:
        raise argparse.ArgumentTypeError(
            "method input must be NAME:GROUP=EVALUATION_DIRECTORY"
        )
    return MethodInput(name=name, group=group, root=Path(raw_path).resolve())


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def as_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def as_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def path_truth_status(payload: dict[str, Any]) -> dict[str, str]:
    statuses = {}
    for item in payload.get("queries", []):
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "")
        if not query:
            continue
        if item.get("unknown_targets"):
            statuses[query] = "unknown"
        elif item.get("related_targets"):
            statuses[query] = "sat"
        else:
            statuses[query] = "unsat"
    return statuses


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def load_path_evidence(
    roots: list[Path],
    expected_keys: set[str],
) -> dict[str, Any]:
    pairs: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    path_failures: list[dict[str, str]] = []
    for root in roots:
        manifest = load_json(root / "manifest.json")
        for pair in manifest.get("pairs") or []:
            key = canonical_case_id(str(pair.get("pair_id") or ""))
            if key not in expected_keys:
                continue
            if key in pairs:
                duplicate_ids.append(key)
            else:
                pairs[key] = {**pair, "_root": str(root)}
        for failure in manifest.get("failures") or []:
            raw_case = str(failure.get("case") or "")
            parts = raw_case.replace("\\", "/").strip("/").split("/")
            if len(parts) >= 3:
                key = canonical_case_id(f"{parts[0]}/{parts[-2]}_{parts[-1]}")
            else:
                key = canonical_case_id(raw_case)
            if key not in expected_keys:
                continue
            path_failures.append(
                {
                    "case_id": key,
                    "error": str(failure.get("error") or "unknown failure"),
                }
            )

    truth_counts = Counter()
    total_candidate_pairs = 0
    incomplete_explorations: list[dict[str, Any]] = []
    bad_profiles: list[str] = []
    graph_backends: Counter[str] = Counter()
    graph_statuses: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    high_confidence_graph_calls: list[str] = []
    bin_diff_fallbacks: list[dict[str, str]] = []
    bin_diff_ready: list[str] = []
    real_bin_diff_cases = 0
    true_mapping_cases = 0
    cache_hits = 0
    for key, pair in pairs.items():
        path_truth = pair.get("path_truth")
        statuses = (
            path_truth_status(path_truth)
            if isinstance(path_truth, dict)
            else {}
        )
        if not statuses or path_truth.get("status") == "pending":
            truth_counts["pending"] += 1
        else:
            truth_counts.update(statuses.values())
        for query in (path_truth or {}).get("queries", []):
            if not isinstance(query, dict):
                continue
            for target in query.get("targets", []) or []:
                if isinstance(target, dict):
                    total_candidate_pairs += 1

        if pair.get("profile_id") != "paper.v3-20261020":
            bad_profiles.append(key)
        paths_dir = (Path(str(pair["_root"])) / str(pair["paths_dir"])).resolve()
        for side in ("oldV", "newV"):
            exploration_path = paths_dir / f"symbolic_{side}_exploration.json"
            if not exploration_path.is_file():
                incomplete_explorations.append(
                    {"case_id": key, "reason": f"missing {exploration_path.name}"}
                )
                continue
            exploration = load_json(exploration_path)
            if not exploration.get("complete"):
                incomplete_explorations.append(
                    {
                        "case_id": key,
                        "side": side,
                        "reasons": exploration.get("incomplete_reasons") or [],
                    }
                )

        ranking_path = Path(str(pair["_root"])) / str(pair["fmcad_ranking_path"])
        ranking = load_json(ranking_path)
        backend = ranking.get("graph_backend") or {}
        backend_name = str(backend.get("backend") or "")
        if not backend_name and backend.get("status") == "not_loaded":
            backend_name = "feature_only_not_requested"
        graph_backends[backend_name or "unknown"] += 1
        graph_statuses[str(backend.get("status") or "unknown")] += 1
        if backend.get("backend") == "google_bindiff_v8":
            real_bin_diff_cases += 1
            if backend.get("status") == "ok":
                true_mapping_cases += 1
                bin_diff_ready.append(key)
            cache_hits += int(bool(backend.get("cache_hit")))
        elif str(backend.get("status")) in {"fallback", "unavailable", "export_failed", "diff_failed"}:
            bin_diff_fallbacks.append(
                {
                    "case_id": key,
                    "status": str(backend.get("status") or ""),
                    "reason": str(backend.get("fallback_reason") or backend.get("reason") or ""),
                }
            )
        for query in ranking.get("queries") or []:
            decision = str(query.get("decision") or "unknown")
            decisions[decision] += 1
            top1 = as_float(query.get("feature_top1")) or 0.0
            margin = as_float(query.get("feature_margin")) or 0.0
            low_confidence = top1 < 0.70 or margin < 0.05
            if "graph_rerank" in decision and not low_confidence:
                high_confidence_graph_calls.append(
                    f"{key}:{query.get('query')}"
                )

    return {
        "cases_found": len(pairs),
        "cases_missing": sorted(expected_keys - set(pairs)),
        "cases_extra": sorted(set(pairs) - expected_keys),
        "duplicate_case_ids": duplicate_ids,
        "path_failures": path_failures,
        "candidate_pairs": total_candidate_pairs,
        "query_truth_status": dict(sorted(truth_counts.items())),
        "incomplete_explorations": incomplete_explorations,
        "bad_profile_cases": bad_profiles,
        "graph_backends": dict(sorted(graph_backends.items())),
        "graph_statuses": dict(sorted(graph_statuses.items())),
        "query_decisions": dict(sorted(decisions.items())),
        "high_confidence_graph_calls": high_confidence_graph_calls,
        "real_bin_diff_cases": real_bin_diff_cases,
        "true_mapping_cases": true_mapping_cases,
        "bin_diff_cache_hits": cache_hits,
        "bin_diff_fallback_cases": bin_diff_fallbacks,
        "bin_diff_ready_cases": sorted(bin_diff_ready),
    }


def load_method_rows(item: MethodInput) -> tuple[list[dict[str, str]], list[str]]:
    path = item.root / "results.csv"
    if not path.is_file():
        return [], [f"missing results.csv: {path}"]
    rows = [
        row
        for row in load_csv(path)
        if str(row.get("group") or "") == item.group
    ]
    keys = [canonical_case_id(str(row.get("pair_id") or "")) for row in rows]
    duplicates = sorted(
        key for key, count in Counter(keys).items() if count > 1
    )
    return rows, duplicates


def summarize_method(
    item: MethodInput,
    rows: list[dict[str, str]],
    duplicates: list[str],
    truth_by_key: dict[str, bool],
) -> dict[str, Any]:
    outcomes = Counter()
    seen = set()
    per_case = []
    one_to_many_old_to_new = 0
    one_to_many_new_to_old = 0
    one_to_many_cases = 0
    one_to_many_case_ids = []
    t_se_total = 0.0
    t_align_total = 0.0
    t_smt_total = 0.0
    t_total_sum = 0.0
    evaluation_wall_sum = 0.0
    ranking_queries = 0
    ranking_all_queries = 0
    ranking_unknown_queries = 0
    ranking_no_related_queries = 0
    ranking_hit1_weighted = 0.0
    ranking_hit3_weighted = 0.0
    ranking_mrr_weighted = 0.0
    for row in rows:
        key = canonical_case_id(str(row.get("pair_id") or ""))
        seen.add(key)
        truth = truth_by_key.get(key)
        status = str(row.get("status") or "")
        prediction = as_bool(row.get("prediction"))
        if status != "ok":
            outcome = "verifier_failed"
        elif prediction is None:
            outcome = "unk"
        elif truth is None:
            outcome = "undetermined"
        elif prediction == truth:
            outcome = "correct_eq" if truth else "correct_neq"
        else:
            outcome = "wrong_eq" if prediction else "wrong_neq"
        outcomes[outcome] += 1
        old_count = int(as_float(row.get("one_to_many_old_to_new")) or 0)
        new_count = int(as_float(row.get("one_to_many_new_to_old")) or 0)
        case_count = int(as_float(row.get("one_to_many_cases")) or 0)
        one_to_many_old_to_new += old_count
        one_to_many_new_to_old += new_count
        one_to_many_cases += case_count
        if old_count or new_count or case_count:
            one_to_many_case_ids.append(key)
        t_se_total += as_float(row.get("t_se")) or 0.0
        t_align_total += as_float(row.get("t_align")) or 0.0
        t_smt_total += as_float(row.get("t_smt")) or 0.0
        t_total_sum += as_float(row.get("t_total")) or 0.0
        evaluation_wall_sum += (
            as_float(row.get("evaluation_wall_seconds")) or 0.0
        )
        query_count = int(as_float(row.get("ranking_queries")) or 0)
        ranking_queries += query_count
        ranking_all_queries += int(
            as_float(row.get("ranking_all_queries")) or 0
        )
        ranking_unknown_queries += int(
            as_float(row.get("ranking_unknown_queries")) or 0
        )
        ranking_no_related_queries += int(
            as_float(row.get("ranking_no_related_queries")) or 0
        )
        ranking_hit1_weighted += query_count * (
            (as_float(row.get("hit_at_1")) or 0.0) / 100.0
        )
        ranking_hit3_weighted += query_count * (
            (as_float(row.get("hit_at_3")) or 0.0) / 100.0
        )
        ranking_mrr_weighted += query_count * (
            as_float(row.get("mrr")) or 0.0
        )
        per_case.append(
            {
                "case_id": key,
                "status": status,
                "ground_truth": truth,
                "prediction": prediction,
                "outcome": outcome,
                "error": str(row.get("error") or ""),
                "t_total": as_float(row.get("t_total")),
            }
        )
    expected = set(truth_by_key)
    correct = outcomes["correct_eq"] + outcomes["correct_neq"]
    return {
        "method": item.name,
        "group": item.group,
        "evaluation_root": str(item.root),
        "cases_run": len(rows),
        "cases_unique": len(seen),
        "expected_cases": len(expected),
        "cases_missing": sorted(expected - seen),
        "cases_extra": sorted(seen - expected),
        "duplicate_case_ids": duplicates,
        "correct": correct,
        "wrong": outcomes["wrong_eq"] + outcomes["wrong_neq"],
        "wrong_eq": outcomes["wrong_eq"],
        "wrong_neq": outcomes["wrong_neq"],
        "unk": outcomes["unk"],
        "verifier_failed": outcomes["verifier_failed"],
        "undetermined": outcomes["undetermined"],
        "correct_rate_percent": 100.0 * correct / len(expected) if expected else None,
        "one_to_many_old_to_new": one_to_many_old_to_new,
        "one_to_many_new_to_old": one_to_many_new_to_old,
        "one_to_many_cases": one_to_many_cases,
        "one_to_many_case_ids": sorted(set(one_to_many_case_ids)),
        "ranking_queries": ranking_queries,
        "ranking_all_queries": ranking_all_queries,
        "ranking_unknown_queries": ranking_unknown_queries,
        "ranking_no_related_queries": ranking_no_related_queries,
        "hit_at_1_percent": (
            100.0 * ranking_hit1_weighted / ranking_queries
            if ranking_queries
            else None
        ),
        "hit_at_3_percent": (
            100.0 * ranking_hit3_weighted / ranking_queries
            if ranking_queries
            else None
        ),
        "mrr": (
            ranking_mrr_weighted / ranking_queries
            if ranking_queries
            else None
        ),
        "t_se_recorded_seconds": t_se_total,
        "t_align_seconds": t_align_total,
        "t_smt_seconds": t_smt_total,
        "derived_t_total_seconds": t_total_sum,
        "evaluation_wall_seconds": evaluation_wall_sum,
        "mean_evaluation_wall_seconds": (
            evaluation_wall_sum / len(expected) if expected else None
        ),
        "mean_derived_t_total_all_cases": (
            t_total_sum / len(expected) if expected else None
        ),
        "completed_total_seconds": sum(
            value for value in (
                as_float(row.get("t_total")) for row in rows
            ) if value is not None
        ),
        "per_case": per_case,
    }


def build_markdown(audit: dict[str, Any]) -> str:
    path = audit["path_evidence"]
    lines = [
        "# Paper experiment audit",
        "",
        f"- Fixed manifest cases: {audit['fixed_cases']}",
        f"- Ground truth: `{json.dumps(audit['ground_truth_counts'], sort_keys=True)}`",
        f"- Path evidence cases: {path['cases_found']}",
        f"- Path evidence missing: {len(path['cases_missing'])}",
        f"- Path evidence extra: {len(path['cases_extra'])}",
        f"- Path failures: {len(path['path_failures'])}",
        f"- Incomplete explorations: {len(path['incomplete_explorations'])}",
        f"- Candidate path pairs: {path['candidate_pairs']}",
        f"- Query truth statuses: `{json.dumps(path['query_truth_status'], sort_keys=True)}`",
        (
            "- Ranking-eligible queries: "
            f"{path['query_truth_status'].get('sat', 0)} / "
            f"{sum(path['query_truth_status'].values())} "
            f"({path['query_truth_status'].get('unknown', 0)} unknown, "
            f"{path['query_truth_status'].get('unsat', 0)} no-related)"
        ),
        f"- Graph backends: `{json.dumps(path['graph_backends'], sort_keys=True)}`",
        f"- Graph statuses: `{json.dumps(path['graph_statuses'], sort_keys=True)}`",
        f"- Query decisions: `{json.dumps(path['query_decisions'], sort_keys=True)}`",
        f"- Real BinDiff cases with parsed mapping: {path['true_mapping_cases']}",
        f"- BinDiff fallback cases: {len(path['bin_diff_fallback_cases'])}",
        f"- High-confidence graph reranks: {len(path['high_confidence_graph_calls'])}",
        "",
        "| Method | Cases | Unique | Missing | Correct | Wrong EQ | Wrong NEQ | UNK | Verifier failed | Correct rate | 1→N old/new records | 1→N cases |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in audit["methods"]:
        rate = method["correct_rate_percent"]
        rate_text = "NA" if rate is None else f"{rate:.2f}%"
        lines.append(
            f"| {method['method']} | {method['cases_run']} | "
            f"{method['cases_unique']} | {len(method['cases_missing'])} | "
            f"{method['correct']} | {method['wrong_eq']} | "
            f"{method['wrong_neq']} | {method['unk']} | "
            f"{method['verifier_failed']} | {rate_text} | "
            f"{method['one_to_many_old_to_new']}/{method['one_to_many_new_to_old']} | "
            f"{method['one_to_many_cases']} |"
        )
    lines.extend(
        [
            "",
            "Correct rate always uses the 62 fixed manifest cases as its denominator.",
            "Missing or verifier-failed cases remain explicit and are not treated as correct or UNK.",
        ]
    )
    lines.extend(
        [
            "",
            "## Ranking and timing",
            "",
            "| Method | Eligible queries | Hit@1 | Hit@3 | MRR | SE recorded | Align | SMT | Derived total | Eval wall sum | Mean wall/case |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method in audit["methods"]:
        hit1 = (
            "NA"
            if method["hit_at_1_percent"] is None
            else f"{method['hit_at_1_percent']:.2f}%"
        )
        hit3 = (
            "NA"
            if method["hit_at_3_percent"] is None
            else f"{method['hit_at_3_percent']:.2f}%"
        )
        mrr = (
            "NA" if method["mrr"] is None else f"{method['mrr']:.4f}"
        )
        wall_mean = (
            "NA"
            if method["mean_evaluation_wall_seconds"] is None
            else f"{method['mean_evaluation_wall_seconds']:.2f}s"
        )
        lines.append(
            f"| {method['method']} | {method['ranking_queries']} | "
            f"{hit1} | {hit3} | {mrr} | "
            f"{method['t_se_recorded_seconds']:.2f}s | "
            f"{method['t_align_seconds']:.2f}s | "
            f"{method['t_smt_seconds']:.2f}s | "
            f"{method['derived_t_total_seconds']:.2f}s | "
            f"{method['evaluation_wall_seconds']:.2f}s | {wall_mean} |"
        )
    lines.extend(
        [
            "",
            "SE is read from the original path-generation logs. Align, SMT and",
            "their sum are evaluation-time stage values; this run reused paths",
            "and does not claim that SE was re-executed. When a timeout occurs,",
            "its 300-second wall-clock cap is included in the SMT component.",
            "Eval wall is the measured verifier subprocess wall time per case;",
            "it is not added to the historical SE log time.",
        ]
    )
    if path["bin_diff_fallback_cases"]:
        lines.extend(["", "## BinDiff fallbacks", ""])
        for item in path["bin_diff_fallback_cases"]:
            lines.append(
                f"- `{item['case_id']}`: {item['status']} ({item['reason']})"
            )
    if audit["issues"]:
        lines.extend(["", "## Audit issues", ""])
        lines.extend(f"- {issue}" for issue in audit["issues"])
    else:
        lines.extend(["", "No structural audit issues were found."])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-manifest", type=Path, required=True)
    parser.add_argument("--benchmarks", type=Path, action="append", required=True)
    parser.add_argument(
        "--method",
        action="append",
        type=parse_method_input,
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    paper_rows = load_csv(args.paper_manifest)
    truth_by_key = {
        canonical_case_id(row["case_id"]): row["ground_truth"] == "EQ"
        for row in paper_rows
    }
    path_evidence = load_path_evidence(
        [root.resolve() for root in args.benchmarks],
        set(truth_by_key),
    )
    grouped_inputs: dict[tuple[str, str], list[MethodInput]] = {}
    for item in args.method:
        grouped_inputs.setdefault((item.name, item.group), []).append(item)
    methods = []
    method_errors = []
    for (name, group), items in grouped_inputs.items():
        rows: list[dict[str, str]] = []
        duplicate_ids: list[str] = []
        for item in items:
            item_rows, item_duplicates = load_method_rows(item)
            item_rows = [
                row
                for row in item_rows
                if canonical_case_id(str(row.get("pair_id") or ""))
                in truth_by_key
            ]
            rows.extend(item_rows)
            duplicate_ids.extend(item_duplicates)
        across_shards = Counter(
            canonical_case_id(str(row.get("pair_id") or ""))
            for row in rows
        )
        duplicate_ids.extend(
            key for key, count in across_shards.items() if count > 1
        )
        duplicate_ids = sorted(set(duplicate_ids))
        aggregate_item = MethodInput(
            name=name,
            group=group,
            root=Path("+".join(str(item.root) for item in items)),
        )
        methods.append(
            summarize_method(
                aggregate_item,
                rows,
                duplicate_ids,
                truth_by_key,
            )
        )
        if not rows:
            method_errors.append(f"{name}: no rows for group {group}")

    issues = []
    if path_evidence["cases_missing"]:
        issues.append(f"missing path cases: {path_evidence['cases_missing']}")
    if path_evidence["cases_extra"]:
        issues.append(f"extra path cases: {path_evidence['cases_extra']}")
    if path_evidence["duplicate_case_ids"]:
        issues.append("duplicate path cases")
    if path_evidence["path_failures"]:
        issues.append("path generation failures exist")
    if path_evidence["query_truth_status"].get("pending"):
        issues.append("path truth is still pending")
    if path_evidence["high_confidence_graph_calls"]:
        issues.append("graph reranking occurred above the confidence threshold")
    for method in methods:
        if method["cases_run"] != len(truth_by_key):
            issues.append(
                f"{method['method']} has {method['cases_run']} rows, expected {len(truth_by_key)}"
            )
        if method["duplicate_case_ids"]:
            issues.append(f"{method['method']} has duplicate case rows")
        if method["cases_missing"]:
            issues.append(f"{method['method']} is missing case rows")
    issues.extend(method_errors)

    audit = {
        "schema": "symbolicana.paper_audit.v1",
        "paper_manifest": str(args.paper_manifest.resolve()),
        "fixed_cases": len(paper_rows),
        "ground_truth_counts": dict(Counter(row["ground_truth"] for row in paper_rows)),
        "path_evidence": path_evidence,
        "methods": methods,
        "issues": issues,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "audit.md").write_text(
        build_markdown(audit),
        encoding="utf-8",
    )
    print(f"wrote {args.output_dir / 'audit.md'}")
    # Path failures and missing method rows are expected for an UNK benchmark;
    # they are recorded in the report rather than treated as harness crashes.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
