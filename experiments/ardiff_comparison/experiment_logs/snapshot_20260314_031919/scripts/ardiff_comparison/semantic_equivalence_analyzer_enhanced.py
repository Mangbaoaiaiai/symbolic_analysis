                      
"""
Enhanced program equivalence analyzer: constraint + output combined judgment.
1. Path constraints equivalent and program output same → equivalent
2. Path constraints not equivalent but output same → suspicious (constraint)
3. Path constraints equivalent but output not same → suspicious (output)
4. Path constraints not equivalent and output not same → not equivalent
"""

import re
import z3
from z3 import *
import glob
import time
import datetime
import json
import sys
import os
from itertools import combinations
from collections import defaultdict

# Add src to sys.path to import feature extraction
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

try:
    from symbolic_analysis.analysis.path_constraint_features import extract_features, normalize_features
except ImportError:
    print("Warning: Could not import path_constraint_features. Similarity ranking will be disabled.")
    extract_features = None
    normalize_features = None

def cosine_similarity(v1, v2):
    """Compute cosine similarity between two vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(x * y for x, y in zip(v1, v2))
    norm1 = sum(x * x for x in v1) ** 0.5
    norm2 = sum(y * y for y in v2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

class ArrayStateComparator:
    """Array state comparator."""
    
    def __init__(self):
        pass
        
    def parse_array_state(self, content):
        """Parse array state from path file content."""
        array_initial = {}
        array_final = {}
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('; 数组初始值:') or line.startswith('; Initial array') or line.startswith('; Array initial'):
                try:
                    array_str = line.split(':', 1)[1].strip()
                    array_initial = eval(array_str)                                
                except:
                    pass
                    
                     
            elif line.startswith('; 数组最终值:') or line.startswith('; Final array') or line.startswith('; Array final'):
                try:
                    array_str = line.split(':', 1)[1].strip()
                    array_final = eval(array_str)                                
                except:
                    pass
                    
        return array_initial, array_final
    
    def compare_array_states(self, state1, state2):
        """Compare whether two array states are the same."""
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
    """Enhanced constraint equivalence checker."""
    
    def __init__(self, timeout=30000):
        self.timeout = timeout
        self.constraint_time = 0.0
        self.constraint_call_count = 0
        self.array_time = 0.0
        self.array_call_count = 0
        self.array_comparator = ArrayStateComparator()
        
    def normalize_variable_names(self, formula, var_mapping):
        """Normalize variable names so two formulas can be compared."""
        for old_name, new_name in var_mapping.items():
            formula = re.sub(rf'\b{old_name}\b', new_name, formula)
        return formula
    
    def extract_path_info(self, file_path):
        """Extract full path info from file: constraints + array state + program output."""
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
        
                
        program_output = ""
        for line in content.split('\n'):
            if line.strip().startswith('; 程序输出:') or line.strip().startswith('; Program output:'):
                try:
                    output_line = line.split(':', 1)[1].strip()
                    if output_line:
                        program_output = output_line
                except:
                    pass
                break
        
        return {
            'variables': variables,
            'constraints': constraints,
            'array_initial': array_initial,
            'array_final': array_final,
            'program_output': program_output
        }
    
    def create_variable_mapping(self, vars1, vars2):
        """Create variable mapping between the two variable sets."""
        mapping = {}
        
                      
        scanf_vars1 = [(name, self.extract_scanf_index(name)) for name in vars1.keys() if 'scanf' in name]
        scanf_vars2 = [(name, self.extract_scanf_index(name)) for name in vars2.keys() if 'scanf' in name]
        
               
        scanf_vars1.sort(key=lambda x: x[1])
        scanf_vars2.sort(key=lambda x: x[1])
        
              
        for (name1, idx1), (name2, idx2) in zip(scanf_vars1, scanf_vars2):
            mapping[name1] = name2
        
        return mapping
    
    def extract_scanf_index(self, var_name):
        """Extract index from scanf variable name."""
        match = re.search(r'scanf_(\d+)', var_name)
        return int(match.group(1)) if match else 0
    
    def check_constraint_and_output_equivalence(self, path1_info, path2_info):
        """Check combined constraint and output equivalence."""
        total_start_time = time.time()
        
                
        var_mapping = self.create_variable_mapping(
            path1_info['variables'], path2_info['variables']
        )
        
        result = {
            'constraint_equivalent': False,
            'output_equivalent': False,
            'overall_equivalent': False,
            'constraint_time': 0.0,
            'array_initial_same': False,
            'array_final_same': False,
            'array_initial_time': 0.0,
            'array_final_time': 0.0,
            'total_time': 0.0,
            'details': {},
            'variable_mapping': var_mapping,
            'path1_output': path1_info['program_output'],
            'path2_output': path2_info['program_output']
        }
        
                     
        print("    Step 1: Check constraint equivalence...")
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
            print(f"      ✓ Constraints equivalent (time: {constraint_time:.3f}s)")
        else:
            print(f"      ❌ Constraints not equivalent: {constraint_result} (time: {constraint_time:.3f}s)")
        print("    Step 2: Check program output equivalence...")
        output_start = time.time()
        output1 = path1_info['program_output'].strip()
        output2 = path2_info['program_output'].strip()
        
        output_equivalent = (output1 == output2)
        result['output_equivalent'] = output_equivalent
        output_time = time.time() - output_start
        result['details']['output'] = {
            'path1_output': output1,
            'path2_output': output2,
            'equivalent': output_equivalent,
            'check_time': output_time
        }
        
        if output_equivalent:
            print(f"      ✓ Program output same: '{output1}' (time: {output_time:.3f}s)")
        else:
            print(f"      ❌ Program output different: '{output1}' vs '{output2}' (time: {output_time:.3f}s)")
        if result['constraint_equivalent']:
            print("    Step 3: Check array initial state...")
            array_initial_start = time.time()
            initial_same, initial_details = self.array_comparator.compare_array_states(
                path1_info['array_initial'], path2_info['array_initial']
            )
            array_initial_time = time.time() - array_initial_start
            result['array_initial_time'] = array_initial_time
            result['details']['array_initial'] = initial_details
            
            if initial_same:
                result['array_initial_same'] = True
                print(f"      ✓ Array initial state same (time: {array_initial_time:.3f}s)")
                print("    Step 4: Check array final state...")
                array_final_start = time.time()
                final_same, final_details = self.array_comparator.compare_array_states(
                    path1_info['array_final'], path2_info['array_final']
                )
                array_final_time = time.time() - array_final_start
                result['array_final_time'] = array_final_time
                result['details']['array_final'] = final_details
                
                if final_same:
                    result['array_final_same'] = True
                    print(f"      ✓ Array final state same (time: {array_final_time:.3f}s)")
                else:
                    print(f"      ❌ Array final state different: {final_details}")
            else:
                print(f"      ❌ Array initial state different: {initial_details}")
        
                 
        result['overall_equivalent'] = (result['constraint_equivalent'] and 
                                      result['output_equivalent'] and
                                      result['array_initial_same'] and
                                      result['array_final_same'])
        
        result['total_time'] = time.time() - total_start_time
        
                
        self.constraint_time += constraint_time
        self.constraint_call_count += 1
        if result['constraint_equivalent']:
            self.array_time += result['array_initial_time'] + result['array_final_time']
            self.array_call_count += 2
        
        return result
    
    def check_constraint_equivalence(self, constraints1, constraints2, vars1, vars2, var_mapping):
        """Check whether two constraint sets are logically equivalent."""
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
        """Build full SMT formula."""
                
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
    """Enhanced path analyzer: constraint + output combined judgment."""
    
    def __init__(self):
        self.checker = EnhancedConstraintChecker()
        self.analysis_start_time = None
        self.analysis_end_time = None
        self.detailed_timing = []
        self.symbolic_execution_time = 0.0           
        
    def set_symbolic_execution_time(self, se_time):
        """Set symbolic execution time (passed from outside)."""
        self.symbolic_execution_time = se_time
        
    def analyze_program_equivalence(self, file_prefix1, file_prefix2):
        """Analyze full equivalence of two programs."""
        self.analysis_start_time = time.time()
        print(f"Starting program equivalence analysis: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
                  
        files1 = sorted(glob.glob(f"{file_prefix1}*.txt"))
        files2 = sorted(glob.glob(f"{file_prefix2}*.txt"))
        
        print(f"Program 1 paths: {len(files1)}")
        print(f"Program 2 paths: {len(files2)}")
        
                
        load_start = time.time()
        paths1 = []
        paths2 = []
        
        print("Loading program 1 path info...")
        for file_path in files1:
            try:
                path_info = self.checker.extract_path_info(file_path)
                path_info['file'] = file_path
                paths1.append(path_info)
            except Exception as e:
                print(f"  ❌ Error processing file {file_path}: {e}")
        
        print("Loading program 2 path info...")
        for file_path in files2:
            try:
                path_info = self.checker.extract_path_info(file_path)
                path_info['file'] = file_path
                paths2.append(path_info)
            except Exception as e:
                print(f"  ❌ Error processing file {file_path}: {e}")
        
        load_time = time.time() - load_start
        print(f"File load done, time: {load_time:.3f} s")
        print(f"Paths loaded: {len(paths1)} vs {len(paths2)}")
        
                   
        comparison_start = time.time()
        results = self.find_equivalent_paths_enhanced(paths1, paths2)
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
        
                
        print(f"\n⏱️  Timing:")
        print(f"  Symbolic execution: {self.symbolic_execution_time:.3f} s")
        print(f"  File load: {load_time:.3f} s")
        print(f"  Path comparison: {comparison_time:.3f} s")
        print(f"    - SMT constraint check: {self.checker.constraint_time:.3f} s ({self.checker.constraint_call_count} calls)")
        print(f"    - Array state compare: {self.checker.array_time:.3f} s ({self.checker.array_call_count} calls)")
        print(f"  Total analysis: {total_time:.3f} s")
        
        return results
    
    def _build_similarity_ranking(self, paths1, paths2):
        """Build candidate ranking for each path1 index based on cosine similarity."""
        if extract_features is None or not paths1 or not paths2:
            return None
        try:
            vecs1 = []
            vecs2 = []
            for path in paths1:
                with open(path['file'], 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                raw, _ = extract_features(content)
                vecs1.append(raw)
            for path in paths2:
                with open(path['file'], 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                raw, _ = extract_features(content)
                vecs2.append(raw)

            all_vecs = vecs1 + vecs2
            if not all_vecs:
                return None

            dim = len(all_vecs[0])
            mins = [min(v[k] for v in all_vecs) for k in range(dim)]
            maxs = [max(v[k] for v in all_vecs) for k in range(dim)]

            def normalize(v):
                out = []
                for k in range(dim):
                    lo = mins[k]
                    hi = maxs[k]
                    if hi <= lo:
                        out.append(0.0)
                    else:
                        out.append((v[k] - lo) / (hi - lo))
                return out

            nvecs1 = [normalize(v) for v in vecs1]
            nvecs2 = [normalize(v) for v in vecs2]

            ranking = {}
            similarity = {}
            for i in range(len(paths1)):
                candidates = []
                for j in range(len(paths2)):
                    score = cosine_similarity(nvecs1[i], nvecs2[j])
                    similarity[(i, j)] = score
                    candidates.append((j, score))
                candidates.sort(key=lambda x: x[1], reverse=True)
                ranking[i] = candidates
            return {"ranking": ranking, "similarity": similarity}
        except Exception as e:
            print(f"Warning: failed to build similarity ranking, fallback to sequential order: {e}")
            return None

    def find_equivalent_paths_enhanced(self, paths1, paths2):
        """Find equivalent paths using enhanced constraint+output combined judgment."""
        results = {
            'equivalent_pairs': [],
            'suspicious_constraint_pairs': [],
            'suspicious_output_pairs': [],
            'non_equivalent_pairs': [],
            'error_pairs': [],
            'unmatched_paths1': list(range(len(paths1))),
            'unmatched_paths2': list(range(len(paths2))),
            'program_equivalent': False
        }

        ranking_data = self._build_similarity_ranking(paths1, paths2)
        use_similarity = ranking_data is not None

        total_comparisons = len(paths1) * len(paths2)
        current_comparison = 0
        comparison_start_time = time.time()

        print(f"\nStarting enhanced equivalence verification ({total_comparisons} pairs max):")
        print(f"Similarity-guided matching: {'enabled' if use_similarity else 'disabled'}")

        matched_path2 = set()

        for i, path1 in enumerate(paths1):
            path1_matched = False
            if use_similarity:
                ordered_candidates = ranking_data["ranking"][i]
                candidate_indices = [j for j, _ in ordered_candidates]
            else:
                candidate_indices = list(range(len(paths2)))

            for rank, j in enumerate(candidate_indices, 1):
                if j in matched_path2:
                    continue

                path2 = paths2[j]
                current_comparison += 1
                pair_start_time = time.time()

                if current_comparison > 1:
                    elapsed = time.time() - comparison_start_time
                    avg_time = elapsed / (current_comparison - 1)
                    remaining = total_comparisons - current_comparison
                    estimated_remaining = avg_time * remaining
                    print(
                        f"  Compare {i+1}-{j+1} ({current_comparison}/{total_comparisons}, "
                        f"{current_comparison/total_comparisons*100:.1f}%) - ETA: {estimated_remaining:.1f}s"
                    )
                else:
                    print(f"  Compare path {i+1} vs {j+1}")

                sim_score = ranking_data["similarity"].get((i, j), 0.0) if use_similarity else 0.0
                if use_similarity:
                    print(f"    Similarity rank #{rank}, score={sim_score:.4f}")

                equivalence_result = self.checker.check_constraint_and_output_equivalence(path1, path2)
                pair_time = time.time() - pair_start_time

                timing_detail = {
                    'path1_index': i,
                    'path2_index': j,
                    'total_time': pair_time,
                    'constraint_time': equivalence_result['constraint_time'],
                    'array_initial_time': equivalence_result['array_initial_time'],
                    'array_final_time': equivalence_result['array_final_time'],
                    'result': 'equivalent' if equivalence_result['overall_equivalent'] else 'not_equivalent',
                    'similarity_score': sim_score,
                    'similarity_rank': rank if use_similarity else None
                }
                self.detailed_timing.append(timing_detail)

                pair_info = {
                    'path1_index': i,
                    'path2_index': j,
                    'path1_file': path1['file'],
                    'path2_file': path2['file'],
                    'equivalence_result': equivalence_result,
                    'comparison_time': pair_time,
                    'similarity_score': sim_score,
                    'similarity_rank': rank if use_similarity else None
                }

                if equivalence_result['overall_equivalent']:
                    results['equivalent_pairs'].append(pair_info)
                    matched_path2.add(j)
                    if i in results['unmatched_paths1']:
                        results['unmatched_paths1'].remove(i)
                    if j in results['unmatched_paths2']:
                        results['unmatched_paths2'].remove(j)

                    print(f"    ✅ Fully equivalent! constraints✓ output✓ time: {pair_time:.3f}s")
                    path1_matched = True
                    break

                elif (not equivalence_result['constraint_equivalent'] and
                      equivalence_result['output_equivalent']):
                    results['suspicious_constraint_pairs'].append(pair_info)
                    print(f"    ⚠️  Suspicious (constraint)! constraints❌ output✓ time: {pair_time:.3f}s")

                elif (equivalence_result['constraint_equivalent'] and
                      not equivalence_result['output_equivalent']):
                    results['suspicious_output_pairs'].append(pair_info)
                    print(f"    ⚠️  Suspicious (output)! constraints✓ output❌ time: {pair_time:.3f}s")

                else:
                    results['non_equivalent_pairs'].append(pair_info)
                    print(f"    ❌ Not equivalent! constraints❌ output❌ time: {pair_time:.3f}s")

            if not path1_matched:
                print(f"    ❌ Path {i+1} has no equivalent path")

        results['program_equivalent'] = (
            len(results['unmatched_paths1']) == 0 and
            len(results['unmatched_paths2']) == 0
        )

        print(f"\n📊 Results:")
        print(f"  Fully equivalent pairs: {len(results['equivalent_pairs'])}")
        print(f"  Suspicious (constraint): {len(results['suspicious_constraint_pairs'])}")
        print(f"  Suspicious (output): {len(results['suspicious_output_pairs'])}")
        print(f"  Not equivalent pairs: {len(results['non_equivalent_pairs'])}")
        print(f"  Program 1 unmatched paths: {len(results['unmatched_paths1'])}")
        print(f"  Program 2 unmatched paths: {len(results['unmatched_paths2'])}")
        print(f"  Program equivalence: {'✅ Equivalent' if results['program_equivalent'] else '❌ Not equivalent'}")

        return results
    
    def generate_comprehensive_report(self, results, output_file="enhanced_equivalence_report.txt"):
        """Generate detailed equivalence analysis report."""
        with open(output_file, "w", encoding='utf-8') as f:
            f.write("Enhanced program equivalence analysis report\n")
            f.write("=" * 60 + "\n\n")
            
                  
            f.write("📋 Overall conclusion:\n")
            f.write("-" * 30 + "\n")
            equivalence_status = "✅ Equivalent" if results['program_equivalent'] else "❌ Not equivalent"
            f.write(f"Program equivalence: {equivalence_status}\n\n")
            
                  
            if 'timing_info' in results:
                timing = results['timing_info']
                f.write("⏱️  Timing:\n")
                f.write("-" * 30 + "\n")
                f.write(f"Analysis start: {timing['start_time']}\n")
                f.write(f"Analysis end: {timing['end_time']}\n")
                f.write(f"Total: {timing['total_time']:.3f} s\n")
                f.write(f"  - Symbolic execution: {timing['symbolic_execution_time']:.3f} s\n")
                f.write(f"  - File load: {timing['load_time']:.3f} s\n")
                f.write(f"  - Path comparison: {timing['comparison_time']:.3f} s\n")
                f.write(f"    * SMT constraint check: {timing['constraint_total_time']:.3f} s ({timing['constraint_call_count']} calls)\n")
                f.write(f"    * Array state compare: {timing['array_total_time']:.3f} s ({timing['array_call_count']} calls)\n")
                f.write(f"Avg SMT solve: {timing['constraint_avg_time']:.3f} s\n")
                f.write(f"Avg array compare: {timing['array_avg_time']:.3f} s\n\n")
            
                  
            f.write("📊 Stats:\n")
            f.write("-" * 30 + "\n")
            f.write(f"Fully equivalent pairs: {len(results['equivalent_pairs'])}\n")
            f.write(f"Suspicious (constraint): {len(results['suspicious_constraint_pairs'])}\n")
            f.write(f"Suspicious (output): {len(results['suspicious_output_pairs'])}\n")
            f.write(f"Not equivalent pairs: {len(results['non_equivalent_pairs'])}\n")
            f.write(f"Analysis errors: {len(results['error_pairs'])}\n")
            f.write(f"Program 1 unmatched paths: {len(results['unmatched_paths1'])}\n")
            f.write(f"Program 2 unmatched paths: {len(results['unmatched_paths2'])}\n\n")
            
                       
            if results['equivalent_pairs']:
                f.write("✅ Fully equivalent pairs:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['equivalent_pairs'], 1):
                    f.write(f"{idx}. Path {pair['path1_index']+1} <-> Path {pair['path2_index']+1}\n")
                    f.write(f"   File1: {pair['path1_file']}\n")
                    f.write(f"   File2: {pair['path2_file']}\n")
                    f.write(f"   Comparison time: {pair['comparison_time']:.3f} s\n")
                    f.write(f"   Similarity score: {pair.get('similarity_score', 0.0):.4f}\n")
                    if pair.get('similarity_rank') is not None:
                        f.write(f"   Similarity rank in candidates: #{pair['similarity_rank']}\n")
                    equiv_result = pair['equivalence_result']
                    f.write(f"   Timing:\n")
                    f.write(f"     - Constraint: {equiv_result['constraint_time']:.3f} s\n")
                    f.write(f"     - Array initial: {equiv_result['array_initial_time']:.3f} s\n")
                    f.write(f"     - Array final: {equiv_result['array_final_time']:.3f} s\n")
                    f.write(f"   Program output: '{equiv_result['path1_output']}' = '{equiv_result['path2_output']}'\n")
                    f.write(f"   Variable mapping: {equiv_result['variable_mapping']}\n\n")
            
                         
            if results['suspicious_constraint_pairs']:
                f.write("⚠️  Suspicious (constraint) pairs:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['suspicious_constraint_pairs'], 1):
                    f.write(f"{idx}. Path {pair['path1_index']+1} vs Path {pair['path2_index']+1}\n")
                    f.write(f"   File1: {pair['path1_file']}\n")
                    f.write(f"   File2: {pair['path2_file']}\n")
                    f.write(f"   Similarity score: {pair.get('similarity_score', 0.0):.4f}\n")
                    if pair.get('similarity_rank') is not None:
                        f.write(f"   Similarity rank in candidates: #{pair['similarity_rank']}\n")
                    equiv_result = pair['equivalence_result']
                    f.write(f"   Equivalence check:\n")
                    f.write(f"     - Constraint equivalent: {'✅' if equiv_result['constraint_equivalent'] else '❌'}\n")
                    f.write(f"     - Output same: {'✅' if equiv_result['output_equivalent'] else '❌'}\n")
                    f.write(f"   Program output: '{equiv_result['path1_output']}' = '{equiv_result['path2_output']}'\n")
                    f.write(f"   Comparison time: {pair['comparison_time']:.3f} s\n\n")
            
                         
            if results['suspicious_output_pairs']:
                f.write("⚠️  Suspicious (output) pairs:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['suspicious_output_pairs'], 1):
                    f.write(f"{idx}. Path {pair['path1_index']+1} vs Path {pair['path2_index']+1}\n")
                    f.write(f"   File1: {pair['path1_file']}\n")
                    f.write(f"   File2: {pair['path2_file']}\n")
                    f.write(f"   Similarity score: {pair.get('similarity_score', 0.0):.4f}\n")
                    if pair.get('similarity_rank') is not None:
                        f.write(f"   Similarity rank in candidates: #{pair['similarity_rank']}\n")
                    equiv_result = pair['equivalence_result']
                    f.write(f"   Equivalence check:\n")
                    f.write(f"     - Constraint equivalent: {'✅' if equiv_result['constraint_equivalent'] else '❌'}\n")
                    f.write(f"     - Output same: {'✅' if equiv_result['output_equivalent'] else '❌'}\n")
                    f.write(f"   Program output: '{equiv_result['path1_output']}' ≠ '{equiv_result['path2_output']}'\n")
                    f.write(f"   Comparison time: {pair['comparison_time']:.3f} s\n\n")
            
                      
            if results['non_equivalent_pairs']:
                f.write("❌ Not equivalent pairs:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['non_equivalent_pairs'], 1):
                    f.write(f"{idx}. Path {pair['path1_index']+1} vs Path {pair['path2_index']+1}\n")
                    f.write(f"   File1: {pair['path1_file']}\n")
                    f.write(f"   File2: {pair['path2_file']}\n")
                    f.write(f"   Similarity score: {pair.get('similarity_score', 0.0):.4f}\n")
                    if pair.get('similarity_rank') is not None:
                        f.write(f"   Similarity rank in candidates: #{pair['similarity_rank']}\n")
                    equiv_result = pair['equivalence_result']
                    f.write(f"   Equivalence check:\n")
                    f.write(f"     - Constraint equivalent: {'✅' if equiv_result['constraint_equivalent'] else '❌'}\n")
                    f.write(f"     - Output same: {'✅' if equiv_result['output_equivalent'] else '❌'}\n")
                    f.write(f"   Program output: '{equiv_result['path1_output']}' ≠ '{equiv_result['path2_output']}'\n")
                    f.write(f"   Comparison time: {pair['comparison_time']:.3f} s\n\n")
            
                   
            if results['unmatched_paths1']:
                f.write("❌ Program 1 unmatched paths:\n")
                f.write("-" * 30 + "\n")
                for idx in results['unmatched_paths1']:
                    f.write(f"  Path {idx+1}\n")
                f.write("\n")
            if results['unmatched_paths2']:
                f.write("❌ Program 2 unmatched paths:\n")
                f.write("-" * 30 + "\n")
                for idx in results['unmatched_paths2']:
                    f.write(f"  Path {idx+1}\n")
                f.write("\n")
        print(f"📄 Report saved to: {output_file}")

def main():
    """Main entry."""
    import argparse
    parser = argparse.ArgumentParser(description='Enhanced program equivalence analyzer: constraint + output combined judgment')
    parser.add_argument('prefix1', help='First program path file prefix')
    parser.add_argument('prefix2', help='Second program path file prefix')
    parser.add_argument('--output', default='enhanced_equivalence_report.txt', help='Output report file')
    parser.add_argument('--timeout', type=int, default=30000, help='Z3 solver timeout (ms)')
    parser.add_argument('--se-time', type=float, default=0.0, help='Symbolic execution time (s), for stats')
    args = parser.parse_args()
    analyzer = EnhancedPathAnalyzer()
    analyzer.checker.timeout = args.timeout
    analyzer.set_symbolic_execution_time(args.se_time)
    print("🚀 Starting enhanced program equivalence analysis...")
    print("=" * 60)
    print("Combined judgment flow:")
    print("  1️⃣  Constraint semantic equivalence (Z3)")
    print("  2️⃣  Program output equivalence")
    print("  3️⃣  Array initial state consistency")
    print("  4️⃣  Array final state consistency")
    print("=" * 60)
    results = analyzer.analyze_program_equivalence(args.prefix1, args.prefix2)
    analyzer.generate_comprehensive_report(results, args.output)
    print("\n" + "=" * 60)
    print("🎯 Final results:")
    print(f"  Program equivalence: {'✅ Equivalent' if results['program_equivalent'] else '❌ Not equivalent'}")
    print(f"  Fully equivalent pairs: {len(results['equivalent_pairs'])}")
    print(f"  Suspicious (constraint): {len(results['suspicious_constraint_pairs'])}")
    print(f"  Suspicious (output): {len(results['suspicious_output_pairs'])}")
    print(f"  Not equivalent pairs: {len(results['non_equivalent_pairs'])}")
    print(f"  Total pairs analyzed: {len(results['equivalent_pairs']) + len(results['suspicious_constraint_pairs']) + len(results['suspicious_output_pairs']) + len(results['non_equivalent_pairs'])}")
    if 'timing_info' in results:
        timing = results['timing_info']
        print(f"\n⏱️  Performance:")
        print(f"  Total: {timing['total_time']:.3f} s")
        print(f"  Symbolic execution: {timing['symbolic_execution_time']:.3f} s")
        print(f"  SMT solve: {timing['constraint_total_time']:.3f} s ({timing['constraint_call_count']} calls)")
        print(f"  Array compare: {timing['array_total_time']:.3f} s ({timing['array_call_count']} calls)")
    print("=" * 60)
    print("✅ Analysis complete. See output file for full report.")

if __name__ == "__main__":
    main()
