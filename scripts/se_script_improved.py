                      
"""
Improved symbolic execution script for benchmark programs.

For programs without external input: generates meaningful constraints by
symbolizing function parameters or memory state.
"""

import angr
import claripy
import re
import os
import glob
import json
import hashlib
import gc
from pathlib import Path
from claripy.backends.backend_z3 import claripy_solver_to_smt2
from angr.sim_type import (
    SimTypeChar,
    SimTypeDouble,
    SimTypeFunction,
    SimTypeInt,
    SimTypeLongLong,
    SimTypePointer,
)
from angr import concretization_strategies
import logging
from program_counterexample import scalar_type_info
from input_domain_contract import (
    build_contract,
    claripy_domain_constraints,
    load_profile,
    schema_from_signature,
    sha256_json,
)
from loop_frontier_audit import classify_smt_frontiers
from round017_counted_loops import analyze_binary as analyze_counted_loops
from round017_semantic_models import (
    audit_binary_imports,
    finalize_runtime_audit,
)

        
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

       
symbolic_var_counter = 0
symbolic_variables = {}

# For binaries without s000 (e.g. ardiff): hook scanf and register symbolic vars here
_scanf_symbolic_vars = {}


def _ast_constants(value, *, seen=None):
    """Return integer bit-vector constants contained in a Claripy AST."""
    if seen is None:
        seen = set()
    marker = id(value)
    if marker in seen:
        return set()
    seen.add(marker)
    if getattr(value, "op", None) == "BVV":
        try:
            return {int(getattr(value, "args", ())[0])}
        except (IndexError, TypeError, ValueError):
            return set()
    out = set()
    for argument in getattr(value, "args", ()):
        if isinstance(argument, (tuple, list)):
            for item in argument:
                if hasattr(item, "args"):
                    out.update(_ast_constants(item, seen=seen))
        elif hasattr(argument, "args"):
            out.update(_ast_constants(argument, seen=seen))
    return out


class SymbolicObjectRangeStrategy(concretization_strategies.SimConcretizationStrategy):
    """Resolve wide symbolic indices into complete in-object candidates.

    This strategy is deliberately a fallback. Accesses whose full address span
    fits the default Range strategy keep their existing behavior. For a wide
    access tied to one known writable object, all feasible in-object addresses
    are enumerated. Feasible out-of-object values are represented by up to two
    boundary values and are marked incomplete, because one representative is
    not an enumeration of the out-of-object domain.
    """

    def __init__(
        self,
        objects,
        *,
        default_range_limit=1024,
        max_object_size=4096,
        outside_representatives=2,
    ):
        super().__init__(exact=True)
        self.objects = tuple(objects)
        self.default_range_limit = int(default_range_limit)
        self.max_object_size = int(max_object_size)
        self.outside_representatives = max(1, int(outside_representatives))
        self.last_resolution = None

    @staticmethod
    def _extra_constraints(kwargs):
        raw = kwargs.get("extra_constraints")
        if raw is None:
            return ()
        if isinstance(raw, (tuple, list)):
            return tuple(raw)
        return (raw,)

    @staticmethod
    def _eval_upto(solver, expression, count, constraints):
        """Support both angr SimSolver and standalone Claripy solvers."""
        if hasattr(solver, "eval_upto"):
            return solver.eval_upto(
                expression,
                count,
                exact=True,
                extra_constraints=constraints,
            )
        return solver.eval(
            expression,
            count,
            exact=True,
            extra_constraints=constraints,
        )

    def _resolve_address_impl(self, memory, addr, **kwargs):
        """Return all feasible in-object values plus bounded outside witnesses."""
        self.last_resolution = None
        constants = _ast_constants(addr)
        matches = [
            item
            for item in self.objects
            if int(item["start"]) in constants and int(item["size"]) > 0
        ]
        if len(matches) != 1:
            return None
        obj = matches[0]
        start = int(obj["start"])
        size = int(obj["size"])
        if size <= 0 or size > self.max_object_size:
            return None

        state = memory.state
        extra_constraints = self._extra_constraints(kwargs)
        bits = int(addr.size())
        start_value = claripy.BVV(start, bits)
        end_value = claripy.BVV(start + size, bits)
        inside = claripy.And(addr >= start_value, addr < end_value)
        inside_constraints = extra_constraints + (inside,)

        inside_values = self._eval_upto(
            state.solver,
            addr,
            size,
            inside_constraints,
        )
        inside_values = sorted({int(value) for value in inside_values})
        inside_complete = len(inside_values) < size
        inside_missing_feasible = False
        if inside_values and not inside_complete:
            exclusions = claripy.Or(
                *[
                    addr == claripy.BVV(value, bits)
                    for value in inside_values
                ]
            )
            inside_missing_feasible = state.solver.satisfiable(
                extra_constraints=inside_constraints
                + (claripy.Not(exclusions),)
            )
            inside_complete = not inside_missing_feasible

        outside = claripy.Not(inside)
        outside_feasible = state.solver.satisfiable(
            extra_constraints=extra_constraints + (outside,)
        )
        outside_values = []
        if outside_feasible:
            outside_constraints = extra_constraints + (outside,)
            outside_values.extend(
                [
                    int(
                        state.solver.min(
                            addr,
                            exact=True,
                            extra_constraints=outside_constraints,
                        )
                    ),
                    int(
                        state.solver.max(
                            addr,
                            exact=True,
                            extra_constraints=outside_constraints,
                        )
                    ),
                ]
            )
            if self.outside_representatives > 2:
                outside_values.extend(
                    int(value)
                    for value in self._eval_upto(
                        state.solver,
                        addr,
                        self.outside_representatives,
                        outside_constraints,
                    )
                )
            outside_values = sorted(set(outside_values))[
                : self.outside_representatives
            ]

        selected = sorted(
            set(inside_values).union(int(value) for value in outside_values)
        )
        if not selected:
            return None
        self.last_resolution = {
            "object_name": str(obj.get("name") or ""),
            "object_start": start,
            "object_size": size,
            "inside_feasible": bool(inside_values),
            "inside_count": len(inside_values),
            "inside_values": inside_values,
            "inside_selection_complete": bool(inside_complete),
            "inside_missing_feasible": bool(inside_missing_feasible),
            "outside_object_feasible": bool(outside_feasible),
            "outside_representatives": outside_values,
            "outside_object_complete": False,
        }
        return selected

    def resolve_address(self, memory, addr, **kwargs):
        """Resolve an object-bound address and preserve solver failures as evidence."""
        try:
            return self._resolve_address_impl(memory, addr, **kwargs)
        except Exception as exc:
            self.last_resolution = {
                "resolution_error": f"{type(exc).__name__}: {exc}",
                "inside_selection_complete": False,
                "outside_object_complete": False,
            }
            return None

    def _concretize(self, memory, addr, **kwargs):
        self.last_resolution = None
        extra_constraints = self._extra_constraints(kwargs)
        state = memory.state
        try:
            minimum = int(
                state.solver.min(
                    addr,
                    exact=True,
                    extra_constraints=extra_constraints,
                )
            )
            maximum = int(
                state.solver.max(
                    addr,
                    exact=True,
                    extra_constraints=extra_constraints,
                )
            )
        except Exception:
            return None
        if maximum - minimum <= self.default_range_limit:
            return None
        return self.resolve_address(memory, addr, **kwargs)


class CoverageAuditedSingleSolutionStrategy:
    """Wrap Any/Max and determine whether their one result is actually unique."""

    def __init__(self, inner):
        self.inner = inner
        self.last_resolution = None

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def concretize(self, memory, addr, **kwargs):
        selected = self.inner.concretize(memory, addr, **kwargs)
        if selected is None:
            self.last_resolution = {
                "inner_strategy": type(self.inner).__name__,
                "selected_count": 0,
                "missing_feasible": None,
                "coverage_verified": False,
                "coverage_error": "inner_strategy_returned_none",
            }
            return None
        selected = sorted({int(value) for value in selected})
        raw_constraints = kwargs.get("extra_constraints")
        if raw_constraints is None:
            extra_constraints = ()
        elif isinstance(raw_constraints, (tuple, list)):
            extra_constraints = tuple(raw_constraints)
        else:
            extra_constraints = (raw_constraints,)
        try:
            bits = int(addr.size())
            excluded = claripy.Not(
                claripy.Or(
                    *[
                        addr == claripy.BVV(value, bits)
                        for value in selected
                    ]
                )
            )
            missing_feasible = bool(
                memory.state.solver.satisfiable(
                    extra_constraints=extra_constraints + (excluded,)
                )
            )
            resolution = {
                "inner_strategy": type(self.inner).__name__,
                "selected_count": len(selected),
                "selected_addresses": selected,
                "missing_feasible": missing_feasible,
                "coverage_verified": not missing_feasible,
                "coverage_error": None,
            }
        except Exception as exc:
            resolution = {
                "inner_strategy": type(self.inner).__name__,
                "selected_count": len(selected),
                "selected_addresses": selected,
                "missing_feasible": None,
                "coverage_verified": False,
                "coverage_error": f"{type(exc).__name__}: {exc}",
            }
        self.last_resolution = resolution
        return selected

    def merge(self, others):
        inner_others = [
            other.inner if isinstance(other, CoverageAuditedSingleSolutionStrategy) else other
            for other in others
        ]
        merge = getattr(self.inner, "merge", None)
        if callable(merge) and inner_others:
            merge(inner_others)


def classify_concretization(strategy, selected, limit, resolution):
    """Classify one selected concretization result without trusting Any/Max."""
    lossy = False
    unverified = False
    if strategy.startswith("CoverageAuditedSingleSolutionStrategy"):
        if not isinstance(resolution, dict):
            classification = "unverified_single_solution"
            unverified = True
        elif resolution.get("coverage_error"):
            classification = "unverified_single_solution"
            unverified = True
        elif resolution.get("missing_feasible") is True:
            classification = "incomplete_single_solution"
            lossy = True
        elif resolution.get("coverage_verified") is True:
            classification = "complete_single_solution"
        else:
            classification = "unverified_single_solution"
            unverified = True
    elif strategy == "SymbolicObjectRangeStrategy":
        if not isinstance(resolution, dict):
            classification = "unverified_object_range"
            unverified = True
        elif resolution.get("resolution_error"):
            classification = "unverified_object_range"
            unverified = True
        elif not resolution.get("inside_selection_complete"):
            classification = "unverified_object_range"
            unverified = True
        elif resolution.get("outside_object_feasible"):
            classification = "incomplete_object_outside_unmodeled"
            lossy = True
        elif resolution.get("inside_feasible"):
            classification = "complete_object_range"
        else:
            classification = "unverified_object_range"
            unverified = True
    elif strategy == "SimConcretizationStrategyAny":
        classification = "unverified_single_solution"
        lossy = True
    elif strategy == "SimConcretizationStrategyMax":
        classification = "unverified_max_solution"
        lossy = True
    elif strategy == "SimConcretizationStrategyRange":
        if isinstance(limit, int) and len(selected) < limit:
            classification = "complete_range"
        else:
            classification = "unverified_range_limit"
            unverified = True
    else:
        classification = "unverified_strategy"
        unverified = True
    return {
        "classification": classification,
        "lossy": lossy,
        "unverified": unverified,
        "coverage_verified": classification
        in {
            "complete_object_range",
            "complete_range",
            "complete_single_solution",
        },
    }


