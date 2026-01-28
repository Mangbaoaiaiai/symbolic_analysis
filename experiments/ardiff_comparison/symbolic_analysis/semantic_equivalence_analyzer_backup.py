                      
"""
增强的路径等价性分析器：三步验证流程
1. 约束语义等价性
2. 数组初始状态一致性
3. 数组最终状态一致性

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
        """从文件中提取完整的路径信息：约束+数组状态"""
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
    
    def check_three_step_equivalence(self, path1_info, path2_info):
        """三步等价性检查：约束->数组初始状态->数组最终状态"""
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
        
                     
        print("    步骤1: 检查约束等价性...")
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
            print(f"      ✓ 约束等价 (耗时: {constraint_time:.3f}s)")
            
                          
            print("    步骤2: 检查数组初始状态...")
            array_initial_start = time.time()
            initial_same, initial_details = self.array_comparator.compare_array_states(
                path1_info['array_initial'], path2_info['array_initial']
            )
            array_initial_time = time.time() - array_initial_start
            result['array_initial_time'] = array_initial_time
            result['details']['array_initial'] = initial_details
            
            if initial_same:
                result['array_initial_same'] = True
                print(f"      ✓ 数组初始状态相同 (耗时: {array_initial_time:.3f}s)")
                
                              
                print("    步骤3: 检查数组最终状态...")
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
                    print(f"      ✓ 数组最终状态相同 (耗时: {array_final_time:.3f}s)")
                    print("      🎉 三步验证全部通过，路径等价！")
                else:
                    print(f"      ❌ 数组最终状态不同: {final_details}")
            else:
                print(f"      ❌ 数组初始状态不同: {initial_details}")
        else:
            print(f"      ❌ 约束不等价: {constraint_result}")
        
        result['total_time'] = time.time() - total_start_time
        
                
        self.constraint_time += constraint_time
        self.constraint_call_count += 1
        if result['constraint_equivalent']:
            self.array_time += result['array_initial_time'] + result['array_final_time']
            self.array_call_count += 2
        
        return result
    
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
    """增强的路径分析器"""
    
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
        
                
        print(f"\n⏱️  时间统计:")
        print(f"  符号执行时间: {self.symbolic_execution_time:.3f} 秒")
        print(f"  文件加载时间: {load_time:.3f} 秒")
        print(f"  路径比较时间: {comparison_time:.3f} 秒")
        print(f"    - SMT约束验证: {self.checker.constraint_time:.3f} 秒 ({self.checker.constraint_call_count} 次调用)")
        print(f"    - 数组状态比较: {self.checker.array_time:.3f} 秒 ({self.checker.array_call_count} 次调用)")
        print(f"  总分析时间: {total_time:.3f} 秒")
        
        return results
    
    def find_equivalent_paths_three_step(self, paths1, paths2):
        """使用三步验证寻找等价路径"""
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
        
        print(f"\n开始三步等价性验证 ({total_comparisons} 对比较):")
        
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
                    
                    print(f"    🎉 完全等价! 耗时: {pair_time:.3f}s")
                    path1_matched = True
                    break           
                    
                elif (equivalence_result['constraint_equivalent'] or 
                      equivalence_result['array_initial_same'] or 
                      equivalence_result['array_final_same']):
                          
                    results['partial_equivalent_pairs'].append(pair_info)
                    print(f"    ⚠️  部分等价 (约束:{equivalence_result['constraint_equivalent']}, "
                          f"初始:{equivalence_result['array_initial_same']}, "
                          f"最终:{equivalence_result['array_final_same']}) 耗时: {pair_time:.3f}s")
                    
                else:
                         
                    results['non_equivalent_pairs'].append(pair_info)
                    
            if not path1_matched:
                print(f"    ❌ 路径 {i+1} 未找到等价路径")
        
                 
        results['program_equivalent'] = (len(results['unmatched_paths1']) == 0 and 
                                       len(results['unmatched_paths2']) == 0)
        
        print(f"\n📊 分析结果:")
        print(f"  完全等价路径对: {len(results['equivalent_pairs'])}")
        print(f"  部分等价路径对: {len(results['partial_equivalent_pairs'])}")
        print(f"  程序1未匹配路径: {len(results['unmatched_paths1'])}")
        print(f"  程序2未匹配路径: {len(results['unmatched_paths2'])}")
        print(f"  程序整体等价性: {'✅ 等价' if results['program_equivalent'] else '❌ 不等价'}")
        
        return results
    
    def generate_comprehensive_report(self, results, output_file="enhanced_equivalence_report.txt"):
        """生成详细的等价性分析报告"""
        with open(output_file, "w", encoding='utf-8') as f:
            f.write("增强的程序等价性分析报告\n")
            f.write("=" * 60 + "\n\n")
            
                  
            f.write("📋 总体结论:\n")
            f.write("-" * 30 + "\n")
            equivalence_status = "✅ 等价" if results['program_equivalent'] else "❌ 不等价"
            f.write(f"程序等价性: {equivalence_status}\n\n")
            
                  
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
            
                  
            f.write("📊 分析统计:\n")
            f.write("-" * 30 + "\n")
            f.write(f"完全等价路径对: {len(results['equivalent_pairs'])}\n")
            f.write(f"部分等价路径对: {len(results['partial_equivalent_pairs'])}\n")
            f.write(f"非等价路径对: {len(results['non_equivalent_pairs'])}\n")
            f.write(f"分析错误: {len(results['error_pairs'])}\n")
            f.write(f"程序1未匹配路径: {len(results['unmatched_paths1'])}\n")
            f.write(f"程序2未匹配路径: {len(results['unmatched_paths2'])}\n\n")
            
                       
            if results['equivalent_pairs']:
                f.write("✅ 完全等价路径对:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['equivalent_pairs'], 1):
                    f.write(f"{idx}. 路径 {pair['path1_index']+1} <-> 路径 {pair['path2_index']+1}\n")
                    f.write(f"   文件1: {pair['path1_file']}\n")
                    f.write(f"   文件2: {pair['path2_file']}\n")
                    f.write(f"   比较耗时: {pair['comparison_time']:.3f} 秒\n")
                    
                    equiv_result = pair['equivalence_result']
                    f.write(f"   详细时间:\n")
                    f.write(f"     - 约束验证: {equiv_result['constraint_time']:.3f} 秒\n")
                    f.write(f"     - 数组初始状态: {equiv_result['array_initial_time']:.3f} 秒\n")
                    f.write(f"     - 数组最终状态: {equiv_result['array_final_time']:.3f} 秒\n")
                    f.write(f"   变量映射: {equiv_result['variable_mapping']}\n\n")
            
                       
            if results['partial_equivalent_pairs']:
                f.write("⚠️  部分等价路径对:\n")
                f.write("-" * 30 + "\n")
                for idx, pair in enumerate(results['partial_equivalent_pairs'], 1):
                    f.write(f"{idx}. 路径 {pair['path1_index']+1} vs 路径 {pair['path2_index']+1}\n")
                    f.write(f"   文件1: {pair['path1_file']}\n")
                    f.write(f"   文件2: {pair['path2_file']}\n")
                    
                    equiv_result = pair['equivalence_result']
                    f.write(f"   等价性检查结果:\n")
                    f.write(f"     - 约束等价: {'✅' if equiv_result['constraint_equivalent'] else '❌'}\n")
                    f.write(f"     - 数组初始状态相同: {'✅' if equiv_result['array_initial_same'] else '❌'}\n")
                    f.write(f"     - 数组最终状态相同: {'✅' if equiv_result['array_final_same'] else '❌'}\n")
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
    
    parser = argparse.ArgumentParser(description='增强的程序等价性分析器：三步验证流程')
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
    print("三步验证流程:")
    print("  1️⃣  约束语义等价性验证 (Z3求解)")
    print("  2️⃣  数组初始状态一致性检查")
    print("  3️⃣  数组最终状态一致性检查")
    print("=" * 60)
    
    results = analyzer.analyze_program_equivalence(args.prefix1, args.prefix2)
    
    analyzer.generate_comprehensive_report(results, args.output)
    
    print("\n" + "=" * 60)
    print("🎯 最终分析结果:")
    print(f"  程序等价性: {'✅ 等价' if results['program_equivalent'] else '❌ 不等价'}")
    print(f"  完全等价路径对: {len(results['equivalent_pairs'])}")
    print(f"  部分等价路径对: {len(results['partial_equivalent_pairs'])}")
    print(f"  总分析路径对: {len(results['equivalent_pairs']) + len(results['partial_equivalent_pairs']) + len(results['non_equivalent_pairs'])}")
    
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