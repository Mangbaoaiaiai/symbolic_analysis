#!/usr/bin/env python3
"""Manifest-backed binary and artifact identity for verifier replay."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any


SCHEMA = "symbolicana.round018.artifact_identity.v1"


class ArtifactIdentityError(ValueError):
    """Raised when a manifest, binary, or source identity is inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def input_schema_hash(inputs: list[dict[str, Any]]) -> str:
    canonical = sorted(
        inputs,
        key=lambda item: (
            int(item.get("index", 0) or 0),
            str(item.get("name") or ""),
        ),
    )
    return canonical_json_hash(
        [
            {
                "index": int(item.get("index", 0) or 0),
                "name": str(item.get("name") or ""),
                "kind": str(item.get("kind") or ""),
                "c_type": str(item.get("c_type") or ""),
                "bits": int(item.get("bits", 0) or 0),
                "precision": int(item.get("precision", 0) or 0),
            }
            for item in canonical
        ]
    )


def materialized_domain_hash(contract: dict[str, Any]) -> str:
    return canonical_json_hash(
        {
            "profile_id": contract.get("profile_id"),
            "profile": contract.get("profile"),
            "schema_hash": contract.get("schema_hash"),
            "inputs": contract.get("inputs"),
            "source_preconditions": contract.get("source_preconditions"),
        }
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _actual_file(
    path: Path,
    *,
    label: str,
    require_executable: bool,
) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ArtifactIdentityError(f"{label}_missing:{resolved}")
    actual_hash = sha256_file(resolved)
    mode = resolved.stat().st_mode
    executable = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    if require_executable and os.name != "nt" and not os.access(resolved, os.X_OK):
        raise ArtifactIdentityError(f"{label}_not_executable:{resolved}")
    return {
        "path": str(resolved),
        "sha256": actual_hash,
        "size": resolved.stat().st_size,
        "executable": executable,
        "executability_checked": os.name != "nt",
    }


def _resolve_manifest_path(
    raw: str,
    *,
    run_root: Path,
    project_root: Path,
    label: str,
) -> Path:
    value = str(raw or "").strip()
    if not value:
        raise ArtifactIdentityError(f"{label}_path_missing")
    candidate = Path(value)
    options = [candidate] if candidate.is_absolute() else [
        run_root / candidate,
        project_root / candidate,
    ]
    existing = [option.resolve() for option in options if option.is_file()]
    if not existing:
        raise ArtifactIdentityError(
            f"{label}_path_unresolved:{value}"
        )
    if len(set(existing)) != 1:
        raise ArtifactIdentityError(
            f"{label}_path_ambiguous:{value}"
        )
    return existing[0]


def _resolve_manifest_directory(
    raw: str,
    *,
    run_root: Path,
    project_root: Path,
    label: str,
) -> Path:
    value = str(raw or "").strip()
    if not value:
        raise ArtifactIdentityError(f"{label}_path_missing")
    candidate = Path(value)
    options = [candidate] if candidate.is_absolute() else [
        run_root / candidate,
        project_root / candidate,
    ]
    existing = [option.resolve() for option in options if option.is_dir()]
    if not existing:
        raise ArtifactIdentityError(
            f"{label}_path_unresolved:{value}"
        )
    if len(set(existing)) != 1:
        raise ArtifactIdentityError(
            f"{label}_path_ambiguous:{value}"
        )
    return existing[0]


def build_task_artifact_identity(
    *,
    run_root: Path,
    project_root: Path,
    build_row: dict[str, str],
    se_rows: list[dict[str, str]],
    contract_path: Path,
    profile_path: Path,
    require_executable: bool = True,
    expected_profile_id: str = "ardiff_numeric_bounds_v1",
) -> dict[str, Any]:
    task_uid = str(build_row.get("task_uid") or "").strip()
    if not task_uid:
        raise ArtifactIdentityError("build_task_uid_missing")
    if build_row.get("build_status") != "completed":
        raise ArtifactIdentityError(f"{task_uid}:build_status_not_completed")
    for side in ("old", "new"):
        if build_row.get(f"{side}_process_status") not in {None, "", "completed"}:
            raise ArtifactIdentityError(
                f"{task_uid}:{side}_build_process_not_completed"
            )

    sides: dict[str, Any] = {}
    for side, expected_stem in (("old", "symbolic_oldV"), ("new", "symbolic_newV")):
        expected_key = f"expected_{side}_binary"
        raw_expected = (
            build_row.get(expected_key)
            or f"build/bin/{task_uid}/{expected_stem}"
        )
        expected = (run_root / raw_expected).resolve()
        raw_actual = build_row.get(f"{side}_binary") or raw_expected
        actual = _resolve_manifest_path(
            raw_actual,
            run_root=run_root,
            project_root=project_root,
            label=f"{task_uid}_{side}_binary",
        )
        if actual != expected:
            raise ArtifactIdentityError(
                f"{task_uid}:{side}_binary_path_mismatch:"
                f"expected={expected}:actual={actual}"
            )
        if actual.stem != expected_stem:
            raise ArtifactIdentityError(
                f"{task_uid}:{side}_binary_side_mismatch:{actual.name}"
            )
        expected_hash = str(
            build_row.get(f"{side}_binary_sha256") or ""
        ).lower()
        if not expected_hash:
            raise ArtifactIdentityError(
                f"{task_uid}:{side}_binary_sha256_missing"
            )
        binary = _actual_file(
            actual,
            label=f"{task_uid}_{side}_binary",
            require_executable=require_executable,
        )
        if binary["sha256"] != expected_hash:
            raise ArtifactIdentityError(
                f"{task_uid}:{side}_binary_sha256_mismatch"
            )

        source = _resolve_manifest_path(
            str(build_row.get(f"{side}_source") or ""),
            run_root=run_root,
            project_root=project_root,
            label=f"{task_uid}_{side}_source",
        )
        source_hash = sha256_file(source)
        expected_source_hash = str(
            build_row.get(f"{side}_source_sha256") or ""
        ).lower()
        if not expected_source_hash or source_hash != expected_source_hash:
            raise ArtifactIdentityError(
                f"{task_uid}:{side}_source_sha256_mismatch"
            )
        sides[side] = {
            "binary_path": str(actual),
            "binary_sha256": binary["sha256"],
            "binary_size": binary["size"],
            "binary_executable": binary["executable"],
            "binary_executability_checked": binary[
                "executability_checked"
            ],
            "source_path": str(source),
            "source_sha256": source_hash,
        }

    relevant_se = [
        row for row in se_rows if row.get("task_uid") == task_uid
    ]
    by_side = {str(row.get("side")): row for row in relevant_se}
    for side in ("old", "new"):
        se_row = by_side.get(side)
        if se_row is None:
            raise ArtifactIdentityError(f"{task_uid}:{side}_se_row_missing")
        manifest_binary = _resolve_manifest_path(
            str(se_row.get("binary") or ""),
            run_root=run_root,
            project_root=project_root,
            label=f"{task_uid}_{side}_se_binary",
        )
        if manifest_binary != Path(sides[side]["binary_path"]):
            raise ArtifactIdentityError(
                f"{task_uid}:{side}_se_build_binary_mismatch"
            )
        paths_dir = _resolve_manifest_directory(
            str(se_row.get("paths_dir") or ""),
            run_root=run_root,
            project_root=project_root,
            label=f"{task_uid}_{side}_paths_dir",
        )
        if not paths_dir.is_dir():
            raise ArtifactIdentityError(
                f"{task_uid}:{side}_paths_dir_missing"
            )
        sides[side]["paths_dir"] = str(paths_dir)
        source_from_se = _resolve_manifest_path(
            str(se_row.get("source") or ""),
            run_root=run_root,
            project_root=project_root,
            label=f"{task_uid}_{side}_se_source",
        )
        if source_from_se != Path(sides[side]["source_path"]):
            raise ArtifactIdentityError(
                f"{task_uid}:{side}_se_source_mismatch"
            )

    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    inputs = contract.get("inputs")
    if not isinstance(inputs, list):
        raise ArtifactIdentityError(f"{task_uid}:input_schema_missing")
    schema_hash = input_schema_hash(inputs)
    if contract.get("schema_hash") not in {None, "", schema_hash}:
        raise ArtifactIdentityError(
            f"{task_uid}:contract_schema_hash_mismatch"
        )
    recorded_domain_hash = str(contract.get("domain_hash") or "")
    if not recorded_domain_hash:
        raise ArtifactIdentityError(f"{task_uid}:contract_domain_hash_missing")
    domain_hash = materialized_domain_hash(contract)
    profile_hash = sha256_file(profile_path)
    profile_id = str(contract.get("profile_id") or "")
    if not expected_profile_id or profile_id != expected_profile_id:
        raise ArtifactIdentityError(
            f"{task_uid}:unexpected_input_domain_profile"
        )
    if expected_profile_id != "ardiff_numeric_bounds_v1":
        profile_payload = json.loads(profile_path.read_text(encoding="utf-8-sig"))
        if (profile_payload.get("profile_id") != profile_id
                or contract.get("profile") != profile_payload):
            raise ArtifactIdentityError(f"{task_uid}:custom_profile_contract_mismatch")

    identity: dict[str, Any] = {
        "schema": SCHEMA,
        "task_uid": task_uid,
        "old": sides["old"],
        "new": sides["new"],
        "input_schema": inputs,
        "input_schema_hash": schema_hash,
        "domain_hash": domain_hash,
        "recorded_domain_hash": recorded_domain_hash,
        "recorded_domain_hash_matches_materialized": (
            recorded_domain_hash == domain_hash
        ),
        "profile_id": profile_id,
        "profile_path": str(profile_path.resolve()),
        "profile_sha256": profile_hash,
        "build_manifest_compiler_profile": build_row.get(
            "compiler_profile"
        ),
        "build_manifest_optimization": build_row.get("optimization"),
    }
    identity["artifact_identity_sha256"] = canonical_json_hash(identity)
    return identity


def validate_live_artifact_identity(
    identity: dict[str, Any],
    *,
    paths_dir: Path,
    old_binary: Path,
    new_binary: Path,
    task_uid: str | None = None,
    require_executable: bool = True,
    expected_input_schema_hash: str | None = None,
    expected_domain_hash: str | None = None,
) -> dict[str, Any]:
    if identity.get("schema") != SCHEMA:
        raise ArtifactIdentityError("artifact_identity_schema_mismatch")
    expected_hash = str(identity.get("artifact_identity_sha256") or "")
    core = {
        key: value
        for key, value in identity.items()
        if key != "artifact_identity_sha256"
    }
    if not expected_hash or canonical_json_hash(core) != expected_hash:
        raise ArtifactIdentityError("artifact_identity_payload_tampered")
    if task_uid and str(identity.get("task_uid")) != str(task_uid):
        raise ArtifactIdentityError("artifact_identity_task_uid_mismatch")

    resolved_paths_dir = paths_dir.resolve()
    for side, expected_binary in (
        ("old", old_binary),
        ("new", new_binary),
    ):
        side_identity = identity.get(side) or {}
        if resolved_paths_dir != Path(
            str(side_identity.get("paths_dir") or "")
        ).resolve():
            raise ArtifactIdentityError(
                f"{side}_paths_dir_identity_mismatch"
            )
        actual = _actual_file(
            expected_binary,
            label=f"{side}_replay_binary",
            require_executable=require_executable,
        )
        if actual["path"] != str(
            Path(str(side_identity.get("binary_path") or "")).resolve()
        ):
            raise ArtifactIdentityError(
                f"{side}_replay_binary_path_identity_mismatch"
            )
        if actual["sha256"] != side_identity.get("binary_sha256"):
            raise ArtifactIdentityError(
                f"{side}_replay_binary_sha256_mismatch"
            )
        source = _actual_file(
            Path(str(side_identity.get("source_path") or "")),
            label=f"{side}_source",
            require_executable=False,
        )
        if source["sha256"] != side_identity.get("source_sha256"):
            raise ArtifactIdentityError(
                f"{side}_source_sha256_identity_mismatch"
            )
    profile = _actual_file(
        Path(str(identity.get("profile_path") or "")),
        label="input_domain_profile",
        require_executable=False,
    )
    if profile["sha256"] != identity.get("profile_sha256"):
        raise ArtifactIdentityError("input_domain_profile_sha256_mismatch")
    if (
        expected_input_schema_hash
        and identity.get("input_schema_hash") != expected_input_schema_hash
    ):
        raise ArtifactIdentityError("input_schema_hash_identity_mismatch")
    if (
        expected_domain_hash
        and identity.get("domain_hash") != expected_domain_hash
    ):
        raise ArtifactIdentityError("domain_hash_identity_mismatch")
    return {
        "schema": "symbolicana.round018.live_artifact_identity_check.v1",
        "task_uid": identity.get("task_uid"),
        "paths_dir": str(resolved_paths_dir),
        "old_binary_sha256": identity["old"]["binary_sha256"],
        "new_binary_sha256": identity["new"]["binary_sha256"],
        "artifact_identity_sha256": expected_hash,
        "pass": True,
    }
