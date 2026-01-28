                      
"""
Enhanced path equivalence analyzer with a three-step verification pipeline:
1. Semantic equivalence of logical constraints
2. Consistency of initial array states
3. Consistency of final array states

The analyzer combines constraint equivalence and array-state comparisons
to reason about full path equivalence between two programs.
"""

import re
import z3
from z3 import *
import glob
import time
import datetime
import json
from itertools import combinations
from collections import defaultdict

class ArrayStateComparator:
    """Helper for comparing encoded array states extracted from path files."""
    
    def __init__(self):
        pass
        
    def parse_array_state(self, content):
        """Parse initial and final array states from a path file."""
        array_initial = {}
        array_final = {}
        
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            
                                        
            if line.startswith('; 数组初始值:') or line.startswith('; Initial array state:'):
                try:
                    array_str = line.split(':', 1)[1].strip()
                    array_initial = eval(array_str)                                
                except:
                    pass
                    
                                      
            elif line.startswith('; 数组最终值:') or line.startswith('; Final array state:'):
                try:
                    array_str = line.split(':', 1)[1].strip()
                    array_final = eval(array_str)                                
                except:
                    pass
                    
        return array_initial, array_final
    
    def compare_array_states(self, state1, state2):
        """Compare two array-state dictionaries for structural and value equality."""
        if not state1 and not state2:
            return True, "both_empty"
            
        if not state1 or not state2:
            return False, "one_empty"
            
                             
        if set(state1.keys()) != set(state2.keys()):
            return False, f"different_arrays: {set(state1.keys())} vs {set(state2.keys())}"
            
                                             
        for array_name in state1.keys():
            arr1 = state1[array_name]
            arr2 = state2[array_name]
            
            if set(arr1.keys()) != set(arr2.keys()):
                return False, f"different_indices_in_{array_name}: {set(arr1.keys())} vs {set(arr2.keys())}"
                
            for idx in arr1.keys():
                if arr1[idx] != arr2[idx]:
                    return False, f"different_value_in_{array_name}[{idx}]: {arr1[idx]} vs {arr2[idx]}"
                    
        return True, "identical"

