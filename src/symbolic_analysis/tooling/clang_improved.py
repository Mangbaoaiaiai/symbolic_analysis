                      
"""
Improved symbolic execution script: obtain path signature info.

Fixes angr API compatibility and improves path identification.
"""

import angr
import claripy
import re
from claripy.backends.backend_z3 import claripy_solver_to_smt2
import logging

        
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

       
scanf_counter = 0
scanf_variables = {}

class ScanfSymProc(angr.SimProcedure):
    """Improved scanf symbolization."""
    
    def run(self, fmt_ptr, value_ptr):
        global scanf_counter, scanf_variables
        
                    
        sym_var = claripy.BVS(f'scanf_{scanf_counter}', 32)
        
                  
        scanf_variables[f'scanf_{scanf_counter}'] = sym_var
        scanf_counter += 1
        
                   
        self.state.memory.store(
            value_ptr,
            sym_var,
            endness=self.state.arch.memory_endness
        )
        
        return claripy.BVV(1, self.state.arch.bits)

class ImprovedPathAnalyzer:
    """Improved path analyzer."""
    
    def __init__(self, binary_path, timeout=120):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
    
    def setup_project(self):
        """Set up angr project."""
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        
        scanf_symbols = ['scanf', '__isoc99_scanf', '__isoc23_scanf', '__scanf_chk']
        for symbol in scanf_symbols:
            if self.project.loader.find_symbol(symbol):
                self.project.hook_symbol(symbol, ScanfSymProc())
                print(f"Hooked symbol: {symbol}")
    
    def extract_path_signature(self, state):
        """Extract multi-dimensional path signature."""
        signature = {}
        
                   
        global scanf_variables
        variable_values = {}
        for var_name, sym_var in scanf_variables.items():
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
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            signature['output'] = output
        except:
            signature['output'] = ""
        
                         
        try:
                           
            memory_hash = hash(str(state.solver.constraints)[:100])
            signature['memory_hash'] = memory_hash
        except:
            signature['memory_hash'] = 0
        
        return signature
    
    def run_symbolic_execution(self):
        """Run symbolic execution."""
        print(f"Starting symbolic execution: {self.binary_path}")
        
        self.setup_project()
        
        if self.project is None:
            print("Project initialization failed")
            return []
        
                
        initial_state = self.project.factory.entry_state()
        
                 
        simgr = self.project.factory.simulation_manager(initial_state)
        
                
        print("Exploring paths...")
        simgr.run(timeout=self.timeout)
        
        print("Symbolic execution finished:")
        print(f"  Deadended paths: {len(simgr.deadended)}")
        print(f"  Active paths: {len(simgr.active)}")
        print(f"  Errored paths: {len(simgr.errored)}")
        
                  
        self.analyze_deadended_states(simgr.deadended)
        
        return self.paths_info
    
    def analyze_deadended_states(self, deadended_states):
        """Analyze all deadended states."""
        for i, state in enumerate(deadended_states):
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
            
                  
            print(f"  Variable values: {signature['variables']}")
            print(f"  Constraint count: {signature['constraints']['count']}")
            print(f"  Program output: {signature['output']}")
    
    def generate_smt_constraints(self, state):
        """Generate SMT constraints."""
        try:
            solver = claripy.Solver()
            for constraint in state.solver.constraints:
                solver.add(constraint)
            smt2_text = claripy_solver_to_smt2(solver)
            return smt2_text
        except Exception as e:
            print(f"Failed to generate SMT constraints: {e}")
            return ""
    
    def save_path_to_file(self, path_info):
        """Save path info to file."""
        filename = f"{self.binary_path.split('/')[-1]}_path_{path_info['index']}.txt"
        
        with open(filename, "w", encoding='utf-8') as f:
            f.write(path_info['smt_constraints'])
            f.write("\n; Path signature:\n")
            f.write(f"; Variable values: {path_info['signature']['variables']}\n")
            f.write(f"; Constraint info: {path_info['signature']['constraints']}\n")
            f.write(f"; Memory hash: {path_info['signature']['memory_hash']}\n")
            f.write(f"; Program output:\n")
            f.write(path_info['signature']['output'])
        
        print(f"  Saved to: {filename}")

def compare_path_collections_improved(analyzer1_results, analyzer2_results):
    """Improved path collection comparison."""
    print("\nStarting improved path comparison...")
    
    matches = {
        'exact_variable_matches': [],
        'exact_output_matches': [],
        'constraint_structure_matches': [],
        'no_matches': []
    }
    
    for path1 in analyzer1_results:
        best_match = None
        best_match_type = None
        best_score = float('inf')
        
        for path2 in analyzer2_results:
                          
            if path1['signature']['variables'] == path2['signature']['variables']:
                matches['exact_variable_matches'].append((path1['index'], path2['index']))
                best_match = path2['index']
                best_match_type = 'exact_variable'
                break
            
                         
            if (path1['signature']['output'] == path2['signature']['output'] and 
                path1['signature']['output'] != ""):
                if best_match_type != 'exact_variable':
                    matches['exact_output_matches'].append((path1['index'], path2['index']))
                    best_match = path2['index']
                    best_match_type = 'exact_output'
            
                          
            constraint_score = abs(
                path1['signature']['constraints']['count'] - 
                path2['signature']['constraints']['count']
            )
            
            if constraint_score < best_score and best_match_type is None:
                best_score = constraint_score
                best_match = path2['index']
                best_match_type = 'constraint_structure'
        
        if best_match_type == 'constraint_structure':
            matches['constraint_structure_matches'].append((path1['index'], best_match, best_score))
        elif best_match_type is None:
            matches['no_matches'].append(path1['index'])
    
            
    print("Path match results:")
    print(f"  Exact variable matches: {len(matches['exact_variable_matches'])} pairs")
    print(f"  Exact output matches: {len(matches['exact_output_matches'])} pairs")
    print(f"  Constraint structure matches: {len(matches['constraint_structure_matches'])} pairs")
    print(f"  Unmatched paths: {len(matches['no_matches'])}")
    
    return matches

def main():
    """Main entry and example usage."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python clang_improved.py <binary_path>")
        print("Example: python clang_improved.py ./test1_clang")
        return
    
    binary_path = sys.argv[1]
    
    analyzer = ImprovedPathAnalyzer(binary_path)
    results = analyzer.run_symbolic_execution()
    
    print(f"\nAnalysis complete. Found {len(results)} paths")

if __name__ == "__main__":
    main() 