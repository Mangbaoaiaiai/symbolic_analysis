                      
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
from claripy.backends.backend_z3 import claripy_solver_to_smt2
from angr.sim_type import (
    SimTypeChar,
    SimTypeDouble,
    SimTypeFunction,
    SimTypeInt,
    SimTypeLongLong,
    SimTypePointer,
)
import logging

        
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

       
symbolic_var_counter = 0
symbolic_variables = {}

# For binaries without s000 (e.g. ardiff): hook scanf and register symbolic vars here
_scanf_symbolic_vars = {}


class SqrtSymbolicHook(angr.SimProcedure):
    """IEEE-754 square root model for libm calls in numerical benchmarks."""

    def run(self, value):
        if getattr(value, "sort", None) == claripy.FSORT_DOUBLE:
            fp_value = value
        elif int(value.size()) == 64:
            fp_value = value.raw_to_fp()
        else:
            fp_value = claripy.ZeroExt(64 - int(value.size()), value).raw_to_fp()
        return claripy.fpSqrt(claripy.RM.RM_NearestTiesEven, fp_value)


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
    """Hook scanf to inject symbolic 32-bit values (e.g. for ardiff snippet(a,b))."""
    def run(self, fmt_ptr, *args):
        global _scanf_symbolic_vars, symbolic_variables
        # Treat each additional arg as a pointer to int; store one symbolic 32-bit per pointer
        for i, ptr in enumerate(args):
            if ptr is None:
                continue
            name = f"scanf_{len(_scanf_symbolic_vars)}"
            sym = claripy.BVS(name, 32)
            _scanf_symbolic_vars[name] = sym
            symbolic_variables[name] = sym
            self.state.memory.store(ptr, sym, endness=self.state.arch.memory_endness)
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
    ):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        self.snippet_addr = None
        self.snippet_signature = parse_snippet_signature(snippet_signature)
        self.loop_bound = loop_bound
        self.max_paths = max_paths
        self.int_min = int_min
        self.int_max = int_max
        self.float_min = float_min
        self.float_max = float_max
        self.global_write_ranges = []
        self.exploration_manifest = {}
        self.output_hook_names = []
        
                
        if output_prefix is None:
            binary_name = os.path.basename(binary_path)
            self.output_prefix = binary_name
        else:
            self.output_prefix = output_prefix
    
    def setup_project(self):
        """Set up angr project."""
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        print(f"Loading binary: {self.binary_path}")
        for name in ("sqrt", "sqrtf", "__sqrt_finite"):
            try:
                if self.project.loader.find_symbol(name):
                    self.project.hook_symbol(
                        name,
                        SqrtSymbolicHook(prototype="double sqrt(double)"),
                    )
                    print(f"Hooked {name} with IEEE-754 symbolic model")
            except (IndexError, AttributeError, TypeError):
                continue
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
        
                
        self.find_target_functions()
    
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
                        self.project.hook_symbol(sym_name, ScanfSymbolicHook())
                        print(f"Hooked {sym_name} for symbolic inputs")
                        break
                except (IndexError, AttributeError, TypeError):
                    continue
    
    def create_symbolic_state(self):
        """Create initial state with symbolic variables."""
        global symbolic_var_counter, symbolic_variables
        # On macOS/ARM64, unconstrained x30 (link register) causes "over 256 solutions; skipping"
        # and 0 paths. Use zero-fill for unconstrained regs/mem so exit states are not skipped.
        if self.snippet_addr is not None:
            arg_types = (self.snippet_signature or {}).get("args") or ["int", "int"]
            arg_values = []
            for idx, arg_type in enumerate(arg_types):
                name = f"arg_{idx}"
                if arg_type in ("double", "float"):
                    sort = claripy.FSORT_DOUBLE if arg_type == "double" else claripy.FSORT_FLOAT
                    sym = claripy.FPS(name, sort)
                else:
                    sym = claripy.BVS(name, 32)
                symbolic_variables[name] = sym
                arg_values.append((arg_type, sym))
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
            for arg_type, sym in arg_values:
                if arg_type in ("double", "float"):
                    sort = claripy.FSORT_DOUBLE if arg_type == "double" else claripy.FSORT_FLOAT
                    if self.float_min is not None:
                        initial_state.solver.add(
                            claripy.fpGEQ(sym, claripy.FPV(float(self.float_min), sort))
                        )
                    if self.float_max is not None:
                        initial_state.solver.add(
                            claripy.fpLEQ(sym, claripy.FPV(float(self.float_max), sort))
                        )
                else:
                    if self.int_min is not None:
                        initial_state.solver.add(
                            claripy.SGE(sym, claripy.BVV(self.int_min, sym.size()))
                        )
                    if self.int_max is not None:
                        initial_state.solver.add(
                            claripy.SLE(sym, claripy.BVV(self.int_max, sym.size()))
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
        self.symbolize_global_arrays(initial_state, max_elements=16)
        # When s000_addr is None (ardiff etc.), remaining symbolic vars are
        # added by ScanfSymbolicHook.
        initial_state.globals["symbolicana_output_events"] = []
        initial_state.globals["symbolicana_output_hooks"] = list(self.output_hook_names)
        return initial_state

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
        simgr = self.project.factory.simulation_manager(initial_state)
        simgr.use_technique(angr.exploration_techniques.Timeout(timeout=self.timeout))
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
        loop_bound_states = self.filter_feasible_states(loop_bound_states_raw)
        active_states = self.filter_feasible_states(list(simgr.active))
        other_errors = [item for item in other_errors if self.state_is_feasible(item.state)]

        incomplete_reasons = []
        if not loop_seer_installed:
            incomplete_reasons.append("loop_bound_setup_failed")
        if active_states:
            incomplete_reasons.append("active_states_remaining")
        if timeout_states:
            incomplete_reasons.append("timeout")
        if loop_bound_states:
            incomplete_reasons.append("loop_bound_reached")
        if other_errors:
            incomplete_reasons.append("execution_error")
        if len(all_states) > self.max_paths:
            incomplete_reasons.append("path_limit_exceeded")
        self.exploration_manifest = {
            "schema": "symbolicana.exploration.v2",
            "binary": os.path.abspath(self.binary_path),
            "timeout_seconds": self.timeout,
            "loop_bound": self.loop_bound,
            "max_paths": self.max_paths,
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
            "loop_seer_installed": loop_seer_installed,
            "loop_seer_error": loop_seer_error,
            "complete": not incomplete_reasons,
            "incomplete_reasons": incomplete_reasons,
            "terminating_path_count": len(all_states),
            "deadended_count": len(simgr.deadended),
            "returned_error_count": len(returned_error_states),
            "active_count": len(active_states),
            "timeout_count": len(timeout_states),
            "loop_bound_event_count": len(loop_bound_states),
            "errored_count": len(other_errors),
            "raw_state_counts": {
                "terminating": len(all_states_raw),
                "active": len(simgr.active),
                "timeout": len(timeout_states_raw),
                "loop_bound": len(loop_bound_states_raw),
            },
        }
        
        self.save_exploration_manifest()
        if len(all_states) > self.max_paths:
            print(
                f"Path limit exceeded ({len(all_states)} > {self.max_paths}); "
                "artifacts intentionally not serialized"
            )
            return []
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
    
    def analyze_states(self, states):
        """Analyze all states."""
        for i, state in enumerate(states):
            print(f"\nAnalyzing path {i + 1}...")
            
                    
            signature = self.extract_path_signature(state)
            
                     
            smt_constraints = self.generate_smt_constraints(state)
            
                    
            path_info = {
                'index': i + 1,
                'signature': signature,
                'smt_constraints': smt_constraints,
                'semantic_summary': self.extract_semantic_summary(state),
                'state': state
            }
            
            self.paths_info.append(path_info)
            
                   
            self.save_path_to_file(path_info)
            
                  
            print(f"  Symbolic variable values: {signature['variables']}")
            print(f"  Constraint count: {signature['constraints']['count']}")
    
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
            solver = claripy.Solver()
            summary_var = claripy.BVS(variable, bits)
            solver.add(summary_var == expr)
            smt = claripy_solver_to_smt2(solver)
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
            solver = claripy.Solver()
            ret_var = claripy.BVS(ret_name, bits)
            solver.add(ret_var == expr)
            return {
                "available": True,
                "bits": bits,
                "variable": ret_name,
                "smt": claripy_solver_to_smt2(solver),
                "repr": str(expr),
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
        solver = claripy.Solver()
        summary_var = claripy.BVS(variable, bits)
        solver.add(summary_var == expr)
        return {
            "available": True,
            "bits": bits,
            "variable": variable,
            "smt": claripy_solver_to_smt2(solver),
            "repr": str(expr),
        }

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
        ast = getattr(value, "ast", value)
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
    parser.add_argument('--int-min', type=int, default=None)
    parser.add_argument('--int-max', type=int, default=None)
    parser.add_argument('--float-min', type=float, default=None)
    parser.add_argument('--float-max', type=float, default=None)
    args = parser.parse_args()
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
        )
        results = analyzer.run_symbolic_execution()
        print(f"Done. Found {len(results)} paths")
    else:
        parser.print_help()

if __name__ == "__main__":
    main() 
