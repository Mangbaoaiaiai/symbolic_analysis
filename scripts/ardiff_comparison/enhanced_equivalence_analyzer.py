                      
"""
Layered equivalence checking system.
Level 1: Control-flow equivalence
Level 2: Memory access pattern equivalence
Level 3: Data transformation equivalence

Addresses the issue of overly high-level constraint representation in traditional symbolic execution.
"""

import re
import z3
from z3 import *
import glob
import time
import datetime
import os
from collections import defaultdict, Counter
from dataclasses import dataclass
from typing import List, Dict, Set, Tuple, Optional
import hashlib

@dataclass
class ConstraintAnalysis:
    """Constraint analysis result."""
    control_flow_constraints: List[str]
    memory_access_constraints: List[str]
    data_transformation_constraints: List[str]
    variable_bounds: Dict[str, Tuple[int, int]]
    memory_addresses: Set[str]
    arithmetic_operations: List[str]

@dataclass
class LayeredEquivalenceResult:
    """Layered equivalence check result."""
    level1_control_flow: str                                       
    level2_memory_access: str
    level3_data_transformation: str
    overall_result: str
    confidence_score: float
    detailed_analysis: Dict
    
class ConstraintClassifier:
    """Constraint classifier: assign SMT constraints to layers."""
    
    def __init__(self):
               
        self.control_flow_patterns = [
            r'bvslt.*scanf_0',          
            r'bvsge.*scanf_0',            
            r'bvuge.*scanf_0',          
            r'bvule.*scanf_0',          
            r'distinct.*scanf_0',       
        ]
        
                
        self.memory_access_patterns = [
            r'distinct.*bv\d+.*64',           
            r'bvule.*bv\d{7,}',              
            r'bvadd.*bv\d{7,}',            
            r'bvshl.*bv\d+.*64',             
        ]
        
                  
        self.data_transformation_patterns = [
            r'bvadd.*extract',          
            r'bvsub.*extract',          
            r'bvmul.*extract',          
            r'bvand.*extract',       
            r'bvor.*extract',        
            r'select.*store',           
        ]
    
    def classify_constraint(self, constraint: str) -> str:
        """Classify constraint as control-flow, memory-access, or data-transformation."""
                    
        clean_constraint = re.sub(r'\s+', ' ', constraint.strip())
        
                               
        for pattern in self.data_transformation_patterns:
            if re.search(pattern, clean_constraint, re.IGNORECASE):
                return 'data_transformation'
        
        for pattern in self.memory_access_patterns:
            if re.search(pattern, clean_constraint, re.IGNORECASE):
                return 'memory_access'
                
        for pattern in self.control_flow_patterns:
            if re.search(pattern, clean_constraint, re.IGNORECASE):
                return 'control_flow'
        
                  
        return 'control_flow'
    
    def extract_memory_addresses(self, constraints: List[str]) -> Set[str]:
        """Extract memory addresses from constraints."""
        addresses = set()
        for constraint in constraints:
                                         
            addr_matches = re.findall(r'_\s+bv(\d{7,})\s+64', constraint)
            addresses.update(addr_matches)
        return addresses
    
    def extract_arithmetic_operations(self, constraints: List[str]) -> List[str]:
        """Extract arithmetic operations."""
        operations = []
        for constraint in constraints:
                    
            ops = re.findall(r'(bvadd|bvsub|bvmul|bvdiv|bvand|bvor|bvxor)', constraint)
            operations.extend(ops)
        return operations
    
    def analyze_constraints(self, constraints: List[str], variables: Dict[str, int]) -> ConstraintAnalysis:
        """Analyze full constraint structure."""
        control_flow = []
        memory_access = []
        data_transformation = []
        
        for constraint in constraints:
            category = self.classify_constraint(constraint)
            if category == 'control_flow':
                control_flow.append(constraint)
            elif category == 'memory_access':
                memory_access.append(constraint)
            else:
                data_transformation.append(constraint)
        
                
        variable_bounds = {}
        for var_name in variables:
            bounds = self.extract_variable_bounds(constraints, var_name)
            if bounds:
                variable_bounds[var_name] = bounds
        
        return ConstraintAnalysis(
            control_flow_constraints=control_flow,
            memory_access_constraints=memory_access,
            data_transformation_constraints=data_transformation,
            variable_bounds=variable_bounds,
            memory_addresses=self.extract_memory_addresses(constraints),
            arithmetic_operations=self.extract_arithmetic_operations(constraints)
        )
    
    def extract_variable_bounds(self, constraints: List[str], var_name: str) -> Optional[Tuple[int, int]]:
        """Extract variable lower/upper bounds."""
        lower_bound = None
        upper_bound = None
        
        for constraint in constraints:
                                       
            lower_match = re.search(rf'bvuge\s+{var_name}.*bv(\d+)\s+32', constraint)
            if lower_match:
                lower_bound = int(lower_match.group(1))
            
                                         
            upper_match = re.search(rf'bvule\s+{var_name}.*bv(\d+)\s+32', constraint)
            if upper_match:
                upper_bound = int(upper_match.group(1))
        
        if lower_bound is not None and upper_bound is not None:
            return (lower_bound, upper_bound)
        return None

