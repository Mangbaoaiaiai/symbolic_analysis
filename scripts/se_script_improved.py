                      
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
from claripy.backends.backend_z3 import claripy_solver_to_smt2
import logging

        
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

       
symbolic_var_counter = 0
symbolic_variables = {}

# For binaries without s000 (e.g. ardiff): hook scanf and register symbolic vars here
_scanf_symbolic_vars = {}


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

class BenchmarkSymbolicExecution:
    """Symbolic execution tailored for benchmark programs."""
    
    def __init__(self, binary_path, output_prefix=None, timeout=120, snippet_signature=None):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        self.snippet_addr = None
        self.snippet_signature = parse_snippet_signature(snippet_signature)
        self.global_write_ranges = []
        
                
        if output_prefix is None:
            binary_name = os.path.basename(binary_path)
            self.output_prefix = binary_name
        else:
            self.output_prefix = output_prefix
    
    def setup_project(self):
        """Set up angr project."""
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        print(f"Loading binary: {self.binary_path}")
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
                },
            )
            self.install_call_arguments(initial_state, arg_values)
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
                }
            )
        else:
            initial_state = self.project.factory.entry_state()
            initial_state.options.add(angr.options.TRACK_MEMORY_ACTIONS)
            initial_state.options.add(angr.options.TRACK_REGISTER_ACTIONS)
        
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
        # When s000_addr is None (ardiff etc.), symbolic vars are added by ScanfSymbolicHook
        
        return initial_state

    def install_call_arguments(self, state, arg_values):
        int_reg_index = 0
        fp_reg_index = 0
        for arg_type, sym in arg_values:
            if arg_type == "double":
                reg_name = f"d{fp_reg_index}"
                fp_reg_index += 1
                if reg_name in state.arch.registers:
                    setattr(state.regs, reg_name, sym.raw_to_bv())
                continue
            if arg_type == "float":
                reg_name = f"s{fp_reg_index}"
                fp_reg_index += 1
                if reg_name in state.arch.registers:
                    setattr(state.regs, reg_name, sym.raw_to_bv())
                continue
            reg_name = f"x{int_reg_index}" if f"x{int_reg_index}" in state.arch.registers else f"r{int_reg_index}"
            int_reg_index += 1
            if reg_name in state.arch.registers:
                setattr(state.regs, reg_name, claripy.ZeroExt(max(0, state.arch.bits - 32), sym))
    
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
        print("Exploring paths...")
        simgr.run(timeout=self.timeout, n=500)
        print("Symbolic execution finished:")
        print(f"  Deadended: {len(simgr.deadended)}")
        print(f"  Active: {len(simgr.active)}")
        print(f"  Errored: {len(simgr.errored)}")
        all_states = simgr.deadended + simgr.active
        if simgr.errored and not all_states:
            print(f"  Handling errored states: {len(simgr.errored)}")
            for errored in simgr.errored:
                all_states.append(errored.state)
        
        self.analyze_states(all_states)
        
        return self.paths_info
    
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
                if state.solver.satisfiable():
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
            if 'ULE' in constraint_str or 'ULT' in constraint_str:
                constraint_info['types'].append('unsigned_comparison')
            elif 'SLE' in constraint_str or 'SLT' in constraint_str:
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
            signature['execution_trace'] = addr_trace[-10:] if len(addr_trace) > 10 else addr_trace
        except:
            signature['execution_trace'] = []
        
                   
        try:
            memory_hash = hash(str(state.solver.constraints)[:200])
            signature['memory_hash'] = memory_hash
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
            "schema": "symbolicana.path_semantics.v1",
            "input_space": {
                "kind": "path_constraints",
                "constraint_count": len(state.solver.constraints),
            },
            "return_value": self.extract_return_summary(state),
            "memory_state": self.extract_memory_summary(state),
            "local_state": self.extract_local_summary(state),
            "global_state": self.extract_global_summary(state),
        }
        return summary

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
            for constraint in state.solver.constraints:
                solver.add(constraint)
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
            for reg_name in ("d0", "s0", "q0", "v0"):
                if reg_name not in state.arch.registers:
                    continue
                try:
                    return getattr(state.regs, reg_name)
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
            if not any(marker in name for marker in ("data", "bss", "got", "common")):
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
        # The current benchmark binaries mostly use stack locals. Keep this as a
        # stable extension point for future watched global ranges.
        return {
            "available": True,
            "regions": {},
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
    args = parser.parse_args()
    if args.benchmark:
        print(f"Starting batch analysis: {args.benchmark}")
        analyzer = BenchmarkAnalyzer(args.benchmark, args.timeout)
        analyzer.analyze_all_binaries()
        analyzer.generate_summary_report()
    elif args.binary:
        print(f"Analyzing single binary: {args.binary}")
        analyzer = BenchmarkSymbolicExecution(args.binary, args.output_prefix, args.timeout, args.signature)
        results = analyzer.run_symbolic_execution()
        print(f"Done. Found {len(results)} paths")
    else:
        parser.print_help()

if __name__ == "__main__":
    main() 