def ieee754_sqrt_formula(value, precision):
    """Return the correctly rounded IEEE-754 sqrt expression for an ABI value."""
    precision = int(precision)
    if precision == 32:
        float_sort = claripy.FSORT_FLOAT
    elif precision == 64:
        float_sort = claripy.FSORT_DOUBLE
    else:
        raise ValueError(f"unsupported sqrt precision: {precision}")
    value_sort = getattr(value, "sort", None)
    is_floating_point = (
        value_sort is not None
        and type(value_sort).__name__ == "FSort"
    )
    if is_floating_point and int(value_sort.length) == precision:
        fp_value = value
    elif is_floating_point:
        raise ValueError(
            f"sqrt ABI value has {int(value_sort.length)} float bits, "
            f"expected {precision}"
        )
    else:
        value_bits = int(value.size())
        if value_bits != precision:
            raise ValueError(
                f"sqrt ABI value has {value_bits} bits, expected {precision}"
            )
        fp_value = value.raw_to_fp()
    return claripy.fpSqrt(
        claripy.RM.RM_NearestTiesEven,
        fp_value,
    )


class SqrtSymbolicHook(angr.SimProcedure):
    """IEEE-754 square root model with the correct binary32/64 ABI."""

    def __init__(self, precision=64, function_name="sqrt", call_evidence=None, **kwargs):
        super().__init__(**kwargs)
        self.precision = int(precision)
        self.function_name = str(function_name)
        self.call_evidence = call_evidence
        if self.precision not in (32, 64):
            raise ValueError(f"unsupported sqrt precision: {self.precision}")

    def run(self, value):
        if self.call_evidence is not None:
            use = self.call_evidence.record(self.state, self.function_name, value, sqrt=True)
            if use["kind"] in {"ieee754_sqrt", "unreachable_call"}:
                return ieee754_sqrt_formula(value, self.precision)
            return claripy.BVS("mathrel_" + use["relation_key"], self.precision,
                               explicit_name=True).raw_to_fp()
        result = ieee754_sqrt_formula(value, self.precision)
        value_sort = getattr(value, "sort", None)
        fp_value = (
            value
            if value_sort is not None
            and type(value_sort).__name__ == "FSort"
            else value.raw_to_fp()
        )
        zero = claripy.FPV(0.0, fp_value.sort)
        try:
            argument_nonnegative = bool(
                self.state.solver.is_true(fp_value >= zero)
            )
        except Exception:
            argument_nonnegative = False
        uses = list(
            self.state.globals.get("symbolicana_external_model_uses") or []
        )
        uses.append(
            {
                "function": self.function_name,
                "precision": self.precision,
                "abi_prototype": (
                    "float sqrtf(float)"
                    if self.precision == 32
                    else (
                        "double __sqrt_finite(double)"
                        if self.function_name == "__sqrt_finite"
                        else "double sqrt(double)"
                    )
                ),
                "argument_nonnegative": argument_nonnegative,
                "argument_expr_sha256": hashlib.sha256(
                    str(fp_value).encode("utf-8")
                ).hexdigest(),
            }
        )
        self.state.globals["symbolicana_external_model_uses"] = uses
        return result


class FixedMathHook(angr.SimProcedure):
    """Shared arbitrary results only for identical complete argument formulas."""
    def __init__(self, function_name, call_evidence, **kwargs):
        super().__init__(**kwargs)
        self.function_name = function_name
        self.call_evidence = call_evidence

    def run(self, value):
        use = self.call_evidence.record(self.state, self.function_name, value)
        return claripy.BVS("mathrel_" + use["relation_key"], use["precision"],
                           explicit_name=True).raw_to_fp()


class FixedSinCosHook(FixedMathHook):
    def run(self, value, sin_ptr, cos_ptr):
        use = self.call_evidence.record(self.state, self.function_name, value)
        if sin_ptr.symbolic or cos_ptr.symbolic:
            # Still explore conservatively; this call cannot authorize EQ.
            use["unsupported_pointer_outputs"] = True
        for component, pointer in (("sin", sin_ptr), ("cos", cos_ptr)):
            result = claripy.BVS("mathrel_" + use["relation_key"] + "_" + component,
                                 use["precision"], explicit_name=True)
            self.state.memory.store(pointer, result, endness=self.state.arch.memory_endness)
        return None


def parse_snippet_signature(raw):
    if not raw:
        return None
    match = re.match(r"\s*(?P<ret>\w+)\s*\((?P<args>[^)]*)\)\s*$", raw)
    if not match:
        raise ValueError(f"invalid snippet signature: {raw}")
    args_text = match.group("args").strip()
    args = [] if not args_text or args_text == "void" else [part.strip() for part in args_text.split(",")]
    return {"return": match.group("ret"), "args": args}

class ScanfSymbolicHook(angr.SimProcedure):
    """Inject typed, domain-constrained symbolic values for scanf inputs."""

    def __init__(self, schema=None, domain_profile=None):
        super().__init__()
        self.schema = list(schema or [])
        self.domain_profile = domain_profile

    def run(self, fmt_ptr, *args):
        global _scanf_symbolic_vars, symbolic_variables
        for i, ptr in enumerate(args):
            if ptr is None:
                continue
            name = f"scanf_{len(_scanf_symbolic_vars)}"
            spec = (
                self.schema[i]
                if i < len(self.schema)
                else {
                    "index": i,
                    "name": name,
                    "c_type": "int",
                    "kind": "bitvec",
                    "bits": 32,
                    "precision": 0,
                }
            )
            if spec.get("kind") == "float":
                sort = (
                    claripy.FSORT_DOUBLE
                    if int(spec.get("bits", 64)) == 64
                    else claripy.FSORT_FLOAT
                )
                sym = claripy.FPS(spec["name"], sort)
                stored = sym.raw_to_bv()
            else:
                sym = claripy.BVS(
                    spec["name"],
                    int(spec.get("bits", 32) or 32),
                )
                stored = sym
            for constraint in claripy_domain_constraints(
                sym,
                spec,
                profile=self.domain_profile,
                claripy_module=claripy,
            ):
                self.state.solver.add(constraint)
            _scanf_symbolic_vars[name] = sym
            symbolic_variables[name] = sym
            self.state.memory.store(
                ptr,
                stored,
                endness=self.state.arch.memory_endness,
            )
        return claripy.BVV(len(args), self.state.arch.bits)


OUTPUT_FORMAT_SPECIFIER = re.compile(
    r"%(?:[-+ #0]*)(?:\d+|\*)?(?:\.(?:\d+|\*))?"
    r"(?:hh|h|ll|l|j|z|t|L)?[diouxXfFeEgGaAcspn%]"
)


def read_concrete_c_string(state, pointer, max_bytes=4096):
    """Read a concrete NUL-terminated string without concretizing a pointer."""
    try:
        address = state.solver.eval(pointer, cast_to=int)
    except Exception:
        return None
    data = bytearray()
    try:
        for offset in range(max_bytes):
            byte = state.memory.load(
                address + offset,
                size=1,
                endness=state.arch.memory_endness,
            )
            if getattr(byte, "symbolic", False):
                return None
            value = int(state.solver.eval(byte, cast_to=int)) & 0xFF
            if value == 0:
                return data.decode("utf-8", errors="backslashreplace")
            data.append(value)
    except Exception:
        return None
    return None


class RecordedOutputHook(angr.SimProcedure):
    """Capture a stdio call as path-local output metadata.

    The hook does not write to the host process.  It records the format string
    and argument ASTs in the symbolic state so every terminating path can be
    compared on its ordered output events.
    """

    format_position = None

    def record(self, call, sink, fmt, args):
        events = list(self.state.globals.get("symbolicana_output_events", []))
        if isinstance(fmt, bytes):
            format_text = fmt.decode("utf-8", errors="backslashreplace")
        elif isinstance(fmt, str):
            format_text = fmt
        else:
            format_text = read_concrete_c_string(self.state, fmt)
        events.append(
            {
                "call": call,
                "sink": sink,
                "format": format_text,
                "args": tuple(args),
            }
        )
        self.state.globals["symbolicana_output_events"] = events
        return claripy.BVV(0, 32)

    def output_argument_types(self, fmt):
        integer_type = SimTypeInt(signed=True)
        long_type = SimTypeLongLong(signed=True)
        string_type = SimTypePointer(SimTypeChar())
        argument_types = []
        for match in OUTPUT_FORMAT_SPECIFIER.finditer(fmt or ""):
            specifier = match.group(0)
            if specifier == "%%":
                continue
            if "*" in specifier:
                argument_types.extend([integer_type] * specifier.count("*"))
            conversion = specifier[-1]
            if conversion in ("s", "p", "n"):
                argument_types.append(string_type)
            elif conversion in ("f", "F", "e", "E", "g", "G", "a", "A"):
                argument_types.append(SimTypeDouble())
            elif "ll" in specifier or conversion in ("j", "z", "t"):
                argument_types.append(long_type)
            elif "l" in specifier:
                argument_types.append(long_type)
            else:
                argument_types.append(integer_type)
        return argument_types

    def execute(self, state, successors=None, arguments=None, ret_to=None):
        """Extend a fixed prototype with the varargs described by ``fmt``."""
        if self.format_position is None:
            return super().execute(
                state,
                successors=successors,
                arguments=arguments,
                ret_to=ret_to,
            )
        format_ptr = None
        if arguments is not None:
            if len(arguments) > self.format_position:
                format_ptr = arguments[self.format_position]
        elif (
            isinstance(state.callstack, angr.engines.ail.AILCallStack)
            and state.callstack.passed_args is not None
        ):
            if len(state.callstack.passed_args) > self.format_position:
                format_ptr = state.callstack.passed_args[self.format_position]
        else:
            cc = state.project.factory.cc()
            session = cc.arg_session(SimTypeInt())
            arch_prototype = self.prototype.with_arch(state.arch)
            for index, argument_type in enumerate(arch_prototype.args):
                value = cc.next_arg(session, argument_type).get_value(state)
                if index == self.format_position:
                    format_ptr = value
                    break
        format_text = (
            read_concrete_c_string(state, format_ptr)
            if format_ptr is not None
            else None
        )
        original_prototype = self.prototype
        original_num_args = self.num_args
        prototype_args = list(original_prototype.args)
        prototype_args.extend(self.output_argument_types(format_text))
        self.prototype = SimTypeFunction(
            prototype_args, SimTypeInt(signed=True)
        ).with_arch(state.arch)
        self.num_args = len(prototype_args)
        try:
            return super().execute(
                state,
                successors=successors,
                arguments=arguments,
                ret_to=ret_to,
            )
        finally:
            self.prototype = original_prototype
            self.num_args = original_num_args


class PrintfOutputHook(RecordedOutputHook):
    format_position = 0

    def run(self, fmt_ptr, *args):
        return self.record("printf", "stdout", fmt_ptr, args)


class FortifiedPrintfOutputHook(RecordedOutputHook):
    format_position = 1

    def run(self, flag, fmt_ptr, *args):
        return self.record("__printf_chk", "stdout", fmt_ptr, args)


class FprintfOutputHook(RecordedOutputHook):
    format_position = 1

    def run(self, stream, fmt_ptr, *args):
        return self.record("fprintf", "stdio", fmt_ptr, args)


class FortifiedFprintfOutputHook(RecordedOutputHook):
    format_position = 2

    def run(self, stream, flag, fmt_ptr, *args):
        return self.record("__fprintf_chk", "stdio", fmt_ptr, args)


