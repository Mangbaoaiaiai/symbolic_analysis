#!/usr/bin/env python3
"""Recognize and certify input-independent counted loops from executable IR."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import angr
import claripy
import networkx as nx

from input_domain_contract import (
    build_contract,
    claripy_domain_constraints,
    load_profile,
    schema_from_signature,
    sha256_json,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "configs/round016_ardiff_numeric_bounds_v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--function", default="snippet")
    parser.add_argument("--signature", required=True)
    parser.add_argument("--domain-profile-json", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--max-steps", type=int, default=100_000)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(raw, path)
    except BaseException:
        try:
            os.unlink(raw)
        except OSError:
            pass
        raise


def candidate_loop_components(
    cfg: angr.analyses.CFGFast,
    function_address: int,
) -> list[dict[str, Any]]:
    function = cfg.functions.get(function_address)
    if function is None:
        return []
    graph = function.graph
    components: list[dict[str, Any]] = []
    for index, component in enumerate(
        nx.strongly_connected_components(graph),
        1,
    ):
        member_nodes = list(component)
        members = sorted(
            int(getattr(node, "addr", node))
            for node in member_nodes
        )
        cyclic = len(members) > 1 or (
            len(members) == 1
            and graph.has_edge(member_nodes[0], member_nodes[0])
        )
        if not cyclic:
            continue
        member_node_set = set(member_nodes)
        member_set = set(members)
        heads = sorted(
            int(getattr(node, "addr", node))
            for node in member_nodes
            if any(
                predecessor not in member_node_set
                for predecessor in graph.predecessors(node)
            )
        )
        components.append(
            {
                "component_index": index,
                "members": members,
                "member_set": member_set,
                "heads": heads,
                "head": heads[0] if len(heads) == 1 else None,
                "entry_ambiguous": len(heads) != 1,
            }
        )
    return components


def normalized_instructions(project: angr.Project, address: int) -> list[str]:
    block = project.factory.block(address, num_inst=1)
    instructions = list(block.capstone.insns)
    if not instructions:
        return [f"0x{address:x}:<empty>"]
    tokens = []
    for instruction in instructions:
        text = f"{instruction.mnemonic} {instruction.op_str}".strip()
        mnemonic = instruction.mnemonic.casefold()
        if (
            mnemonic.startswith("j")
            or mnemonic in {"call", "loop", "loope", "loopne"}
        ) and instruction.op_str.startswith("0x"):
            text = f"{instruction.mnemonic} ADDR"
        tokens.append(text)
    return tokens


def loop_body_tokens(
    project: angr.Project,
    members: list[int],
) -> list[str]:
    tokens = []
    for address in sorted(members):
        tokens.extend(normalized_instructions(project, address))
    return tokens


def expanded_loop_member_addresses(
    project: angr.Project,
    members: list[int],
) -> set[int]:
    addresses: set[int] = set()
    for member in members:
        block = project.factory.block(member)
        addresses.update(
            int(instruction.address)
            for instruction in block.capstone.insns
        )
        addresses.add(int(member))
    return addresses


def symbolic_state(
    project: angr.Project,
    function_address: int,
    signature: str,
    profile: dict[str, Any],
) -> tuple[angr.SimState, dict[str, Any], list[dict[str, Any]]]:
    schema = schema_from_signature(
        signature,
        arch_bits=int(project.arch.bits),
    )
    contract = build_contract(
        schema,
        profile=profile,
        source="round017_counted_loops",
    )
    arguments = []
    for spec in schema:
        if spec["kind"] == "float":
            sort = (
                claripy.FSORT_DOUBLE
                if int(spec["bits"]) == 64
                else claripy.FSORT_FLOAT
            )
            value = claripy.FPS(spec["name"], sort)
        else:
            value = claripy.BVS(spec["name"], int(spec["bits"]))
        arguments.append(value)
    state = project.factory.call_state(
        function_address,
        *arguments,
        ret_addr=0,
        add_options={
            angr.options.ZERO_FILL_UNCONSTRAINED_MEMORY,
            angr.options.ZERO_FILL_UNCONSTRAINED_REGISTERS,
        },
    )
    state.options.discard(angr.options.LAZY_SOLVES)
    for argument, spec in zip(arguments, schema):
        for constraint in claripy_domain_constraints(
            argument,
            spec,
            profile=profile,
            claripy_module=claripy,
        ):
            state.solver.add(constraint)
    return state, contract, schema


def concrete_register_values(state: angr.SimState) -> dict[str, int]:
    values: dict[str, int] = {}
    for register in state.arch.register_list:
        name = str(register.name)
        if name in {
            "ip",
            "sp",
            "bp",
            "cc_op",
            "cc_dep1",
            "cc_dep2",
            "cc_ndep",
            "fs_base",
            "gs_base",
        }:
            continue
        try:
            value = getattr(state.regs, name)
            if getattr(value, "symbolic", False):
                continue
            values[name] = int(state.solver.eval(value, cast_to=int))
        except Exception:
            continue
    return values


def induction_registers(
    visit_values: list[dict[str, int]],
    exit_values: dict[str, int],
    bits: int,
) -> list[dict[str, Any]]:
    if len(visit_values) < 2:
        return []
    shared = set(visit_values[0])
    for values in visit_values[1:]:
        shared.intersection_update(values)
    candidates = []
    modulus = 1 << bits
    for name in sorted(shared):
        sequence = [values[name] for values in visit_values]
        deltas = {
            (following - current) % modulus
            for current, following in zip(sequence, sequence[1:])
        }
        if len(deltas) != 1:
            continue
        delta = next(iter(deltas))
        if delta == 0:
            continue
        signed_delta = delta - modulus if delta >= (1 << (bits - 1)) else delta
        candidates.append(
            {
                "register": name,
                "initial_unsigned": sequence[0],
                "last_header_unsigned": sequence[-1],
                "step_unsigned": delta,
                "step_signed": signed_delta,
                "visit_count": len(sequence),
                "exit_unsigned": (
                    int(exit_values[name]) % modulus
                    if name in exit_values
                    else None
                ),
                "transition": "bitvector_modulo_2_power_width",
            }
        )
    return candidates


def analyze_binary(
    binary: Path,
    *,
    function_name: str,
    signature: str,
    profile: dict[str, Any],
    max_steps: int,
) -> dict[str, Any]:
    project = angr.Project(str(binary), auto_load_libs=False)
    symbol = project.loader.find_symbol(function_name)
    if symbol is None:
        return {
            "status": "unsupported",
            "reason": "function_symbol_not_found",
            "loops": [],
        }
    function_address = int(symbol.rebased_addr)
    cfg = project.analyses.CFGFast(
        normalize=True,
        data_references=False,
    )
    components = candidate_loop_components(cfg, function_address)
    for candidate in components:
        candidate["member_set"] = expanded_loop_member_addresses(
            project,
            candidate["members"],
        )
    if not components:
        return {
            "status": "no_loop",
            "reason": "no_cyclic_cfg_component",
            "loops": [],
        }
    viable_components = [
        component for component in components if component["head"] is not None
    ]
    if len(viable_components) != 1:
        return {
            "status": "unsupported",
            "reason": "b1_requires_one_unambiguous_loop_component",
            "loop_component_count": len(viable_components),
            "loops": [],
        }
    component = viable_components[0]
    state, contract, schema = symbolic_state(
        project,
        function_address,
        signature,
        profile,
    )
    queue = [
        {
            "state": state,
            "previous_address": None,
            "inside": False,
            "trace": [],
            "entries": [],
            "visits": [],
            "exit_address": None,
            "exit_values": {},
            "terminal": "",
            "unsupported_reason": "",
        }
    ]
    terminal_frames: list[dict[str, Any]] = []
    unresolved_branches: list[dict[str, Any]] = []
    steps = 0
    while queue and steps < max_steps:
        frame = queue.pop()
        while True:
            if steps >= max_steps:
                frame["terminal"] = "max_steps_exceeded"
                terminal_frames.append(frame)
                queue.clear()
                break
            steps += 1
            state = frame["state"]
            address = int(state.addr)
            frame["trace"].append(address)
            previous_address = frame["previous_address"]
            was_inside = (
                previous_address is not None
                and previous_address in component["member_set"]
            )
            is_inside = address in component["member_set"]
            if is_inside and not was_inside:
                frame["entries"].append(
                    {
                        "step": len(frame["trace"]),
                        "address": address,
                        "registers": concrete_register_values(state),
                    }
                )
            if address == component["head"]:
                frame["visits"].append(
                    {
                        "step": len(frame["trace"]),
                        "address": address,
                        "registers": concrete_register_values(state),
                    }
                )
            if was_inside and not is_inside and frame["visits"]:
                frame["exit_address"] = address
                frame["exit_values"] = concrete_register_values(state)
                frame["terminal"] = "loop_exited"
                terminal_frames.append(frame)
                break
            frame["inside"] = was_inside or is_inside
            frame["previous_address"] = address
            if address == 0:
                frame["terminal"] = (
                    "function_returned_without_loop"
                    if not frame["visits"]
                    else "function_returned"
                )
                terminal_frames.append(frame)
                break
            try:
                successors = state.step(num_inst=1)
                candidates = [
                    successor
                    for successor in successors.flat_successors
                    if successor.solver.satisfiable()
                ]
            except Exception as exc:  # noqa: BLE001
                reason = f"step_error:{type(exc).__name__}"
                frame["terminal"] = reason
                frame["unsupported_reason"] = reason
                unresolved_branches.append(
                    {
                        "address": address,
                        "reason": reason,
                        "error": str(exc),
                    }
                )
                terminal_frames.append(frame)
                break
            if not candidates:
                frame["terminal"] = "no_feasible_successor"
                frame["unsupported_reason"] = frame["terminal"]
                unresolved_branches.append(
                    {"address": address, "reason": frame["terminal"]}
                )
                terminal_frames.append(frame)
                break
            if len(candidates) > 1:
                if frame["inside"]:
                    frame["terminal"] = "branch_inside_loop"
                    frame["unsupported_reason"] = (
                        "symbolic_or_multiple_loop_body_successors"
                    )
                    unresolved_branches.append(
                        {
                            "address": address,
                            "reason": frame["unsupported_reason"],
                            "successor_count": len(candidates),
                        }
                    )
                    terminal_frames.append(frame)
                    break
                for successor in candidates:
                    queued = {
                        **frame,
                        "state": successor,
                        "trace": list(frame["trace"]),
                        "entries": copy.deepcopy(frame["entries"]),
                        "visits": copy.deepcopy(frame["visits"]),
                        "exit_values": dict(frame["exit_values"]),
                    }
                    queue.append(queued)
                break
            frame["state"] = candidates[0]
    if queue:
        unresolved_branches.append(
            {
                "reason": "max_steps_exceeded_with_pending_paths",
                "pending_paths": len(queue),
            }
        )
    completed_runs = [
        frame
        for frame in terminal_frames
        if frame["terminal"] == "loop_exited"
    ]
    skipped_runs = [
        frame
        for frame in terminal_frames
        if frame["terminal"] == "function_returned_without_loop"
    ]
    unresolved_frames = [
        frame
        for frame in terminal_frames
        if frame["terminal"]
        not in {"loop_exited", "function_returned_without_loop"}
    ] + list(queue)

    body_tokens = loop_body_tokens(project, component["members"])
    run_summaries = []
    for frame in completed_runs:
        head_steps = [visit["step"] for visit in frame["visits"]]
        cycle_trace = []
        if len(head_steps) >= 2:
            cycle_trace = frame["trace"][
                head_steps[0] - 1 : head_steps[1] - 1
            ]
        cycle_tokens = []
        for address in cycle_trace:
            cycle_tokens.extend(normalized_instructions(project, address))
        body_digest = hashlib.sha256(
            "\n".join(cycle_tokens or body_tokens).encode("utf-8")
        ).hexdigest()
        unique_points: dict[tuple[int, int], dict[str, Any]] = {}
        for point in [*frame["entries"], *frame["visits"]]:
            unique_points.setdefault(
                (int(point["step"]), int(point["address"])),
                point,
            )
        iteration_points = [
            unique_points[key] for key in sorted(unique_points)
        ]
        visit_values = [point["registers"] for point in iteration_points]
        inductions = induction_registers(
            visit_values,
            frame["exit_values"],
            int(project.arch.bits),
        )
        run_summaries.append(
            {
                "iteration_count": len(visit_values),
                "head_visit_count": len(frame["visits"]),
                "entry_point_count": len(frame["entries"]),
                "body_digest": body_digest,
                "cycle_instruction_count": len(cycle_tokens),
                "cycle_tokens": cycle_tokens,
                "induction_registers": inductions,
                "iteration_points": iteration_points,
                "exit_address": frame["exit_address"],
            }
        )
    summary_keys = {
        (
            item["iteration_count"],
            item["body_digest"],
            tuple(
                (
                    register["register"],
                    register["initial_unsigned"],
                    register["step_unsigned"],
                    register["exit_unsigned"],
                )
                for register in item["induction_registers"]
            ),
        )
        for item in run_summaries
    }
    proved = bool(
        run_summaries
        and not unresolved_frames
        and not unresolved_branches
        and len(summary_keys) == 1
        and all(item["induction_registers"] for item in run_summaries)
    )
    representative = run_summaries[0] if run_summaries else {}
    loops = (
        [
            {
                "component_index": component["component_index"],
                "head": component["head"],
                "members": component["members"],
                "entry_ambiguous": component["entry_ambiguous"],
                "body_instruction_count": len(body_tokens),
                "body_tokens": body_tokens,
                **representative,
                "proof_eligible": proved,
                "control_path_unique": not unresolved_branches,
                "conditional_entry_path_count": len(skipped_runs),
                "loop_run_count": len(run_summaries),
                "run_summaries": run_summaries,
                "reason": (
                    "constant_count_loop_proved"
                    if proved
                    else "loop_control_or_count_not_proved_constant"
                ),
            }
        ]
        if representative
        else []
    )
    terminal_reason = (
        "all_control_paths_classified"
        if not unresolved_frames and not unresolved_branches
        else "control_paths_unresolved"
    )
    return {
        "schema": "symbolicana.round017.counted_loop_certificate.v1",
        "status": (
            "proved"
            if loops and all(item["proof_eligible"] for item in loops)
            else "unsupported"
        ),
        "reason": terminal_reason,
        "binary": str(binary.resolve()),
        "binary_sha256": sha256_file(binary),
        "function": function_name,
        "function_address": function_address,
        "signature": signature,
        "input_schema": schema,
        "input_contract": contract,
        "domain_profile_hash": sha256_json(profile),
        "analysis_steps": steps,
        "terminal_path_count": len(terminal_frames),
        "loop_run_count": len(completed_runs),
        "skipped_loop_path_count": len(skipped_runs),
        "unresolved_path_count": len(unresolved_frames),
        "unique_control_path": not unresolved_branches,
        "unresolved_branches": unresolved_branches,
        "loops": loops,
        "state_trace": completed_runs[0]["trace"] if completed_runs else [],
        "analysis_script_sha256": sha256_file(Path(__file__).resolve()),
    }


def main() -> int:
    args = parse_args()
    profile = load_profile(args.domain_profile_json)
    certificate = analyze_binary(
        args.binary.resolve(),
        function_name=args.function,
        signature=args.signature,
        profile=profile,
        max_steps=args.max_steps,
    )
    if args.out:
        atomic_json(args.out.resolve(), certificate)
    print(json.dumps(certificate, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
