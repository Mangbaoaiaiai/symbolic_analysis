#!/usr/bin/env python3
"""Versioned static-counterexample identity and checkpoint records."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


SCHEMA = "symbolicana.round018.static_counterexample_candidate.v1"
TERMINAL_STATES = frozenset(
    {"accepted", "rejected", "indeterminate", "interrupted"}
)
DIRECTIONS = frozenset({"old_to_new", "new_to_old"})

_OLD_KEYS = (
    "old_path_id",
    "old_path",
    "path_a",
    "left_path",
)
_NEW_KEYS = (
    "new_path_id",
    "new_path",
    "path_b",
    "right_path",
)
_SOURCE_KEYS = ("source", "query")
_TARGET_KEYS = ("target", "match")


class CandidateSchemaError(ValueError):
    """Raised when path aliases are missing or contradictory."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def public_candidate_value(value: Any) -> Any:
    """Copy report-safe JSON data while omitting private checkpoint backrefs."""
    if isinstance(value, dict):
        return {
            str(key): public_candidate_value(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, (list, tuple)):
        return [public_candidate_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _path_value(record: dict[str, Any], key: str) -> str | None:
    if key not in record:
        return None
    value = record[key]
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple, dict)):
        raise CandidateSchemaError(
            f"{key} must identify exactly one path, got {type(value).__name__}"
        )
    text = str(value).strip()
    if not text:
        return None
    return Path(text).stem if text.endswith(".txt") else text


def _collect_role_values(
    record: dict[str, Any],
    keys: tuple[str, ...],
) -> set[str]:
    return {
        value
        for key in keys
        if (value := _path_value(record, key)) is not None
    }


def _single_role_value(
    record: dict[str, Any],
    role: str,
    keys: tuple[str, ...],
) -> str | None:
    values = _collect_role_values(record, keys)
    if len(values) > 1:
        raise CandidateSchemaError(
            f"conflicting {role} path aliases: {sorted(values)}"
        )
    return next(iter(values), None)


