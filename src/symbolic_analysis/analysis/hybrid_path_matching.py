"""
Hybrid path matching: feature-vector retrieval with BinDiff-style graph reranking.

The default path is the existing 11-dimensional constraint feature vector plus
cosine similarity. When that ranking is low-confidence, this module reranks all
candidate paths using VeriBin's BinDiff-style basic-block overlap score.
"""

from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from symbolic_analysis.analysis.path_constraint_features import (
    extract_features,
    normalize_features,
)
from symbolic_analysis.tracing import time_block


@dataclass(frozen=True)
class PathRecord:
    path_id: str
    path: Path
    content: str
    vector: list[float]
    trace: list[int]


@dataclass(frozen=True)
class HybridConfig:
    high_threshold: float = 0.80
    margin_threshold: float = 0.05
    graph_min_score: float = 0.01
    graph_weight: float = 1.0
    feature_weight: float = 0.0


def load_path_records(paths: list[Path], min_max: Optional[dict[str, tuple[float, float]]] = None) -> list[PathRecord]:
    records = []
    for path in sorted(paths, key=lambda p: natural_path_key(p.stem)):
        content = path.read_text(encoding="utf-8", errors="replace")
        raw, _ = extract_features(content)
        records.append(
            PathRecord(
                path_id=path.stem,
                path=path,
                content=content,
                vector=normalize_features(raw, min_max),
                trace=parse_execution_trace(content),
            )
        )
    return records


