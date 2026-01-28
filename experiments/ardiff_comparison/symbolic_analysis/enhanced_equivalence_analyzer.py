                      
"""
分层等价性检查系统
Level 1: 控制流等价性
Level 2: 内存访问模式等价性  
Level 3: 数据变换等价性

解决传统符号执行约束表示层次过高的问题
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
    """约束分析结果"""
    control_flow_constraints: List[str]
    memory_access_constraints: List[str]
    data_transformation_constraints: List[str]
    variable_bounds: Dict[str, Tuple[int, int]]
    memory_addresses: Set[str]
    arithmetic_operations: List[str]

@dataclass 
class LayeredEquivalenceResult:
    """分层等价性检查结果"""
    level1_control_flow: str                                       
    level2_memory_access: str
    level3_data_transformation: str
    overall_result: str
    confidence_score: float
    detailed_analysis: Dict
    
class ConstraintClassifier:
    """约束分类器 - 将SMT约束分类到不同层次"""
    
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
        """将约束分类到控制流、内存访问或数据变换"""
                    
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
        """提取约束中的内存地址"""
        addresses = set()
        for constraint in constraints:
                                         
            addr_matches = re.findall(r'_\s+bv(\d{7,})\s+64', constraint)
            addresses.update(addr_matches)
        return addresses
    
    def extract_arithmetic_operations(self, constraints: List[str]) -> List[str]:
        """提取算术运算操作"""
        operations = []
        for constraint in constraints:
                    
            ops = re.findall(r'(bvadd|bvsub|bvmul|bvdiv|bvand|bvor|bvxor)', constraint)
            operations.extend(ops)
        return operations
    
    def analyze_constraints(self, constraints: List[str], variables: Dict[str, int]) -> ConstraintAnalysis:
        """全面分析约束结构"""
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
        """提取变量的上下界"""
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
    """分层等价性检查器"""
    
    def __init__(self, timeout=30000):
        self.timeout = timeout
        self.classifier = ConstraintClassifier()
        self.z3_total_time = 0.0
        self.z3_call_count = 0
    
    def extract_constraint_formula(self, file_path: str):
        """从文件中提取约束公式（复用原有方法）"""
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
        """Level 1: 控制流等价性检查"""
        print("    📊 Level 1: 控制流等价性检查")
        
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
            details['reason'] = f"控制流约束数量差异过大: {len(cf1)} vs {len(cf2)}"
        elif not bounds_equivalent:
            result = "not_equivalent" 
            details['reason'] = "变量边界不一致"
        else:
            result = "equivalent"
            details['reason'] = "控制流结构基本一致"
        
        solve_time = time.time() - start_time
        details['check_time'] = solve_time
        
        print(f"      结果: {result}")
        print(f"      控制流约束: {len(cf1)} vs {len(cf2)}")
        print(f"      变量边界: {analysis1.variable_bounds} vs {analysis2.variable_bounds}")
        
        return result, details
    
    def check_level2_memory_access_equivalence(self, analysis1: ConstraintAnalysis,
                                             analysis2: ConstraintAnalysis) -> Tuple[str, Dict]:
        """Level 2: 内存访问模式等价性检查"""
        print("    🔍 Level 2: 内存访问模式等价性检查")
        
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
            details['reason'] = f"内存访问模式显著不同: 约束数差异{access_count_diff}, 地址相似度{addr_similarity:.2f}"
        elif addr_similarity < 0.1:
            result = "not_equivalent"
            details['reason'] = f"内存地址集合几乎完全不同: 相似度{addr_similarity:.2f}"
        elif addr_similarity > 0.8 and access_count_diff <= 3:
            result = "equivalent"
            details['reason'] = f"内存访问模式高度相似: 相似度{addr_similarity:.2f}"
        else:
            result = "partial_equivalent"
            details['reason'] = f"内存访问模式部分相似: 相似度{addr_similarity:.2f}"
        
        solve_time = time.time() - start_time
        details['check_time'] = solve_time
        
        print(f"      结果: {result}")
        print(f"      内存访问约束: {len(ma1)} vs {len(ma2)}")
        print(f"      地址相似度: {addr_similarity:.2f}")
        print(f"      共同地址: {len(addr_intersection)} 个")
        
        return result, details
    
    def check_level3_data_transformation_equivalence(self, analysis1: ConstraintAnalysis,
                                                   analysis2: ConstraintAnalysis) -> Tuple[str, Dict]:
        """Level 3: 数据变换等价性检查"""
        print("    🧮 Level 3: 数据变换等价性检查")
        
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
            details['reason'] = "都没有数据变换操作"
        elif op_similarity > 0.8 and complexity_diff <= 2:
            result = "equivalent"
            details['reason'] = f"数据变换模式高度相似: 运算相似度{op_similarity:.2f}"
        elif op_similarity < 0.3:
            result = "not_equivalent"
            details['reason'] = f"数据变换模式显著不同: 运算相似度{op_similarity:.2f}"
        else:
            result = "partial_equivalent"
            details['reason'] = f"数据变换模式部分相似: 运算相似度{op_similarity:.2f}"
        
        solve_time = time.time() - start_time
        details['check_time'] = solve_time
        
        print(f"      结果: {result}")
        print(f"      数据变换约束: {len(dt1)} vs {len(dt2)}")
        print(f"      运算模式相似度: {op_similarity:.2f}")
        print(f"      算术操作: {dict(ops1)} vs {dict(ops2)}")
        
        return result, details
    
    def calculate_confidence_score(self, level1_result: str, level2_result: str, 
                                 level3_result: str) -> float:
        """计算置信度分数"""
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
        """确定总体等价性结果"""
                                   
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
        """执行分层等价性检查"""
        print(f"\n🔬 分层等价性检查: {os.path.basename(file1)} vs {os.path.basename(file2)}")
        
              
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
        
        print(f"  路径1: {len(constraints1)} 约束 -> CF:{len(analysis1.control_flow_constraints)} MA:{len(analysis1.memory_access_constraints)} DT:{len(analysis1.data_transformation_constraints)}")
        print(f"  路径2: {len(constraints2)} 约束 -> CF:{len(analysis2.control_flow_constraints)} MA:{len(analysis2.memory_access_constraints)} DT:{len(analysis2.data_transformation_constraints)}")
        
              
        level1_result, level1_details = self.check_level1_control_flow_equivalence(analysis1, analysis2)
        level2_result, level2_details = self.check_level2_memory_access_equivalence(analysis1, analysis2)
        level3_result, level3_details = self.check_level3_data_transformation_equivalence(analysis1, analysis2)
        
                    
        confidence = self.calculate_confidence_score(level1_result, level2_result, level3_result)
        overall_result = self.determine_overall_result(level1_result, level2_result, level3_result, confidence)
        
        print(f"\n  📊 分层结果:")
        print(f"    Level 1 (控制流): {level1_result}")
        print(f"    Level 2 (内存访问): {level2_result}")
        print(f"    Level 3 (数据变换): {level3_result}")
        print(f"    整体结果: {overall_result}")
        print(f"    置信度: {confidence:.2f}")
        
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
    """增强等价性分析器"""
    
    def __init__(self, benchmark_dir: str = '.'):
        self.benchmark_dir = benchmark_dir
        self.checker = LayeredEquivalenceChecker()
        
    def analyze_path_pair(self, file1: str, file2: str) -> LayeredEquivalenceResult:
        """分析单个路径对"""
        return self.checker.check_layered_equivalence(file1, file2)
    
    def generate_layered_report(self, results: List[Tuple[str, str, LayeredEquivalenceResult]], 
                               output_file: str = "layered_equivalence_report.txt"):
        """生成分层分析报告"""
        with open(output_file, "w", encoding='utf-8') as f:
            f.write("分层等价性分析报告\n")
            f.write("=" * 60 + "\n\n")
            
            f.write("分析方法:\n")
            f.write("  Level 1: 控制流等价性 (循环边界、分支条件)\n")
            f.write("  Level 2: 内存访问模式等价性 (地址模式、访问频率)\n") 
            f.write("  Level 3: 数据变换等价性 (算术运算、数据流)\n\n")
            
                  
            total_pairs = len(results)
            overall_equivalent = sum(1 for _, _, result in results if result.overall_result == 'equivalent')
            overall_not_equivalent = sum(1 for _, _, result in results if result.overall_result == 'not_equivalent')
            
            f.write(f"总体统计:\n")
            f.write(f"  分析路径对数: {total_pairs}\n")
            f.write(f"  整体等价: {overall_equivalent} ({overall_equivalent/total_pairs*100:.1f}%)\n")
            f.write(f"  整体不等价: {overall_not_equivalent} ({overall_not_equivalent/total_pairs*100:.1f}%)\n")
            f.write(f"  其他情况: {total_pairs - overall_equivalent - overall_not_equivalent}\n\n")
            
                  
            level1_eq = sum(1 for _, _, result in results if result.level1_control_flow == 'equivalent')
            level2_eq = sum(1 for _, _, result in results if result.level2_memory_access == 'equivalent') 
            level3_eq = sum(1 for _, _, result in results if result.level3_data_transformation == 'equivalent')
            
            f.write(f"分层等价性统计:\n")
            f.write(f"  Level 1 (控制流) 等价: {level1_eq}/{total_pairs} ({level1_eq/total_pairs*100:.1f}%)\n")
            f.write(f"  Level 2 (内存访问) 等价: {level2_eq}/{total_pairs} ({level2_eq/total_pairs*100:.1f}%)\n")
            f.write(f"  Level 3 (数据变换) 等价: {level3_eq}/{total_pairs} ({level3_eq/total_pairs*100:.1f}%)\n\n")
            
                  
            f.write("详细分析结果:\n")
            f.write("-" * 60 + "\n")
            
            for file1, file2, result in results:
                f.write(f"\n比较: {os.path.basename(file1)} vs {os.path.basename(file2)}\n")
                f.write(f"  Level 1 (控制流): {result.level1_control_flow}\n")
                f.write(f"  Level 2 (内存访问): {result.level2_memory_access}\n")
                f.write(f"  Level 3 (数据变换): {result.level3_data_transformation}\n")
                f.write(f"  整体结果: {result.overall_result}\n")
                f.write(f"  置信度: {result.confidence_score:.2f}\n")
                
                      
                if 'level1_details' in result.detailed_analysis:
                    level1 = result.detailed_analysis['level1_details']
                    f.write(f"  控制流详情: {level1.get('reason', '')}\n")
                
                if 'level2_details' in result.detailed_analysis:
                    level2 = result.detailed_analysis['level2_details']
                    f.write(f"  内存访问详情: {level2.get('reason', '')}\n")
                    if 'address_similarity' in level2:
                        f.write(f"    地址相似度: {level2['address_similarity']:.2f}\n")
                
                if 'level3_details' in result.detailed_analysis:
                    level3 = result.detailed_analysis['level3_details']
                    f.write(f"  数据变换详情: {level3.get('reason', '')}\n")
                    if 'operation_similarity' in level3:
                        f.write(f"    运算相似度: {level3['operation_similarity']:.2f}\n")
        
        print(f"📄 分层分析报告已保存到: {output_file}")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='分层等价性检查系统')
    parser.add_argument('--file1', help='第一个路径文件')
    parser.add_argument('--file2', help='第二个路径文件')
    parser.add_argument('--benchmark', default='.', help='基准测试目录')
    parser.add_argument('--output', default='layered_equivalence_report.txt', help='输出报告文件')
    
    args = parser.parse_args()
    
    analyzer = EnhancedEquivalenceAnalyzer(args.benchmark)
    
    if args.file1 and args.file2:
              
        result = analyzer.analyze_path_pair(args.file1, args.file2)
        results = [(args.file1, args.file2, result)]
        analyzer.generate_layered_report(results, args.output)
    else:
        print("请提供要比较的两个路径文件: --file1 <file1> --file2 <file2>")

if __name__ == "__main__":
    main() 