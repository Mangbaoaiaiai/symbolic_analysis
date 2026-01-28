"""
超详细调试版本的符号执行脚本
包含最详细的angr和claripy调试信息，以及路径探索控制
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
import signal
import sys

            
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

               
loggers_to_debug = [
    'angr', 'claripy', 'angr.sim_manager', 'angr.engines',
    'angr.engines.vex', 'angr.engines.successors', 'angr.storage',
    'claripy.solver', 'claripy.backends', 'claripy.frontend',
    'claripy.backends.backend_z3', 'angr.state_plugins',
    'angr.sim_procedure', 'angr.engines.hook'
]

for logger_name in loggers_to_debug:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

              
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

for logger_name in loggers_to_debug:
    logger = logging.getLogger(logger_name)
    logger.addHandler(console_handler)

          
scanf_counter = 0
scanf_variables = {}
array_symbols = {}
symbolized_arrays = []
execution_step_count = 0
max_execution_steps = 50            
step_timeout = 5          

class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("Step execution timeout")

class UltraDebugScanfSymProc(angr.SimProcedure):
    """超详细调试的scanf符号化过程"""
    
    def run(self, fmt_ptr, *args):
        global scanf_counter, scanf_variables
        
        print(f"🔧🔧 ULTRA DEBUG: ScanfSymProc.run() 被调用")
        print(f"🔧🔧 ULTRA DEBUG: 当前时间: {datetime.datetime.now().strftime('%H:%M:%S.%f')}")
        print(f"🔧🔧 ULTRA DEBUG: 参数数量: {len(args)}")
        print(f"🔧🔧 ULTRA DEBUG: scanf_counter: {scanf_counter}")
        print(f"🔧🔧 ULTRA DEBUG: 当前状态地址: 0x{self.state.addr:x}")
        
                 
        try:
            fmt_str = self.state.mem[fmt_ptr].string.concrete.decode('utf-8')
            print(f"🔧🔧 ULTRA DEBUG: 格式字符串读取成功: {fmt_str}")
        except Exception as e:
            fmt_str = "%d"          
            print(f"🔧🔧 ULTRA DEBUG: 格式字符串读取失败: {e}, 使用默认: {fmt_str}")
        
        print(f"scanf格式字符串: {fmt_str}")
        
                     
        param_count = fmt_str.count('%lf') + fmt_str.count('%f') + fmt_str.count('%d')
        if param_count == 0:
            param_count = 1          
            
        print(f"需要符号化参数数量: {param_count}")
        print(f"🔧🔧 ULTRA DEBUG: 实际传入参数数量: {len(args)}")
        
                     
        for i in range(min(param_count, len(args))):
            print(f"🔧🔧 ULTRA DEBUG: ========== 创建第 {i+1} 个符号变量 ==========")
            
                       
            sym_var_name = f'scanf_{scanf_counter}'
            print(f"🔧🔧 ULTRA DEBUG: 符号变量名: {sym_var_name}")
            
                      
            start_time = time.time()
            sym_var_bv = claripy.BVS(sym_var_name, 32)
            creation_time = time.time() - start_time
            
            print(f"🔧🔧 ULTRA DEBUG: 符号变量创建耗时: {creation_time:.6f} 秒")
            print(f"🔧🔧 ULTRA DEBUG: 创建的符号变量: {sym_var_bv}")
            print(f"🔧🔧 ULTRA DEBUG: 符号变量类型: {type(sym_var_bv)}")
            print(f"🔧🔧 ULTRA DEBUG: 符号变量长度: {sym_var_bv.length}")
            print(f"🔧🔧 ULTRA DEBUG: 符号变量变量集合: {sym_var_bv.variables}")
            
                        
            print(f"🔧🔧 ULTRA DEBUG: 开始添加约束...")
            constraint1 = sym_var_bv >= 0
            constraint2 = sym_var_bv <= 15
            
            print(f"🔧🔧 ULTRA DEBUG: 约束1对象: {constraint1}")
            print(f"🔧🔧 ULTRA DEBUG: 约束1类型: {type(constraint1)}")
            print(f"🔧🔧 ULTRA DEBUG: 约束2对象: {constraint2}")
            print(f"🔧🔧 ULTRA DEBUG: 约束2类型: {type(constraint2)}")
            
                      
            print(f"🔧🔧 ULTRA DEBUG: 添加约束前solver约束数量: {len(self.state.solver.constraints)}")
            
            constraint_add_start = time.time()
            self.state.solver.add(constraint1)
            constraint1_time = time.time() - constraint_add_start
            
            constraint_add_start = time.time()
            self.state.solver.add(constraint2)
            constraint2_time = time.time() - constraint_add_start
            
            print(f"🔧🔧 ULTRA DEBUG: 约束1添加耗时: {constraint1_time:.6f} 秒")
            print(f"🔧🔧 ULTRA DEBUG: 约束2添加耗时: {constraint2_time:.6f} 秒")
            print(f"🔧🔧 ULTRA DEBUG: 添加约束后solver约束数量: {len(self.state.solver.constraints)}")
            
                        
            print(f"🔧🔧 ULTRA DEBUG: 开始测试solver可满足性...")
            satisfiability_start = time.time()
            try:
                is_sat = self.state.solver.satisfiable()
                satisfiability_time = time.time() - satisfiability_start
                print(f"🔧🔧 ULTRA DEBUG: 可满足性检查耗时: {satisfiability_time:.6f} 秒")
                print(f"🔧🔧 ULTRA DEBUG: solver可满足性: {is_sat}")
            except Exception as e:
                satisfiability_time = time.time() - satisfiability_start
                print(f"🔧🔧 ULTRA DEBUG: 可满足性检查失败: {e}")
                print(f"🔧🔧 ULTRA DEBUG: 检查失败耗时: {satisfiability_time:.6f} 秒")
            
            print(f"创建符号变量: {sym_var_name} (范围: 0-15)")
            
                      
            scanf_variables[sym_var_name] = sym_var_bv
            scanf_counter += 1
            
                            
            if i < len(args):
                memory_addr = args[i]
                print(f"🔧🔧 ULTRA DEBUG: 目标内存地址: {memory_addr}")
                print(f"🔧🔧 ULTRA DEBUG: 内存地址类型: {type(memory_addr)}")
                
                        
                print(f"🔧🔧 ULTRA DEBUG: 开始内存写入...")
                memory_write_start = time.time()
                
                if '%lf' in fmt_str or '%f' in fmt_str:
                                     
                    double_bits = sym_var_bv.zero_extend(32)
                    print(f"🔧🔧 ULTRA DEBUG: 扩展后的64位变量: {double_bits}")
                    
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
                
                memory_write_time = time.time() - memory_write_start
                print(f"🔧🔧 ULTRA DEBUG: 内存写入耗时: {memory_write_time:.6f} 秒")
                print(f"🔧🔧 ULTRA DEBUG: 内存写入完成")
        
                
        print(f"🔧🔧 ULTRA DEBUG: ========== 最终状态检查 ==========")
        print(f"🔧🔧 ULTRA DEBUG: 最终solver约束数量: {len(self.state.solver.constraints)}")
        
                    
        if scanf_variables:
            print(f"🔧🔧 ULTRA DEBUG: 开始求解所有符号变量...")
            solve_start = time.time()
            try:
                if self.state.solver.satisfiable():
                    for var_name, var_sym in scanf_variables.items():
                        val = self.state.solver.eval(var_sym)
                        print(f"🔧🔧 ULTRA DEBUG: {var_name} 的一个可能值: {val}")
                else:
                    print(f"🔧🔧 ULTRA DEBUG: solver不可满足!")
            except Exception as e:
                print(f"🔧🔧 ULTRA DEBUG: 求解失败: {e}")
            
            solve_time = time.time() - solve_start
            print(f"🔧🔧 ULTRA DEBUG: 求解耗时: {solve_time:.6f} 秒")
        
                     
        return_val = claripy.BVV(min(param_count, len(args)), self.state.arch.bits)
        print(f"🔧🔧 ULTRA DEBUG: 返回值: {return_val}")
        print(f"🔧🔧 ULTRA DEBUG: ScanfSymProc.run() 执行完成")
        
        return return_val

class UltraDebugPathAnalyzer:
    """超详细调试的路径分析器"""
    
    def __init__(self, binary_path, output_prefix=None, timeout=60, max_steps=50):
        self.binary_path = binary_path
        self.timeout = timeout
        self.max_steps = max_steps
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
        print(f"🔧🔧 ULTRA DEBUG: ========== 开始设置项目 ==========")
        print(f"🔧🔧 ULTRA DEBUG: 二进制文件路径: {self.binary_path}")
        print(f"🔧🔧 ULTRA DEBUG: 文件是否存在: {os.path.exists(self.binary_path)}")
        
        if os.path.exists(self.binary_path):
            file_size = os.path.getsize(self.binary_path)
            print(f"🔧🔧 ULTRA DEBUG: 文件大小: {file_size} 字节")
        
        project_start = time.time()
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        project_time = time.time() - project_start
        
        print(f"🔧🔧 ULTRA DEBUG: 项目创建耗时: {project_time:.6f} 秒")
        print(f"🔧🔧 ULTRA DEBUG: 项目架构: {self.project.arch}")
        print(f"🔧🔧 ULTRA DEBUG: 入口点: 0x{self.project.entry:x}")
        print(f"🔧🔧 ULTRA DEBUG: 主对象: {self.project.loader.main_object}")
        print(f"🔧🔧 ULTRA DEBUG: 加载的对象数量: {len(self.project.loader.all_objects)}")
        
                          
        scanf_symbols = ['scanf', '__isoc99_scanf', '__isoc23_scanf', '__scanf_chk']
        for symbol in scanf_symbols:
            symbol_obj = self.project.loader.find_symbol(symbol)
            if symbol_obj:
                print(f"🔧🔧 ULTRA DEBUG: 找到符号: {symbol} at 0x{symbol_obj.rebased_addr:x}")
                hook_start = time.time()
                self.project.hook_symbol(symbol, UltraDebugScanfSymProc())
                hook_time = time.time() - hook_start
                print(f"🔧🔧 ULTRA DEBUG: hook {symbol} 耗时: {hook_time:.6f} 秒")
                print(f"已hook符号: {symbol}")
            else:
                print(f"🔧🔧 ULTRA DEBUG: 未找到符号: {symbol}")
        
        print(f"🔧🔧 ULTRA DEBUG: 项目设置完成")
    
    def debug_simgr_state(self, simgr, step_num):
        """调试仿真管理器状态"""
        print(f"🔧🔧 ULTRA DEBUG: === 仿真管理器状态 (步骤 {step_num}) ===")
        print(f"🔧🔧 ULTRA DEBUG: active状态数: {len(simgr.active)}")
        print(f"🔧🔧 ULTRA DEBUG: deadended状态数: {len(simgr.deadended)}")
        print(f"🔧🔧 ULTRA DEBUG: errored状态数: {len(simgr.errored)}")
        print(f"🔧🔧 ULTRA DEBUG: unconstrained状态数: {len(simgr.unconstrained)}")
        
                        
        for i, state in enumerate(simgr.active[:2]):            
            print(f"🔧🔧 ULTRA DEBUG: --- Active状态 {i+1} ---")
            print(f"🔧🔧 ULTRA DEBUG: 状态地址: 0x{state.addr:x}")
            print(f"🔧🔧 ULTRA DEBUG: 约束数量: {len(state.solver.constraints)}")
            print(f"🔧🔧 ULTRA DEBUG: 历史长度: {len(state.history.bbl_addrs)}")
            
                        
            if state.history.bbl_addrs:
                recent_bbls = state.history.bbl_addrs.hardcopy[-5:]        
                print(f"🔧🔧 ULTRA DEBUG: 最近的基本块: {[hex(addr) for addr in recent_bbls]}")
            
                        
            try:
                sat_check_start = time.time()
                is_sat = state.solver.satisfiable()
                sat_check_time = time.time() - sat_check_start
                print(f"🔧🔧 ULTRA DEBUG: 可满足性: {is_sat} (耗时: {sat_check_time:.6f}s)")
            except Exception as e:
                print(f"🔧🔧 ULTRA DEBUG: 可满足性检查失败: {e}")
            
                  
            if len(state.solver.constraints) > 0:
                print(f"🔧🔧 ULTRA DEBUG: 前3个约束:")
                for j, constraint in enumerate(state.solver.constraints[:3]):
                    print(f"🔧🔧 ULTRA DEBUG:   {j+1}. {constraint}")
    
    def run_symbolic_execution(self):
        """运行符号执行（超详细调试）"""
        global execution_step_count
        execution_step_count = 0
        
        print(f"🔧🔧 ULTRA DEBUG: ========== 开始符号执行 ==========")
        print(f"🔧🔧 ULTRA DEBUG: 最大步数限制: {self.max_steps}")
        print(f"🔧🔧 ULTRA DEBUG: 超时设置: {self.timeout} 秒")
        print(f"开始符号执行: {self.binary_path}")
        print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
                 
        self.start_time = time.time()
        
                
        global scanf_counter, scanf_variables, array_symbols, symbolized_arrays
        scanf_counter = 0
        scanf_variables = {}
        array_symbols = {}
        symbolized_arrays = []
        
        print(f"🔧🔧 ULTRA DEBUG: 全局变量已重置")
        
                       
        setup_start = time.time()
        self.setup_project()
        
        if self.project is None:
            print("项目初始化失败")
            return []
        
                
        print(f"🔧🔧 ULTRA DEBUG: 创建初始状态")
        initial_state_start = time.time()
        initial_state = self.project.factory.entry_state(
            add_options={
                angr.options.SYMBOL_FILL_UNCONSTRAINED_MEMORY,
                angr.options.SYMBOL_FILL_UNCONSTRAINED_REGISTERS
            }
        )
        initial_state_time = time.time() - initial_state_start
        
        print(f"🔧🔧 ULTRA DEBUG: 初始状态创建耗时: {initial_state_time:.6f} 秒")
        print(f"🔧🔧 ULTRA DEBUG: 初始状态地址: 0x{initial_state.addr:x}")
        print(f"🔧🔧 ULTRA DEBUG: 初始约束数量: {len(initial_state.solver.constraints)}")
        
        self.setup_time = time.time() - setup_start
        print(f"项目设置完成，耗时: {self.setup_time:.3f} 秒")
        
                 
        print(f"🔧🔧 ULTRA DEBUG: 创建仿真管理器")
        simgr_start = time.time()
        simgr = self.project.factory.simulation_manager(initial_state)
        simgr_time = time.time() - simgr_start
        
        print(f"🔧🔧 ULTRA DEBUG: 仿真管理器创建耗时: {simgr_time:.6f} 秒")
        print(f"🔧🔧 ULTRA DEBUG: 初始active状态数: {len(simgr.active)}")
        
                  
        print("开始探索路径...")
        exploration_start = time.time()
        
        try:
            step_count = 0
            while simgr.active and step_count < self.max_steps:
                step_count += 1
                execution_step_count = step_count
                
                print(f"🔧🔧 ULTRA DEBUG: ========== 执行步骤 {step_count} ==========")
                print(f"🔧🔧 ULTRA DEBUG: 当前时间: {datetime.datetime.now().strftime('%H:%M:%S.%f')}")
                
                       
                if time.time() - exploration_start > self.timeout:
                    print(f"🔧🔧 ULTRA DEBUG: 总超时，停止探索")
                    break
                
                        
                self.debug_simgr_state(simgr, step_count)
                
                        
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(step_timeout)
                
                try:
                    step_start = time.time()
                    print(f"🔧🔧 ULTRA DEBUG: 开始执行步骤...")
                    
                    simgr.step()
                    
                    step_time = time.time() - step_start
                    print(f"🔧🔧 ULTRA DEBUG: 步骤执行耗时: {step_time:.6f} 秒")
                    
                            
                    signal.alarm(0)
                    
                except TimeoutException:
                    print(f"🔧🔧 ULTRA DEBUG: 步骤 {step_count} 超时 (>{step_timeout}s)")
                    signal.alarm(0)
                    break
                except Exception as e:
                    print(f"🔧🔧 ULTRA DEBUG: 步骤 {step_count} 执行出错: {e}")
                    signal.alarm(0)
                    break
                
                             
                if step_count % 5 == 0:
                    print(f"🔧🔧 ULTRA DEBUG: ========== 第 {step_count} 步详细状态 ==========")
                    print(f"🔧🔧 ULTRA DEBUG: 累计探索时间: {time.time() - exploration_start:.3f} 秒")
                    print(f"🔧🔧 ULTRA DEBUG: 平均每步时间: {(time.time() - exploration_start)/step_count:.6f} 秒")
                    
                               
                    if len(simgr.active) > 0:
                        current_addrs = [hex(state.addr) for state in simgr.active]
                        print(f"🔧🔧 ULTRA DEBUG: 当前活跃状态地址: {current_addrs}")
                
                print(f"🔧🔧 ULTRA DEBUG: 步骤 {step_count} 完成")
        
        except KeyboardInterrupt:
            print(f"🔧🔧 ULTRA DEBUG: 用户中断")
        except Exception as e:
            print(f"🔧🔧 ULTRA DEBUG: 探索过程异常: {e}")
            import traceback
            traceback.print_exc()
        
        self.exploration_time = time.time() - exploration_start
        
        print(f"路径探索完成，耗时: {self.exploration_time:.3f} 秒")
        print(f"符号执行完成：")
        print(f"  执行步数: {step_count}")
        print(f"  终止路径数: {len(simgr.deadended)}")
        print(f"  活跃路径数: {len(simgr.active)}")
        print(f"  错误路径数: {len(simgr.errored)}")
        
                
        if simgr.deadended:
            print("开始分析路径状态...")
            analysis_start = time.time()
            self.analyze_deadended_states_debug(simgr.deadended)
            self.analysis_time = time.time() - analysis_start
        else:
            print("🔧🔧 ULTRA DEBUG: 没有终止状态需要分析")
            self.analysis_time = 0.0
        
                 
        self.end_time = time.time()
        self.total_time = self.end_time - self.start_time
        
                
        print(f"\n⏱️  符号执行时间统计:")
        print(f"  开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  结束时间: {datetime.datetime.fromtimestamp(self.end_time).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  项目设置: {self.setup_time:.3f} 秒")
        print(f"  路径探索: {self.exploration_time:.3f} 秒")
        print(f"  状态分析: {self.analysis_time:.3f} 秒")
        print(f"  总计时间: {self.total_time:.3f} 秒")
        print(f"  平均每步时间: {self.exploration_time/max(1, step_count):.6f} 秒")
        
        return self.paths_info
    
    def analyze_deadended_states_debug(self, deadended_states):
        """分析所有终止状态（超详细调试）"""
        print(f"🔧🔧 ULTRA DEBUG: 开始分析 {len(deadended_states)} 个终止状态")
        
        for i, state in enumerate(deadended_states):
            print(f"\n🔧🔧 ULTRA DEBUG: ========== 分析路径 {i + 1} ==========")
            print(f"分析路径 {i + 1}...")
            
                     
            signature = {
                'variables': {},
                'constraints': {'count': len(state.solver.constraints)},
                'output': "",
                'memory_hash': 0
            }
            
                     
            smt_constraints = ""
            try:
                solver = claripy.Solver()
                for constraint in state.solver.constraints:
                    solver.add(constraint)
                smt_constraints = claripy_solver_to_smt2(solver)
            except Exception as e:
                print(f"🔧🔧 ULTRA DEBUG: SMT生成失败: {e}")
            
                    
            path_info = {
                'index': i + 1,
                'signature': signature,
                'smt_constraints': smt_constraints,
                'state': state
            }
            
            self.paths_info.append(path_info)
            
                   
            self.save_path_to_file_ultra_debug(path_info)
            
            print(f"  约束数量: {signature['constraints']['count']}")
    
    def save_path_to_file_ultra_debug(self, path_info):
        """保存路径信息到文件（超详细调试）"""
                           
        binary_dir = os.path.dirname(os.path.abspath(self.binary_path))
        filename = os.path.join(binary_dir, f"{self.output_prefix}_ultra_debug_path_{path_info['index']}.txt")
        
        print(f"🔧🔧 ULTRA DEBUG: 保存文件到: {filename}")
        
        with open(filename, "w", encoding='utf-8') as f:
            f.write("; === ULTRA DEBUG 符号执行约束文件 ===\n")
            f.write(f"; 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"; 程序: {self.binary_path}\n")
            f.write(f"; 路径索引: {path_info['index']}\n")
            f.write(f"; 最大执行步数: {self.max_steps}\n")
            f.write(f"; 实际执行步数: {execution_step_count}\n")
            f.write(";\n")
            
            f.write(path_info['smt_constraints'])
            f.write("\n; === 路径签名信息 ===\n")
            f.write(f"; 约束数量: {path_info['signature']['constraints']['count']}\n")
            f.write(";\n")
            
                    
            f.write("; === ULTRA DEBUG 信息 ===\n")
            f.write(f"; 符号变量总数: {len(scanf_variables)}\n")
            f.write(f"; 探索超时: {self.timeout} 秒\n")
            f.write(f"; 单步超时: {step_timeout} 秒\n")
            f.write(";\n")
            
                    
            f.write(f"; === 时间信息 ===\n")
            f.write(f"; 项目设置时间: {self.setup_time:.3f} 秒\n")
            f.write(f"; 路径探索时间: {self.exploration_time:.3f} 秒\n")
            f.write(f"; 状态分析时间: {self.analysis_time:.3f} 秒\n")
            f.write(f"; 总时间: {self.total_time:.3f} 秒\n")
            f.write(f"; 平均每步时间: {self.exploration_time/max(1, execution_step_count):.6f} 秒\n")
        
        print(f"  已保存到: {filename}")

def main():
    """主函数 - 超详细调试符号执行"""
    import argparse
    
    parser = argparse.ArgumentParser(description='超详细调试的符号执行分析工具')
    parser.add_argument('--binary', help='二进制文件路径', required=True)
    parser.add_argument('--timeout', type=int, default=60, help='符号执行超时时间(秒)')
    parser.add_argument('--max-steps', type=int, default=50, help='最大执行步数')
    parser.add_argument('--output-prefix', help='输出文件前缀')
    
    args = parser.parse_args()
    
    print(f"🔧🔧 ULTRA DEBUG: ========== 启动超详细调试模式 ==========")
    print(f"🔧🔧 ULTRA DEBUG: 目标程序: {args.binary}")
    print(f"🔧🔧 ULTRA DEBUG: 超时设置: {args.timeout} 秒")
    print(f"🔧🔧 ULTRA DEBUG: 最大步数: {args.max_steps}")
    print(f"🔧🔧 ULTRA DEBUG: 输出前缀: {args.output_prefix}")
    print(f"🔧🔧 ULTRA DEBUG: 单步超时: {step_timeout} 秒")
    print(f"🔧🔧 ULTRA DEBUG: ================================================")
    
    analyzer = UltraDebugPathAnalyzer(args.binary, args.output_prefix, args.timeout, args.max_steps)
    results = analyzer.run_symbolic_execution()
    
    print(f"\n🔧🔧 ULTRA DEBUG: ========== 分析完成 ==========")
    print(f"分析完成！共发现 {len(results)} 条路径")
    print(f"🔧🔧 ULTRA DEBUG: 调试文件已保存，文件名格式: {analyzer.output_prefix}_ultra_debug_path_*.txt")

if __name__ == "__main__":
    main() 