class LayeredEquivalenceChecker:
    """Layered equivalence checker."""
    
    def __init__(self, timeout=30000):
        self.timeout = timeout
        self.classifier = ConstraintClassifier()
        self.z3_total_time = 0.0
        self.z3_call_count = 0
    
    def extract_constraint_formula(self, file_path: str):
        """Extract constraint formula from file."""
        with open(file_path, 'r') as f:
            content = f.read()
        
              
        lines = [line for line in content.splitlines() if not line.strip().startswith(';')]
        content = '\n'.join(lines)
        
                
        variables = {}
        var_pattern = r'\(declare-fun\s+(\w+)\s+\(\)\s+\(_\s+BitVec\s+(\d+)\)\)'
        for match in re.finditer(var_pattern, content):
            var_name, bit_width = match.groups()
            variables[var_name] = int(bit_width)
        
              
        constraints = []
        constraint_pattern = r'\(assert\s+(.*?)\)(?=\s*(?:\(assert|\(check-sat|$))'
        for match in re.finditer(constraint_pattern, content, re.DOTALL):
            constraint = match.group(1).strip()
            constraints.append(constraint)
        
        return variables, constraints
    
    def check_level1_control_flow_equivalence(self, analysis1: ConstraintAnalysis, 
                                            analysis2: ConstraintAnalysis) -> Tuple[str, Dict]:
        """Level 1: Control-flow equivalence check."""
        print("    📊 Level 1: Control-flow equivalence")
        
        start_time = time.time()
        
                      
        cf1 = analysis1.control_flow_constraints
        cf2 = analysis2.control_flow_constraints
        
        details = {
            'control_flow_count1': len(cf1),
            'control_flow_count2': len(cf2),
            'variable_bounds1': analysis1.variable_bounds,
            'variable_bounds2': analysis2.variable_bounds,
        }
        
                
        bounds_equivalent = True
        if analysis1.variable_bounds != analysis2.variable_bounds:
            bounds_equivalent = False
            details['bounds_difference'] = {
                'path1_bounds': analysis1.variable_bounds,
                'path2_bounds': analysis2.variable_bounds
            }
        
                     
        count_diff = abs(len(cf1) - len(cf2))
        if count_diff > 2:          
            result = "not_equivalent"
            details['reason'] = f"Control-flow constraint count diff too large: {len(cf1)} vs {len(cf2)}"
        elif not bounds_equivalent:
            result = "not_equivalent"
            details['reason'] = "Variable bounds inconsistent"
        else:
            result = "equivalent"
            details['reason'] = "Control-flow structure largely consistent"
        solve_time = time.time() - start_time
        details['check_time'] = solve_time
        print(f"      Result: {result}")
        print(f"      Control-flow constraints: {len(cf1)} vs {len(cf2)}")
        print(f"      Variable bounds: {analysis1.variable_bounds} vs {analysis2.variable_bounds}")
        
        return result, details
    
    def check_level2_memory_access_equivalence(self, analysis1: ConstraintAnalysis,
                                             analysis2: ConstraintAnalysis) -> Tuple[str, Dict]:
        """Level 2: Memory access pattern equivalence check."""
        print("    🔍 Level 2: Memory access pattern equivalence")
        
        start_time = time.time()
        
        ma1 = analysis1.memory_access_constraints
        ma2 = analysis2.memory_access_constraints
        
        details = {
            'memory_access_count1': len(ma1),
            'memory_access_count2': len(ma2),
            'memory_addresses1': analysis1.memory_addresses,
            'memory_addresses2': analysis2.memory_addresses,
        }
        
                  
        addr_intersection = analysis1.memory_addresses & analysis2.memory_addresses
        addr_union = analysis1.memory_addresses | analysis2.memory_addresses
        
        if len(addr_union) == 0:
            addr_similarity = 1.0           
        else:
            addr_similarity = len(addr_intersection) / len(addr_union)
        
        details['address_similarity'] = addr_similarity
        details['common_addresses'] = list(addr_intersection)
        details['unique_addresses1'] = list(analysis1.memory_addresses - analysis2.memory_addresses)
        details['unique_addresses2'] = list(analysis2.memory_addresses - analysis1.memory_addresses)
        
                  
        access_count_diff = abs(len(ma1) - len(ma2))
        
        if access_count_diff > 5 and addr_similarity < 0.3:
            result = "not_equivalent"
            details['reason'] = f"Memory access pattern very different: count diff {access_count_diff}, addr similarity {addr_similarity:.2f}"
        elif addr_similarity < 0.1:
            result = "not_equivalent"
            details['reason'] = f"Memory address sets almost disjoint: similarity {addr_similarity:.2f}"
        elif addr_similarity > 0.8 and access_count_diff <= 3:
            result = "equivalent"
            details['reason'] = f"Memory access pattern highly similar: similarity {addr_similarity:.2f}"
        else:
            result = "partial_equivalent"
            details['reason'] = f"Memory access pattern partially similar: similarity {addr_similarity:.2f}"
        solve_time = time.time() - start_time
        details['check_time'] = solve_time
        print(f"      Result: {result}")
        print(f"      Memory access constraints: {len(ma1)} vs {len(ma2)}")
        print(f"      Address similarity: {addr_similarity:.2f}")
        print(f"      Common addresses: {len(addr_intersection)}")
        
        return result, details
    
    def check_level3_data_transformation_equivalence(self, analysis1: ConstraintAnalysis,
                                                   analysis2: ConstraintAnalysis) -> Tuple[str, Dict]:
        """Level 3: Data transformation equivalence check."""
        print("    🧮 Level 3: Data transformation equivalence")
        
        start_time = time.time()
        
        dt1 = analysis1.data_transformation_constraints
        dt2 = analysis2.data_transformation_constraints
        
                  
        ops1 = Counter(analysis1.arithmetic_operations)
        ops2 = Counter(analysis2.arithmetic_operations)
        
        details = {
            'data_transformation_count1': len(dt1),
            'data_transformation_count2': len(dt2),
            'arithmetic_operations1': dict(ops1),
            'arithmetic_operations2': dict(ops2),
        }
        
                   
        all_ops = set(ops1.keys()) | set(ops2.keys())
        if len(all_ops) == 0:
            op_similarity = 1.0           
        else:
            similarity_sum = 0
            for op in all_ops:
                count1 = ops1.get(op, 0)
                count2 = ops2.get(op, 0)
                max_count = max(count1, count2)
                if max_count > 0:
                    similarity_sum += min(count1, count2) / max_count
            op_similarity = similarity_sum / len(all_ops)
        
        details['operation_similarity'] = op_similarity
        
                   
        complexity_diff = abs(len(dt1) - len(dt2))
        
        if len(dt1) == 0 and len(dt2) == 0:
            result = "equivalent"
            details['reason'] = "No data transformation ops in either"
        elif op_similarity > 0.8 and complexity_diff <= 2:
            result = "equivalent"
            details['reason'] = f"Data transformation pattern highly similar: op similarity {op_similarity:.2f}"
        elif op_similarity < 0.3:
            result = "not_equivalent"
            details['reason'] = f"Data transformation pattern very different: op similarity {op_similarity:.2f}"
        else:
            result = "partial_equivalent"
            details['reason'] = f"Data transformation pattern partially similar: op similarity {op_similarity:.2f}"
        solve_time = time.time() - start_time
        details['check_time'] = solve_time
        print(f"      Result: {result}")
        print(f"      Data transformation constraints: {len(dt1)} vs {len(dt2)}")
        print(f"      Operation similarity: {op_similarity:.2f}")
        print(f"      Arithmetic ops: {dict(ops1)} vs {dict(ops2)}")
        
        return result, details
    
    def calculate_confidence_score(self, level1_result: str, level2_result: str, 
                                 level3_result: str) -> float:
        """Compute confidence score."""
        score_map = {
            'equivalent': 1.0,
            'partial_equivalent': 0.5,
            'not_equivalent': 0.0,
            'unknown': 0.3
        }
        
        scores = [
            score_map.get(level1_result, 0.3) * 0.3,            
            score_map.get(level2_result, 0.3) * 0.4,             
            score_map.get(level3_result, 0.3) * 0.3              
        ]
        
        return sum(scores)
    
    def determine_overall_result(self, level1_result: str, level2_result: str, 
                               level3_result: str, confidence: float) -> str:
        """Determine overall equivalence result."""
                                   
        if 'not_equivalent' in [level1_result, level2_result, level3_result]:
            if confidence < 0.4:
                return 'not_equivalent'
            elif confidence < 0.7:
                return 'likely_not_equivalent'
        
                  
        if all(result == 'equivalent' for result in [level1_result, level2_result, level3_result]):
            return 'equivalent'
        
                  
        equiv_count = sum(1 for result in [level1_result, level2_result, level3_result] 
                         if result == 'equivalent')
        
        if equiv_count >= 2:
            return 'likely_equivalent'
        elif confidence > 0.7:
            return 'partial_equivalent'
        else:
            return 'not_equivalent'
    
    def check_layered_equivalence(self, file1: str, file2: str) -> LayeredEquivalenceResult:
        """Run layered equivalence check."""
        print(f"\n🔬 Layered equivalence check: {os.path.basename(file1)} vs {os.path.basename(file2)}")
        
              
        try:
            vars1, constraints1 = self.extract_constraint_formula(file1)
            vars2, constraints2 = self.extract_constraint_formula(file2)
        except Exception as e:
            return LayeredEquivalenceResult(
                level1_control_flow="error",
                level2_memory_access="error", 
                level3_data_transformation="error",
                overall_result="error",
                confidence_score=0.0,
                detailed_analysis={"error": str(e)}
            )
        
                
        analysis1 = self.classifier.analyze_constraints(constraints1, vars1)
        analysis2 = self.classifier.analyze_constraints(constraints2, vars2)
        
        print(f"  Path1: {len(constraints1)} constraints -> CF:{len(analysis1.control_flow_constraints)} MA:{len(analysis1.memory_access_constraints)} DT:{len(analysis1.data_transformation_constraints)}")
        print(f"  Path2: {len(constraints2)} constraints -> CF:{len(analysis2.control_flow_constraints)} MA:{len(analysis2.memory_access_constraints)} DT:{len(analysis2.data_transformation_constraints)}")
        
              
        level1_result, level1_details = self.check_level1_control_flow_equivalence(analysis1, analysis2)
        level2_result, level2_details = self.check_level2_memory_access_equivalence(analysis1, analysis2)
        level3_result, level3_details = self.check_level3_data_transformation_equivalence(analysis1, analysis2)
        
                    
        confidence = self.calculate_confidence_score(level1_result, level2_result, level3_result)
        overall_result = self.determine_overall_result(level1_result, level2_result, level3_result, confidence)
        
        print(f"\n  📊 Layered results:")
        print(f"    Level 1 (control flow): {level1_result}")
        print(f"    Level 2 (memory access): {level2_result}")
        print(f"    Level 3 (data transformation): {level3_result}")
        print(f"    Overall: {overall_result}")
        print(f"    Confidence: {confidence:.2f}")
        
        return LayeredEquivalenceResult(
            level1_control_flow=level1_result,
            level2_memory_access=level2_result,
            level3_data_transformation=level3_result,
            overall_result=overall_result,
            confidence_score=confidence,
            detailed_analysis={
                'level1_details': level1_details,
                'level2_details': level2_details,
                'level3_details': level3_details,
                'analysis1': analysis1,
                'analysis2': analysis2
            }
        )

