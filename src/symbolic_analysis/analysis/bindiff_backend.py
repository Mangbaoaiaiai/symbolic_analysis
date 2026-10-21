"""Traceable BinDiff/BinExport backend with explicit fallback metadata."""

from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable


BINDIFF_BACKEND_SCHEMA = "symbolicana.bindiff_backend.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_tool(explicit: str | None, names: list[str], fallbacks: list[str]) -> str | None:
    if explicit:
        return explicit if Path(explicit).is_file() else None
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for candidate in fallbacks:
        if Path(candidate).is_file():
            return candidate
    return None


def build_bindiff_mapping(
    old_binary: Path,
    new_binary: Path,
    output_dir: Path,
    *,
    old_traces: Iterable[Iterable[int]],
    new_traces: Iterable[Iterable[int]],
    bindiff_binary: str | None = None,
    ghidra_headless: str | None = None,
    java_home: str | None = None,
    export_script: Path | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Generate and parse a real BinDiff mapping, or return an explicit failure."""
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    bindiff = find_tool(
        bindiff_binary,
        ["bindiff"],
        ["/opt/bindiff/bin/bindiff"],
    )
    ghidra = find_tool(
        ghidra_headless,
        ["analyzeHeadless"],
        ["/opt/ghidra/support/analyzeHeadless"],
    )
    script = export_script or Path(__file__).resolve().parents[3] / "scripts" / "ghidra" / "BinExportHeadless.java"
    if bindiff is None or ghidra is None or not script.is_file():
        missing = []
        if bindiff is None:
            missing.append("bindiff")
        if ghidra is None:
            missing.append("ghidra/BinExport")
        if not script.is_file():
            missing.append("BinExportHeadless.java")
        return {
            "schema": BINDIFF_BACKEND_SCHEMA,
            "status": "unavailable",
            "backend": "feature_only_fallback",
            "reason": "missing_tool:" + ",".join(missing),
            "mapping": None,
            "elapsed": time.perf_counter() - started,
        }

    old_sha = sha256_file(old_binary)
    new_sha = sha256_file(new_binary)
    cache_path = output_dir / "basic_block_map.json"
    cached = load_bindiff_mapping_artifact(
        cache_path, old_binary, new_binary
    )
    if cached is not None:
        cached["cache_hit"] = True
        cached["elapsed"] = time.perf_counter() - started
        return cached

    old_export = output_dir / f"{old_binary.name}.BinExport"
    new_export = output_dir / f"{new_binary.name}.BinExport"
    (output_dir / "ghidra_project").mkdir(parents=True, exist_ok=True)
    export_started = time.perf_counter()
    exports = []
    for binary, export in ((old_binary, old_export), (new_binary, new_export)):
        command = [
            ghidra,
            str(output_dir / "ghidra_project"),
            "Symbolicana",
            "-import",
            str(binary),
            "-scriptPath",
            str(script.parent),
            "-postScript",
            script.name,
            str(export),
            "-deleteProject",
        ]
        environment = os.environ.copy()
        if java_home:
            environment["JAVA_HOME"] = java_home
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=environment,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "schema": BINDIFF_BACKEND_SCHEMA,
                "status": "export_failed",
                "backend": "feature_only_fallback",
                "reason": f"BinExport failed for {binary.name}: {exc}",
                "command": command,
                "mapping": None,
                "elapsed": time.perf_counter() - started,
            }
        (output_dir / f"{binary.name}.ghidra.log").write_text(
            completed.stdout + completed.stderr,
            encoding="utf-8",
        )
        if completed.returncode != 0 or not export.is_file():
            return {
                "schema": BINDIFF_BACKEND_SCHEMA,
                "status": "export_failed",
                "backend": "feature_only_fallback",
                "reason": f"BinExport failed for {binary.name}",
                "command": command,
                "returncode": completed.returncode,
                "mapping": None,
                "elapsed": time.perf_counter() - started,
            }
        exports.append(
            {
                "binary": str(binary),
                "bin_export": str(export),
                "bin_export_sha256": sha256_file(export),
                "command": command,
            }
        )
    export_seconds = time.perf_counter() - export_started

    diff_started = time.perf_counter()
    diff_command = [
        bindiff,
        f"--output_dir={output_dir}",
        "--output_format=bin,log",
        str(old_export),
        str(new_export),
    ]
    try:
        completed = subprocess.run(
            diff_command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "schema": BINDIFF_BACKEND_SCHEMA,
            "status": "diff_failed",
            "backend": "feature_only_fallback",
            "reason": f"BinDiff command failed: {exc}",
            "command": diff_command,
            "mapping": None,
            "elapsed": time.perf_counter() - started,
        }
    (output_dir / "bindiff.log").write_text(
        completed.stdout + completed.stderr,
        encoding="utf-8",
    )
    diff_seconds = time.perf_counter() - diff_started
    if completed.returncode != 0:
        return {
            "schema": BINDIFF_BACKEND_SCHEMA,
            "status": "diff_failed",
            "backend": "feature_only_fallback",
            "reason": "BinDiff command failed",
            "command": diff_command,
            "returncode": completed.returncode,
            "mapping": None,
            "elapsed": time.perf_counter() - started,
        }
    candidates = sorted(
        output_dir.glob(f"{old_export.stem}_vs_{new_export.stem}.BinDiff")
    )
    if not candidates:
        candidates = sorted(output_dir.glob("*.BinDiff"))
    if not candidates:
        return {
            "schema": BINDIFF_BACKEND_SCHEMA,
            "status": "database_missing",
            "backend": "feature_only_fallback",
            "reason": "BinDiff produced no database",
            "mapping": None,
            "elapsed": time.perf_counter() - started,
        }
    database = candidates[-1]
    parsed = parse_bindiff_database(
        database,
        old_binary,
        new_binary,
        old_traces,
        new_traces,
    )
    parsed.update(
        {
            "schema": BINDIFF_BACKEND_SCHEMA,
            "backend": "google_bindiff_v8",
            "bindiff_binary": bindiff,
            "ghidra_headless": ghidra,
            "bin_exports": exports,
            "database": str(database),
            "database_sha256": sha256_file(database),
            "command": diff_command,
            "elapsed": time.perf_counter() - started,
            "t_export": export_seconds,
            "t_diff": diff_seconds,
            "cache_hit": False,
        }
    )
    if parsed.get("status") == "ok":
        mapping = parsed.get("mapping") or {}
        cache_path.write_text(
            json.dumps(
                {
                    **parsed,
                    "matching_bb_addrs": {
                        hex(source): hex(target)
                        for source, target in mapping.items()
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return parsed


def load_bindiff_mapping_artifact(
    path: Path,
    old_binary: Path,
    new_binary: Path,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("backend") != "google_bindiff_v8" or data.get("status") != "ok":
        return None
    if (
        data.get("old_binary_sha256") != sha256_file(old_binary)
        or data.get("new_binary_sha256") != sha256_file(new_binary)
    ):
        return None
    raw_mapping = data.get("matching_bb_addrs") or {}
    if not raw_mapping:
        return None
    mapping = {}
    for source, target in raw_mapping.items():
        try:
            mapping[int(source, 0)] = int(target, 0)
        except (TypeError, ValueError):
            return None
    return {**data, "mapping": mapping}


def parse_bindiff_database(
    database: Path,
    old_binary: Path,
    new_binary: Path,
    old_traces: Iterable[Iterable[int]],
    new_traces: Iterable[Iterable[int]],
) -> dict[str, Any]:
    old_sha = sha256_file(old_binary)
    new_sha = sha256_file(new_binary)
    try:
        conn = sqlite3.connect(database)
        meta_row = conn.execute(
            "select version, similarity, confidence from metadata limit 1"
        ).fetchone()
        file_rows = {
            int(row[0]): {
                "filename": row[1],
                "exefilename": row[2],
                "hash": str(row[3]).lower(),
            }
            for row in conn.execute(
                "select id, filename, exefilename, hash from file"
            )
        }
        function_rows = list(
            conn.execute(
                "select address1, address2, name1, name2, similarity, confidence "
                "from function where address1 is not null and address2 is not null"
            )
        )
        block_rows = list(
            conn.execute(
                "select address1, address2, functionid from basicblock "
                "where address1 is not null and address2 is not null"
            )
        )
    except sqlite3.Error as exc:
        return {
            "status": "schema_error",
            "reason": f"cannot read BinDiff database: {exc}",
            "mapping": None,
        }

    old_file = file_rows.get(1) or {}
    new_file = file_rows.get(2) or {}
    if old_file.get("hash") != old_sha or new_file.get("hash") != new_sha:
        return {
            "status": "elf_validation_failed",
            "reason": "BinDiff database hashes do not match input ELF files",
            "database_hashes": [old_file.get("hash"), new_file.get("hash")],
            "elf_hashes": [old_sha, new_sha],
            "mapping": None,
        }

    old_trace_addrs = {int(addr) for trace in old_traces for addr in trace}
    new_trace_addrs = {int(addr) for trace in new_traces for addr in trace}
    old_raw = [int(row[0]) for row in block_rows]
    new_raw = [int(row[1]) for row in block_rows]
    old_base, old_score = _best_address_base(old_raw, old_trace_addrs, old_binary)
    new_base, new_score = _best_address_base(new_raw, new_trace_addrs, new_binary)
    mapping = {}
    conflicts = []
    for row in block_rows:
        source = int(row[0]) + old_base
        target = int(row[1]) + new_base
        if source in mapping and mapping[source] != target:
            conflicts.append({"source": hex(source)})
            continue
        mapping[source] = target
    if len(set(mapping.values())) != len(mapping):
        conflicts.append({"reason": "non_injective_target_mapping"})
    if conflicts:
        return {
            "status": "mapping_conflict",
            "reason": "conflicting basic-block mapping",
            "conflicts": conflicts,
            "mapping": None,
        }
    old_covered = sum(1 for address in mapping if address in old_trace_addrs)
    new_covered = sum(1 for address in mapping.values() if address in new_trace_addrs)
    return {
        "status": "ok",
        "mapping": mapping,
        "old_binary_sha256": old_sha,
        "new_binary_sha256": new_sha,
        "tool_version": meta_row[0] if meta_row else None,
        "database_similarity": meta_row[1] if meta_row else None,
        "database_confidence": meta_row[2] if meta_row else None,
        "old_address_base": old_base,
        "new_address_base": new_base,
        "old_base_trace_overlap": old_score,
        "new_base_trace_overlap": new_score,
        "mapping_count": len(mapping),
        "old_trace_blocks": len(old_trace_addrs),
        "new_trace_blocks": len(new_trace_addrs),
        "old_trace_covered": old_covered,
        "new_trace_covered": new_covered,
        "function_mapping_count": len(function_rows),
        "address_model": "ddb_address_plus_inferred_elf_base",
    }


def _best_address_base(
    raw_addresses: list[int],
    trace_addresses: set[int],
    binary: Path,
) -> tuple[int, int]:
    candidates = {0}
    if raw_addresses and trace_addresses:
        try:
            import angr

            project = angr.Project(str(binary), auto_load_libs=False)
            candidates.add(int(project.loader.main_object.min_addr))
        except Exception:
            pass
    best = (0, 0)
    for base in candidates:
        score = sum(1 for address in raw_addresses if address + base in trace_addresses)
        if score > best[1]:
            best = (base, score)
    return best
