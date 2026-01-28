"""
带有claripy调试信息的符号执行脚本
在原有se_script.py基础上，增加详细的claripy调试输出
"""

import angr
import claripy
import re
import os
import glob
import time
import datetime
from claripy.backends.backend_z3 import claripy_solver_to_smt2
import logging

           
logging.getLogger('angr').setLevel(logging.DEBUG)
logging.getLogger('claripy').setLevel(logging.DEBUG)
logging.getLogger('claripy.solver').setLevel(logging.DEBUG)
logging.getLogger('claripy.backends').setLevel(logging.DEBUG)

           
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

                            
logging.getLogger('claripy').addHandler(console_handler)
logging.getLogger('claripy.solver').addHandler(console_handler)
logging.getLogger('claripy.backends').addHandler(console_handler)

          
scanf_counter = 0
scanf_variables = {}
array_symbols = {}
symbolized_arrays = []

class DebugScanfSymProc(angr.SimProcedure):
    """带有详细调试信息的scanf符号化过程"""
    
    def run(self, fmt_ptr, *args):
        global scanf_counter, scanf_variables
        
        print(f"🔧 DEBUG: ScanfSymProc.run() 被调用")
        print(f"🔧 DEBUG: 参数数量: {len(args)}")
        print(f"🔧 DEBUG: scanf_counter: {scanf_counter}")
        
                 
        try:
            fmt_str = self.state.mem[fmt_ptr].string.concrete.decode('utf-8')
            print(f"🔧 DEBUG: 格式字符串: {fmt_str}")
        except Exception as e:
            fmt_str = "%d"          
            print(f"🔧 DEBUG: 格式字符串读取失败: {e}, 使用默认: {fmt_str}")
        
        print(f"scanf格式字符串: {fmt_str}")
        
                     
        param_count = fmt_str.count('%lf') + fmt_str.count('%f') + fmt_str.count('%d')
        if param_count == 0:
            param_count = 1          
            
        print(f"需要符号化参数数量: {param_count}")
        
                     
        for i in range(min(param_count, len(args))):
            print(f"🔧 DEBUG: 创建第 {i+1} 个符号变量")
            
                       
            sym_var_name = f'scanf_{scanf_counter}'
            sym_var_bv = claripy.BVS(sym_var_name, 32)
            
            print(f"🔧 DEBUG: 创建的符号变量: {sym_var_bv}")
            print(f"🔧 DEBUG: 符号变量类型: {type(sym_var_bv)}")
            print(f"🔧 DEBUG: 符号变量长度: {sym_var_bv.length}")
            
                        
            constraint1 = sym_var_bv >= 0
            constraint2 = sym_var_bv <= 15
            
            print(f"🔧 DEBUG: 约束1: {constraint1}")
            print(f"🔧 DEBUG: 约束2: {constraint2}")
            
            self.state.solver.add(constraint1)
            self.state.solver.add(constraint2)
            
            print(f"🔧 DEBUG: 约束已添加到solver")
            print(f"🔧 DEBUG: 当前solver约束数量: {len(self.state.solver.constraints)}")
            
            print(f"创建符号变量: {sym_var_name} (范围: 0-15)")
            
                      
            scanf_variables[sym_var_name] = sym_var_bv
            scanf_counter += 1
            
                            
            if i < len(args):
                memory_addr = args[i]
                print(f"🔧 DEBUG: 写入内存地址: {memory_addr}")
                
                if '%lf' in fmt_str or '%f' in fmt_str:
                                     
                    double_bits = sym_var_bv.zero_extend(32)
                    print(f"🔧 DEBUG: 扩展为64位: {double_bits}")
                    
                    self.state.memory.store(
                        memory_addr,
                        double_bits,
                        endness=self.state.arch.memory_endness
                    )
                    print(f"  写入double(64位)到地址 {memory_addr}")
                else:
                                 
                    self.state.memory.store(
                        memory_addr,
                        sym_var_bv,
                        endness=self.state.arch.memory_endness
                    )
                    print(f"  写入int(32位)到地址 {memory_addr}")
                
                print(f"🔧 DEBUG: 内存写入完成")
        
                    
        print(f"🔧 DEBUG: 最终solver状态:")
        print(f"🔧 DEBUG: - 约束数量: {len(self.state.solver.constraints)}")
        print(f"🔧 DEBUG: - 是否可满足: {self.state.solver.satisfiable()}")
        
                  
        try:
            if self.state.solver.satisfiable():
                for var_name, var_sym in scanf_variables.items():
                    val = self.state.solver.eval(var_sym)
                    print(f"🔧 DEBUG: {var_name} 的一个可能值: {val}")
        except Exception as e:
            print(f"🔧 DEBUG: 求解失败: {e}")
        
                     
        return_val = claripy.BVV(min(param_count, len(args)), self.state.arch.bits)
        print(f"🔧 DEBUG: 返回值: {return_val}")
        
        return return_val

