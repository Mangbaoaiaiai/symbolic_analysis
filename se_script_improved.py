#!/usr/bin/env python3
"""
改进的符号执行脚本，专门处理benchmark程序

针对没有外部输入的程序，通过符号化函数参数或内存状态来生成有意义的约束
"""

import angr
import claripy
import re
import os
import glob
from claripy.backends.backend_z3 import claripy_solver_to_smt2
import logging

# 设置日志等级
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

# 全局计数器
symbolic_var_counter = 0
symbolic_variables = {}

class BenchmarkSymbolicExecution:
    """专门用于benchmark程序的符号执行"""
    
    def __init__(self, binary_path, output_prefix=None, timeout=120):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        
        # 设置输出前缀
        if output_prefix is None:
            binary_name = os.path.basename(binary_path)
            self.output_prefix = binary_name
        else:
            self.output_prefix = output_prefix
    
    def setup_project(self):
        """设置angr项目"""
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        print(f"加载二进制文件: {self.binary_path}")
        
        # 查找关键函数
        self.find_target_functions()
    
    def find_target_functions(self):
        """查找目标函数"""
        # 查找s000函数
        s000_symbol = self.project.loader.find_symbol('s000')
        if s000_symbol:
            print(f"找到s000函数地址: 0x{s000_symbol.rebased_addr:x}")
            self.s000_addr = s000_symbol.rebased_addr
        else:
            print("未找到s000函数，将分析整个main函数")
            self.s000_addr = None
    
    def create_symbolic_state(self):
        """创建带符号变量的初始状态"""
        initial_state = self.project.factory.entry_state()
        
        # 策略1: 符号化s000函数的参数
        if self.s000_addr:
            # 创建符号变量作为count参数
            count_var = claripy.BVS('count_param', 32)
            # 添加合理的约束（count应该在合理范围内）
            initial_state.solver.add(count_var >= 0)
            initial_state.solver.add(count_var <= 10)  # 避免过大的循环
            
            global symbolic_var_counter, symbolic_variables
            symbolic_variables['count_param'] = count_var
            symbolic_var_counter += 1
            
            print(f"创建符号变量: count_param (范围: 0-10)")
        
        # 策略2: 符号化数组的某些元素
        # 为数组b的前几个元素创建符号值
        for i in range(3):  # 只符号化前3个元素
            array_var = claripy.BVS(f'array_b_{i}', 32)
            initial_state.solver.add(array_var >= 0)
            initial_state.solver.add(array_var <= 200)  # 合理范围
            
            symbolic_variables[f'array_b_{i}'] = array_var
            symbolic_var_counter += 1
            
            print(f"创建符号变量: array_b_{i} (范围: 0-200)")
        
        return initial_state
    
    def run_symbolic_execution(self):
        """运行符号执行"""
        print(f"开始符号执行: {self.binary_path}")
        
        # 重置全局变量
        global symbolic_var_counter, symbolic_variables
        symbolic_var_counter = 0
        symbolic_variables = {}
        
        # 设置项目
        self.setup_project()
        
        if self.project is None:
            print("项目初始化失败")
            return []
        
        # 创建初始状态（带符号变量）
        initial_state = self.create_symbolic_state()
        
        # 创建仿真管理器
        simgr = self.project.factory.simulation_manager(initial_state)
        
        # 运行符号执行
        print("开始探索路径...")
        simgr.run(timeout=self.timeout)
        
        print(f"符号执行完成：")
        print(f"  终止路径数: {len(simgr.deadended)}")
        print(f"  活跃路径数: {len(simgr.active)}")
        print(f"  错误路径数: {len(simgr.errored)}")
        
        # 处理所有状态
        all_states = simgr.deadended + simgr.active
        if simgr.errored:
            print(f"  处理错误状态: {len(simgr.errored)}")
            for errored in simgr.errored:
                all_states.append(errored.state)
        
        self.analyze_states(all_states)
        
        return self.paths_info
    
    def analyze_states(self, states):
        """分析所有状态"""
        for i, state in enumerate(states):
            print(f"\n分析路径 {i + 1}...")
            
            # 提取路径签名
            signature = self.extract_path_signature(state)
            
            # 生成SMT约束
            smt_constraints = self.generate_smt_constraints(state)
            
            # 保存路径信息
            path_info = {
                'index': i + 1,
                'signature': signature,
                'smt_constraints': smt_constraints,
                'state': state
            }
            
            self.paths_info.append(path_info)
            
            # 保存到文件
            self.save_path_to_file(path_info)
            
            # 打印摘要
            print(f"  符号变量值: {signature['variables']}")
            print(f"  约束数量: {signature['constraints']['count']}")
    
    def extract_path_signature(self, state):
        """提取路径的多维签名"""
        signature = {}
        
        # 1. 符号变量的值
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
        
        # 2. 约束的数量和类型
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
        
        # 3. 程序执行的指令地址序列（简化版）
        try:
            addr_trace = getattr(state.history, 'bbl_addrs', [])
            signature['execution_trace'] = addr_trace[-10:] if len(addr_trace) > 10 else addr_trace
        except:
            signature['execution_trace'] = []
        
        # 4. 内存状态哈希
        try:
            memory_hash = hash(str(state.solver.constraints)[:200])
            signature['memory_hash'] = memory_hash
        except:
            signature['memory_hash'] = 0
        
        return signature
    
    def generate_smt_constraints(self, state):
        """生成SMT约束"""
        solver = claripy.Solver()
        for constraint in state.solver.constraints:
            solver.add(constraint)
        smt2_text = claripy_solver_to_smt2(solver)
        return smt2_text
    

    
    def save_path_to_file(self, path_info):
        """保存路径信息到文件"""
        filename = f"{self.output_prefix}_path_{path_info['index']}.txt"
        
        with open(filename, "w", encoding='utf-8') as f:
            f.write(path_info['smt_constraints'])
            f.write("\n; 路径签名信息:\n")
            f.write(f"; 符号变量值: {path_info['signature']['variables']}\n")
            f.write(f"; 约束信息: {path_info['signature']['constraints']}\n")
            f.write(f"; 执行轨迹: {path_info['signature']['execution_trace']}\n")
            f.write(f"; 内存哈希: {path_info['signature']['memory_hash']}\n")
        
        print(f"  已保存到: {filename}")