class EnhancedEquivalenceAnalyzer:
    """Enhanced equivalence analyzer."""
    
    def __init__(self, benchmark_dir: str = '.'):
        self.benchmark_dir = benchmark_dir
        self.checker = LayeredEquivalenceChecker()
        
    def analyze_path_pair(self, file1: str, file2: str) -> LayeredEquivalenceResult:
        """Analyze a single path pair."""
        return self.checker.check_layered_equivalence(file1, file2)
    
    def generate_layered_report(self, results: List[Tuple[str, str, LayeredEquivalenceResult]], 
                               output_file: str = "layered_equivalence_report.txt"):
        """Generate layered analysis report."""
        with open(output_file, "w", encoding='utf-8') as f:
            f.write("Layered equivalence analysis report\n")
            f.write("=" * 60 + "\n\n")
            f.write("Method:\n")
            f.write("  Level 1: Control-flow equivalence (loop bounds, branch conditions)\n")
            f.write("  Level 2: Memory access pattern equivalence (address patterns, access frequency)\n")
            f.write("  Level 3: Data transformation equivalence (arithmetic ops, data flow)\n\n")
            total_pairs = len(results)
            overall_equivalent = sum(1 for _, _, result in results if result.overall_result == 'equivalent')
            overall_not_equivalent = sum(1 for _, _, result in results if result.overall_result == 'not_equivalent')
            f.write(f"Overall stats:\n")
            f.write(f"  Path pairs analyzed: {total_pairs}\n")
            f.write(f"  Overall equivalent: {overall_equivalent} ({overall_equivalent/total_pairs*100:.1f}%)\n")
            f.write(f"  Overall not equivalent: {overall_not_equivalent} ({overall_not_equivalent/total_pairs*100:.1f}%)\n")
            f.write(f"  Other: {total_pairs - overall_equivalent - overall_not_equivalent}\n\n")
            level1_eq = sum(1 for _, _, result in results if result.level1_control_flow == 'equivalent')
            level2_eq = sum(1 for _, _, result in results if result.level2_memory_access == 'equivalent')
            level3_eq = sum(1 for _, _, result in results if result.level3_data_transformation == 'equivalent')
            f.write(f"Layered equivalence stats:\n")
            f.write(f"  Level 1 (control flow) equivalent: {level1_eq}/{total_pairs} ({level1_eq/total_pairs*100:.1f}%)\n")
            f.write(f"  Level 2 (memory access) equivalent: {level2_eq}/{total_pairs} ({level2_eq/total_pairs*100:.1f}%)\n")
            f.write(f"  Level 3 (data transformation) equivalent: {level3_eq}/{total_pairs} ({level3_eq/total_pairs*100:.1f}%)\n\n")
            f.write("Detailed results:\n")
            f.write("-" * 60 + "\n")
            for file1, file2, result in results:
                f.write(f"\nCompare: {os.path.basename(file1)} vs {os.path.basename(file2)}\n")
                f.write(f"  Level 1 (control flow): {result.level1_control_flow}\n")
                f.write(f"  Level 2 (memory access): {result.level2_memory_access}\n")
                f.write(f"  Level 3 (data transformation): {result.level3_data_transformation}\n")
                f.write(f"  Overall: {result.overall_result}\n")
                f.write(f"  Confidence: {result.confidence_score:.2f}\n")
                if 'level1_details' in result.detailed_analysis:
                    level1 = result.detailed_analysis['level1_details']
                    f.write(f"  Control-flow details: {level1.get('reason', '')}\n")
                if 'level2_details' in result.detailed_analysis:
                    level2 = result.detailed_analysis['level2_details']
                    f.write(f"  Memory access details: {level2.get('reason', '')}\n")
                    if 'address_similarity' in level2:
                        f.write(f"    Address similarity: {level2['address_similarity']:.2f}\n")
                if 'level3_details' in result.detailed_analysis:
                    level3 = result.detailed_analysis['level3_details']
                    f.write(f"  Data transformation details: {level3.get('reason', '')}\n")
                    if 'operation_similarity' in level3:
                        f.write(f"    Operation similarity: {level3['operation_similarity']:.2f}\n")
        print(f"📄 Layered report saved to: {output_file}")

def main():
    """Main entry."""
    import argparse
    parser = argparse.ArgumentParser(description='Layered equivalence checking system')
    parser.add_argument('--file1', help='First path file')
    parser.add_argument('--file2', help='Second path file')
    parser.add_argument('--benchmark', default='.', help='Benchmark directory')
    parser.add_argument('--output', default='layered_equivalence_report.txt', help='Output report file')
    args = parser.parse_args()
    analyzer = EnhancedEquivalenceAnalyzer(args.benchmark)
    if args.file1 and args.file2:
        result = analyzer.analyze_path_pair(args.file1, args.file2)
        results = [(args.file1, args.file2, result)]
        analyzer.generate_layered_report(results, args.output)
    else:
        print("Provide two path files to compare: --file1 <file1> --file2 <file2>")

if __name__ == "__main__":
    main() 