def compute_min_max_for_paths(paths: list[Path]) -> dict[str, tuple[float, float]]:
    raw_by_id = {}
    for path in paths:
        content = path.read_text(encoding="utf-8", errors="replace")
        raw_by_id[path.stem] = extract_features(content)[0]
    names = [
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
    values = list(raw_by_id.values())
    if not values:
        return {}
    return {
        name: (min(vec[i] for vec in values), max(vec[i] for vec in values))
        for i, name in enumerate(names)
    }


def hybrid_rank_paths(
    old_paths: list[Path],
    new_paths: list[Path],
    config: HybridConfig = HybridConfig(),
    matching_bb_map: Optional[dict[int, int]] = None,
) -> dict[str, Any]:
    with time_block(
        "align",
        "hybrid_feature_graph_path_matching",
        old_path_count=len(old_paths),
        new_path_count=len(new_paths),
    ) as trace:
        min_max = compute_min_max_for_paths(old_paths + new_paths)
        old_records = load_path_records(old_paths, min_max)
        new_records = load_path_records(new_paths, min_max)
        graph_available = has_graph_evidence(old_records, new_records, matching_bb_map)
        queries = []
        reranked_queries = 0
        fallback_queries = 0

        for old in old_records:
            feature_ranking = feature_rank(old, new_records)
            confidence = ranking_confidence(feature_ranking, config)
            use_graph = confidence["low_confidence"] and graph_available
            final_ranking = feature_ranking
            reason = confidence["reason"]

            if use_graph:
                graph_ranking = graph_rank_all(old, new_records, feature_ranking, matching_bb_map, config)
                if graph_ranking and graph_ranking[0]["graph_similarity"] >= config.graph_min_score:
                    final_ranking = graph_ranking
                    reranked_queries += 1
                    reason = "graph_rerank"
                else:
                    fallback_queries += 1
                    reason = "graph_failed_feature_fallback"
            elif confidence["low_confidence"]:
                fallback_queries += 1
                reason = "graph_unavailable_feature_fallback"

            queries.append(
                {
                    "query": old.path_id,
                    "decision": reason,
                    "feature_top1": confidence["top1"],
                    "feature_margin": confidence["margin"],
                    "ranking": final_ranking,
                }
            )

        trace["graph_available"] = graph_available
        trace["reranked_queries"] = reranked_queries
        trace["fallback_queries"] = fallback_queries
        trace["candidate_pairs"] = len(old_records) * len(new_records)

    return {
        "method": "hybrid_feature_cosine_bindiff_graph",
        "config": {
            "high_threshold": config.high_threshold,
            "margin_threshold": config.margin_threshold,
            "graph_min_score": config.graph_min_score,
            "graph_weight": config.graph_weight,
            "feature_weight": config.feature_weight,
        },
        "graph_available": graph_available,
        "queries": queries,
    }


def feature_rank(old: PathRecord, new_records: list[PathRecord]) -> list[dict[str, Any]]:
    ranking = []
    for new in new_records:
        score = cosine(old.vector, new.vector)
        ranking.append(
            {
                "path_id": new.path_id,
                "similarity": round(score, 6),
                "feature_similarity": round(score, 6),
            }
        )
    ranking.sort(key=lambda item: (-item["similarity"], natural_path_key(item["path_id"])))
    return ranking


def ranking_confidence(ranking: list[dict[str, Any]], config: HybridConfig) -> dict[str, Any]:
    top1 = float(ranking[0]["feature_similarity"]) if ranking else 0.0
    top2 = float(ranking[1]["feature_similarity"]) if len(ranking) > 1 else 0.0
    margin = top1 - top2
    if top1 < config.high_threshold:
        return {"low_confidence": True, "top1": top1, "margin": margin, "reason": "low_feature_score"}
    if margin < config.margin_threshold:
        return {"low_confidence": True, "top1": top1, "margin": margin, "reason": "small_feature_margin"}
    return {"low_confidence": False, "top1": top1, "margin": margin, "reason": "feature_confident"}


def graph_rank_all(
    old: PathRecord,
    new_records: list[PathRecord],
    feature_ranking: list[dict[str, Any]],
    matching_bb_map: Optional[dict[int, int]],
    config: HybridConfig,
) -> list[dict[str, Any]]:
    feature_by_id = {item["path_id"]: float(item["feature_similarity"]) for item in feature_ranking}
    ranking = []
    for new in new_records:
        graph_score = bindiff_path_similarity(old.trace, new.trace, matching_bb_map)
        feature_score = feature_by_id.get(new.path_id, 0.0)
        final_score = config.graph_weight * graph_score + config.feature_weight * feature_score
        ranking.append(
            {
                "path_id": new.path_id,
                "similarity": round(final_score, 6),
                "feature_similarity": round(feature_score, 6),
                "graph_similarity": round(graph_score, 6),
            }
        )
    ranking.sort(key=lambda item: (-item["similarity"], natural_path_key(item["path_id"])))
    return ranking


def bindiff_path_similarity(
    old_trace: list[int],
    new_trace: list[int],
    matching_bb_map: Optional[dict[int, int]] = None,
) -> float:
    if not old_trace or not new_trace:
        return 0.0
    if matching_bb_map:
        score = 0
        visited_old = []
        for old_addr in old_trace:
            mapped_new = matching_bb_map.get(old_addr)
            if mapped_new is None or mapped_new not in new_trace:
                continue
            if old_addr not in visited_old:
                visited_old.append(old_addr)
                score += 1
            elif new_trace.count(mapped_new) >= old_trace.count(old_addr):
                score += 1
        return 2.0 * score / (len(old_trace) + len(new_trace))
    old_set = set(old_trace)
    new_set = set(new_trace)
    if not old_set or not new_set:
        return 0.0
    return 2.0 * len(old_set & new_set) / (len(old_set) + len(new_set))


def has_graph_evidence(
    old_records: list[PathRecord],
    new_records: list[PathRecord],
    matching_bb_map: Optional[dict[int, int]],
) -> bool:
    if matching_bb_map:
        return True
    return any(record.trace for record in old_records) and any(record.trace for record in new_records)


def parse_execution_trace(content: str) -> list[int]:
    match = re.search(r";\s*Execution trace:\s*(.*)", content)
    if not match:
        return []
    try:
        value = ast.literal_eval(match.group(1).strip())
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def load_matching_bb_map(path: Optional[Path]) -> Optional[dict[int, int]]:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "matching_bb_addrs" in data:
        data = data["matching_bb_addrs"]
    if not isinstance(data, dict):
        raise ValueError(f"Matching basic-block map must be a JSON object: {path}")
    out = {}
    for key, value in data.items():
        out[parse_int_addr(key)] = parse_int_addr(value)
    return out


def parse_int_addr(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def natural_path_key(path_id: str) -> tuple[str, int]:
    match = re.search(r"^(.*)_path_(\d+)$", path_id)
    if match:
        return match.group(1), int(match.group(2))
    return path_id, 0
