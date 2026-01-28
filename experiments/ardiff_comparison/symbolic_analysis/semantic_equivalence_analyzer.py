                      
"""
增强的路径等价性分析器：四类判断流程
1. 路径约束等价且程序输出相同 → 等价
2. 路径约束不等价但程序输出相同 → 疑似不等价（约束）
3. 路径约束等价但程序输出不等价 → 疑似不等价（输出）
4. 路径约束不等价且程序输出不等价 → 不等价

基于约束语义等价性、数组初始状态和最终状态的完整路径分析器
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
    """数组状态比较器"""
    
    def __init__(self):
        pass
        
    def parse_array_state(self, content):
        """从路径文件内容中解析数组状态信息"""
        array_initial = {}
        array_final = {}
        
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            
                     
            if line.startswith('; 数组初始值:'):
                try:
                    array_str = line.split(':', 1)[1].strip()
                    array_initial = eval(array_str)                                
                except:
                    pass
                    
                     
            elif line.startswith('; 数组最终值:'):
                try:
                    array_str = line.split(':', 1)[1].strip()
                    array_final = eval(array_str)                                
                except:
                    pass
                    
        return array_initial, array_final
    
    def compare_array_states(self, state1, state2):
        """比较两个数组状态是否相同"""
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
    """增强的约束等价性检查器"""
    
    def __init__(self, timeout=30000):
        self.timeout = timeout
        self.constraint_time = 0.0
        self.constraint_call_count = 0
        self.array_time = 0.0
        self.array_call_count = 0
        self.array_comparator = ArrayStateComparator()
        
    def normalize_variable_names(self, formula, var_mapping):
        """标准化变量名，使两个公式可以比较"""
        for old_name, new_name in var_mapping.items():
            formula = re.sub(rf'\b{old_name}\b', new_name, formula)
        return formula
    
    def extract_path_info(self, file_path):
        """从文件中提取完整的路径信息：约束+数组状态+程序输出"""
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
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith("; 程序输出:"):
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not next_line.startswith(";"):
                        program_output = next_line
                        break
        return {
            'variables': variables,
            'constraints': constraints,
            'array_initial': array_initial,
            'array_final': array_final,
            'program_output': program_output
        }
    
    def create_variable_mapping(self, vars1, vars2):
        """创建变量映射，将两组变量对应起来"""
        mapping = {}
        
                      
        scanf_vars1 = [(name, self.extract_scanf_index(name)) for name in vars1.keys() if 'scanf' in name]
        scanf_vars2 = [(name, self.extract_scanf_index(name)) for name in vars2.keys() if 'scanf' in name]
        
               
        scanf_vars1.sort(key=lambda x: x[1])
        scanf_vars2.sort(key=lambda x: x[1])
        
              
        for (name1, idx1), (name2, idx2) in zip(scanf_vars1, scanf_vars2):
            mapping[name1] = name2
        
        return mapping
    
    def extract_scanf_index(self, var_name):
        """从scanf变量名中提取索引"""
        match = re.search(r'scanf_(\d+)', var_name)
        return int(match.group(1)) if match else 0
    
    def check_constraint_equivalence(self, constraints1, constraints2, vars1, vars2, var_mapping):
        """检查两组约束是否逻辑等价"""
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
        """构建完整的SMT公式"""
                
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
    """增强的路径分析器 - 支持四类判断"""
    
    def __init__(self):
        self.checker = EnhancedConstraintChecker()
        self.analysis_start_time = None
        self.analysis_end_time = None
        self.detailed_timing = []
        self.symbolic_execution_time = 0.0           
        
    def set_symbolic_execution_time(self, se_time):
        """设置符号执行时间（从外部传入）"""
        self.symbolic_execution_time = se_time
        
    def analyze_program_equivalence(self, file_prefix1, file_prefix2):
        """分析两个程序的完整等价性"""
        self.analysis_start_time = time.time()
        print(f"开始程序等价性分析: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
                  
        files1 = sorted(glob.glob(f"{file_prefix1}*.txt"))
        files2 = sorted(glob.glob(f"{file_prefix2}*.txt"))
        
        print(f"程序1路径数: {len(files1)}")
        print(f"程序2路径数: {len(files2)}")
        
                
        load_start = time.time()
        paths1 = []
        paths2 = []
        
        print("正在加载程序1的路径信息...")
        for file_path in files1:
            try:
                path_info = self.checker.extract_path_info(file_path)
                path_info['file'] = file_path
                paths1.append(path_info)
            except Exception as e:
                print(f"  ❌ 处理文件 {file_path} 时出错: {e}")
        
        print("正在加载程序2的路径信息...")
        for file_path in files2:
            try:
                path_info = self.checker.extract_path_info(file_path)
                path_info['file'] = file_path
                paths2.append(path_info)
            except Exception as e:
                print(f"  ❌ 处理文件 {file_path} 时出错: {e}")
        
        load_time = time.time() - load_start
        print(f"文件加载完成，耗时: {load_time:.3f} 秒")
        print(f"成功加载路径: {len(paths1)} vs {len(paths2)}")
        
                   
        comparison_start = time.time()
        results = self.find_equivalent_paths_four_categories(paths1, paths2)
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
        
                
        print(f"\n⏱️  时间统计:")
        print(f"  符号执行时间: {self.symbolic_execution_time:.3f} 秒")
        print(f"  文件加载时间: {load_time:.3f} 秒")
        print(f"  路径比较时间: {comparison_time:.3f} 秒")
        print(f"    - SMT约束验证: {self.checker.constraint_time:.3f} 秒 ({self.checker.constraint_call_count} 次调用)")
        print(f"    - 数组状态比较: {self.checker.array_time:.3f} 秒 ({self.checker.array_call_count} 次调用)")
        print(f"  总分析时间: {total_time:.3f} 秒")
        
        return results
    
    def find_equivalent_paths_four_categories(self, paths1, paths2):
        """使用四类判断寻找等价路径"""
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
        
        total_comparisons = len(paths1) * len(paths2)
        current_comparison = 0
        comparison_start_time = time.time()
        
        print(f"\n开始四类等价性验证 ({total_comparisons} 对比较):")
        
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
                    print(f"  比较 {i+1}-{j+1} ({current_comparison}/{total_comparisons}, {current_comparison/total_comparisons*100:.1f}%) "
                          f"- 预计剩余: {estimated_remaining:.1f}s")
                else:
                    print(f"  比较路径 {i+1} vs {j+1}")
                
                           
                constraint_start = time.time()
                constraint_result, constraint_details = self.checker.check_constraint_equivalence(
                    path1['constraints'], path2['constraints'],
                    path1['variables'], path2['variables'],
                    self.checker.create_variable_mapping(path1['variables'], path2['variables'])
                )
                constraint_time = time.time() - constraint_start
                
                            
                output1 = path1.get('program_output', '')
                output2 = path2.get('program_output', '')
                outputs_same = (output1 == output2)
                
                            
                pair_info = {
                    'path1_index': i,
                    'path2_index': j,
                    'path1_file': path1['file'],
                    'path2_file': path2['file'],
                    'constraint_result': constraint_result,
                    'constraint_details': constraint_details,
                    'output1': output1,
                    'output2': output2,
                    'outputs_same': outputs_same,
                    'constraint_time': constraint_time,
                    'comparison_time': time.time() - pair_start_time
                }
                
                if constraint_result == "equivalent" and outputs_same:
                                       
                    results['equivalent_pairs'].append(pair_info)
                    if i in results['unmatched_paths1']:
                        results['unmatched_paths1'].remove(i)
                    if j in results['unmatched_paths2']:
                        results['unmatched_paths2'].remove(j)
                    
                    print(f"    ✅ 等价 (约束等价+输出相同) 耗时: {pair_info['comparison_time']:.3f}s")
                    path1_matched = True
                    break           
                    
                elif constraint_result != "equivalent" and outputs_same:
                                               
                    results['suspicious_constraint_pairs'].append(pair_info)
                    print(f"    ⚠️  疑似不等价-约束 (约束不等价+输出相同) 耗时: {pair_info['comparison_time']:.3f}s")
                    
                elif constraint_result == "equivalent" and not outputs_same:
                                              
                    results['suspicious_output_pairs'].append(pair_info)
                    print(f"    ⚠️  疑似不等价-输出 (约束等价+输出不同) 耗时: {pair_info['comparison_time']:.3f}s")
                    
                else:
                                         
                    results['non_equivalent_pairs'].append(pair_info)
                    print(f"    ❌ 不等价 (约束不等价+输出不同) 耗时: {pair_info['comparison_time']:.3f}s")
                
                        
                self.checker.constraint_time += constraint_time
                self.checker.constraint_call_count += 1
                
                        
                timing_detail = {
                    'path1_index': i,
                    'path2_index': j,
                    'total_time': pair_info['comparison_time'],
                    'constraint_time': constraint_time,
                    'result': f"{constraint_result}_{'same_output' if outputs_same else 'diff_output'}"
                }
                self.detailed_timing.append(timing_detail)
            
            if not path1_matched:
                print(f"    ❌ 路径 {i+1} 未找到等价路径")
        
                 
        results['program_equivalent'] = (len(results['unmatched_paths1']) == 0 and 
                                       len(results['unmatched_paths2']) == 0)
        
        print(f"\n📊 四类分析结果:")
        print(f"  ✅ 等价路径对: {len(results['equivalent_pairs'])}")
        print(f"  ⚠️  疑似不等价-约束: {len(results['suspicious_constraint_pairs'])}")
        print(f"  ⚠️  疑似不等价-输出: {len(results['suspicious_output_pairs'])}")
        print(f"  ❌ 不等价路径对: {len(results['non_equivalent_pairs'])}")
        print(f"  程序1未匹配路径: {len(results['unmatched_paths1'])}")
        print(f"  程序2未匹配路径: {len(results['unmatched_paths2'])}")
        print(f"  程序整体等价性: {'✅ 等价' if results['program_equivalent'] else '❌ 不等价'}")
        
        return results
    
    def generate_comprehensive_report(self, results, output_file="enhanced_equivalence_report.txt"):
        """生成详细的等价性分析报告"""
        with open(output_file, "w", encoding='utf-8') as f:
            f.write("增强的程序等价性分析报告（四类判断）\n")
            f.write("=" * 60 + "\n\n")
            
                  
            f.write("📋 总体结论:\n")
            f.write("-" * 30 + "\n")
            equivalence_status = "✅ 等价" if results['program_equivalent'] else "❌ 不等价"
            f.write(f"程序等价性: {equivalence_status}\n\n")
            
                  
            f.write("📊 四类分析统计:\n")
            f.write("-" * 30 + "\n")
            f.write(f"✅ 等价路径对: {len(results['equivalent_pairs'])}\n")
            f.write(f"⚠️  疑似不等价-约束: {len(results['suspicious_constraint_pairs'])}\n")
            f.write(f"⚠️  疑似不等价-输出: {len(results['suspicious_output_pairs'])}\n")
            f.write(f"❌ 不等价路径对: {len(results['non_equivalent_pairs'])}\n")
            f.write(f"程序1未匹配路径: {len(results['unmatched_paths1'])}\n")
            f.write(f"程序2未匹配路径: {len(results['unmatched_paths2'])}\n\n")
            
                  
            if 'timing_info' in results:
                timing = results['timing_info']
                f.write("⏱️  时间统计:\n")
                f.write("-" * 30 + "\n")
                f.write(f"分析开始时间: {timing['start_time']}\n")
                f.write(f"分析结束时间: {timing['end_time']}\n")
                f.write(f"总分析时间: {timing['total_time']:.3f} 秒\n")
                f.write(f"  - 符号执行时间: {timing['symbolic_execution_time']:.3f} 秒\n")
                f.write(f"  - 文件加载时间: {timing['load_time']:.3f} 秒\n")
                f.write(f"  - 路径比较时间: {timing['comparison_time']:.3f} 秒\n")
                f.write(f"    * SMT约束验证: {timing['constraint_total_time']:.3f} 秒 ({timing['constraint_call_count']} 次)\n")
                f.write(f"    * 数组状态比较: {timing['array_total_time']:.3f} 秒 ({timing['array_call_count']} 次)\n")
                f.write(f"平均SMT求解时间: {timing['constraint_avg_time']:.3f} 秒\n")
                f.write(f"平均数组比较时间: {timing['array_avg_time']:.3f} 秒\n\n")
            
                     
            if results['equivalent_pairs']:
                f.write("✅ 等价路径对:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['equivalent_pairs'], 1):
                    f.write(f"{idx}. 路径 {pair['path1_index']+1} <-> 路径 {pair['path2_index']+1}\n")
                    f.write(f"   文件1: {pair['path1_file']}\n")
                    f.write(f"   文件2: {pair['path2_file']}\n")
                    f.write(f"   约束结果: {pair['constraint_result']}\n")
                    f.write(f"   输出1: {pair['output1']}\n")
                    f.write(f"   输出2: {pair['output2']}\n")
                    f.write(f"   比较耗时: {pair['comparison_time']:.3f} 秒\n\n")
            
                        
            if results['suspicious_constraint_pairs']:
                f.write("⚠️  疑似不等价-约束 (约束不等价但输出相同):\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['suspicious_constraint_pairs'], 1):
                    f.write(f"{idx}. 路径 {pair['path1_index']+1} vs 路径 {pair['path2_index']+1}\n")
                    f.write(f"   文件1: {pair['path1_file']}\n")
                    f.write(f"   文件2: {pair['path2_file']}\n")
                    f.write(f"   约束结果: {pair['constraint_result']}\n")
                    f.write(f"   输出1: {pair['output1']}\n")
                    f.write(f"   输出2: {pair['output2']}\n")
                    f.write(f"   比较耗时: {pair['comparison_time']:.3f} 秒\n\n")
            
                        
            if results['suspicious_output_pairs']:
                f.write("⚠️  疑似不等价-输出 (约束等价但输出不同):\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['suspicious_output_pairs'], 1):
                    f.write(f"{idx}. 路径 {pair['path1_index']+1} vs 路径 {pair['path2_index']+1}\n")
                    f.write(f"   文件1: {pair['path1_file']}\n")
                    f.write(f"   文件2: {pair['path2_file']}\n")
                    f.write(f"   约束结果: {pair['constraint_result']}\n")
                    f.write(f"   输出1: {pair['output1']}\n")
                    f.write(f"   输出2: {pair['output2']}\n")
                    f.write(f"   比较耗时: {pair['comparison_time']:.3f} 秒\n\n")
            
                      
            if results['non_equivalent_pairs']:
                f.write("❌ 不等价路径对:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['non_equivalent_pairs'], 1):
                    f.write(f"{idx}. 路径 {pair['path1_index']+1} vs 路径 {pair['path2_index']+1}\n")
                    f.write(f"   文件1: {pair['path1_file']}\n")
                    f.write(f"   文件2: {pair['path2_file']}\n")
                    f.write(f"   约束结果: {pair['constraint_result']}\n")
                    f.write(f"   输出1: {pair['output1']}\n")
                    f.write(f"   输出2: {pair['output2']}\n")
                    f.write(f"   比较耗时: {pair['comparison_time']:.3f} 秒\n\n")
            
                   
            if results['unmatched_paths1']:
                f.write("❌ 程序1中的未匹配路径:\n")
                f.write("-" * 30 + "\n")
                for idx in results['unmatched_paths1']:
                    f.write(f"  路径 {idx+1}\n")
                f.write("\n")
            
            if results['unmatched_paths2']:
                f.write("❌ 程序2中的未匹配路径:\n")
                f.write("-" * 30 + "\n")
                for idx in results['unmatched_paths2']:
                    f.write(f"  路径 {idx+1}\n")
                f.write("\n")
        
        print(f"📄 详细报告已保存到: {output_file}")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='增强的程序等价性分析器：四类判断流程')
    parser.add_argument('prefix1', help='第一个程序路径文件的前缀')
    parser.add_argument('prefix2', help='第二个程序路径文件的前缀')
    parser.add_argument('--output', default='enhanced_equivalence_report.txt', help='输出报告文件')
    parser.add_argument('--timeout', type=int, default=30000, help='Z3求解器超时时间(毫秒)')
    parser.add_argument('--se-time', type=float, default=0.0, help='符号执行时间(秒)，用于统计')
    
    args = parser.parse_args()
    
    analyzer = EnhancedPathAnalyzer()
    analyzer.checker.timeout = args.timeout
    analyzer.set_symbolic_execution_time(args.se_time)
    
    print("🚀 开始增强的程序等价性分析...")
    print("=" * 60)
    print("四类判断流程:")
    print("  1️⃣  约束等价且输出相同 → 等价")
    print("  2️⃣  约束不等价但输出相同 → 疑似不等价（约束）")
    print("  3️⃣  约束等价但输出不同 → 疑似不等价（输出）")
    print("  4️⃣  约束不等价且输出不同 → 不等价")
    print("=" * 60)
    
    results = analyzer.analyze_program_equivalence(args.prefix1, args.prefix2)
    
    analyzer.generate_comprehensive_report(results, args.output)
    
    print("\n" + "=" * 60)
    print("🎯 最终分析结果:")
    print(f"  程序等价性: {'✅ 等价' if results['program_equivalent'] else '❌ 不等价'}")
    print(f"  ✅ 等价路径对: {len(results['equivalent_pairs'])}")
    print(f"  ⚠️  疑似不等价-约束: {len(results['suspicious_constraint_pairs'])}")
    print(f"  ⚠️  疑似不等价-输出: {len(results['suspicious_output_pairs'])}")
    print(f"  ❌ 不等价路径对: {len(results['non_equivalent_pairs'])}")
    print(f"  总分析路径对: {len(results['equivalent_pairs']) + len(results['suspicious_constraint_pairs']) + len(results['suspicious_output_pairs']) + len(results['non_equivalent_pairs'])}")
    
    if 'timing_info' in results:
        timing = results['timing_info']
        print(f"\n⏱️  性能统计:")
        print(f"  总耗时: {timing['total_time']:.3f} 秒")
        print(f"  符号执行: {timing['symbolic_execution_time']:.3f} 秒")
        print(f"  SMT求解: {timing['constraint_total_time']:.3f} 秒 ({timing['constraint_call_count']} 次)")
        print(f"  数组比较: {timing['array_total_time']:.3f} 秒 ({timing['array_call_count']} 次)")
    
    print("=" * 60)
    print("✅ 分析完成！详细报告请查看输出文件。")

if __name__ == "__main__":
    main()
