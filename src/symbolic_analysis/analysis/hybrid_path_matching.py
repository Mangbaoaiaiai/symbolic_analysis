"""
Hybrid path matching: feature-vector retrieval with BinDiff-style graph reranking.

The default path is the existing 11-dimensional constraint feature vector plus
cosine similarity. When that ranking is low-confidence, this module reranks all
candidate paths using VeriBin's BinDiff-style basic-block overlap score.
"""

from __future__ import annotations

import ast
import heapq
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from symbolic_analysis.analysis.path_constraint_features import (
    FEATURE_NAMES,
    FEATURE_SCHEMA,
    cosine_with_validity,
    extract_feature_record,
    normalize_features,
)
from symbolic_analysis.tracing import time_block
from symbolic_analysis.profile import (
    HYBRID_MARGIN_THRESHOLD,
    HYBRID_TOP1_THRESHOLD,
    PAPER_PROFILE_ID,
    paper_profile,
)


@dataclass(frozen=True)
class PathRecord:
    path_id: str
    path: Path
    content: str
    vector: list[float]
    vector_valid: list[bool]
    trace: list[int]
    memory_hash: str | None


@dataclass(frozen=True)
class _RawPathRecord:
    path: Path
    content: str
    raw: tuple[float, ...]
    valid: tuple[bool, ...]
    trace: list[int]
    memory_hash: str | None


@dataclass(frozen=True)
class HybridConfig:
    # Paper Section 3.4: rerank if top-1 < 0.70 or top-1/top-2 gap < 0.05.
    high_threshold: float = HYBRID_TOP1_THRESHOLD
    margin_threshold: float = HYBRID_MARGIN_THRESHOLD
    graph_min_score: float = 0.01
    graph_weight: float = 1.0
    feature_weight: float = 0.0


def _load_raw_path_records(
    paths: list[Path],
    *,
    retain_content: bool = True,
) -> list[_RawPathRecord]:
    records = []
    for path in sorted(paths, key=lambda p: natural_path_key(p.stem)):
        content = path.read_text(encoding="utf-8", errors="replace")
        feature_record = extract_feature_record(content)
        records.append(
            _RawPathRecord(
                path=path,
                content=content if retain_content else "",
                raw=tuple(feature_record.raw),
                valid=tuple(feature_record.valid[name] for name in FEATURE_NAMES),
                trace=parse_execution_trace(content),
                memory_hash=parse_memory_hash(content),
            )
        )
    return records


def _compute_min_max(raw_records) -> dict[str, tuple[float, float]]:
    if not raw_records:
        return {}
    result = {}
    for i, name in enumerate(FEATURE_NAMES):
        values = [
            record.raw[i]
            for record in raw_records
            if record.valid[i]
        ]
        if values:
            result[name] = (min(values), max(values))
    return result


def _materialize_path_records(raw_records, min_max):
    records = []
    for record in raw_records:
        records.append(
            PathRecord(
                path_id=record.path.stem,
                path=record.path,
                content=record.content,
                vector=normalize_features(list(record.raw), min_max),
                vector_valid=list(record.valid),
                trace=record.trace,
                memory_hash=record.memory_hash,
            )
        )
    return records


def load_path_records(
    paths: list[Path],
    min_max: Optional[dict[str, tuple[float, float]]] = None,
) -> list[PathRecord]:
    return _materialize_path_records(_load_raw_path_records(paths), min_max)


def compute_min_max_for_paths(paths: list[Path]) -> dict[str, tuple[float, float]]:
    return _compute_min_max(_load_raw_path_records(paths))


def hybrid_rank_paths(
    old_paths: list[Path],
    new_paths: list[Path],
    config: HybridConfig = HybridConfig(),
    matching_bb_map: Optional[dict[int, int]] = None,
    graph_provider: Optional[
        Callable[[], tuple[Optional[dict[int, int]], dict[str, Any]]]
    ] = None,
    profile_id: str = PAPER_PROFILE_ID,
    profile: Optional[dict[str, Any]] = None,
    max_results_per_query: Optional[int] = None,
) -> dict[str, Any]:
    with time_block(
        "align",
        "hybrid_feature_graph_path_matching",
        old_path_count=len(old_paths),
        new_path_count=len(new_paths),
    ) as trace:
        old_raw = _load_raw_path_records(old_paths, retain_content=False)
        new_raw = _load_raw_path_records(new_paths, retain_content=False)
        min_max = _compute_min_max(old_raw + new_raw)
        old_records = _materialize_path_records(old_raw, min_max)
        new_records = _materialize_path_records(new_raw, min_max)
        del old_raw, new_raw
        graph_available = has_graph_evidence(old_records, new_records, matching_bb_map)
        graph_metadata: dict[str, Any] = {
            "status": "loaded" if graph_available else "not_loaded",
        }
        queries = []
        reranked_queries = 0
        fallback_queries = 0

        for old in old_records:
            feature_ranking = feature_rank(
                old,
                new_records,
                max_results=max_results_per_query,
            )
            confidence = ranking_confidence(feature_ranking, config)
            use_graph = confidence["low_confidence"] and graph_available
            final_ranking = feature_ranking
            reason = confidence["reason"]

            if use_graph:
                graph_ranking = graph_rank_all(
                    old,
                    new_records,
                    feature_ranking,
                    matching_bb_map,
                    config,
                    max_results=max_results_per_query,
                )
                if graph_ranking and graph_ranking[0]["graph_similarity"] >= config.graph_min_score:
                    final_ranking = graph_ranking
                    reranked_queries += 1
                    reason = "graph_rerank"
                else:
                    fallback_queries += 1
                    reason = "graph_failed_feature_fallback"
            elif confidence["low_confidence"]:
                if graph_provider is not None and not graph_available:
                    provided_map, provided_metadata = graph_provider()
                    graph_metadata = provided_metadata
                    if provided_map:
                        matching_bb_map = provided_map
                        graph_available = True
                        graph_ranking = graph_rank_all(
                            old,
                            new_records,
                            feature_ranking,
                            matching_bb_map,
                            config,
                            max_results=max_results_per_query,
                        )
                        if (
                            graph_ranking
                            and graph_ranking[0]["graph_similarity"]
                            >= config.graph_min_score
                        ):
                            final_ranking = graph_ranking
                            reranked_queries += 1
                            reason = "graph_rerank_lazy"
                        elif graph_ranking:
                            fallback_queries += 1
                            reason = "graph_failed_feature_fallback"
                if not graph_available:
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
        trace["graph_backend"] = graph_metadata

    return {
        "method": "hybrid_feature_cosine_bindiff_graph",
        "profile_id": profile_id,
        "profile": profile if profile is not None else paper_profile(),
        "feature_schema": FEATURE_SCHEMA,
        "config": {
            "high_threshold": config.high_threshold,
            "margin_threshold": config.margin_threshold,
            "graph_min_score": config.graph_min_score,
            "graph_weight": config.graph_weight,
            "feature_weight": config.feature_weight,
        },
        "graph_available": graph_available,
        "graph_backend": graph_metadata,
        "max_results_per_query": max_results_per_query,
        "queries": queries,
    }