class PutsOutputHook(RecordedOutputHook):
    def run(self, string_ptr):
        return self.record("puts", "stdout", b"%s\n", (string_ptr,))


class FputsOutputHook(RecordedOutputHook):
    def run(self, string_ptr, stream):
        return self.record("fputs", "stdio", b"%s", (string_ptr,))


class PutcharOutputHook(RecordedOutputHook):
    def run(self, character):
        return self.record("putchar", "stdout", b"%c", (character,))


class FputcOutputHook(RecordedOutputHook):
    def run(self, character, stream):
        return self.record("fputc", "stdio", b"%c", (character,))


class FlushOutputHook(angr.SimProcedure):
    def run(self, stream):
        return claripy.BVV(0, 32)


class CallDepthBound(angr.exploration_techniques.ExplorationTechnique):
    """Move states whose call stack exceeds the explicit recursion budget."""

    def __init__(self, max_depth):
        super().__init__()
        self.max_depth = max(1, int(max_depth))
        self.max_observed_depth = 0
        self.bound_event_count = 0

    @staticmethod
    def _depth(state):
        try:
            return int(state.callstack.depth)
        except Exception:
            try:
                return int(len(state.callstack))
            except Exception:
                return 0

    def step(self, simgr, stash="active", **kwargs):
        result = super().step(simgr, stash=stash, **kwargs)
        retained = []
        bounded = []
        for state in simgr.stashes.get(stash, []):
            depth = self._depth(state)
            self.max_observed_depth = max(self.max_observed_depth, depth)
            if depth > self.max_depth:
                bounded.append(state)
            else:
                retained.append(state)
        simgr.stashes[stash] = retained
        if bounded:
            simgr.stashes.setdefault("recursion_bound", []).extend(bounded)
            self.bound_event_count += len(bounded)
        return result