class EnhancedConstraintChecker:
    """Enhanced checker for logical constraint equivalence plus array-state checks."""
    
    def __init__(self, timeout=30000):
        self.timeout = timeout
        self.constraint_time = 0.0
        self.constraint_call_count = 0
        self.array_time = 0.0
        self.array_call_count = 0
        self.array_comparator = ArrayStateComparator()
        
    def normalize_variable_names(self, formula, var_mapping):
        """Normalize variable names so that the two formulas can be compared."""
        for old_name, new_name in var_mapping.items():
            formula = re.sub(rf'\b{old_name}\b', new_name, formula)
        return formula
    
    def extract_path_info(self, file_path):
        """Extract full path information (constraints + array states) from a file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
                                                          
        constraint_lines = [line for line in content.splitlines() if not line.strip().startswith(';')]
        constraint_content = '\n'.join(constraint_lines)
        
                                       
        variables = {}
        var_pattern = r'\(declare-fun\s+(\w+)\s+\(\)\s+\(_\s+BitVec\s+(\d+)\)\)'
        for match in re.finditer(var_pattern, constraint_content):
            var_name, bit_width = match.groups()
            variables[var_name] = int(bit_width)
        
                                                 
        constraints = []
        constraint_pattern = r'\(assert\s+(.*?)\)(?=\s*(?:\(assert|\(check-sat|$))'
        for match in re.finditer(constraint_pattern, constraint_content, re.DOTALL):
            constraint = match.group(1).strip()
            constraints.append(constraint)
        
                                      
        array_initial, array_final = self.array_comparator.parse_array_state(content)
        
        return {
            'variables': variables,
            'constraints': constraints,
            'array_initial': array_initial,
            'array_final': array_final
        }
    
    def create_variable_mapping(self, vars1, vars2):
        """Create a mapping that aligns scanf-style variables between two paths."""
        mapping = {}
        
                                                         
        scanf_vars1 = [(name, self.extract_scanf_index(name)) for name in vars1.keys() if 'scanf' in name]
        scanf_vars2 = [(name, self.extract_scanf_index(name)) for name in vars2.keys() if 'scanf' in name]
        
                                             
        scanf_vars1.sort(key=lambda x: x[1])
        scanf_vars2.sort(key=lambda x: x[1])
        
                           
        for (name1, idx1), (name2, idx2) in zip(scanf_vars1, scanf_vars2):
            mapping[name1] = name2
        
        return mapping
    
    def extract_scanf_index(self, var_name):
        """Extract the numeric index embedded in a scanf_* style variable name."""
        match = re.search(r'scanf_(\d+)', var_name)
        return int(match.group(1)) if match else 0
    
    def check_three_step_equivalence(self, path1_info, path2_info):
        """Run the three-step equivalence check: constraints → initial arrays → final arrays."""
        total_start_time = time.time()
        
                                                             
        var_mapping = self.create_variable_mapping(
            path1_info['variables'], path2_info['variables']
        )
        
        result = {
            'overall_equivalent': False,
            'constraint_equivalent': False,
            'array_initial_same': False,
            'array_final_same': False,
            'constraint_time': 0.0,
            'array_initial_time': 0.0,
            'array_final_time': 0.0,
            'total_time': 0.0,
            'details': {},
            'variable_mapping': var_mapping
        }
        
                                                
        print("    Step 1: checking constraint equivalence...")
        constraint_start = time.time()
        constraint_result, constraint_details = self.check_constraint_equivalence(
            path1_info['constraints'], path2_info['constraints'],
            path1_info['variables'], path2_info['variables'],
            var_mapping
        )
        constraint_time = time.time() - constraint_start
        result['constraint_time'] = constraint_time
        result['details']['constraint'] = constraint_details
        
        if constraint_result == "equivalent":
            result['constraint_equivalent'] = True
            print(f"      ✓ Constraints are equivalent (time: {constraint_time:.3f}s)")
            
                                                  
            print("    Step 2: checking initial array states...")
            array_initial_start = time.time()
            initial_same, initial_details = self.array_comparator.compare_array_states(
                path1_info['array_initial'], path2_info['array_initial']
            )
            array_initial_time = time.time() - array_initial_start
            result['array_initial_time'] = array_initial_time
            result['details']['array_initial'] = initial_details
            
            if initial_same:
                result['array_initial_same'] = True
                print(f"      ✓ Initial array states match (time: {array_initial_time:.3f}s)")
                
                                                    
            print("    Step 3: checking final array states...")
                array_final_start = time.time()
                final_same, final_details = self.array_comparator.compare_array_states(
                    path1_info['array_final'], path2_info['array_final']
                )
                array_final_time = time.time() - array_final_start
                result['array_final_time'] = array_final_time
                result['details']['array_final'] = final_details
                
                if final_same:
                    result['array_final_same'] = True
                    result['overall_equivalent'] = True
                    print(f"      ✓ Final array states match (time: {array_final_time:.3f}s)")
                    print("      🎉 All three checks passed; paths are equivalent.")
                else:
                    print(f"      ❌ Final array states differ: {final_details}")
            else:
                print(f"      ❌ Initial array states differ: {initial_details}")
        else:
            print(f"      ❌ Constraints are not equivalent: {constraint_result}")
        
        result['total_time'] = time.time() - total_start_time
        
                                            
        self.constraint_time += constraint_time
        self.constraint_call_count += 1
        if result['constraint_equivalent']:
            self.array_time += result['array_initial_time'] + result['array_final_time']
            self.array_call_count += 2
        
        return result
    
    def check_constraint_equivalence(self, constraints1, constraints2, vars1, vars2, var_mapping):
        """Check whether two sets of constraints are logically equivalent."""
        start_time = time.time()
        
        solver = Solver()
        solver.set("timeout", self.timeout)
        
        try:
                                               
            smt_formula1 = self.build_smt_formula(vars1, constraints1)
            smt_formula2 = self.build_smt_formula(vars2, constraints2, var_mapping)
            
                                     
            F1 = parse_smt2_string(smt_formula1)
            F2 = parse_smt2_string(smt_formula2)
            
                                                      
            formula1 = And(*F1) if len(F1) > 1 else F1[0] if F1 else BoolVal(True)
            formula2 = And(*F2) if len(F2) > 1 else F2[0] if F2 else BoolVal(True)
            
                                                             
            equivalence_check = Or(
                And(formula1, Not(formula2)),
                And(Not(formula1), formula2)
            )
            
            solver.add(equivalence_check)
            result = solver.check()
            
            solve_time = time.time() - start_time
            
            if result == unsat:
                return "equivalent", {"solve_time": solve_time}
            elif result == sat:
                model = solver.model()
                return "not_equivalent", {"model": str(model), "solve_time": solve_time}
            else:
                return "unknown", {"solve_time": solve_time}
                
        except Exception as e:
            solve_time = time.time() - start_time
            return "error", {"error": str(e), "solve_time": solve_time}
    
    def build_smt_formula(self, variables, constraints, var_mapping=None):
        """Build a complete SMT-LIB formula from variable declarations and constraints."""
                                            
        if var_mapping:
            mapped_variables = {}
            mapped_constraints = []
            
            for old_name, bit_width in variables.items():
                new_name = var_mapping.get(old_name, old_name)
                mapped_variables[new_name] = bit_width
            
            for constraint in constraints:
                mapped_constraint = constraint
                for old_name, new_name in var_mapping.items():
                    mapped_constraint = re.sub(rf'\b{old_name}\b', new_name, mapped_constraint)
                mapped_constraints.append(mapped_constraint)
            
            variables = mapped_variables
            constraints = mapped_constraints
        
                                   
        formula_parts = ["(set-logic QF_BV)"]
        
                                   
        for var_name, bit_width in variables.items():
            formula_parts.append(f"(declare-fun {var_name} () (_ BitVec {bit_width}))")
        
                         
        for constraint in constraints:
            formula_parts.append(f"(assert {constraint})")
        
        formula_parts.append("(check-sat)")
        
        return '\n'.join(formula_parts)

class EnhancedPathAnalyzer:
    """High-level driver that orchestrates enhanced path equivalence analysis."""
    
    def __init__(self):
        self.checker = EnhancedConstraintChecker()
        self.analysis_start_time = None
        self.analysis_end_time = None
        self.detailed_timing = []
        self.symbolic_execution_time = 0.0           
        
    def set_symbolic_execution_time(self, se_time):
        """Set the symbolic execution time (from an external run) for reporting."""
        self.symbolic_execution_time = se_time
        
    def analyze_program_equivalence(self, file_prefix1, file_prefix2):
        """Analyze full program equivalence based on path files from two binaries."""
        self.analysis_start_time = time.time()
        print(f"开始程序等价性分析: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
                                 
        files1 = sorted(glob.glob(f"{file_prefix1}*.txt"))
        files2 = sorted(glob.glob(f"{file_prefix2}*.txt"))
        
        print(f"程序1路径数: {len(files1)}")
        print(f"程序2路径数: {len(files2)}")
        
                                         
        load_start = time.time()
        paths1 = []
        paths2 = []
        
        print("Loading path information for program 1...")
        for file_path in files1:
            try:
                path_info = self.checker.extract_path_info(file_path)
                path_info['file'] = file_path
                paths1.append(path_info)
            except Exception as e:
                print(f"  ❌ Error while processing file {file_path}: {e}")
        
        print("Loading path information for program 2...")
        for file_path in files2:
            try:
                path_info = self.checker.extract_path_info(file_path)
                path_info['file'] = file_path
                paths2.append(path_info)
            except Exception as e:
                print(f"  ❌ Error while processing file {file_path}: {e}")
        
        load_time = time.time() - load_start
        print(f"Finished loading files in {load_time:.3f} seconds")
        print(f"Successfully loaded paths: {len(paths1)} vs {len(paths2)}")
        
                                                 
        comparison_start = time.time()
        results = self.find_equivalent_paths_three_step(paths1, paths2)
        comparison_time = time.time() - comparison_start
        
        self.analysis_end_time = time.time()
        total_time = self.analysis_end_time - self.analysis_start_time
        
                                  
        results['timing_info'] = {
            'total_time': total_time,
            'load_time': load_time,
            'comparison_time': comparison_time,
            'symbolic_execution_time': self.symbolic_execution_time,
            'constraint_total_time': self.checker.constraint_time,
            'constraint_call_count': self.checker.constraint_call_count,
            'constraint_avg_time': self.checker.constraint_time / max(1, self.checker.constraint_call_count),
            'array_total_time': self.checker.array_time,
            'array_call_count': self.checker.array_call_count,
            'array_avg_time': self.checker.array_time / max(1, self.checker.array_call_count),
            'detailed_timing': self.detailed_timing,
            'start_time': datetime.datetime.fromtimestamp(self.analysis_start_time).strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': datetime.datetime.fromtimestamp(self.analysis_end_time).strftime('%Y-%m-%d %H:%M:%S')
        }
        
                              
        print(f"\n⏱️  Timing summary:")
        print(f"  Symbolic execution (external): {self.symbolic_execution_time:.3f} seconds")
        print(f"  File loading: {load_time:.3f} seconds")
        print(f"  Path comparison: {comparison_time:.3f} seconds")
        print(f"    - SMT constraint checking: {self.checker.constraint_time:.3f} seconds ({self.checker.constraint_call_count} calls)")
        print(f"    - Array state comparison: {self.checker.array_time:.3f} seconds ({self.checker.array_call_count} calls)")
        print(f"  Total analysis time: {total_time:.3f} seconds")
        
        return results
    
    def find_equivalent_paths_three_step(self, paths1, paths2):
        """Use the three-step procedure to identify equivalent path pairs."""
        results = {
            'equivalent_pairs': [],
            'partial_equivalent_pairs': [],                                                 
            'non_equivalent_pairs': [],
            'error_pairs': [],
            'unmatched_paths1': list(range(len(paths1))),
            'unmatched_paths2': list(range(len(paths2))),
            'program_equivalent': False
        }
        
        total_comparisons = len(paths1) * len(paths2)
        current_comparison = 0
        comparison_start_time = time.time()
        
        print(f"\nStarting three-step equivalence checking ({total_comparisons} comparisons):")
        
        for i, path1 in enumerate(paths1):
            path1_matched = False
            
            for j, path2 in enumerate(paths2):
                if j in [pair['path2_index'] for pair in results['equivalent_pairs']]:
                    continue            
                    
                current_comparison += 1
                pair_start_time = time.time()
                
                                          
                if current_comparison > 1:
                    elapsed = time.time() - comparison_start_time
                    avg_time = elapsed / (current_comparison - 1)
                    remaining = total_comparisons - current_comparison
                    estimated_remaining = avg_time * remaining
                    print(f"  Comparing {i+1}-{j+1} ({current_comparison}/{total_comparisons}, {current_comparison/total_comparisons*100:.1f}%) "
                          f"- estimated remaining: {estimated_remaining:.1f}s")
                else:
                    print(f"  Comparing paths {i+1} vs {j+1}")
                
                                                                    
                equivalence_result = self.checker.check_three_step_equivalence(path1, path2)
                
                pair_time = time.time() - pair_start_time
                
                        
                timing_detail = {
                    'path1_index': i,
                    'path2_index': j,
                    'total_time': pair_time,
                    'constraint_time': equivalence_result['constraint_time'],
                    'array_initial_time': equivalence_result['array_initial_time'],
                    'array_final_time': equivalence_result['array_final_time'],
                    'result': 'equivalent' if equivalence_result['overall_equivalent'] else 'not_equivalent'
                }
                self.detailed_timing.append(timing_detail)
                
                                              
                pair_info = {
                    'path1_index': i,
                    'path2_index': j,
                    'path1_file': path1['file'],
                    'path2_file': path2['file'],
                    'equivalence_result': equivalence_result,
                    'comparison_time': pair_time
                }
                
                if equivalence_result['overall_equivalent']:
                                      
                    results['equivalent_pairs'].append(pair_info)
                    if i in results['unmatched_paths1']:
                        results['unmatched_paths1'].remove(i)
                    if j in results['unmatched_paths2']:
                        results['unmatched_paths2'].remove(j)
                    
                    print(f"    🎉 Fully equivalent! Time: {pair_time:.3f}s")
                    path1_matched = True
                    break           
                    
                elif (equivalence_result['constraint_equivalent'] or 
                      equivalence_result['array_initial_same'] or 
                      equivalence_result['array_final_same']):
                          
                    results['partial_equivalent_pairs'].append(pair_info)
                    print(f"    ⚠️  Partially equivalent "
                          f"(constraint:{equivalence_result['constraint_equivalent']}, "
                          f"initial:{equivalence_result['array_initial_same']}, "
                          f"final:{equivalence_result['array_final_same']}) "
                          f"time: {pair_time:.3f}s")
                    
                else:
                         
                    results['non_equivalent_pairs'].append(pair_info)
                    
            if not path1_matched:
                print(f"    ❌ No equivalent path found for path {i+1}")
        
                                                  
        results['program_equivalent'] = (len(results['unmatched_paths1']) == 0 and 
                                       len(results['unmatched_paths2']) == 0)
        
        print(f"\n📊 Analysis summary:")
        print(f"  Fully equivalent path pairs: {len(results['equivalent_pairs'])}")
        print(f"  Partially equivalent path pairs: {len(results['partial_equivalent_pairs'])}")
        print(f"  Unmatched paths in program 1: {len(results['unmatched_paths1'])}")
        print(f"  Unmatched paths in program 2: {len(results['unmatched_paths2'])}")
        print(f"  Overall program equivalence: {'✅ equivalent' if results['program_equivalent'] else '❌ NOT equivalent'}")
        
        return results
    
    def generate_comprehensive_report(self, results, output_file="enhanced_equivalence_report.txt"):
        """Generate a comprehensive human-readable report for the analysis."""
        with open(output_file, "w", encoding='utf-8') as f:
            f.write("Enhanced Program Equivalence Analysis Report\n")
            f.write("=" * 60 + "\n\n")
            
                                
            f.write("📋 Overall conclusion:\n")
            f.write("-" * 30 + "\n")
            equivalence_status = "✅ equivalent" if results['program_equivalent'] else "❌ NOT equivalent"
            f.write(f"Program equivalence: {equivalence_status}\n\n")
            
                               
            if 'timing_info' in results:
                timing = results['timing_info']
                f.write("⏱️  Timing statistics:\n")
                f.write("-" * 30 + "\n")
                f.write(f"Analysis start time: {timing['start_time']}\n")
                f.write(f"Analysis end time:   {timing['end_time']}\n")
                f.write(f"Total analysis time: {timing['total_time']:.3f} seconds\n")
                f.write(f"  - Symbolic execution (external): {timing['symbolic_execution_time']:.3f} seconds\n")
                f.write(f"  - File loading:                  {timing['load_time']:.3f} seconds\n")
                f.write(f"  - Path comparison:              {timing['comparison_time']:.3f} seconds\n")
                f.write(f"    * SMT constraint checking:    {timing['constraint_total_time']:.3f} seconds ({timing['constraint_call_count']} calls)\n")
                f.write(f"    * Array state comparison:     {timing['array_total_time']:.3f} seconds ({timing['array_call_count']} calls)\n")
                f.write(f"Average SMT solve time:           {timing['constraint_avg_time']:.3f} seconds\n")
                f.write(f"Average array-compare time:       {timing['array_avg_time']:.3f} seconds\n\n")
            
                                 
            f.write("📊 Analysis statistics:\n")
            f.write("-" * 30 + "\n")
            f.write(f"Fully equivalent path pairs:   {len(results['equivalent_pairs'])}\n")
            f.write(f"Partially equivalent path pairs: {len(results['partial_equivalent_pairs'])}\n")
            f.write(f"Non-equivalent path pairs:     {len(results['non_equivalent_pairs'])}\n")
            f.write(f"Analysis errors:               {len(results['error_pairs'])}\n")
            f.write(f"Unmatched paths in program 1:  {len(results['unmatched_paths1'])}\n")
            f.write(f"Unmatched paths in program 2:  {len(results['unmatched_paths2'])}\n\n")
            
                                                    
            if results['equivalent_pairs']:
                f.write("✅ Fully equivalent path pairs:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['equivalent_pairs'], 1):
                    f.write(f"{idx}. Path {pair['path1_index']+1} <-> Path {pair['path2_index']+1}\n")
                    f.write(f"   File 1: {pair['path1_file']}\n")
                    f.write(f"   File 2: {pair['path2_file']}\n")
                    f.write(f"   Comparison time: {pair['comparison_time']:.3f} seconds\n")
                    
                    equiv_result = pair['equivalence_result']
                    f.write(f"   Timing breakdown:\n")
                    f.write(f"     - Constraint checking:     {equiv_result['constraint_time']:.3f} seconds\n")
                    f.write(f"     - Initial array comparison:{equiv_result['array_initial_time']:.3f} seconds\n")
                    f.write(f"     - Final array comparison:  {equiv_result['array_final_time']:.3f} seconds\n")
                    f.write(f"   Variable mapping: {equiv_result['variable_mapping']}\n\n")
            
                                                        
            if results['partial_equivalent_pairs']:
                f.write("⚠️  Partially equivalent path pairs:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['partial_equivalent_pairs'], 1):
                    f.write(f"{idx}. Path {pair['path1_index']+1} vs Path {pair['path2_index']+1}\n")
                    f.write(f"   File 1: {pair['path1_file']}\n")
                    f.write(f"   File 2: {pair['path2_file']}\n")
                    
                    equiv_result = pair['equivalence_result']
                    f.write(f"   Equivalence breakdown:\n")
                    f.write(f"     - Constraints equivalent:        {'✅' if equiv_result['constraint_equivalent'] else '❌'}\n")
                    f.write(f"     - Initial array states match:    {'✅' if equiv_result['array_initial_same'] else '❌'}\n")
                    f.write(f"     - Final array states match:      {'✅' if equiv_result['array_final_same'] else '❌'}\n")
                    f.write(f"   Comparison time: {pair['comparison_time']:.3f} seconds\n\n")
            
                             
            if results['unmatched_paths1']:
                f.write("❌ Unmatched paths in program 1:\n")
                f.write("-" * 30 + "\n")
                for idx in results['unmatched_paths1']:
                    f.write(f"  Path {idx+1}\n")
                f.write("\n")
            
            if results['unmatched_paths2']:
                f.write("❌ Unmatched paths in program 2:\n")
                f.write("-" * 30 + "\n")
                for idx in results['unmatched_paths2']:
                    f.write(f"  Path {idx+1}\n")
                f.write("\n")
            
        print(f"📄 Detailed report written to: {output_file}")

def main():
    """CLI entry point for the enhanced path-equivalence analyzer."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Enhanced program equivalence analyzer with a three-step verification pipeline'
    )
    parser.add_argument('prefix1', help='Prefix of path files for the first program (e.g., paths_prog1/path_)')
    parser.add_argument('prefix2', help='Prefix of path files for the second program (e.g., paths_prog2/path_)')
    parser.add_argument('--output', default='enhanced_equivalence_report.txt', help='Report output file path')
    parser.add_argument('--timeout', type=int, default=30000, help='Z3 solver timeout in milliseconds')
    parser.add_argument('--se-time', type=float, default=0.0, help='Symbolic execution time (seconds), for stats only')
    
    args = parser.parse_args()
    
    analyzer = EnhancedPathAnalyzer()
    analyzer.checker.timeout = args.timeout
    analyzer.set_symbolic_execution_time(args.se_time)
    
    print("🚀 Starting enhanced program equivalence analysis...")
    print("=" * 60)
    print("Three-step verification pipeline:")
    print("  1️⃣  Constraint semantic equivalence (Z3 solver)")
    print("  2️⃣  Initial array-state consistency")
    print("  3️⃣  Final array-state consistency")
    print("=" * 60)
    
    results = analyzer.analyze_program_equivalence(args.prefix1, args.prefix2)
    
    analyzer.generate_comprehensive_report(results, args.output)
    
    print("\n" + "=" * 60)
    print("🎯 Final analysis result:")
    print(f"  Program equivalence: {'✅ equivalent' if results['program_equivalent'] else '❌ NOT equivalent'}")
    print(f"  Fully equivalent path pairs:   {len(results['equivalent_pairs'])}")
    print(f"  Partially equivalent path pairs: {len(results['partial_equivalent_pairs'])}")
    print(f"  Total analyzed path pairs:     {len(results['equivalent_pairs']) + len(results['partial_equivalent_pairs']) + len(results['non_equivalent_pairs'])}")
    
    if 'timing_info' in results:
        timing = results['timing_info']
        print(f"\n⏱️  Performance statistics:")
        print(f"  Total time:        {timing['total_time']:.3f} seconds")
        print(f"  Symbolic execution:{timing['symbolic_execution_time']:.3f} seconds")
        print(f"  SMT solving:       {timing['constraint_total_time']:.3f} seconds ({timing['constraint_call_count']} calls)")
        print(f"  Array comparison:  {timing['array_total_time']:.3f} seconds ({timing['array_call_count']} calls)")
    
    print("=" * 60)
    print("✅ Analysis complete. Please check the output report file for full details.")

if __name__ == "__main__":
    main() 