def _ranking_key(item: dict[str, Any]) -> tuple[int, float, tuple[Any, ...]]:
    return (
        -int(item["memory_hash_match"]),
        -item["similarity"],
        natural_path_key(item["path_id"]),
    )


def feature_rank(
    old: PathRecord,
    new_records: list[PathRecord],
    *,
    max_results: Optional[int] = None,
) -> list[dict[str, Any]]:
    def scored_candidates():
        for new in new_records:
            score = cosine_with_validity(
                old.vector,
                new.vector,
                old.vector_valid,
                new.vector_valid,
            )
            hash_match = bool(old.memory_hash and old.memory_hash == new.memory_hash)
            yield {
                "path_id": new.path_id,
                "similarity": round(score, 6),
                "feature_similarity": round(score, 6),
                "memory_hash_match": hash_match,
            }

    if max_results is not None:
        if max_results <= 0:
            return []
        return heapq.nlargest(
            max_results,
            scored_candidates(),
            key=_ranking_key,
        )
    ranking = list(scored_candidates())
    ranking.sort(key=_ranking_key)
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
    *,
    max_results: Optional[int] = None,
) -> list[dict[str, Any]]:
    feature_by_id = {item["path_id"]: float(item["feature_similarity"]) for item in feature_ranking}
    hash_by_id = {item["path_id"]: bool(item.get("memory_hash_match")) for item in feature_ranking}
    def scored_candidates():
        for new in new_records:
            graph_score = bindiff_path_similarity(old.trace, new.trace, matching_bb_map)
            feature_score = feature_by_id.get(new.path_id, 0.0)
            final_score = config.graph_weight * graph_score + config.feature_weight * feature_score
            yield {
                "path_id": new.path_id,
                "similarity": round(final_score, 6),
                "feature_similarity": round(feature_score, 6),
                "graph_similarity": round(graph_score, 6),
                "memory_hash_match": hash_by_id.get(new.path_id, False),
            }

    if max_results is not None:
        if max_results <= 0:
            return []
        return heapq.nlargest(
            max_results,
            scored_candidates(),
            key=_ranking_key,
        )
    ranking = list(scored_candidates())
    ranking.sort(key=_ranking_key)
    return ranking


def bindiff_path_similarity(
    old_trace: list[int],
    new_trace: list[int],
    matching_bb_map: Optional[dict[int, int]] = None,
) -> float:
    if not old_trace or not new_trace:
        return 0.0
    if not matching_bb_map:
        # Absolute addresses from independently linked binaries are not
        # semantic evidence. A missing map triggers the feature-only fallback.
        return 0.0

    target_addresses = [
        matching_bb_map[old_addr]
        for old_addr in set(old_trace)
        if old_addr in matching_bb_map
    ]
    if len(target_addresses) != len(set(target_addresses)):
        return 0.0

    old_counts = Counter(old_trace)
    new_counts = Counter(new_trace)
    intersection = sum(
        min(count, new_counts.get(matching_bb_map.get(address), 0))
        for address, count in old_counts.items()
        if address in matching_bb_map
    )
    return max(
        0.0,
        min(1.0, 2.0 * intersection / (len(old_trace) + len(new_trace))),
    )


def has_graph_evidence(
    old_records: list[PathRecord],
    new_records: list[PathRecord],
    matching_bb_map: Optional[dict[int, int]],
) -> bool:
    return bool(matching_bb_map)


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


def parse_memory_hash(content: str) -> str | None:
    match = re.search(r";\s*Memory hash:\s*([^\r\n]+)", content)
    if not match:
        return None
    value = match.group(1).strip()
    return value if value and value != "0" else None


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