class BenchmarkSymbolicExecution:
    """Symbolic execution tailored for benchmark programs."""
    
    def __init__(
        self,
        binary_path,
        output_prefix=None,
        timeout=120,
        snippet_signature=None,
        loop_bound=30,
        max_paths=128,
        int_min=None,
        int_max=None,
        float_min=None,
        float_max=None,
        domain_profile=None,
        input_schema=None,
        auto_loop_bound=False,
        max_auto_loop_bound=4096,
        max_call_depth=30,
        fixed_math_runtime=False,
        initialized_entry=False,
        model_query_timeout_ms=2000,
    ):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        self.snippet_addr = None
        self.snippet_signature = parse_snippet_signature(snippet_signature)
        self.loop_bound = loop_bound
        self.max_paths = max_paths
        self.auto_loop_bound = bool(auto_loop_bound)
        self.max_auto_loop_bound = max(1, int(max_auto_loop_bound))
        self.max_call_depth = max(1, int(max_call_depth))
        self.fixed_math_runtime = bool(fixed_math_runtime)
        self.initialized_entry = bool(initialized_entry or fixed_math_runtime)
        self.model_query_timeout_ms = int(model_query_timeout_ms)
        self.call_evidence = None
        self.fixed_runtime_certificate = None
        self.automatic_loop_bound_audit = None
        if domain_profile is None and any(
            value is not None
            for value in (int_min, int_max, float_min, float_max)
        ):
            domain_profile = {
                "schema": "symbolicana.input_domain_profile.v1",
                "profile_id": "legacy_explicit_bounds",
                "integer": {
                    "minimum": int_min if int_min is not None else -100,
                    "maximum": int_max if int_max is not None else 100,
                    "unsigned_intersection": [
                        0,
                        int_max if int_max is not None else 100,
                    ],
                    "apply_to_pointer_addresses": False,
                },
                "floating_point": {
                    "minimum": float_min if float_min is not None else -100.0,
                    "maximum": float_max if float_max is not None else 100.0,
                    "include_endpoints": True,
                    "include_positive_zero": True,
                    "include_negative_zero": True,
                    "include_subnormal": True,
                    "include_nan": False,
                    "include_positive_infinity": False,
                    "include_negative_infinity": False,
                },
                "internal_values": {"restrict": False},
            }
        self.domain_profile = domain_profile or load_profile()
        self.int_min = (
            int(self.domain_profile["integer"]["minimum"])
            if int_min is None
            else int_min
        )
        self.int_max = (
            int(self.domain_profile["integer"]["maximum"])
            if int_max is None
            else int_max
        )
        self.float_min = (
            float(self.domain_profile["floating_point"]["minimum"])
            if float_min is None
            else float_min
        )
        self.float_max = (
            float(self.domain_profile["floating_point"]["maximum"])
            if float_max is None
            else float_max
        )
        self.domain_profile_hash = sha256_json(self.domain_profile)
        self.input_schema_hint = list(input_schema or [])
        if self.snippet_signature and not self.input_schema_hint:
            self.input_schema_hint = schema_from_signature(
                (
                    f"{self.snippet_signature['return']}"
                    f"({','.join(self.snippet_signature['args'])})"
                )
            )
        self.input_contract = build_contract(
            self.input_schema_hint,
            profile=self.domain_profile,
            source="se_script_improved",
        )
        self.global_write_ranges = []
        self.symbolic_objects = []
        self.exploration_manifest = {}
        self.output_hook_names = []
        self.input_schema = []
        self.concretization_events = {}
        self._concretization_event_sequence = 0
        self._observable_serialization_cache = {}
        self._observable_serialization_cache_limit = 256
        self._observable_serialization_cache_expressions = 0
        self._observable_serialization_cache_chars = 0
        self._observable_serialization_cache_char_limit = 64 * 1024 * 1024
        self._observable_serialization_cache_entry_char_limit = 2 * 1024 * 1024
        self.result_retention_limit = 2
        
                
        if output_prefix is None:
            binary_name = os.path.basename(binary_path)
            self.output_prefix = binary_name
        else:
            self.output_prefix = output_prefix
    
    def setup_project(self):
        """Set up angr project."""
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        print(f"Loading binary: {self.binary_path}")
        self.binary_imports = sorted(
            {
                str(name)
                for name in self.project.loader.main_object.imports
            }
        )
        self.external_model_audit = audit_binary_imports(
            self.binary_imports
        )
        if self.fixed_math_runtime:
            from fixed_math_runtime import build_certificate, CallEvidence
            evidence_dir = Path(str(self.output_prefix) + "_model_evidence").resolve()
            self.fixed_runtime_certificate = build_certificate(self.binary_path, evidence_dir)
            self.call_evidence = CallEvidence(self.fixed_runtime_certificate,
                evidence_dir / "queries", self.model_query_timeout_ms)
        for name, prototype, precision in (
            ("sqrt", "double sqrt(double)", 64),
            ("sqrtf", "float sqrtf(float)", 32),
            ("__sqrt_finite", "double __sqrt_finite(double)", 64),
        ):
            try:
                if self.project.loader.find_symbol(name):
                    self.project.hook_symbol(
                        name,
                        SqrtSymbolicHook(
                            prototype=prototype,
                            precision=precision,
                            function_name=name,
                            call_evidence=self.call_evidence if name != "__sqrt_finite" else None,
                        ),
                    )
                    print(f"Hooked {name} with IEEE-754 symbolic model")
            except (IndexError, AttributeError, TypeError):
                continue
        if self.fixed_math_runtime:
            from fixed_math_runtime import SUPPORTED, MULTI
            for name, binding in self.fixed_runtime_certificate["bindings"].items():
                if name in {"sqrt", "sqrtf"}:
                    continue
                hook_type = FixedSinCosHook if name in MULTI else FixedMathHook
                self.project.hook_symbol(name, hook_type(function_name=name,
                    call_evidence=self.call_evidence, prototype=binding["abi"]))
        output_hooks = {
            "printf": PrintfOutputHook(
                prototype="int printf(const char *format, ...)"
            ),
            "fprintf": FprintfOutputHook(
                prototype="int fprintf(void *stream, const char *format, ...)"
            ),
            "puts": PutsOutputHook(prototype="int puts(const char *string)"),
            "fputs": FputsOutputHook(
                prototype="int fputs(const char *string, void *stream)"
            ),
            "putchar": PutcharOutputHook(prototype="int putchar(int character)"),
            "putc": FputcOutputHook(
                prototype="int putc(int character, void *stream)"
            ),
            "fputc": FputcOutputHook(
                prototype="int fputc(int character, void *stream)"
            ),
            "fflush": FlushOutputHook(prototype="int fflush(void *stream)"),
            "__printf_chk": FortifiedPrintfOutputHook(
                prototype="int __printf_chk(int flag, const char *format, ...)"
            ),
            "__fprintf_chk": FortifiedFprintfOutputHook(
                prototype=(
                    "int __fprintf_chk(void *stream, int flag, "
                    "const char *format, ...)"
                )
            ),
        }
        for name, hook in output_hooks.items():
            try:
                if self.project.loader.find_symbol(name):
                    self.project.hook_symbol(name, hook)
                    self.output_hook_names.append(name)
            except (IndexError, AttributeError, TypeError):
                continue
        if self.output_hook_names:
            print("Hooked output functions: " + ", ".join(self.output_hook_names))
        self.global_write_ranges = self.collect_global_write_ranges()
        self.symbolic_objects = self.collect_symbolic_objects()
        if self.symbolic_objects:
            print(
                "Eligible symbolic range objects: "
                + ", ".join(
                    f"{item['name']}@{item['start']:#x}+{item['size']}"
                    for item in self.symbolic_objects
                )
            )
        
                
        self.find_target_functions()
        self.apply_automatic_loop_bound()

    def apply_automatic_loop_bound(self):
        if not self.auto_loop_bound:
            return
        function_name = None
        if self.s000_addr is not None:
            function_name = "s000"
        elif self.snippet_addr is not None:
            function_name = "snippet"
        if function_name is None:
            self.automatic_loop_bound_audit = {
                "status": "not_applicable",
                "reason": "no_supported_entry_symbol",
            }
            return
        try:
            certificate = analyze_counted_loops(
                Path(self.binary_path),
                function_name=function_name,
                signature=(
                    f"{self.snippet_signature['return']}"
                    f"({','.join(self.snippet_signature['args'])})"
                    if self.snippet_signature is not None
                    else None
                ),
                profile=self.domain_profile,
                max_steps=100_000,
            )
        except Exception as exc:
            self.automatic_loop_bound_audit = {
                "status": "error",
                "reason": f"{type(exc).__name__}:{exc}",
            }
            return
        loops = certificate.get("loops") or []
        counts = [
            int(loop.get("iteration_count", 0) or 0)
            for loop in loops
            if loop.get("proof_eligible") is True
        ]
        proposed = max(counts, default=0)
        if proposed > 0:
            adjusted = min(
                self.max_auto_loop_bound,
                proposed + 2,
            )
            if adjusted > self.loop_bound:
                self.loop_bound = adjusted
        self.automatic_loop_bound_audit = {
            "status": certificate.get("status"),
            "reason": certificate.get("reason"),
            "function": function_name,
            "certificate": certificate,
            "max_proved_iteration_count": proposed,
            "effective_loop_bound": self.loop_bound,
            "capped": proposed + 2 > self.max_auto_loop_bound,
        }
    
    def find_target_functions(self):
        """Find target functions (TSVC s000 or generic entry)."""
        try:
            s000_symbol = self.project.loader.find_symbol('s000')
            if s000_symbol:
                print(f"Found s000 at: 0x{s000_symbol.rebased_addr:x}")
                self.s000_addr = s000_symbol.rebased_addr
            else:
                self.s000_addr = None
        except (IndexError, AttributeError, TypeError):
            # No symbol 's000' (e.g. ardiff benchmarks: symbolic_oldV/symbolic_newV)
            self.s000_addr = None
        if self.s000_addr is None:
            for sym_name in ('snippet', '_snippet'):
                try:
                    sym = self.project.loader.find_symbol(sym_name)
                    if sym:
                        self.snippet_addr = sym.rebased_addr
                        print(f"Found snippet at: 0x{self.snippet_addr:x}")
                        break
                except (IndexError, AttributeError, TypeError):
                    continue
        if self.s000_addr is None and self.snippet_addr is None:
            print("s000/snippet not found; will analyze from entry (e.g. main)")
            # Hook scanf so ardiff-style binaries get symbolic a, b from scanf("%d %d", &a, &b)
            for sym_name in ('scanf', '_scanf', '__isoc99_scanf', '__isoc23_scanf', '__scanf_chk'):
                try:
                    if self.project.loader.find_symbol(sym_name):
                        self.project.hook_symbol(
                            sym_name,
                            ScanfSymbolicHook(
                                schema=self.input_schema_hint,
                                domain_profile=self.domain_profile,
                            ),
                        )
                        print(f"Hooked {sym_name} for symbolic inputs")
                        break
                except (IndexError, AttributeError, TypeError):
                    continue
    
    def create_symbolic_state(self):
        """Create initial state with symbolic variables."""
        global symbolic_var_counter, symbolic_variables
        self.input_schema = []
        # On macOS/ARM64, unconstrained x30 (link register) causes "over 256 solutions; skipping"
        # and 0 paths. Use zero-fill for unconstrained regs/mem so exit states are not skipped.
        if self.snippet_addr is not None:
            arg_types = (
                self.snippet_signature["args"]
                if self.snippet_signature is not None
                else ["int", "int"]
            )
            arg_values = []
            for idx, arg_type in enumerate(arg_types):
                name = f"arg_{idx}"
                schema_hint = (
                    self.input_schema_hint[idx]
                    if idx < len(self.input_schema_hint)
                    else {}
                )
                type_info = scalar_type_info(
                    arg_type,
                    arch_bits=int(self.project.arch.bits),
                )
                if not type_info["supported"]:
                    raise ValueError(
                        f"unsupported snippet argument type {arg_type!r}: "
                        f"{type_info.get('reason', 'unknown')}"
                    )
                if type_info["kind"] == "float":
                    sort = (
                        claripy.FSORT_DOUBLE
                        if type_info["bits"] == 64
                        else claripy.FSORT_FLOAT
                    )
                    sym = claripy.FPS(name, sort)
                else:
                    sym = claripy.BVS(name, int(type_info["bits"]))
                symbolic_variables[name] = sym
                arg_values.append((arg_type, sym))
                self.input_schema.append(
                    {
                        "index": idx,
                        "name": name,
                        "c_type": schema_hint.get("c_type") or arg_type,
                        "kind": type_info["kind"],
                        "bits": int(type_info["bits"]),
                        "precision": 0,
                    }
                )
            initial_state = self.project.factory.call_state(
                self.snippet_addr,
                ret_addr=0,
                add_options={
                    angr.options.ZERO_FILL_UNCONSTRAINED_MEMORY,
                    angr.options.ZERO_FILL_UNCONSTRAINED_REGISTERS,
                    angr.options.TRACK_MEMORY_ACTIONS,
                    angr.options.TRACK_REGISTER_ACTIONS,
                    angr.options.LAZY_SOLVES,
                },
            )
            if any(arg_type not in ("double", "float") for arg_type in arg_types):
                initial_state.options.discard(angr.options.LAZY_SOLVES)
                print("Using eager feasibility checks for integer-controlled paths")
            self.install_call_arguments(initial_state, arg_values)
            self.input_contract = build_contract(
                self.input_schema,
                profile=self.domain_profile,
                source="snippet_signature",
            )
            for (_arg_type, sym), spec in zip(arg_values, self.input_schema):
                for constraint in claripy_domain_constraints(
                    sym,
                    spec,
                    profile=self.domain_profile,
                    claripy_module=claripy,
                ):
                    initial_state.solver.add(constraint)
            initial_state.globals["symbolicana_input_contract"] = (
                self.input_contract
            )
            try:
                initial_state.globals["snippet_initial_sp"] = initial_state.solver.eval(
                    initial_state.regs.sp, cast_to=int
                )
            except Exception:
                pass
            print(
                "Created symbolic snippet arguments: "
                + ", ".join(f"arg_{i}:{typ}" for i, typ in enumerate(arg_types))
            )
        elif self.s000_addr is None:
            initial_state = self.project.factory.entry_state(
                add_options={
                    angr.options.ZERO_FILL_UNCONSTRAINED_MEMORY,
                    angr.options.ZERO_FILL_UNCONSTRAINED_REGISTERS,
                    angr.options.TRACK_MEMORY_ACTIONS,
                    angr.options.TRACK_REGISTER_ACTIONS,
                    angr.options.LAZY_SOLVES,
                }
            )
        else:
            initial_state = self.project.factory.entry_state()
            initial_state.options.add(angr.options.TRACK_MEMORY_ACTIONS)
            initial_state.options.add(angr.options.TRACK_REGISTER_ACTIONS)
            initial_state.options.add(angr.options.LAZY_SOLVES)
        
        if self.s000_addr:
            count_var = claripy.BVS('count_param', 32)
            initial_state.solver.add(count_var >= 0)
            initial_state.solver.add(count_var <= 10)
            symbolic_variables['count_param'] = count_var
            symbolic_var_counter += 1
            print(f"Created symbolic variable: count_param (range 0-10)")
            for i in range(3):
                array_var = claripy.BVS(f'array_b_{i}', 32)
                initial_state.solver.add(array_var >= 0)
                initial_state.solver.add(array_var <= 200)
                symbolic_variables[f'array_b_{i}'] = array_var
                symbolic_var_counter += 1
                print(f"Created symbolic variable: array_b_{i} (range 0-200)")
        # Paper configuration: bound global arrays to their first 16 32-bit
        # elements.  Raw bit-vectors preserve both integer and FP bit patterns.
        if not self.initialized_entry:
            self.symbolize_global_arrays(initial_state, max_elements=16)
        # When s000_addr is None (ardiff etc.), remaining symbolic vars are
        # added by ScanfSymbolicHook.
        initial_state.globals["symbolicana_output_events"] = []
        initial_state.globals["symbolicana_output_hooks"] = list(self.output_hook_names)
        initial_state.globals["symbolicana_external_model_uses"] = []
        if self.input_contract:
            initial_state.globals["symbolicana_input_contract"] = self.input_contract
        return initial_state

    def install_symbolic_object_strategies(self, state):
        """Install object-range fallback before angr's default Any fallback."""
        if not self.symbolic_objects:
            return
        for strategy_list in (
            state.memory.read_strategies,
            state.memory.write_strategies,
        ):
            strategy_list.insert(
                0,
                SymbolicObjectRangeStrategy(self.symbolic_objects),
            )

    def install_single_solution_coverage_strategies(self, state):
        """Audit Any/Max instead of assuming lossiness or completeness by name."""
        for strategy_list in (
            state.memory.read_strategies,
            state.memory.write_strategies,
        ):
            for index, strategy in enumerate(list(strategy_list)):
                if isinstance(
                    strategy,
                    (
                        concretization_strategies.SimConcretizationStrategyAny,
                        concretization_strategies.SimConcretizationStrategyMax,
                    ),
                ) and not isinstance(
                    strategy,
                    CoverageAuditedSingleSolutionStrategy,
                ):
                    strategy_list[index] = CoverageAuditedSingleSolutionStrategy(
                        strategy
                    )

    def install_concretization_monitor(self, state):
        """Record symbolic-address concretization before restrictions are added."""

        def before(callback_state):
            strategy = getattr(
                callback_state.inspect,
                "address_concretization_strategy",
                None,
            )
            expr = getattr(
                callback_state.inspect,
                "address_concretization_expr",
                None,
            )
            attempt = {
                "pc": int(callback_state.addr),
                "action": str(
                    getattr(
                        callback_state.inspect,
                        "address_concretization_action",
                        "",
                    )
                ),
                "strategy": (
                    type(strategy).__name__ if strategy is not None else ""
                ),
                "strategy_limit": getattr(strategy, "_limit", None),
                "strategy_exact": getattr(strategy, "_exact", None),
                "address_expr": str(expr) if expr is not None else "",
                "constraint_count": len(callback_state.solver.constraints),
            }
            attempts = callback_state.globals.get(
                "_symbolicana_concretization_attempts",
                None,
            )
            if not isinstance(attempts, list):
                attempts = []
                callback_state.globals[
                    "_symbolicana_concretization_attempts"
                ] = attempts
            attempts.append(attempt)
            callback_state.globals[
                "_symbolicana_concretization_pending_index"
            ] = len(attempts) - 1

        def after(callback_state):
            attempts = callback_state.globals.get(
                "_symbolicana_concretization_attempts",
                [],
            )
            index = callback_state.globals.get(
                "_symbolicana_concretization_pending_index",
                -1,
            )
            if not isinstance(index, int) or index < 0 or index >= len(attempts):
                return
            pending = attempts[index]
            strategy_object = getattr(
                callback_state.inspect,
                "address_concretization_strategy",
                None,
            )
            result = getattr(
                callback_state.inspect,
                "address_concretization_result",
                None,
            )
            if result is None:
                pending["selected"] = False
                return
            selected = sorted({int(value) for value in result})
            strategy = str(pending.get("strategy") or "")
            limit = pending.get("strategy_limit")
            resolution = getattr(
                strategy_object,
                "last_resolution",
                None,
            )
            classification_result = classify_concretization(
                strategy,
                selected,
                limit,
                resolution,
            )
            attempt_history = []
            for item in attempts:
                attempt_history.append(
                    {
                        **dict(item),
                        "selected": bool(item.get("selected", True)),
                    }
                )
            pending["selected"] = True
            pending["selected_addresses"] = selected
            event = {
                **pending,
                "selected_addresses": selected,
                "selected_count": len(selected),
                "classification": classification_result["classification"],
                "strategy_resolution": (
                    dict(resolution) if isinstance(resolution, dict) else None
                ),
                "strategy_attempts": attempt_history,
                "lossy": classification_result["lossy"],
                "unverified": classification_result["unverified"],
                "coverage_verified": classification_result[
                    "coverage_verified"
                ],
            }
            key = json.dumps(event, sort_keys=True, separators=(",", ":"))
            if key not in self.concretization_events:
                self._concretization_event_sequence += 1
                event["event_id"] = self._concretization_event_sequence
                event["occurrences"] = 0
                self.concretization_events[key] = event
            self.concretization_events[key]["occurrences"] += 1
            callback_state.globals[
                "_symbolicana_concretization_attempts"
            ] = []
            callback_state.globals.pop(
                "_symbolicana_concretization_pending_index",
                None,
            )

        state.inspect.b(
            "address_concretization",
            when=angr.BP_BEFORE,
            action=before,
        )
        state.inspect.b(
            "address_concretization",
            when=angr.BP_AFTER,
            action=after,
        )

    def concretization_summary(self):
        events = sorted(
            self.concretization_events.values(),
            key=lambda item: int(item.get("event_id", 0)),
        )
        classes = {}
        for event in events:
            name = str(event.get("classification") or "unknown")
            classes[name] = classes.get(name, 0) + 1
        lossy = [
            event
            for event in events
            if event.get("lossy")
        ]
        unverified = [
            event
            for event in events
            if event.get("unverified")
        ]
        invalid = [
            event
            for event in events
            if event.get("lossy")
            or event.get("unverified")
            or not event.get("coverage_verified")
        ]
        return {
            "schema": "symbolicana.address_concretization_audit.v1",
            "event_count": len(events),
            "classification_counts": dict(sorted(classes.items())),
            "lossy_event_count": len(lossy),
            "lossy_event_ids": [
                int(event["event_id"]) for event in lossy
            ],
            "unverified_event_count": len(unverified),
            "unverified_event_ids": [
                int(event["event_id"]) for event in unverified
            ],
            "lossy_or_unverified_event_count": len(invalid),
            "lossy_or_unverified_event_ids": [
                int(event["event_id"]) for event in invalid
            ],
            "coverage_verified": not invalid,
            "events": events,
        }

    def save_concretization_audit(self):
        path = f"{self.output_prefix}_concretization_audit.json"
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        summary = self.concretization_summary()
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(summary, stream, indent=2, sort_keys=True)
        return path, summary

    def symbolize_global_arrays(self, state, max_elements=16):
        global symbolic_variables, symbolic_var_counter
        try:
            symbols = list(self.project.loader.main_object.symbols)
        except Exception:
            return
        seen = set()
        for symbol in symbols:
            name = str(getattr(symbol, "name", "") or "")
            size = int(getattr(symbol, "size", 0) or 0)
            address = int(getattr(symbol, "rebased_addr", 0) or 0)
            # Restrict this to user-named writable objects large enough to be
            # arrays; toolchain/runtime symbols commonly begin with '_'.
            if not name or name.startswith("_") or size <= 4 or not address:
                continue
            if not any(start <= address and address + size <= end for start, end, _ in self.global_write_ranges):
                continue
            key = (address, size)
            if key in seen:
                continue
            seen.add(key)
            count = min(max_elements, size // 4)
            for index in range(count):
                var_name = f"global_{re.sub(r'[^A-Za-z0-9_]', '_', name)}_{index}"
                value = claripy.BVS(var_name, 32)
                state.memory.store(
                    address + 4 * index,
                    value,
                    size=4,
                    endness=state.arch.memory_endness,
                )
                symbolic_variables[var_name] = value
                symbolic_var_counter += 1
            if count:
                print(f"Symbolized global array {name}: {count} elements")

    def install_call_arguments(self, state, arg_values):
        """Install snippet arguments using the target architecture's ABI."""
        is_amd64 = "amd64" in str(getattr(state.arch, "name", "")).lower()
        try:
            binary_os = str(
                getattr(self.project.loader.main_object, "os", "") or ""
            ).lower()
        except Exception:
            binary_os = ""
        is_windows_amd64 = is_amd64 and (
            "windows" in binary_os or self.binary_path.lower().endswith(".exe")
        )
        is_x86 = str(getattr(state.arch, "name", "")).lower() == "x86"
        int_register_limit = 4 if is_windows_amd64 else 6
        fp_register_limit = 4 if is_windows_amd64 else 8
        int_reg_index = 0
        fp_reg_index = 0
        stack_index = 0
        for position, (arg_type, sym) in enumerate(arg_values):
            if is_x86:
                self.store_stack_argument(state, position, sym, slot_size=4)
                continue
            if arg_type in ("double", "float"):
                if fp_reg_index < fp_register_limit:
                    reg_name = self.argument_register_name(
                        state, arg_type, fp_reg_index, position
                    )
                    if reg_name in state.arch.registers:
                        self.set_register_value(
                            state, reg_name, sym.raw_to_bv()
                        )
                else:
                    slot_size = 8 if arg_type == "double" else 4
                    self.store_stack_argument(
                        state,
                        stack_index,
                        sym.raw_to_bv(),
                        slot_size=slot_size,
                        windows=is_windows_amd64,
                    )
                    stack_index += 1
                fp_reg_index += 1
                continue
            if int_reg_index < int_register_limit:
                reg_name = self.argument_register_name(
                    state, arg_type, int_reg_index, position
                )
                if reg_name in state.arch.registers:
                    self.set_register_value(state, reg_name, sym)
            else:
                self.store_stack_argument(
                    state,
                    stack_index,
                    sym,
                    slot_size=4,
                    windows=is_windows_amd64,
                )
                stack_index += 1
            int_reg_index += 1

    def store_stack_argument(
        self,
        state,
        index,
        value,
        *,
        slot_size,
        windows=False,
    ):
        """Store an argument beyond the register-passed prefix on the stack."""
        if str(getattr(state.arch, "name", "")).lower() == "x86":
            offset = 4 + index * 4
            slot_size = min(slot_size, 4)
        elif "amd64" in str(getattr(state.arch, "name", "")).lower():
            # SysV places the first stack argument at [rsp+8], after the
            # return address. Win64 reserves return address plus shadow space.
            base = 0x28 if windows else 8
            offset = base + index * 8
        else:
            raise ValueError(
                f"unsupported stack argument ABI: {state.arch.name}"
            )
        state.memory.store(
            state.regs.sp + offset,
            value,
            size=slot_size,
            endness=state.arch.memory_endness,
        )

    def argument_register_name(self, state, arg_type, index, position=None):
        is_amd64 = "amd64" in str(getattr(state.arch, "name", "")).lower()
        try:
            binary_os = str(getattr(self.project.loader.main_object, "os", "") or "").lower()
        except Exception:
            binary_os = ""
        is_windows_amd64 = is_amd64 and ("windows" in binary_os or self.binary_path.lower().endswith(".exe"))
        ordinal = index if position is None else position
        if arg_type == "double":
            if is_windows_amd64:
                candidates = [f"xmm{ordinal}"]
            else:
                candidates = [f"d{index}", f"xmm{index}", f"q{index}", f"v{index}"]
        elif arg_type == "float":
            if is_windows_amd64:
                candidates = [f"xmm{ordinal}"]
            else:
                candidates = [f"s{index}", f"xmm{index}", f"v{index}"]
        else:
            win64 = ["ecx", "edx", "r8d", "r9d"]
            sysv_amd64 = ["edi", "esi", "edx", "ecx", "r8d", "r9d"]
            i386 = ["eax", "edx", "ecx"]
            candidates = []
            if is_windows_amd64 and ordinal < len(win64):
                candidates.append(win64[ordinal])
            if index < len(sysv_amd64):
                candidates.append(sysv_amd64[index])
            if index < len(i386):
                candidates.append(i386[index])
            candidates.extend([f"w{index}", f"x{index}", f"r{index}"])
        for reg_name in candidates:
            if reg_name in state.arch.registers:
                return reg_name
        return candidates[0] if candidates else ""

    def set_register_value(self, state, reg_name, value):
        reg_bits = state.arch.registers[reg_name][1] * 8
        value_bits = int(value.size())
        if reg_bits > value_bits:
            value = claripy.ZeroExt(reg_bits - value_bits, value)
        elif reg_bits < value_bits:
            value = value[value_bits - reg_bits - 1 : 0]
        setattr(state.regs, reg_name, value)
    
    def run_symbolic_execution(self):
        """Run symbolic execution."""
        print(f"Starting symbolic execution: {self.binary_path}")
        global symbolic_var_counter, symbolic_variables, _scanf_symbolic_vars
        symbolic_var_counter = 0
        symbolic_variables = {}
        _scanf_symbolic_vars = {}
        self.setup_project()
        if self.project is None:
            print("Project initialization failed")
            return []
        initial_state = self.create_symbolic_state()
        self.install_symbolic_object_strategies(initial_state)
        self.install_single_solution_coverage_strategies(initial_state)
        self.install_concretization_monitor(initial_state)
        simgr = self.project.factory.simulation_manager(initial_state)
        simgr.use_technique(angr.exploration_techniques.Timeout(timeout=self.timeout))
        call_depth_bound = CallDepthBound(self.max_call_depth)
        simgr.use_technique(call_depth_bound)
        loop_seer_installed = False
        loop_seer_error = None
        try:
            simgr.use_technique(
                angr.exploration_techniques.LoopSeer(
                    bound=self.loop_bound,
                    discard_stash="loop_bound",
                )
            )
            loop_seer_installed = True
        except Exception as exc:
            loop_seer_error = str(exc)
            print(f"Loop bound setup failed: {exc}")
        print("Exploring paths...")
        simgr.run()
        print("Symbolic execution finished:")
        print(f"  Deadended: {len(simgr.deadended)}")
        print(f"  Active: {len(simgr.active)}")
        print(f"  Errored: {len(simgr.errored)}")
        timeout_states_raw = list(simgr.stashes.get("timeout", []))
        loop_bound_states_raw = list(simgr.stashes.get("loop_bound", []))
        recursion_bound_states_raw = list(
            simgr.stashes.get("recursion_bound", [])
        )
        all_states_raw = list(simgr.deadended)
        returned_error_states = []
        other_errors = []
        for errored in simgr.errored:
            state = errored.state
            try:
                is_return_sentinel = int(state.addr) == 0
            except Exception:
                is_return_sentinel = False
            if self.snippet_addr is not None and is_return_sentinel:
                returned_error_states.append(state)
            else:
                other_errors.append(errored)
        all_states_raw.extend(returned_error_states)

        # LAZY_SOLVES deliberately keeps infeasible states until a result is
        # demanded.  Prune them before completeness/path-limit accounting;
        # otherwise infeasible loop continuations look like real bound events.
        all_states = self.filter_feasible_states(all_states_raw)
        timeout_states = self.filter_feasible_states(timeout_states_raw)
        (
            loop_bound_states,
            loop_bound_frontier_audit,
        ) = self.audit_loop_bound_states(loop_bound_states_raw)
        recursion_bound_states = self.filter_feasible_states(
            recursion_bound_states_raw
        )
        active_states = self.filter_feasible_states(list(simgr.active))
        other_errors = [item for item in other_errors if self.state_is_feasible(item.state)]

        runtime_model_uses = []
        evidence_states = list(all_states)
        evidence_states.extend(timeout_states)
        evidence_states.extend(loop_bound_states)
        evidence_states.extend(recursion_bound_states)
        evidence_states.extend(active_states)
        evidence_states.extend(item.state for item in other_errors)
        for evidence_state in evidence_states:
            runtime_model_uses.extend(
                evidence_state.globals.get(
                    "symbolicana_external_model_uses",
                    [],
                )
                or []
            )
        if self.fixed_math_runtime:
            from fixed_math_runtime import finalize_audit
            external_model_audit = finalize_audit(self.external_model_audit,
                runtime_model_uses, self.fixed_runtime_certificate)
        else:
            external_model_audit = finalize_runtime_audit(
                self.external_model_audit, runtime_model_uses)

        concretization_path, concretization = self.save_concretization_audit()
        incomplete_reasons = []
        if not loop_seer_installed:
            incomplete_reasons.append("loop_bound_setup_failed")
        if active_states:
            incomplete_reasons.append("active_states_remaining")
        if timeout_states:
            incomplete_reasons.append("timeout")
        if loop_bound_states:
            incomplete_reasons.append("loop_bound_reached")
        if recursion_bound_states:
            incomplete_reasons.append("recursion_depth_bound_reached")
        if other_errors:
            incomplete_reasons.append("execution_error")
        if len(all_states) > self.max_paths:
            incomplete_reasons.append("path_limit_exceeded")
        exploration_finished = not incomplete_reasons
        if concretization["lossy_event_count"]:
            incomplete_reasons.append(
                "lossy_address_concretization"
            )
        if concretization["unverified_event_count"]:
            incomplete_reasons.append(
                "unverified_address_concretization"
            )
        if any(
            event.get("classification") == "incomplete_object_outside_unmodeled"
            for event in concretization["events"]
        ):
            incomplete_reasons.append(
                "outside_object_address_abstraction_present"
            )
        self.exploration_manifest = {
            "schema": "symbolicana.exploration.v4",
            "analysis_script": str(Path(__file__).resolve()),
            "analysis_script_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "binary": os.path.abspath(self.binary_path),
            "timeout_seconds": self.timeout,
            "loop_bound": self.loop_bound,
            "max_paths": self.max_paths,
            "max_call_depth": self.max_call_depth,
            "auto_loop_bound": self.auto_loop_bound,
            "automatic_loop_bound_audit": self.automatic_loop_bound_audit,
            "input_schema": self.input_schema,
            "input_ranges": {
                "integer": (
                    [self.int_min, self.int_max]
                    if self.int_min is not None or self.int_max is not None
                    else "unbounded"
                ),
                "floating_point": (
                    [self.float_min, self.float_max]
                    if self.float_min is not None or self.float_max is not None
                    else "unbounded"
                ),
            },
            "input_domain_profile": self.domain_profile,
            "input_domain_profile_hash": self.domain_profile_hash,
            "input_contract": self.input_contract,
            "externally_restricted_inputs": True,
            "external_model_audit": external_model_audit,
            "entry_state_contract": {
                "mode": "initialized_single_call" if self.initialized_entry else "legacy_symbolic_globals",
                "global_initialization": "ELF_loader_data_bss" if self.initialized_entry else "size_based_symbolization",
                "scope": "one_snippet_invocation",
            },
            "eq_model_eligible": external_model_audit.get("eq_eligible"),
            "loop_seer_installed": loop_seer_installed,
            "loop_seer_error": loop_seer_error,
            "exploration_finished": exploration_finished,
            "complete": not incomplete_reasons,
            "proof_eligible": not incomplete_reasons,
            "artifact_class": (
                "complete_symbolic_enumeration"
                if not incomplete_reasons
                else "incomplete_symbolic_enumeration"
            ),
            "incomplete_reasons": incomplete_reasons,
            "terminating_path_count": len(all_states),
            "deadended_count": len(simgr.deadended),
            "returned_error_count": len(returned_error_states),
            "active_count": len(active_states),
            "timeout_count": len(timeout_states),
            "loop_bound_event_count": len(loop_bound_states),
            "raw_loop_bound_event_count": len(loop_bound_states_raw),
            "loop_bound_frontier_audit": loop_bound_frontier_audit,
            "recursion_depth_bound_event_count": len(
                recursion_bound_states
            ),
            "raw_recursion_depth_bound_event_count": len(
                recursion_bound_states_raw
            ),
            "recursion_depth_bound_audit": {
                "max_call_depth": self.max_call_depth,
                "max_observed_depth": call_depth_bound.max_observed_depth,
                "bound_event_count": call_depth_bound.bound_event_count,
                "feasible_bound_states": len(recursion_bound_states),
            },
            "errored_count": len(other_errors),
            "raw_state_counts": {
                "terminating": len(all_states_raw),
                "active": len(simgr.active),
                "timeout": len(timeout_states_raw),
                "loop_bound": len(loop_bound_states_raw),
                "recursion_bound": len(recursion_bound_states_raw),
            },
            "address_concretization": {
                "audit_path": concretization_path,
                "event_count": concretization["event_count"],
                "classification_counts": concretization[
                    "classification_counts"
                ],
                "lossy_event_count": concretization["lossy_event_count"],
                "lossy_event_ids": concretization["lossy_event_ids"],
                "unverified_event_count": concretization[
                    "unverified_event_count"
                ],
                "unverified_event_ids": concretization[
                    "unverified_event_ids"
                ],
                "lossy_or_unverified_event_count": concretization[
                    "lossy_or_unverified_event_count"
                ],
                "lossy_or_unverified_event_ids": concretization[
                    "lossy_or_unverified_event_ids"
                ],
                "coverage_verified": concretization["coverage_verified"],
            },
            "unconstrained_substitution": {
                "zero_fill_unconstrained_memory": True,
                "zero_fill_unconstrained_registers": True,
                "recorded_as_model_assumption": True,
            },
        }
        
        self.save_exploration_manifest()
        if len(all_states) > self.max_paths:
            print(
                f"Path limit exceeded ({len(all_states)} > {self.max_paths}); "
                "artifacts intentionally not serialized"
            )
            return []
        # The manager stashes duplicate every terminating state. Counts are
        # already persisted, so release those references before serialization.
        for stash_name in list(simgr.stashes):
            simgr.stashes[stash_name] = []
        for state_list in (
            all_states_raw,
            timeout_states_raw,
            loop_bound_states_raw,
            returned_error_states,
            active_states,
            other_errors,
        ):
            state_list.clear()
        self.analyze_states(all_states)
        
        return self.paths_info

    def state_is_feasible(self, state):
        # Pure-floating numerical paths use LAZY_SOLVES specifically because
        # eager FP satisfiability can exceed the analysis budget.  Preserve
        # their path formulas (including an occasional unsat formula); overlap
        # checks in the SMT verification stage safely discard unsat regions.
        if angr.options.LAZY_SOLVES in state.options:
            return True
        try:
            return bool(state.solver.satisfiable())
        except Exception:
            # Retain states when feasibility itself cannot be established; the
            # downstream verifier must conservatively return UNK.
            return True

    def filter_feasible_states(self, states):
        return [state for state in states if self.state_is_feasible(state)]

    def audit_loop_bound_states(self, states):
        """Keep only frontiers that are feasible or not proved infeasible."""
        output_prefix = Path(self.output_prefix)
        audit_path = output_prefix.parent / (
            f"{output_prefix.name}_loop_bound_audit.json"
        )
        queries = []
        query_paths = []
        query_hashes = []
        query_sizes = []
        capture_errors = []
        for index, state in enumerate(states, 1):
            query_path = output_prefix.parent / (
                f"{output_prefix.name}_loop_bound_{index}.smt2"
            )
            try:
                query = self.generate_smt_constraints(state)
                error = ""
            except Exception as exc:
                query = ""
                error = f"{type(exc).__name__}:{exc}"
            query_path.write_text(query, encoding="utf-8")
            queries.append(query)
            query_paths.append(str(query_path))
            query_hashes.append(
                hashlib.sha256(query.encode("utf-8")).hexdigest()
            )
            query_sizes.append(len(query.encode("utf-8")))
            capture_errors.append(error)
        audit = classify_smt_frontiers(
            queries,
            timeout_ms=60_000,
            stop_on_blocking=True,
        )
        blocking_states = []
        for state, record in zip(states, audit.records):
            if record.status != "unsat":
                blocking_states.append(state)
        payload = {
            **audit.as_json(),
            "query_paths": query_paths,
            "query_sha256": query_hashes,
            "query_bytes": query_sizes,
            "capture_errors": capture_errors,
        }
        audit_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return blocking_states, payload
    
    def analyze_states(self, states):
        """Analyze all states."""
        total = len(states)
        for i in range(total):
            state = states[i]
            states[i] = None
            print(f"\nAnalyzing path {i + 1}...")
            
                    
            signature = self.extract_path_signature(state)
            
                     
            smt_constraints = self.generate_smt_constraints(state)
            
                    
            path_info = {
                'index': i + 1,
                'signature': signature,
                'smt_constraints': smt_constraints,
                'semantic_summary': self.extract_semantic_summary(state),
            }
            self.save_path_to_file(path_info)

            retained = {
                "index": path_info["index"],
                "signature": path_info["signature"],
                "artifact_path": (
                    f"{self.output_prefix}_path_{path_info['index']}.txt"
                ),
            }
            if i < self.result_retention_limit:
                retained["semantic_summary"] = path_info["semantic_summary"]
            self.paths_info.append(retained)
            
                  
            print(f"  Symbolic variable values: {signature['variables']}")
            print(f"  Constraint count: {signature['constraints']['count']}")
            if (i + 1) % 32 == 0:
                gc.collect()
        gc.collect()
    
    def extract_path_signature(self, state):
        """Extract multi-dimensional path signature."""
        signature = {}
        
                   
        global symbolic_variables
        variable_values = {}
        for var_name, sym_var in symbolic_variables.items():
            try:
                if angr.options.LAZY_SOLVES in state.options:
                    # Diagnostic samples are not part of the proof artifact.
                    # Avoid forcing an expensive FP solve solely for logging.
                    variable_values[var_name] = None
                elif state.solver.satisfiable():
                    val = state.solver.eval(sym_var, cast_to=int)
                    variable_values[var_name] = val
                else:
                    variable_values[var_name] = None
            except:
                variable_values[var_name] = None
        signature['variables'] = variable_values
        
                     
        constraint_info = {
            'count': len(state.solver.constraints),
            'types': []
        }
        
        for constraint in state.solver.constraints:
            constraint_str = str(constraint)
            constraint_kind = constraint_str.lower()
            if (
                'ule' in constraint_kind or 'ult' in constraint_kind
                or '<=u' in constraint_kind or '<u' in constraint_kind
                or '>=u' in constraint_kind or '>u' in constraint_kind
            ):
                constraint_info['types'].append('unsigned_comparison')
            elif (
                'sle' in constraint_kind or 'slt' in constraint_kind
                or 'sge' in constraint_kind or 'sgt' in constraint_kind
                or '<=s' in constraint_kind or '<s' in constraint_kind
                or '>=s' in constraint_kind or '>s' in constraint_kind
                or 'fp' in constraint_kind
            ):
                constraint_info['types'].append('signed_comparison')
            elif '==' in constraint_str:
                constraint_info['types'].append('equality')
            elif '!=' in constraint_str:
                constraint_info['types'].append('inequality')
            else:
                constraint_info['types'].append('other')
        
        signature['constraints'] = constraint_info
        
                             
        try:
            addr_trace = list(getattr(state.history, 'bbl_addrs', []))
            # Ranking uses the complete dynamic basic-block trace.  Truncating
            # this to a suffix makes trace overlap unstable for long paths.
            signature['execution_trace'] = addr_trace
        except:
            signature['execution_trace'] = []
        
                   
        try:
            memory_payload = {
                "memory_state": self.extract_memory_summary(state),
                "global_state": self.extract_global_summary(state),
            }
            encoded = json.dumps(memory_payload, sort_keys=True, separators=(",", ":"), default=str)
            signature['memory_hash'] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        except:
            signature['memory_hash'] = 0
        
        return signature
    
    def generate_smt_constraints(self, state):
        """Generate SMT constraints."""
        solver = claripy.Solver()
        for constraint in state.solver.constraints:
            solver.add(constraint)
        smt2_text = claripy_solver_to_smt2(solver)
        return smt2_text

    def extract_semantic_summary(self, state):
        """Extract path-level semantic observations for equivalence checking.

        The summary is deliberately serializable and conservative:
        - input_space is represented by the path constraints already emitted.
        - return_value is encoded as a separate SMT equation, preserving a
          symbolic return expression when the architecture exposes one.
        - memory_state records observable memory writes from angr history. Empty
          write sets on both sides mean this layer is vacuously equal.
        """
        summary = {
            "schema": "symbolicana.path_semantics.v3",
            "input_space": {
                "kind": "path_constraints",
                "constraint_count": len(state.solver.constraints),
            },
            "return_value": self.extract_return_summary(state),
            "program_output": self.extract_output_summary(state),
            "memory_state": self.extract_memory_summary(state),
            "local_state": self.extract_local_summary(state),
            "global_state": self.extract_global_summary(state),
        }
        return summary

    def extract_output_summary(self, state):
        raw_events = state.globals.get("symbolicana_output_events")
        if not isinstance(raw_events, list):
            return {
                "available": False,
                "reason": "output_tracking_not_initialized",
                "events": [],
                "segment_count": 0,
                "unresolved": [],
            }
        events = []
        unresolved = []
        for event_index, raw_event in enumerate(raw_events):
            fmt = raw_event.get("format")
            call = str(raw_event.get("call") or "stdio")
            if not isinstance(fmt, str):
                unresolved.append(
                    {
                        "event": event_index,
                        "call": call,
                        "reason": "non_concrete_format_string",
                    }
                )
                events.append(
                    {
                        "call": call,
                        "sink": str(raw_event.get("sink") or "stdio"),
                        "format": None,
                        "format_available": False,
                        "argument_count": len(raw_event.get("args") or ()),
                        "segments": [],
                    }
                )
                continue
            segments, event_unresolved = self.output_segments_for_event(
                state,
                call,
                fmt,
                tuple(raw_event.get("args") or ()),
                event_index,
            )
            unresolved.extend(event_unresolved)
            events.append(
                {
                    "call": call,
                    "sink": str(raw_event.get("sink") or "stdio"),
                    "format": fmt,
                    "format_available": not event_unresolved,
                    "argument_count": len(raw_event.get("args") or ()),
                    "segments": segments,
                }
            )
        return {
            "available": not unresolved,
            "schema": "symbolicana.program_output.v1",
            "hooks": list(state.globals.get("symbolicana_output_hooks", [])),
            "events": events,
            "event_count": len(events),
            "segment_count": sum(len(event["segments"]) for event in events),
            "unresolved": unresolved,
        }

    def output_segments_for_event(self, state, call, fmt, args, event_index):
        segments = []
        unresolved = []
        position = 0
        argument_index = 0
        while position < len(fmt):
            marker = fmt.find("%", position)
            if marker < 0:
                if position < len(fmt):
                    segments.append({"kind": "text", "value": fmt[position:]})
                break
            if marker > position:
                segments.append({"kind": "text", "value": fmt[position:marker]})
            match = OUTPUT_FORMAT_SPECIFIER.match(fmt, marker)
            if match is None:
                unresolved.append(
                    {
                        "event": event_index,
                        "call": call,
                        "reason": "unsupported_format_specifier",
                        "offset": marker,
                    }
                )
                segments.append({"kind": "text", "value": fmt[marker:]})
                break
            specifier = match.group(0)
            position = match.end()
            if specifier == "%%":
                segments.append({"kind": "text", "value": "%"})
                continue
            if "*" in specifier:
                unresolved.append(
                    {
                        "event": event_index,
                        "call": call,
                        "reason": "dynamic_width_or_precision",
                        "specifier": specifier,
                    }
                )
                continue
            if argument_index >= len(args):
                unresolved.append(
                    {
                        "event": event_index,
                        "call": call,
                        "reason": "missing_format_argument",
                        "specifier": specifier,
                    }
                )
                continue
            argument = args[argument_index]
            argument_index += 1
            conversion = specifier[-1]
            if conversion == "s":
                value = read_concrete_c_string(state, argument)
                if value is None:
                    unresolved.append(
                        {
                            "event": event_index,
                            "call": call,
                            "reason": "non_concrete_string_argument",
                            "argument": argument_index - 1,
                        }
                    )
                else:
                    segments.append({"kind": "text", "value": value})
                continue
            if conversion == "c":
                try:
                    symbolic = bool(getattr(argument, "symbolic", False))
                    if not symbolic:
                        value = int(state.solver.eval(argument, cast_to=int))
                        segments.append(
                            {"kind": "text", "value": chr(value & 0xFF)}
                        )
                        continue
                except Exception:
                    pass
            segments.append(
                self.serialize_output_argument(
                    state,
                    argument,
                    event_index,
                    argument_index - 1,
                    specifier,
                )
            )
        return segments, unresolved

    def serialize_output_argument(
        self, state, expr, event_index, argument_index, specifier
    ):
        try:
            bits = int(expr.size())
        except Exception:
            return {
                "kind": "unavailable",
                "specifier": specifier,
                "repr": str(expr),
            }
        variable = f"__output_{event_index}_{argument_index}"
        try:
            encoded_expr = (
                expr.raw_to_bv()
                if hasattr(expr, "raw_to_bv")
                else expr
            )
            smt, _encoded_repr = self.serialize_observable_expression(
                variable,
                bits,
                encoded_expr,
            )
        except Exception:
            smt = None
        return {
            "kind": "formatted_value",
            "available": smt is not None,
            "specifier": specifier,
            "bits": bits,
            "variable": variable,
            "smt": smt,
            "repr": str(expr),
        }

    def save_exploration_manifest(self):
        path = f"{self.output_prefix}_exploration.json"
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(self.exploration_manifest, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(f"Exploration manifest saved to: {path}")

    def extract_return_summary(self, state):
        expr = self.get_return_expr(state)
        if expr is None:
            return {"available": False, "reason": "return_register_not_found"}
        try:
            bits = int(expr.size())
        except Exception:
            bits = int(getattr(state.arch, "bits", 0) or 0)
        ret_name = "__return_value"
        try:
            smt, encoded_repr = self.serialize_observable_expression(
                ret_name,
                bits,
                expr,
            )
            return {
                "available": True,
                "bits": bits,
                "variable": ret_name,
                "smt": smt,
                "repr": encoded_repr,
            }
        except Exception as exc:
            return {
                "available": False,
                "reason": f"return_smt_failed: {exc}",
                "repr": str(expr),
            }

    def get_return_expr(self, state):
        ret_type = (self.snippet_signature or {}).get("return")
        if ret_type in ("double", "float"):
            for reg_name in ("d0", "s0", "xmm0", "q0", "v0"):
                if reg_name not in state.arch.registers:
                    continue
                try:
                    expr = getattr(state.regs, reg_name)
                    target_bits = 64 if ret_type == "double" else 32
                    if int(expr.size()) > target_bits:
                        return expr[target_bits - 1 : 0]
                    return expr
                except Exception:
                    continue
        # ARDiff benchmark snippets are generated as int snippet(...). Prefer
        # the 32-bit return register where the architecture exposes one.
        for reg_name in ("w0", "eax", "r0", "x0", "rax", "v0"):
            if reg_name not in state.arch.registers:
                continue
            try:
                return getattr(state.regs, reg_name)
            except Exception:
                continue
        try:
            offset = getattr(state.arch, "ret_offset", None)
            if offset is not None:
                size = max(1, int(getattr(state.arch, "bits", 0) or 0) // 8)
                return state.registers.load(offset, size=size)
        except Exception:
            pass
        return None

    def collect_global_write_ranges(self):
        ranges = []
        if self.project is None:
            return ranges
        try:
            sections = list(self.project.loader.main_object.sections)
        except Exception:
            sections = []
        for section in sections:
            name = str(getattr(section, "name", "") or "").lower()
            if not any(marker in name for marker in ("data", "bss", "common")):
                continue
            start = int(getattr(section, "vaddr", 0) or 0)
            size = int(getattr(section, "memsize", getattr(section, "filesize", 0)) or 0)
            if start and size:
                ranges.append((start, start + size, name))
        return ranges

    def collect_symbolic_objects(self):
        """Collect non-toolchain writable objects with trustworthy ELF bounds."""
        candidates = {}
        try:
            symbols = list(self.project.loader.main_object.symbols)
        except Exception:
            symbols = []
        for symbol in symbols:
            name = str(getattr(symbol, "name", "") or "")
            size = int(getattr(symbol, "size", 0) or 0)
            address = int(getattr(symbol, "rebased_addr", 0) or 0)
            symbol_type = str(getattr(symbol, "type", "") or "").upper()
            if (
                not name
                or name.startswith("_")
                or size <= 0
                or size > 4096
                or not address
                or "OBJECT" not in symbol_type
            ):
                continue
            if not any(
                start <= address and address + size <= end
                for start, end, _section_name in self.global_write_ranges
            ):
                continue
            candidate = {
                "name": name,
                "start": address,
                "size": size,
                "end": address + size,
            }
            previous = candidates.get((address, size))
            if previous is None or (
                len(candidate["name"]) < len(previous["name"])
            ):
                candidates[(address, size)] = candidate

        # If aliases have the same start but different extents, the object
        # boundary is ambiguous and the fallback must not guess.
        by_start = {}
        for candidate in candidates.values():
            by_start.setdefault(candidate["start"], []).append(candidate)
        objects = []
        for start in sorted(by_start):
            aliases = by_start[start]
            if len({item["size"] for item in aliases}) != 1:
                continue
            objects.append(min(aliases, key=lambda item: item["name"]))
        return objects

    def extract_memory_summary(self, state):
        writes = []
        try:
            actions = list(state.history.actions)
        except Exception:
            actions = []
        for action in actions:
            if getattr(action, "type", None) != "mem" or getattr(action, "action", None) != "write":
                continue
            addr = self.safe_action_value(getattr(action, "addr", None), state)
            if not self.is_observable_heap_or_global_address(addr, state):
                continue
            data = self.safe_action_value(getattr(action, "data", None), state)
            size = self.safe_action_value(getattr(action, "size", None), state)
            writes.append({"addr": addr, "data": data, "size": size})
        return {
            "available": True,
            "writes": writes,
            "write_count": len(writes),
        }

    def extract_local_summary(self, state):
        """Record writes to the snippet stack frame using stack-relative offsets.

        The ARDiff benchmarks put the interesting computation inside snippet().
        Local variables live on the stack at -O0, so comparing stack-relative
        writes gives us a concrete observation of local state at function exit
        without depending on absolute stack addresses.
        """
        initial_sp = state.globals.get("snippet_initial_sp")
        if not isinstance(initial_sp, int):
            return {
                "available": False,
                "reason": "snippet_initial_sp_unavailable",
                "writes": [],
                "write_count": 0,
            }
        writes = []
        try:
            actions = list(state.history.actions)
        except Exception:
            actions = []
        for action in actions:
            if getattr(action, "type", None) != "mem" or getattr(action, "action", None) != "write":
                continue
            addr = self.safe_action_value(getattr(action, "addr", None), state)
            if not isinstance(addr, int):
                continue
            rel = addr - initial_sp
            # Keep the current snippet frame and a small caller-spill band. Stack
            # grows downward on our benchmark target; the positive band catches
            # ABI/linkage writes near SP without swallowing unrelated memory.
            if rel < -0x10000 or rel > 0x100:
                continue
            data = self.safe_action_value(getattr(action, "data", None), state)
            size = self.safe_action_value(getattr(action, "size", None), state)
            writes.append({"offset": rel, "data": data, "size": size})
        return {
            "available": True,
            "base": "snippet_initial_sp",
            "writes": writes,
            "write_count": len(writes),
        }

    def extract_global_summary(self, state):
        """Snapshot the final symbolic value of every concretely written global cell.

        Keys are section-relative so image-base relocation and consistent section
        shifts do not affect cross-binary comparison.  Write order is deliberately
        excluded: it remains available in ``memory_state`` only for diagnosis.
        """
        cells = {}
        unresolved = []
        try:
            actions = list(state.history.actions)
        except Exception:
            actions = []
        for action in actions:
            if getattr(action, "type", None) != "mem" or getattr(action, "action", None) != "write":
                continue
            addr = self.safe_action_value(getattr(action, "addr", None), state)
            size_bits = self.safe_action_value(getattr(action, "size", None), state)
            if not isinstance(addr, int):
                unresolved.append({"address": addr, "reason": "symbolic_write_address"})
                continue
            region = next(
                ((start, end, name) for start, end, name in self.global_write_ranges if start <= addr < end),
                None,
            )
            if region is None:
                continue
            if not isinstance(size_bits, int) or size_bits <= 0:
                unresolved.append({"address": addr, "reason": "unknown_write_size"})
                continue
            start, end, name = region
            size_bytes = max(1, (size_bits + 7) // 8)
            if addr + size_bytes > end:
                unresolved.append({"address": addr, "reason": "write_crosses_region"})
                continue
            canonical = f"{name}:{addr - start:#x}:{size_bytes}"
            try:
                expr = state.memory.load(addr, size_bytes, endness=state.arch.memory_endness)
                cells[canonical] = self.serialize_observable_expr(state, expr, canonical)
            except Exception as exc:
                unresolved.append({"address": addr, "reason": f"load_failed:{exc}"})
        return {
            "available": not unresolved,
            "address_model": "section_relative_written_cells",
            "regions": cells,
            "unresolved": unresolved,
        }

    def serialize_observable_expr(self, state, expr, canonical):
        bits = int(expr.size())
        safe_name = re.sub(r"[^A-Za-z0-9_]", "_", canonical)
        variable = f"__global_{safe_name}"
        smt, encoded_repr = self.serialize_observable_expression(
            variable,
            bits,
            expr,
        )
        return {
            "available": True,
            "bits": bits,
            "variable": variable,
            "smt": smt,
            "repr": encoded_repr,
        }

    def serialize_observable_expression(self, variable, bits, expr):
        """Serialize one observable expression with a bounded structural cache.

        Leaves must be the same Claripy symbol objects for a cache hit.  This
        avoids treating equal-looking text or a hash collision as semantic
        evidence.  A miss runs the ordinary solver-to-SMT conversion.
        """
        key = (str(variable), int(bits), int(expr.hash()))
        bucket = self._observable_serialization_cache.get(key)
        if bucket:
            for candidate_expr, smt, encoded_repr in bucket:
                try:
                    matched = expr.structurally_match(candidate_expr)
                except Exception:
                    matched = False
                if matched:
                    return smt, encoded_repr
        else:
            bucket = []
            self._observable_serialization_cache[key] = bucket

        solver = claripy.Solver()
        summary_var = claripy.BVS(str(variable), int(bits))
        solver.add(summary_var == expr)
        smt = claripy_solver_to_smt2(solver)
        encoded_repr = str(expr)
        entry_chars = len(smt) + len(encoded_repr)
        if (
            entry_chars
            > self._observable_serialization_cache_entry_char_limit
        ):
            if not bucket:
                self._observable_serialization_cache.pop(key, None)
            return smt, encoded_repr
        bucket.append((expr, smt, encoded_repr))
        self._observable_serialization_cache_expressions += 1
        self._observable_serialization_cache_chars += entry_chars
        while (
            self._observable_serialization_cache_expressions
            > self._observable_serialization_cache_limit
            or self._observable_serialization_cache_chars
            > self._observable_serialization_cache_char_limit
        ):
            oldest_key = next(iter(self._observable_serialization_cache))
            evicted = self._observable_serialization_cache.pop(oldest_key)
            self._observable_serialization_cache_expressions -= len(evicted)
            self._observable_serialization_cache_chars -= sum(
                len(candidate_smt) + len(candidate_repr)
                for _candidate_expr, candidate_smt, candidate_repr in evicted
            )
        return smt, encoded_repr

    def is_observable_heap_or_global_address(self, addr, state):
        if not isinstance(addr, int):
            return True
        for start, end, _name in self.global_write_ranges:
            if start <= addr < end:
                return True
        try:
            sp = state.solver.eval(state.regs.sp, cast_to=int)
            if abs(addr - sp) < 0x100000:
                return False
        except Exception:
            pass
        return False

    def safe_action_value(self, value, state):
        if value is None:
            return None
        if isinstance(value, (int, bool)):
            return int(value)
        ast = getattr(value, "ast", value)
        if isinstance(ast, (int, bool)):
            return int(ast)
        try:
            if hasattr(ast, "symbolic") and not ast.symbolic:
                return state.solver.eval(ast, cast_to=int)
        except Exception:
            pass
        return str(ast)
    

    
    def save_path_to_file(self, path_info):
        """Save path info to file."""
        filename = f"{self.output_prefix}_path_{path_info['index']}.txt"
        with open(filename, "w", encoding='utf-8') as f:
            f.write(path_info['smt_constraints'])
            f.write("\n; Path signature:\n")
            f.write(f"; Symbolic variable values: {path_info['signature']['variables']}\n")
            f.write(f"; Constraint info: {path_info['signature']['constraints']}\n")
            f.write(f"; Execution trace: {path_info['signature']['execution_trace']}\n")
            f.write(f"; Memory hash: {path_info['signature']['memory_hash']}\n")
            f.write("; Semantic summary JSON: ")
            f.write(json.dumps(path_info['semantic_summary'], ensure_ascii=True, sort_keys=True))
            f.write("\n")
        print(f"  Saved to: {filename}")

class BenchmarkAnalyzer:
    """Batch analyzer for benchmarks."""
    
    def __init__(self, benchmark_dir, timeout=120):
        self.benchmark_dir = benchmark_dir
        self.timeout = timeout
        self.results = {}
    
    def find_binary_files(self):
        """Find binary files in benchmark directory."""
        pattern = os.path.join(self.benchmark_dir, "*_O[0123]")
        binary_files = glob.glob(pattern)
        binary_files = [f for f in binary_files if not f.endswith('.c')]
        return sorted(binary_files)
    
    def analyze_all_binaries(self):
        """Analyze all binaries."""
        binary_files = self.find_binary_files()
        if not binary_files:
            print(f"No binaries found in {self.benchmark_dir}")
            return
        print(f"Found {len(binary_files)} binaries:")
        for binary in binary_files:
            print(f"  {binary}")
        for binary_path in binary_files:
            print(f"\n{'='*60}")
            print(f"Analyzing: {binary_path}")
            print(f"{'='*60}")
            basename = os.path.basename(binary_path)
            output_prefix = basename
            try:
                analyzer = BenchmarkSymbolicExecution(binary_path, output_prefix, self.timeout)
                results = analyzer.run_symbolic_execution()
                self.results[basename] = results
                print(f"Finished {basename}: {len(results)} paths")
            except Exception as e:
                print(f"Error analyzing {basename}: {e}")
                self.results[basename] = []
        return self.results
    
    def generate_summary_report(self):
        """Generate analysis summary report."""
        report_file = os.path.join(self.benchmark_dir, "improved_symbolic_execution_summary.txt")
        with open(report_file, "w", encoding='utf-8') as f:
            f.write("Improved symbolic execution batch analysis summary\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Analysis directory: {self.benchmark_dir}\n")
            f.write(f"Binaries analyzed: {len(self.results)}\n")
            f.write("Symbolization: function params + array elements\n\n")
            for binary_name, paths in self.results.items():
                f.write(f"Binary: {binary_name}\n")
                f.write(f"  Paths: {len(paths)}\n")
                f.write(f"  Output files: {binary_name}_path_*.txt\n\n")
            f.write("Next: run semantic_equivalence_analyzer.py for equivalence analysis\n")
        print(f"Summary saved to: {report_file}")

def main():
    """Main entry."""
    import sys
    import argparse
    parser = argparse.ArgumentParser(description='Improved symbolic execution analysis tool')
    parser.add_argument('--benchmark', help='Benchmark directory for batch analysis')
    parser.add_argument('--binary', help='Single binary path')
    parser.add_argument('--timeout', type=int, default=120, help='Symbolic execution timeout (seconds)')
    parser.add_argument('--output-prefix', help='Output file prefix')
    parser.add_argument('--signature', help='Snippet signature, e.g. double(double,int)')
    parser.add_argument('--loop-bound', type=int, default=30, help='Per-loop iteration bound (default: 30)')
    parser.add_argument('--max-paths', type=int, default=128, help='Maximum terminating paths to serialize')
    parser.add_argument('--fixed-math-runtime', action='store_true')
    parser.add_argument('--initialized-entry', action='store_true')
    parser.add_argument('--model-query-timeout-ms', type=int, default=2000)
    parser.add_argument(
        '--max-call-depth',
        type=int,
        default=30,
        help='Maximum call-stack depth before a state is marked incomplete',
    )
    parser.add_argument('--int-min', type=int, default=None)
    parser.add_argument('--int-max', type=int, default=None)
    parser.add_argument('--float-min', type=float, default=None)
    parser.add_argument('--float-max', type=float, default=None)
    parser.add_argument(
        '--domain-profile-json',
        type=str,
        default=None,
        help='Path to the shared input-domain profile JSON.',
    )
    parser.add_argument(
        '--input-schema-json',
        default=None,
        help='Typed external input schema as JSON.',
    )
    parser.add_argument(
        '--auto-loop-bound',
        action='store_true',
        help='Raise the SE loop bound from a proved counted-loop certificate.',
    )
    parser.add_argument(
        '--max-auto-loop-bound',
        type=int,
        default=4096,
    )
    args = parser.parse_args()
    domain_profile = load_profile(
        Path(args.domain_profile_json)
        if args.domain_profile_json
        else None
    )
    input_schema = json.loads(args.input_schema_json) if args.input_schema_json else []
    if args.benchmark:
        print(f"Starting batch analysis: {args.benchmark}")
        analyzer = BenchmarkAnalyzer(args.benchmark, args.timeout)
        analyzer.analyze_all_binaries()
        analyzer.generate_summary_report()
    elif args.binary:
        print(f"Analyzing single binary: {args.binary}")
        analyzer = BenchmarkSymbolicExecution(
            args.binary,
            args.output_prefix,
            args.timeout,
            args.signature,
            args.loop_bound,
            args.max_paths,
            args.int_min,
            args.int_max,
            args.float_min,
            args.float_max,
            domain_profile,
            input_schema,
            auto_loop_bound=args.auto_loop_bound,
            max_auto_loop_bound=args.max_auto_loop_bound,
            max_call_depth=args.max_call_depth,
            fixed_math_runtime=args.fixed_math_runtime,
            initialized_entry=args.initialized_entry,
            model_query_timeout_ms=args.model_query_timeout_ms,
        )
        results = analyzer.run_symbolic_execution()
        print(f"Done. Found {len(results)} paths")
    else:
        parser.print_help()

if __name__ == "__main__":
    main() 