def canonicalize_path_identity(
    record: dict[str, Any],
    *,
    direction: str | None = None,
    task_uid: str | None = None,
    query_kind: str | None = None,
    evidence_source: str | None = None,
    logical_query_sha256: str | None = None,
    input_contract_hash: str | None = None,
    artifact_identity_hash: str | None = None,
    candidate_id: str | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    """Normalize legacy query/match and source/target path aliases.

    Conflicting aliases are rejected. A list-valued ``match`` is intentionally
    not collapsed to one path because that would invent an identity.
    """
    resolved_direction = str(direction or record.get("direction") or "")
    if not resolved_direction:
        resolved_direction = "old_to_new"
    if resolved_direction not in DIRECTIONS:
        raise CandidateSchemaError(
            f"unsupported candidate direction: {resolved_direction}"
        )

    old_explicit = _single_role_value(record, "old", _OLD_KEYS)
    new_explicit = _single_role_value(record, "new", _NEW_KEYS)
    source = _single_role_value(record, "source/query", _SOURCE_KEYS)
    target = _single_role_value(record, "target/match", _TARGET_KEYS)

    if resolved_direction == "old_to_new":
        source_role = "old"
        target_role = "new"
    else:
        source_role = "new"
        target_role = "old"

    old_values = set()
    new_values = set()
    for value in (old_explicit, source if source_role == "old" else None):
        if value:
            old_values.add(value)
    for value in (new_explicit, target if target_role == "new" else None):
        if value:
            new_values.add(value)
    for value in (new_explicit, source if source_role == "new" else None):
        if value:
            new_values.add(value)
    for value in (old_explicit, target if target_role == "old" else None):
        if value:
            old_values.add(value)

    if len(old_values) > 1:
        raise CandidateSchemaError(
            f"conflicting old/new-program path identity: {sorted(old_values)}"
        )
    if len(new_values) > 1:
        raise CandidateSchemaError(
            f"conflicting new-program path identity: {sorted(new_values)}"
        )
    old_path_id = next(iter(old_values), None)
    new_path_id = next(iter(new_values), None)
    if not old_path_id or not new_path_id:
        raise CandidateSchemaError("candidate_requires_old_and_new_path_ids")

    resolved_task_uid = str(task_uid or record.get("task_uid") or "").strip()
    resolved_query_kind = str(
        query_kind or record.get("query_kind") or record.get("stage") or ""
    ).strip()
    resolved_evidence_source = str(
        evidence_source
        or record.get("evidence_source")
        or record.get("counterexample_source")
        or ""
    ).strip()
    identity_core = {
        "task_uid": resolved_task_uid,
        "direction": resolved_direction,
        "old_path_id": old_path_id,
        "new_path_id": new_path_id,
        "logical_query_sha256": str(logical_query_sha256 or ""),
        "dedupe_key": str(dedupe_key or ""),
    }
    resolved_candidate_id = candidate_id or (
        "cex-" + canonical_json_hash(identity_core)[:20]
    )
    return {
        "schema": SCHEMA,
        "task_uid": resolved_task_uid,
        "candidate_id": resolved_candidate_id,
        "query_kind": resolved_query_kind,
        "direction": resolved_direction,
        "old_path_id": old_path_id,
        "new_path_id": new_path_id,
        "logical_query_sha256": str(logical_query_sha256 or ""),
        "model_sha256": canonical_json_hash(
            public_candidate_value(record.get("counterexample") or {})
        ),
        "input_contract_hash": str(input_contract_hash or ""),
        "artifact_identity_hash": str(artifact_identity_hash or ""),
        "evidence_source": resolved_evidence_source,
        "status": str(record.get("status") or "pending"),
        "reason": str(record.get("reason") or ""),
        "counterexample": public_candidate_value(
            record.get("counterexample")
        ),
        "input_schema": record.get("input_schema"),
        "replay": record.get("replay"),
        "mismatch_component": record.get("mismatch_component"),
        "query_path": record.get("query_path"),
        "query_sha256": logical_query_sha256
        or record.get("query_sha256"),
        "identity_core": identity_core,
    }


def candidate_with_state(
    candidate: dict[str, Any],
    *,
    status: str,
    reason: str = "",
    replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status != "pending" and status not in TERMINAL_STATES:
        raise CandidateSchemaError(f"unsupported candidate state: {status}")
    updated = dict(candidate)
    updated["status"] = status
    updated["reason"] = reason
    updated["updated_at_unix"] = time.time()
    if replay is not None:
        updated["replay"] = replay
    return updated


def persist_candidate_checkpoint(
    candidate: dict[str, Any],
    directory: Path,
) -> dict[str, str]:
    """Atomically save one checkpoint and append an fsynced journal event."""
    if candidate.get("schema") != SCHEMA:
        raise CandidateSchemaError("candidate_schema_mismatch")
    candidate_id = str(candidate.get("candidate_id") or "")
    if not candidate_id:
        raise CandidateSchemaError("candidate_id_missing")
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / f"{candidate_id}.json"
    temporary = checkpoint.with_name(
        f".{checkpoint.name}.{time.time_ns()}.tmp"
    )
    payload = (
        json.dumps(
            public_candidate_value(candidate),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(checkpoint)
    journal = directory / "candidate_journal.jsonl"
    event = {
        "recorded_at_unix": time.time(),
        "candidate_id": candidate_id,
        "status": candidate["status"],
        "reason": candidate.get("reason") or "",
        "direction": candidate.get("direction"),
        "old_path_id": candidate.get("old_path_id"),
        "new_path_id": candidate.get("new_path_id"),
        "query_kind": candidate.get("query_kind"),
        "logical_query_sha256": candidate.get("logical_query_sha256"),
    }
    with journal.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "checkpoint_path": str(checkpoint),
        "journal_path": str(journal),
    }
