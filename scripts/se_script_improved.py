                      
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
from claripy.backends.backend_z3 import claripy_solver_to_smt2
import logging

        
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

       
symbolic_var_counter = 0
symbolic_variables = {}

class BenchmarkSymbolicExecution:
    """Symbolic execution tailored for benchmark programs."""
    
    def __init__(self, binary_path, output_prefix=None, timeout=120):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        
                
        if output_prefix is None:
            binary_name = os.path.basename(binary_path)
            self.output_prefix = binary_name
        else:
            self.output_prefix = output_prefix
    
    def setup_project(self):
        """Set up angr project."""
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        print(f"Loading binary: {self.binary_path}")
        
                
        self.find_target_functions()
    
    def find_target_functions(self):
        """Find target functions."""
        s000_symbol = self.project.loader.find_symbol('s000')
        if s000_symbol:
            print(f"Found s000 at: 0x{s000_symbol.rebased_addr:x}")
            self.s000_addr = s000_symbol.rebased_addr
        else:
            print("s000 not found; will analyze entire main")
            self.s000_addr = None
    
    def create_symbolic_state(self):
        """Create initial state with symbolic variables."""
        initial_state = self.project.factory.entry_state()
        
                           
        if self.s000_addr:
                             
            count_var = claripy.BVS('count_param', 32)
                                    
            initial_state.solver.add(count_var >= 0)
            initial_state.solver.add(count_var <= 10)           
            
            global symbolic_var_counter, symbolic_variables
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
        
        return initial_state
    
    def run_symbolic_execution(self):
        """Run symbolic execution."""
        print(f"Starting symbolic execution: {self.binary_path}")
        global symbolic_var_counter, symbolic_variables
        symbolic_var_counter = 0
        symbolic_variables = {}
        self.setup_project()
        if self.project is None:
            print("Project initialization failed")
            return []
        initial_state = self.create_symbolic_state()
        simgr = self.project.factory.simulation_manager(initial_state)
        print("Exploring paths...")
        simgr.run(timeout=self.timeout)
        print("Symbolic execution finished:")
        print(f"  Deadended: {len(simgr.deadended)}")
        print(f"  Active: {len(simgr.active)}")
        print(f"  Errored: {len(simgr.errored)}")
        all_states = simgr.deadended + simgr.active
        if simgr.errored:
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
            addr_trace = getattr(state.history, 'bbl_addrs', [])
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
    args = parser.parse_args()
    if args.benchmark:
        print(f"Starting batch analysis: {args.benchmark}")
        analyzer = BenchmarkAnalyzer(args.benchmark, args.timeout)
        analyzer.analyze_all_binaries()
        analyzer.generate_summary_report()
    elif args.binary:
        print(f"Analyzing single binary: {args.binary}")
        analyzer = BenchmarkSymbolicExecution(args.binary, args.output_prefix, args.timeout)
        results = analyzer.run_symbolic_execution()
        print(f"Done. Found {len(results)} paths")
    else:
        parser.print_help()

if __name__ == "__main__":
    main() 