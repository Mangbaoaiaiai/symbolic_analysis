#!/usr/bin/env python3
"""
改进的符号执行脚本，获取路径签名信息

改进的符号执行脚本
修复了angr API兼容性问题，改善了路径标识方法
"""

import angr
import claripy
import re
from claripy.backends.backend_z3 import claripy_solver_to_smt2
import logging

# 设置日志等级
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

# 全局计数器
scanf_counter = 0
scanf_variables = {}

class ScanfSymProc(angr.SimProcedure):
    """改进的scanf符号化过程"""
    
    def run(self, fmt_ptr, value_ptr):
        global scanf_counter, scanf_variables
        
        # 创建更清晰的变量命名
        sym_var = claripy.BVS(f'scanf_{scanf_counter}', 32)
        
        # 存储符号变量引用
        scanf_variables[f'scanf_{scanf_counter}'] = sym_var
        scanf_counter += 1
        
        # 将符号变量写入内存
        self.state.memory.store(
            value_ptr,
            sym_var,
            endness=self.state.arch.memory_endness
        )
        
        return claripy.BVV(1, self.state.arch.bits)

class ImprovedPathAnalyzer:
    """改进的路径分析器"""
    
    def __init__(self, binary_path, timeout=120):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
    
    def setup_project(self):
        """设置angr项目"""
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        
        # Hook所有可能的scanf函数
        scanf_symbols = ['scanf', '__isoc99_scanf', '__isoc23_scanf', '__scanf_chk']
        for symbol in scanf_symbols:
            if self.project.loader.find_symbol(symbol):
                self.project.hook_symbol(symbol, ScanfSymProc())
                print(f"已hook符号: {symbol}")
    
    def extract_path_signature(self, state):
        """提取路径的多维签名"""
        signature = {}
        
        # 1. 符号变量的值
        global scanf_variables
        variable_values = {}
        for var_name, sym_var in scanf_variables.items():
            try:
                # 尝试获取具体值
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
            # 分析约束类型
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
        
        # 3. 程序输出
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            signature['output'] = output
        except:
            signature['output'] = ""
        
        # 4. 内存状态的哈希（简化版）
        try:
            # 获取一些关键内存位置的状态
            memory_hash = hash(str(state.solver.constraints)[:100])
            signature['memory_hash'] = memory_hash
        except:
            signature['memory_hash'] = 0
        
        return signature
    
    def run_symbolic_execution(self):
        """运行符号执行"""
        print(f"开始符号执行: {self.binary_path}")
        
        # 设置项目
        self.setup_project()
        
        if self.project is None:
            print("项目初始化失败")
            return []
        
        # 创建初始状态
        initial_state = self.project.factory.entry_state()
        
        # 创建仿真管理器
        simgr = self.project.factory.simulation_manager(initial_state)
        
        # 运行符号执行
        print("开始探索路径...")
        simgr.run(timeout=self.timeout)
        
        print(f"符号执行完成：")
        print(f"  终止路径数: {len(simgr.deadended)}")
        print(f"  活跃路径数: {len(simgr.active)}")
        print(f"  错误路径数: {len(simgr.errored)}")
        
        # 处理所有终止状态
        self.analyze_deadended_states(simgr.deadended)
        
        return self.paths_info
    
    def analyze_deadended_states(self, deadended_states):
        """分析所有终止状态"""
        for i, state in enumerate(deadended_states):
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
                'state': state  # 保留状态引用以便后续分析
            }
            
            self.paths_info.append(path_info)
            
            # 保存到文件
            self.save_path_to_file(path_info)
            
            # 打印摘要
            print(f"  变量值: {signature['variables']}")
            print(f"  约束数量: {signature['constraints']['count']}")
            print(f"  程序输出: {signature['output']}")
    
    def generate_smt_constraints(self, state):
        """生成SMT约束"""
        try:
            solver = claripy.Solver()
            for constraint in state.solver.constraints:
                solver.add(constraint)
            smt2_text = claripy_solver_to_smt2(solver)
            return smt2_text
        except Exception as e:
            print(f"生成SMT约束失败: {e}")
            return ""
    
    def save_path_to_file(self, path_info):
        """保存路径信息到文件"""
        filename = f"{self.binary_path.split('/')[-1]}_path_{path_info['index']}.txt"
        
        with open(filename, "w", encoding='utf-8') as f:
            f.write(path_info['smt_constraints'])
            f.write("\n; 路径签名信息:\n")
            f.write(f"; 变量值: {path_info['signature']['variables']}\n")
            f.write(f"; 约束信息: {path_info['signature']['constraints']}\n")
            f.write(f"; 内存哈希: {path_info['signature']['memory_hash']}\n")
            f.write(f"; 程序输出:\n")
            f.write(path_info['signature']['output'])
        
        print(f"  已保存到: {filename}")

def compare_path_collections_improved(analyzer1_results, analyzer2_results):
    """改进的路径集合比较"""
    print("\n开始改进的路径比较...")
    
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
            # 1. 检查变量值完全匹配
            if path1['signature']['variables'] == path2['signature']['variables']:
                matches['exact_variable_matches'].append((path1['index'], path2['index']))
                best_match = path2['index']
                best_match_type = 'exact_variable'
                break
            
            # 2. 检查程序输出匹配
            if (path1['signature']['output'] == path2['signature']['output'] and 
                path1['signature']['output'] != ""):
                if best_match_type != 'exact_variable':
                    matches['exact_output_matches'].append((path1['index'], path2['index']))
                    best_match = path2['index']
                    best_match_type = 'exact_output'
            
            # 3. 检查约束结构相似性
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
    
    # 打印比较结果
    print(f"\n路径匹配结果:")
    print(f"  精确变量匹配: {len(matches['exact_variable_matches'])} 对")
    print(f"  精确输出匹配: {len(matches['exact_output_matches'])} 对")
    print(f"  约束结构匹配: {len(matches['constraint_structure_matches'])} 对")
    print(f"  无匹配路径: {len(matches['no_matches'])} 个")
    
    return matches

def main():
    """主函数 - 示例用法"""
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python clang_improved.py <binary_path>")
        print("例如: python clang_improved.py ./test1_clang")
        return
    
    binary_path = sys.argv[1]
    
    # 创建分析器并运行
    analyzer = ImprovedPathAnalyzer(binary_path)
    results = analyzer.run_symbolic_execution()
    
    print(f"\n分析完成！共发现 {len(results)} 条路径")

if __name__ == "__main__":
    main() 