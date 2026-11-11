#!/usr/bin/env python3
"""Reproduce a compact path-union inclusion benchmark with domain bounds."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from z3 import BitVec, Context, FP, FPSort

from input_domain_contract import (
    symbol_matches_spec,
    z3_domain_constraints,
)
from smt_path_union import build_path_union_query


DECLARATION = re.compile(
    r"\(\s*declare-fun\s+"
    r"(?P<name>[^\s()]+)\s*\(\)\s*"
    r"(?P<sort>\(_\s+(?:BitVec|FloatingPoint)\s+[^)]+\))",
    re.DOTALL,
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def extract_domain_expressions(
    texts: list[str],
    contract: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    declarations: dict[str, str] = {}
    for text in texts:
        for match in DECLARATION.finditer(text):
            name = match.group("name")
            sort = re.sub(r"\s+", " ", match.group("sort")).strip()
            previous = declarations.get(name)
            if previous is not None and previous != sort:
                raise ValueError(
                    f"conflicting declaration for {name}: "
                    f"{previous!r} != {sort!r}"
                )
            declarations[name] = sort

    context = Context()
    expressions: list[str] = []
    selected: list[dict[str, Any]] = []
    selected_declarations: dict[str, str] = {}
    for spec in contract.get("inputs") or []:
        names = sorted(
            name
            for name in declarations
            if symbol_matches_spec(name, spec)
        )
        for name in names:
            sort = declarations[name]
            bits = int(spec["bits"])
            if spec["kind"] == "float":
                if "FloatingPoint" in sort:
                    if bits == 64:
                        variable = FP(name, FPSort(11, 53, ctx=context))
                    elif bits == 32:
                        variable = FP(name, FPSort(8, 24, ctx=context))
                    else:
                        raise ValueError(
                            f"unsupported float width: {bits}"
                        )
                elif "BitVec" in sort:
                    if f"BitVec {bits}" not in sort:
                        continue
                    variable = BitVec(
                        name,
                        bits,
                        ctx=context,
                    ).raw_to_fp()
                else:
                    continue
            else:
                if "BitVec" not in sort or f"BitVec {bits}" not in sort:
                    continue
                variable = BitVec(name, bits, ctx=context)
            constraints = z3_domain_constraints(
                variable,
                spec,
                profile=contract.get("profile"),
            )
            expressions.extend(
                expression.sexpr() for expression in constraints
            )
            selected.append(
                {
                    "name": name,
                    "index": int(spec["index"]),
                    "kind": spec["kind"],
                    "bits": bits,
                    "sort": sort,
                    "constraint_count": len(constraints),
                }
            )
            selected_declarations[name] = (
                f"(declare-fun {name} () {sort})"
            )
    return (
        list(dict.fromkeys(expressions)),
        selected,
        [
            selected_declarations[name]
            for name in sorted(selected_declarations)
        ],
    )


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths-dir", type=Path, required=True)
    parser.add_argument("--pair-id", required=True)
    parser.add_argument(
        "--source-prefix",
        default="symbolic_oldV",
    )
    parser.add_argument(
        "--target-prefix",
        default="symbolic_newV",
    )
    parser.add_argument(
        "--domain-manifest",
        type=Path,
        default=root
        / "experiments/round_016_static_analysis/domain/"
        "domain_contract_272.json",
    )
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    parser.add_argument("--z3", default="z3")
    parser.add_argument("--query-out", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = next(
        item
        for item in read_json(args.domain_manifest).get("contracts") or []
        if item.get("pair_id") == args.pair_id
    )
    source_paths = sorted(
        args.paths_dir.glob(f"{args.source_prefix}_path_*.txt"),
        key=_path_number,
    )
    target_paths = sorted(
        args.paths_dir.glob(f"{args.target_prefix}_path_*.txt"),
        key=_path_number,
    )
    source_texts = [
        path.read_text(encoding="utf-8", errors="replace")
        for path in source_paths
    ]
    target_texts = [
        path.read_text(encoding="utf-8", errors="replace")
        for path in target_paths
    ]
    (
        domain_expressions,
        selected_inputs,
        domain_declarations,
    ) = extract_domain_expressions(
        [*source_texts, *target_texts],
        contract,
    )
    query = build_path_union_query(
        source_texts,
        target_texts,
        extra_domain_expressions=domain_expressions,
        extra_declarations=domain_declarations,
    )
    if query.unsupported_commands:
        raise ValueError(
            "unsupported SMT commands: "
            + ", ".join(query.unsupported_commands)
        )
    query_bytes = query.text.encode("utf-8")
    query_hash = hashlib.sha256(query_bytes).hexdigest()
    if args.query_out is not None:
        args.query_out.parent.mkdir(parents=True, exist_ok=True)
        args.query_out.write_bytes(query_bytes)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [
                args.z3,
                "-smt2",
                "-in",
                f"-t:{int(args.timeout_ms)}",
            ],
            input=query.text,
            text=True,
            capture_output=True,
            timeout=max(1, math.ceil(args.timeout_ms / 1000) + 30),
            check=False,
        )
        elapsed = time.perf_counter() - started
        status = completed.stdout.strip().splitlines()[-1:] or [""]
        result = {
            "returncode": completed.returncode,
            "status": status[0],
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "elapsed_seconds": elapsed,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        result = {
            "returncode": None,
            "status": "timeout",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "elapsed_seconds": time.perf_counter() - started,
            "timed_out": True,
        }
    payload = {
        "schema": "symbolicana.round016_compact_path_union_benchmark.v1",
        "pair_id": args.pair_id,
        "source_prefix": args.source_prefix,
        "target_prefix": args.target_prefix,
        "source_paths": len(source_paths),
        "target_paths": len(target_paths),
        "query_bytes": len(query_bytes),
        "query_sha256": query_hash,
        "query_out": str(args.query_out) if args.query_out else None,
        "declarations": len(query.declarations),
        "domain_expression_count": len(domain_expressions),
        "domain_inputs": selected_inputs,
        "timeout_ms": int(args.timeout_ms),
        "z3": args.z3,
        "result": result,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "pair_id",
                    "source_paths",
                    "target_paths",
                    "query_bytes",
                    "query_sha256",
                    "domain_expression_count",
                    "result",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _path_number(path: Path) -> int:
    match = re.search(r"path_(\d+)", path.stem)
    return int(match.group(1)) if match else 0


if __name__ == "__main__":
    raise SystemExit(main())

