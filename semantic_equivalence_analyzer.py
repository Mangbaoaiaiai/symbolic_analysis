#!/usr/bin/env python3
"""
枚举匹配路径对，然后检查约束语义等价性

基于约束语义等价性的路径分析器
通过Z3验证约束公式的逻辑等价性，而不是比较变量值或程序输出
"""

import re
import z3
from z3 import *
import glob
import time
import datetime
from itertools import combinations
from collections import defaultdict

class ConstraintEquivalenceChecker:
    """约束等价性检查器"""
    
    def __init__(self, timeout=30000):
        self.timeout = timeout
        self.z3_total_time = 0.0
        self.z3_call_count = 0
        
    def normalize_variable_names(self, formula, var_mapping):
        """标准化变量名，使两个公式可以比较"""
        for old_name, new_name in var_mapping.items():
            formula = re.sub(rf'\b{old_name}\b', new_name, formula)
        return formula
    
    def extract_constraint_formula(self, file_path):
        """从文件中提取完整的约束公式"""
        with open(file_path, 'r') as f:
            content = f.read()
        
        # 移除注释
        lines = [line for line in content.splitlines() if not line.strip().startswith(';')]
        content = '\n'.join(lines)
        
        # 提取变量声明
        variables = {}
        var_pattern = r'\(declare-fun\s+(\w+)\s+\(\)\s+\(_\s+BitVec\s+(\d+)\)\)'
        for match in re.finditer(var_pattern, content):
            var_name, bit_width = match.groups()
            variables[var_name] = int(bit_width)
        
        # 提取约束
        constraints = []
        constraint_pattern = r'\(assert\s+(.*?)\)(?=\s*(?:\(assert|\(check-sat|$))'
        for match in re.finditer(constraint_pattern, content, re.DOTALL):
            constraint = match.group(1).strip()
            constraints.append(constraint)
        
        return variables, constraints
    
    def create_variable_mapping(self, vars1, vars2):
        """创建变量映射，将两组变量对应起来"""
        # 策略1：按照变量名的模式匹配
        mapping = {}
        
        # 提取scanf变量的索引
        scanf_vars1 = [(name, self.extract_scanf_index(name)) for name in vars1.keys() if 'scanf' in name]
        scanf_vars2 = [(name, self.extract_scanf_index(name)) for name in vars2.keys() if 'scanf' in name]
        
        # 按索引排序
        scanf_vars1.sort(key=lambda x: x[1])
        scanf_vars2.sort(key=lambda x: x[1])
        
        # 建立映射
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
            # 创建标准化的公式
            smt_formula1 = self.build_smt_formula(vars1, constraints1)
            smt_formula2 = self.build_smt_formula(vars2, constraints2, var_mapping)
            
            # 解析公式
            F1 = parse_smt2_string(smt_formula1)
            F2 = parse_smt2_string(smt_formula2)
            
            # 合并为单个公式
            formula1 = And(*F1) if len(F1) > 1 else F1[0] if F1 else BoolVal(True)
            formula2 = And(*F2) if len(F2) > 1 else F2[0] if F2 else BoolVal(True)
            
            # 检查 (F1 ∧ ¬F2) ∨ (¬F1 ∧ F2) 是否可满足
            # 如果不可满足，则F1 ≡ F2
            equivalence_check = Or(
                And(formula1, Not(formula2)),
                And(Not(formula1), formula2)
            )
            
            solver.add(equivalence_check)
            result = solver.check()
            
            # 记录Z3求解时间
            solve_time = time.time() - start_time
            self.z3_total_time += solve_time
            self.z3_call_count += 1
            
            if result == unsat:
                return "equivalent", {"solve_time": solve_time}
            elif result == sat:
                model = solver.model()
                return "not_equivalent", {"model": model, "solve_time": solve_time}
            else:
                return "unknown", {"solve_time": solve_time}
                
        except Exception as e:
            solve_time = time.time() - start_time
            self.z3_total_time += solve_time
            self.z3_call_count += 1
            return "error", {"error": str(e), "solve_time": solve_time}
    
    def build_smt_formula(self, variables, constraints, var_mapping=None):
        """构建完整的SMT公式"""
        # 应用变量映射
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
        
        # 构建SMT-LIB格式的公式
        formula_parts = ["(set-logic QF_BV)"]
        
        # 添加变量声明
        for var_name, bit_width in variables.items():
            formula_parts.append(f"(declare-fun {var_name} () (_ BitVec {bit_width}))")
        
        # 添加约束
        for constraint in constraints:
            formula_parts.append(f"(assert {constraint})")
        
        formula_parts.append("(check-sat)")
        
        return '\n'.join(formula_parts)