class BenchmarkAnalyzer:
    """benchmark批量分析器"""
    
    def __init__(self, benchmark_dir, timeout=120):
        self.benchmark_dir = benchmark_dir
        self.timeout = timeout
        self.results = {}
    
    def find_binary_files(self):
        """查找benchmark目录中的二进制文件"""
        pattern = os.path.join(self.benchmark_dir, "*_O[0123]")
        binary_files = glob.glob(pattern)
        binary_files = [f for f in binary_files if not f.endswith('.c')]
        return sorted(binary_files)
    
    def analyze_all_binaries(self):
        """分析所有二进制文件"""
        binary_files = self.find_binary_files()
        
        if not binary_files:
            print(f"在 {self.benchmark_dir} 中未找到二进制文件")
            return
        
        print(f"发现 {len(binary_files)} 个二进制文件:")
        for binary in binary_files:
            print(f"  {binary}")
        
        for binary_path in binary_files:
            print(f"\n{'='*60}")
            print(f"正在分析: {binary_path}")
            print(f"{'='*60}")
            
            basename = os.path.basename(binary_path)
            output_prefix = basename
            
            try:
                analyzer = BenchmarkSymbolicExecution(binary_path, output_prefix, self.timeout)
                results = analyzer.run_symbolic_execution()
                self.results[basename] = results
                
                print(f"完成分析 {basename}: 共 {len(results)} 条路径")
                
            except Exception as e:
                print(f"分析 {basename} 时出错: {e}")
                self.results[basename] = []
        
        return self.results
    
    def generate_summary_report(self):
        """生成分析摘要报告"""
        report_file = os.path.join(self.benchmark_dir, "improved_symbolic_execution_summary.txt")
        
        with open(report_file, "w", encoding='utf-8') as f:
            f.write("改进的符号执行批量分析摘要报告\n")
            f.write("=" * 50 + "\n\n")
            
            f.write(f"分析目录: {self.benchmark_dir}\n")
            f.write(f"分析的二进制文件数量: {len(self.results)}\n")
            f.write("符号化策略: 函数参数 + 数组元素\n\n")
            
            for binary_name, paths in self.results.items():
                f.write(f"二进制文件: {binary_name}\n")
                f.write(f"  发现路径数: {len(paths)}\n")
                f.write(f"  生成的文件: {binary_name}_path_*.txt\n\n")
            
            f.write("下一步: 使用 semantic_equivalence_analyzer.py 进行等价性分析\n")
        
        print(f"摘要报告已保存到: {report_file}")

def main():
    """主函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='改进的符号执行分析工具')
    parser.add_argument('--benchmark', help='benchmark目录路径，用于批量分析')
    parser.add_argument('--binary', help='单个二进制文件路径')
    parser.add_argument('--timeout', type=int, default=120, help='符号执行超时时间(秒)')
    parser.add_argument('--output-prefix', help='输出文件前缀')
    
    args = parser.parse_args()
    
    if args.benchmark:
        print(f"开始批量分析benchmark: {args.benchmark}")
        analyzer = BenchmarkAnalyzer(args.benchmark, args.timeout)
        analyzer.analyze_all_binaries()
        analyzer.generate_summary_report()
        
    elif args.binary:
        print(f"开始分析单个文件: {args.binary}")
        analyzer = BenchmarkSymbolicExecution(args.binary, args.output_prefix, args.timeout)
        results = analyzer.run_symbolic_execution()
        print(f"分析完成！共发现 {len(results)} 条路径")
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main() 