class DebugPathAnalyzer:
    """带有详细调试信息的路径分析器"""
    
    def __init__(self, binary_path, output_prefix=None, timeout=120):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        
                  
        self.start_time = None
        self.end_time = None
        self.setup_time = 0.0
        self.exploration_time = 0.0
        self.analysis_time = 0.0
        self.total_time = 0.0
        
                
        if output_prefix is None:
            binary_name = os.path.basename(binary_path)
            self.output_prefix = binary_name
        else:
            self.output_prefix = output_prefix
    
    def setup_project(self):
        """设置angr项目"""
        print(f"🔧 DEBUG: 开始设置项目: {self.binary_path}")
        
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        
        print(f"🔧 DEBUG: 项目创建完成")
        print(f"🔧 DEBUG: 架构: {self.project.arch}")
        print(f"🔧 DEBUG: 入口点: 0x{self.project.entry:x}")
        
                          
        scanf_symbols = ['scanf', '__isoc99_scanf', '__isoc23_scanf', '__scanf_chk']
        for symbol in scanf_symbols:
            symbol_obj = self.project.loader.find_symbol(symbol)
            if symbol_obj:
                print(f"🔧 DEBUG: 找到符号: {symbol} at 0x{symbol_obj.rebased_addr:x}")
                self.project.hook_symbol(symbol, DebugScanfSymProc())
                print(f"已hook符号: {symbol}")
        
        print(f"🔧 DEBUG: 项目设置完成")
    
    def debug_state_info(self, state, label=""):
        """打印状态调试信息"""
        print(f"🔧 DEBUG: === 状态信息 {label} ===")
        print(f"🔧 DEBUG: 状态地址: 0x{state.addr:x}")
        print(f"🔧 DEBUG: 约束数量: {len(state.solver.constraints)}")
        print(f"🔧 DEBUG: 是否可满足: {state.solver.satisfiable()}")
        
                 
        for i, constraint in enumerate(state.solver.constraints[:3]):
            print(f"🔧 DEBUG: 约束{i+1}: {constraint}")
        
        if len(state.solver.constraints) > 3:
            print(f"🔧 DEBUG: ... 还有 {len(state.solver.constraints)-3} 个约束")
        
                  
        print(f"🔧 DEBUG: 符号变量数量: {len(scanf_variables)}")
        for var_name, var_sym in scanf_variables.items():
            try:
                if state.solver.satisfiable():
                    val = state.solver.eval(var_sym)
                    print(f"🔧 DEBUG: {var_name} = {val}")
            except Exception as e:
                print(f"🔧 DEBUG: {var_name} 求解失败: {e}")
    
    def generate_smt_constraints_debug(self, state):
        """生成SMT约束（带调试信息）"""
        print(f"🔧 DEBUG: 开始生成SMT约束")
        
        try:
            solver = claripy.Solver()
            print(f"🔧 DEBUG: 创建新的solver: {solver}")
            
            constraint_count = 0
            for constraint in state.solver.constraints:
                solver.add(constraint)
                constraint_count += 1
                print(f"🔧 DEBUG: 添加约束 {constraint_count}: {constraint}")
            
            print(f"🔧 DEBUG: 总共添加 {constraint_count} 个约束")
            print(f"🔧 DEBUG: 开始转换为SMT2格式")
            
            smt2_text = claripy_solver_to_smt2(solver)
            
            print(f"🔧 DEBUG: SMT2转换完成")
            print(f"🔧 DEBUG: SMT2文本长度: {len(smt2_text)} 字符")
            print(f"🔧 DEBUG: SMT2文本预览 (前200字符):")
            print(f"🔧 DEBUG: {smt2_text[:200]}...")
            
            return smt2_text
            
        except Exception as e:
            print(f"🔧 DEBUG: 生成SMT约束失败: {e}")
            print(f"🔧 DEBUG: 异常类型: {type(e)}")
            import traceback
            print(f"🔧 DEBUG: 完整异常信息:")
            traceback.print_exc()
            return ""
    
    def run_symbolic_execution(self):
        """运行符号执行（带调试信息）"""
        print(f"🔧 DEBUG: ========== 开始符号执行 ==========")
        print(f"开始符号执行: {self.binary_path}")
        print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
                 
        self.start_time = time.time()
        
                
        global scanf_counter, scanf_variables, array_symbols, symbolized_arrays
        scanf_counter = 0
        scanf_variables = {}
        array_symbols = {}
        symbolized_arrays = []
        
        print(f"🔧 DEBUG: 全局变量已重置")
        
                       
        setup_start = time.time()
        self.setup_project()
        
        if self.project is None:
            print("项目初始化失败")
            return []
        
                
        print(f"🔧 DEBUG: 创建初始状态")
        initial_state = self.project.factory.entry_state(
            add_options={
                angr.options.SYMBOL_FILL_UNCONSTRAINED_MEMORY,
                angr.options.SYMBOL_FILL_UNCONSTRAINED_REGISTERS
            }
        )
        
        print(f"🔧 DEBUG: 初始状态创建完成")
        self.debug_state_info(initial_state, "初始状态")
        
        self.setup_time = time.time() - setup_start
        print(f"项目设置完成，耗时: {self.setup_time:.3f} 秒")
        
                 
        print(f"🔧 DEBUG: 创建仿真管理器")
        simgr = self.project.factory.simulation_manager(initial_state)
        
        print(f"🔧 DEBUG: 仿真管理器创建完成")
        print(f"🔧 DEBUG: 初始active状态数: {len(simgr.active)}")
        
                         
        print("开始探索路径...")
        print(f"🔧 DEBUG: 超时设置: {self.timeout} 秒")
        
        exploration_start = time.time()
        
                        
        step_count = 0
        while simgr.active and step_count < 100:                
            step_count += 1
            print(f"🔧 DEBUG: === 执行步骤 {step_count} ===")
            print(f"🔧 DEBUG: active状态数: {len(simgr.active)}")
            print(f"🔧 DEBUG: deadended状态数: {len(simgr.deadended)}")
            print(f"🔧 DEBUG: errored状态数: {len(simgr.errored)}")
            
                    
            if time.time() - exploration_start > self.timeout:
                print(f"🔧 DEBUG: 执行超时，停止探索")
                break
            
                  
            try:
                simgr.step()
                
                          
                if simgr.active:
                    for i, state in enumerate(simgr.active[:2]):            
                        self.debug_state_info(state, f"步骤{step_count}-状态{i+1}")
                        
            except Exception as e:
                print(f"🔧 DEBUG: 执行步骤时出错: {e}")
                break
        
        self.exploration_time = time.time() - exploration_start
        
        print(f"路径探索完成，耗时: {self.exploration_time:.3f} 秒")
        print(f"符号执行完成：")
        print(f"  终止路径数: {len(simgr.deadended)}")
        print(f"  活跃路径数: {len(simgr.active)}")
        print(f"  错误路径数: {len(simgr.errored)}")
        
                           
        print("开始分析路径状态...")
        analysis_start = time.time()
        self.analyze_deadended_states_debug(simgr.deadended)
        self.analysis_time = time.time() - analysis_start
        
                 
        self.end_time = time.time()
        self.total_time = self.end_time - self.start_time
        
                
        print(f"\n⏱️  符号执行时间统计:")
        print(f"  开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  结束时间: {datetime.datetime.fromtimestamp(self.end_time).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  项目设置: {self.setup_time:.3f} 秒")
        print(f"  路径探索: {self.exploration_time:.3f} 秒")
        print(f"  状态分析: {self.analysis_time:.3f} 秒")
        print(f"  总计时间: {self.total_time:.3f} 秒")
        print(f"  探索效率: {len(self.paths_info)/max(1, self.exploration_time):.2f} 路径/秒")
        
        return self.paths_info
    
    def analyze_deadended_states_debug(self, deadended_states):
        """分析所有终止状态（带调试信息）"""
        print(f"🔧 DEBUG: 开始分析 {len(deadended_states)} 个终止状态")
        
        for i, state in enumerate(deadended_states):
            print(f"\n🔧 DEBUG: ========== 分析路径 {i + 1} ==========")
            print(f"分析路径 {i + 1}...")
            
            self.debug_state_info(state, f"路径{i+1}")
            
                    
            print(f"🔧 DEBUG: 提取路径签名")
            signature = self.extract_path_signature_debug(state)
            
                     
            print(f"🔧 DEBUG: 生成SMT约束")
            smt_constraints = self.generate_smt_constraints_debug(state)
            
                    
            path_info = {
                'index': i + 1,
                'signature': signature,
                'smt_constraints': smt_constraints,
                'state': state
            }
            
            self.paths_info.append(path_info)
            
                   
            self.save_path_to_file_debug(path_info)
            
                  
            print(f"  输入变量值: {signature['variables']}")
            print(f"  约束数量: {signature['constraints']['count']}")
            print(f"  程序输出: {signature['output']}")
    
    def extract_path_signature_debug(self, state):
        """提取路径的多维签名（带调试信息）"""
        print(f"🔧 DEBUG: 开始提取路径签名")
        signature = {}
        
                         
        global scanf_variables
        variable_values = {}
        
        print(f"🔧 DEBUG: 处理 {len(scanf_variables)} 个符号变量")
        
        for var_name, sym_var in scanf_variables.items():
            print(f"🔧 DEBUG: 处理变量 {var_name}: {sym_var}")
            try:
                if state.solver.satisfiable():
                    val = state.solver.eval(sym_var, cast_to=int)
                    variable_values[var_name] = val
                    print(f"🔧 DEBUG: {var_name} = {val}")
                else:
                    variable_values[var_name] = None
                    print(f"🔧 DEBUG: {var_name} = None (不可满足)")
            except Exception as e:
                variable_values[var_name] = None
                print(f"🔧 DEBUG: {var_name} 求解失败: {e}")
        
        signature['variables'] = variable_values
        
                     
        print(f"🔧 DEBUG: 分析约束信息")
        constraint_info = {
            'count': len(state.solver.constraints),
            'types': [],
            'array_related_count': 0
        }
        
        for i, constraint in enumerate(state.solver.constraints):
            print(f"🔧 DEBUG: 约束{i+1}: {constraint}")
            
                    
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
        
                 
        print(f"🔧 DEBUG: 获取程序输出")
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            signature['output'] = output
            print(f"🔧 DEBUG: 程序输出: {output}")
        except Exception as e:
            signature['output'] = ""
            print(f"🔧 DEBUG: 获取程序输出失败: {e}")
        
                    
        try:
            constraint_hash = hash(str(state.solver.constraints)[:200])
            signature['memory_hash'] = constraint_hash
            print(f"🔧 DEBUG: 内存哈希: {constraint_hash}")
        except Exception as e:
            signature['memory_hash'] = 0
            print(f"🔧 DEBUG: 计算内存哈希失败: {e}")
        
        print(f"🔧 DEBUG: 路径签名提取完成")
        return signature
    
    def save_path_to_file_debug(self, path_info):
        """保存路径信息到文件（带调试信息）"""
                           
        binary_dir = os.path.dirname(os.path.abspath(self.binary_path))
        filename = os.path.join(binary_dir, f"{self.output_prefix}_debug_path_{path_info['index']}.txt")
        
        print(f"🔧 DEBUG: 保存文件到: {filename}")
        
        with open(filename, "w", encoding='utf-8') as f:
            f.write("; === CLARIPY DEBUG 符号执行约束文件 ===\n")
            f.write(f"; 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"; 程序: {self.binary_path}\n")
            f.write(f"; 路径索引: {path_info['index']}\n")
            f.write(";\n")
            
            f.write(path_info['smt_constraints'])
            f.write("\n; === 路径签名信息 ===\n")
            f.write(f"; 输入变量值: {path_info['signature']['variables']}\n")
            f.write(f"; 约束信息: {path_info['signature']['constraints']}\n")
            f.write(f"; 内存哈希: {path_info['signature']['memory_hash']}\n")
            f.write(";\n")
            
                    
            f.write("; === 调试信息 ===\n")
            f.write(f"; 符号变量总数: {len(scanf_variables)}\n")
            f.write(f"; 约束总数: {path_info['signature']['constraints']['count']}\n")
            f.write(f"; 约束类型分布: {path_info['signature']['constraints']['types']}\n")
            f.write(";\n")
            
                    
            f.write(f"; === 时间信息 ===\n")
            f.write(f"; 符号执行开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S') if self.start_time else 'N/A'}\n")
            f.write(f"; 项目设置时间: {self.setup_time:.3f} 秒\n")
            f.write(f"; 路径探索时间: {self.exploration_time:.3f} 秒\n")
            f.write(f"; 状态分析时间: {self.analysis_time:.3f} 秒\n")
            f.write(f"; 路径索引: {path_info['index']}\n")
            f.write(";\n")
            
            f.write(f"; === 程序输出 ===\n")
            f.write(f"; {path_info['signature']['output']}\n")
        
        print(f"  已保存到: {filename}")

def main():
    """主函数 - 带调试信息的符号执行"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='带claripy调试信息的符号执行分析工具')
    parser.add_argument('--binary', help='二进制文件路径', required=True)
    parser.add_argument('--timeout', type=int, default=120, help='符号执行超时时间(秒)')
    parser.add_argument('--output-prefix', help='输出文件前缀')
    
    args = parser.parse_args()
    
    print(f"🔧 DEBUG: ========== 启动调试模式符号执行 ==========")
    print(f"🔧 DEBUG: 目标程序: {args.binary}")
    print(f"🔧 DEBUG: 超时设置: {args.timeout} 秒")
    print(f"🔧 DEBUG: 输出前缀: {args.output_prefix}")
    print(f"🔧 DEBUG: ================================================")
    
    analyzer = DebugPathAnalyzer(args.binary, args.output_prefix, args.timeout)
    results = analyzer.run_symbolic_execution()
    
    print(f"\n🔧 DEBUG: ========== 分析完成 ==========")
    print(f"分析完成！共发现 {len(results)} 条路径")
    print(f"🔧 DEBUG: 调试文件已保存，文件名格式: {analyzer.output_prefix}_debug_path_*.txt")

if __name__ == "__main__":
    main() 