class PathClusterAnalyzer:
    """路径聚类分析器"""
    
    def __init__(self):
        self.equivalence_checker = ConstraintEquivalenceChecker()
        self.analysis_start_time = None
        self.analysis_end_time = None
        self.detailed_timing = []
        
    def analyze_path_clusters(self, file_prefix1, file_prefix2):
        """分析两组路径文件的聚类等价性"""
        self.analysis_start_time = time.time()
        print(f"开始分析时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 查找所有路径文件
        files1 = sorted(glob.glob(f"{file_prefix1}*.txt"))
        files2 = sorted(glob.glob(f"{file_prefix2}*.txt"))
        
        print(f"分析路径文件: {len(files1)} vs {len(files2)}")
        
        # 提取所有路径的约束
        load_start = time.time()
        paths1 = []
        paths2 = []
        
        for file_path in files1:
            try:
                variables, constraints = self.equivalence_checker.extract_constraint_formula(file_path)
                paths1.append({
                    'file': file_path,
                    'variables': variables,
                    'constraints': constraints
                })
            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {e}")
        
        for file_path in files2:
            try:
                variables, constraints = self.equivalence_checker.extract_constraint_formula(file_path)
                paths2.append({
                    'file': file_path,
                    'variables': variables,
                    'constraints': constraints
                })
            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {e}")
        
        load_time = time.time() - load_start
        print(f"成功加载路径: {len(paths1)} vs {len(paths2)}")
        print(f"文件加载耗时: {load_time:.3f} 秒")
        
        # 执行等价性分析
        comparison_start = time.time()
        results = self.find_equivalent_paths(paths1, paths2)
        comparison_time = time.time() - comparison_start
        
        self.analysis_end_time = time.time()
        total_time = self.analysis_end_time - self.analysis_start_time
        
        print(f"\n时间统计:")
        print(f"  文件加载: {load_time:.3f} 秒")
        print(f"  路径比较: {comparison_time:.3f} 秒")
        print(f"  Z3求解总时间: {self.equivalence_checker.z3_total_time:.3f} 秒")
        print(f"  Z3调用次数: {self.equivalence_checker.z3_call_count}")
        print(f"  平均每次Z3求解: {self.equivalence_checker.z3_total_time/max(1, self.equivalence_checker.z3_call_count):.3f} 秒")
        print(f"  总分析时间: {total_time:.3f} 秒")
        
        # 添加时间信息到结果中
        results['timing_info'] = {
            'total_time': total_time,
            'load_time': load_time,
            'comparison_time': comparison_time,
            'z3_total_time': self.equivalence_checker.z3_total_time,
            'z3_call_count': self.equivalence_checker.z3_call_count,
            'z3_avg_time': self.equivalence_checker.z3_total_time/max(1, self.equivalence_checker.z3_call_count),
            'detailed_timing': self.detailed_timing,
            'start_time': datetime.datetime.fromtimestamp(self.analysis_start_time).strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': datetime.datetime.fromtimestamp(self.analysis_end_time).strftime('%Y-%m-%d %H:%M:%S')
        }
        
        return results
    
    def find_equivalent_paths(self, paths1, paths2):
        """寻找等价路径"""
        results = {
            'equivalent_pairs': [],
            'non_equivalent_pairs': [],
            'error_pairs': [],
            'unmatched_paths1': list(range(len(paths1))),
            'unmatched_paths2': list(range(len(paths2)))
        }
        
        total_comparisons = len(paths1) * len(paths2)
        current_comparison = 0
        comparison_start_time = time.time()
        
        for i, path1 in enumerate(paths1):
            for j, path2 in enumerate(paths2):
                current_comparison += 1
                pair_start_time = time.time()
                
                # 估算剩余时间
                if current_comparison > 1:
                    elapsed = time.time() - comparison_start_time
                    avg_time_per_comparison = elapsed / (current_comparison - 1)
                    remaining_comparisons = total_comparisons - current_comparison
                    estimated_remaining = avg_time_per_comparison * remaining_comparisons
                    print(f"比较进度: {current_comparison}/{total_comparisons} ({current_comparison/total_comparisons*100:.1f}%) "
                          f"- 预计剩余: {estimated_remaining:.1f}秒")
                else:
                    print(f"比较进度: {current_comparison}/{total_comparisons} ({current_comparison/total_comparisons*100:.1f}%)")
                
                # 创建变量映射
                var_mapping = self.equivalence_checker.create_variable_mapping(
                    path1['variables'], path2['variables']
                )
                
                # 检查等价性
                result, extra_info = self.equivalence_checker.check_constraint_equivalence(
                    path1['constraints'], path2['constraints'],
                    path1['variables'], path2['variables'],
                    var_mapping
                )
                
                pair_time = time.time() - pair_start_time
                
                # 记录详细时间信息
                timing_detail = {
                    'path1_index': i,
                    'path2_index': j,
                    'total_time': pair_time,
                    'z3_time': extra_info.get('solve_time', 0) if extra_info else 0,
                    'result': result
                }
                self.detailed_timing.append(timing_detail)
                
                pair_info = {
                    'path1_index': i,
                    'path2_index': j,
                    'path1_file': path1['file'],
                    'path2_file': path2['file'],
                    'variable_mapping': var_mapping,
                    'extra_info': extra_info,
                    'comparison_time': pair_time
                }
                
                if result == "equivalent":
                    results['equivalent_pairs'].append(pair_info)
                    # 从未匹配列表中移除
                    if i in results['unmatched_paths1']:
                        results['unmatched_paths1'].remove(i)
                    if j in results['unmatched_paths2']:
                        results['unmatched_paths2'].remove(j)
                    
                    print(f"  ✓ 等价: {path1['file']} <-> {path2['file']} (耗时: {pair_time:.3f}s)")
                    break  # 找到匹配后跳出内层循环
                    
                elif result == "not_equivalent":
                    results['non_equivalent_pairs'].append(pair_info)
                    
                elif result == "error":
                    results['error_pairs'].append(pair_info)
                    print(f"  ❌ 错误: {path1['file']} vs {path2['file']}: {extra_info.get('error', '未知错误')} (耗时: {pair_time:.3f}s)")
        
        return results
    
    def generate_report(self, results, output_file="semantic_equivalence_report.txt"):
        """生成等价性分析报告"""
        with open(output_file, "w", encoding='utf-8') as f:
            f.write("基于约束语义等价性的路径分析报告\n")
            f.write("=" * 50 + "\n\n")
            
            # 添加时间统计信息
            if 'timing_info' in results:
                timing = results['timing_info']
                f.write("时间统计:\n")
                f.write("-" * 30 + "\n")
                f.write(f"  分析开始时间: {timing['start_time']}\n")
                f.write(f"  分析结束时间: {timing['end_time']}\n")
                f.write(f"  总分析时间: {timing['total_time']:.3f} 秒\n")
                f.write(f"  文件加载时间: {timing['load_time']:.3f} 秒\n")
                f.write(f"  路径比较时间: {timing['comparison_time']:.3f} 秒\n")
                f.write(f"  Z3求解总时间: {timing['z3_total_time']:.3f} 秒\n")
                f.write(f"  Z3调用次数: {timing['z3_call_count']}\n")
                f.write(f"  平均每次Z3求解: {timing['z3_avg_time']:.3f} 秒\n")
                f.write(f"  Z3时间占比: {timing['z3_total_time']/timing['total_time']*100:.1f}%\n\n")
            
            f.write(f"分析统计:\n")
            f.write(f"  等价路径对: {len(results['equivalent_pairs'])}\n")
            f.write(f"  非等价路径对: {len(results['non_equivalent_pairs'])}\n")
            f.write(f"  分析错误: {len(results['error_pairs'])}\n")
            f.write(f"  未匹配路径1: {len(results['unmatched_paths1'])}\n")
            f.write(f"  未匹配路径2: {len(results['unmatched_paths2'])}\n\n")
            
            if results['equivalent_pairs']:
                f.write("等价路径对:\n")
                f.write("-" * 30 + "\n")
                for pair in results['equivalent_pairs']:
                    f.write(f"路径 {pair['path1_index']+1} <-> 路径 {pair['path2_index']+1}\n")
                    f.write(f"  文件1: {pair['path1_file']}\n")
                    f.write(f"  文件2: {pair['path2_file']}\n")
                    f.write(f"  比较耗时: {pair.get('comparison_time', 0):.3f} 秒\n")
                    f.write(f"  变量映射: {pair['variable_mapping']}\n\n")
            
            if results['unmatched_paths1']:
                f.write("仅在集合1中的路径:\n")
                f.write("-" * 30 + "\n")
                for idx in results['unmatched_paths1']:
                    f.write(f"  路径 {idx+1}\n")
                f.write("\n")
            
            if results['unmatched_paths2']:
                f.write("仅在集合2中的路径:\n")
                f.write("-" * 30 + "\n")
                for idx in results['unmatched_paths2']:
                    f.write(f"  路径 {idx+1}\n")
                f.write("\n")
            
            if results['error_pairs']:
                f.write("分析错误的路径对:\n")
                f.write("-" * 30 + "\n")
                for pair in results['error_pairs']:
                    f.write(f"路径 {pair['path1_index']+1} vs 路径 {pair['path2_index']+1}\n")
                    error_msg = pair['extra_info'].get('error', '未知错误') if pair['extra_info'] else '未知错误'
                    f.write(f"  错误信息: {error_msg}\n")
                    f.write(f"  比较耗时: {pair.get('comparison_time', 0):.3f} 秒\n\n")
            
            # 添加详细时间分析
            if 'timing_info' in results and results['timing_info']['detailed_timing']:
                f.write("详细时间分析:\n")
                f.write("-" * 30 + "\n")
                detailed = results['timing_info']['detailed_timing']
                
                # 统计不同结果类型的时间
                equiv_times = [t['total_time'] for t in detailed if t['result'] == 'equivalent']
                non_equiv_times = [t['total_time'] for t in detailed if t['result'] == 'not_equivalent'] 
                error_times = [t['total_time'] for t in detailed if t['result'] == 'error']
                
                if equiv_times:
                    f.write(f"  等价比较平均时间: {sum(equiv_times)/len(equiv_times):.3f} 秒\n")
                if non_equiv_times:
                    f.write(f"  非等价比较平均时间: {sum(non_equiv_times)/len(non_equiv_times):.3f} 秒\n")
                if error_times:
                    f.write(f"  错误比较平均时间: {sum(error_times)/len(error_times):.3f} 秒\n")
        
        print(f"分析报告已保存到: {output_file}")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='基于约束语义等价性的路径分析')
    parser.add_argument('prefix1', help='第一组路径文件的前缀')
    parser.add_argument('prefix2', help='第二组路径文件的前缀')
    parser.add_argument('--output', default='semantic_equivalence_report.txt', help='输出报告文件')
    parser.add_argument('--timeout', type=int, default=30000, help='Z3求解器超时时间(毫秒)')
    
    args = parser.parse_args()
    
    analyzer = PathClusterAnalyzer()
    analyzer.equivalence_checker.timeout = args.timeout
    
    print("开始基于约束语义的等价性分析...")
    results = analyzer.analyze_path_clusters(args.prefix1, args.prefix2)
    
    analyzer.generate_report(results, args.output)
    
    print(f"\n分析完成！")
    print(f"  发现等价路径对: {len(results['equivalent_pairs'])}")
    print(f"  分析的总路径对: {len(results['equivalent_pairs']) + len(results['non_equivalent_pairs']) + len(results['error_pairs'])}")
    if 'timing_info' in results:
        print(f"  总耗时: {results['timing_info']['total_time']:.3f} 秒")

if __name__ == "__main__":
    main() 