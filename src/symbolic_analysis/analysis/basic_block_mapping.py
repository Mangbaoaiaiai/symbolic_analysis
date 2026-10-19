"""Deterministic basic-block mapping for path-trace comparison.

The paper uses BinDiff.  This module is the redistributable fallback used when
no exported BinDiff mapping is supplied: it matches blocks by normalized
instruction fingerprints, preferring identical relative virtual addresses and
then unambiguous fingerprint groups.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def build_structural_block_map(
    old_binary: Path,
    new_binary: Path,
    old_traces: Iterable[Iterable[int]],
    new_traces: Iterable[Iterable[int]],
) -> tuple[dict[int, int], dict[str, Any]]:
    import angr

    old_project = angr.Project(str(old_binary), auto_load_libs=False)
    new_project = angr.Project(str(new_binary), auto_load_libs=False)
    old_addrs = sorted({int(addr) for trace in old_traces for addr in trace})
    new_addrs = sorted({int(addr) for trace in new_traces for addr in trace})
    old_fp = _fingerprints(old_project, old_addrs)
    new_fp = _fingerprints(new_project, new_addrs)

    mapping: dict[int, int] = {}
    used_new: set[int] = set()
    old_base = int(old_project.loader.main_object.min_addr)
    new_base = int(new_project.loader.main_object.min_addr)

    # Named functions survive the benchmark compilation.  Pair their executed
    # blocks by control-flow order; this also aligns edited entry blocks whose
    # instruction fingerprint and RVA both changed.
    symbol_pairs = _function_symbol_pairs(old_project, new_project)
    for old_start, old_end, new_start, new_end in symbol_pairs:
        old_group = sorted(a for a in old_fp if old_start <= a < old_end)
        new_group = sorted(a for a in new_fp if new_start <= a < new_end)
        for old_addr, new_addr in zip(old_group, new_group):
            mapping[old_addr] = new_addr
            used_new.add(new_addr)

    # Same-RVA matches are stable for paired builds from the same harness and
    # deliberately align modified blocks as BinDiff would.  This compares RVAs,
    # not process/image addresses, so relocation does not create false matches.
    new_by_rva = {addr - new_base: addr for addr in new_fp}
    for old_addr in old_fp:
        if old_addr in mapping:
            continue
        new_addr = new_by_rva.get(old_addr - old_base)
        if new_addr is not None:
            mapping[old_addr] = new_addr
            used_new.add(new_addr)

    remaining_old = {a: f for a, f in old_fp.items() if a not in mapping}
    remaining_new = {a: f for a, f in new_fp.items() if a not in used_new}
    mapping.update(pair_fingerprint_groups(remaining_old, remaining_new))
    stats = {
        "backend": "normalized_instruction_fingerprint",
        "old_trace_blocks": len(old_addrs),
        "new_trace_blocks": len(new_addrs),
        "old_decoded_blocks": len(old_fp),
        "new_decoded_blocks": len(new_fp),
        "mapped_blocks": len(mapping),
        "coverage_old": len(mapping) / len(old_addrs) if old_addrs else 0.0,
    }
    return mapping, stats


def _function_symbol_pairs(old_project: Any, new_project: Any) -> list[tuple[int, int, int, int]]:
    def ranges(project: Any) -> dict[str, tuple[int, int]]:
        result = {}
        for symbol in project.loader.main_object.symbols:
            if not bool(getattr(symbol, "is_function", False)):
                continue
            name = str(getattr(symbol, "name", "") or "")
            start = int(getattr(symbol, "rebased_addr", 0) or 0)
            size = int(getattr(symbol, "size", 0) or 0)
            if name and start and size:
                result[name] = (start, start + size)
        return result

    old_ranges = ranges(old_project)
    new_ranges = ranges(new_project)
    return [(*old_ranges[name], *new_ranges[name]) for name in sorted(old_ranges.keys() & new_ranges.keys())]


def pair_fingerprint_groups(
    old_fingerprints: dict[int, tuple[Any, ...]],
    new_fingerprints: dict[int, tuple[Any, ...]],
) -> dict[int, int]:
    old_groups: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    new_groups: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for address, fingerprint in old_fingerprints.items():
        old_groups[fingerprint].append(address)
    for address, fingerprint in new_fingerprints.items():
        new_groups[fingerprint].append(address)

    result: dict[int, int] = {}
    for fingerprint, old_group in old_groups.items():
        new_group = new_groups.get(fingerprint, [])
        # Equal-sized groups can be paired deterministically in address order.
        # If cardinalities differ, only an unambiguous singleton is safe.
        if len(old_group) == len(new_group) or (len(old_group) == len(new_group) == 1):
            result.update(zip(sorted(old_group), sorted(new_group)))
    return result


def _fingerprints(project: Any, addresses: Iterable[int]) -> dict[int, tuple[Any, ...]]:
    main = project.loader.main_object
    result: dict[int, tuple[Any, ...]] = {}
    for address in addresses:
        if not main.contains_addr(address):
            continue
        try:
            block = project.factory.block(address)
            mnemonics = tuple(insn.mnemonic.lower() for insn in block.capstone.insns)
            if not mnemonics:
                continue
            result[address] = (block.size, block.vex.jumpkind, mnemonics)
        except Exception:  # malformed/indirect trace entries are simply unmapped
            continue
    return result
