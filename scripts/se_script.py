"""
改进的符号执行脚本，获取路径签名信息

增强版符号执行脚本
- 修复了angr API兼容性问题，改善了路径标识方法
- 添加了关键数组区域的符号化支持
- 增强了数据流分析能力
- 添加了详细的时间记录功能
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

        
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

          
scanf_counter = 0
scanf_variables = {}
array_symbols = {}            
symbolized_arrays = []             

class ScanfSymProc(angr.SimProcedure):
    """改进的scanf符号化过程，添加合理的约束避免状态爆炸"""
    
    def run(self, fmt_ptr, value_ptr):
        global scanf_counter, scanf_variables
        
                    
        sym_var = claripy.BVS(f'scanf_{scanf_counter}', 32)
        
                       
                                     
        self.state.solver.add(sym_var >= 0)
        self.state.solver.add(sym_var <= 15)                
        
        print(f"创建约束符号变量: scanf_{scanf_counter} (范围: 0-10)")
        
                  
        scanf_variables[f'scanf_{scanf_counter}'] = sym_var
        scanf_counter += 1
        
                   
        self.state.memory.store(
            value_ptr,
            sym_var,
            endness=self.state.arch.memory_endness
        )
        
        return claripy.BVV(1, self.state.arch.bits)

class ArraySymbolizer:
    """数组符号化管理器"""
    
    def __init__(self, project):
        self.project = project
        self.symbolized_regions = {}
        
    def symbolize_global_arrays(self, state, array_configs):
        """符号化全局数组
        
        Args:
            state: angr状态对象
            array_configs: 数组配置列表，格式为 [{'name': 'a', 'size': 128, 'element_size': 4}, ...]
        """
        global array_symbols, symbolized_arrays
        
        print("开始符号化全局数组...")
        
        for config in array_configs:
            array_name = config['name']
            array_size = config.get('size', 128)
            element_size = config.get('element_size', 4)              
            symbolize_range = config.get('symbolize_range', None)            
            
                    
            array_symbol = self.project.loader.find_symbol(array_name)
            if not array_symbol:
                print(f"警告: 未找到数组符号 '{array_name}'")
                continue
                
            array_addr = array_symbol.rebased_addr
            print(f"找到数组 {array_name} at 0x{array_addr:x}")
            
                     
            if symbolize_range:
                start_idx, end_idx = symbolize_range
                symbolize_size = min(end_idx - start_idx, array_size - start_idx)
                start_addr = array_addr + start_idx * element_size
            else:
                                      
                symbolize_size = min(16, array_size)
                start_addr = array_addr
                start_idx = 0
            
                      
            array_symbols[array_name] = {}
            
            for i in range(symbolize_size):
                element_addr = start_addr + i * element_size
                symbol_name = f"{array_name}_init_{start_idx + i}"
                
                        
                sym_element = claripy.BVS(symbol_name, element_size * 8)
                
                                          
                                 
                
                                      
                state.memory.store(
                    element_addr,
                    sym_element,
                    endness=state.arch.memory_endness
                )
                
                        
                array_symbols[array_name][start_idx + i] = {
                    'symbol': sym_element,
                    'address': element_addr,
                    'name': symbol_name
                }
            
            symbolized_arrays.append({
                'name': array_name,
                'start_index': start_idx,
                'symbolized_count': symbolize_size,
                'total_size': array_size
            })
            
            print(f"  已符号化 {array_name}[{start_idx}:{start_idx + symbolize_size}] "
                  f"({symbolize_size}/{array_size} 个元素)")
    
    def symbolize_stack_arrays(self, state, function_name, local_arrays):
        """符号化栈上的局部数组"""
        print(f"符号化函数 {function_name} 的局部数组...")
        
                            
                       
        pass
    
    def get_array_constraints(self, state):
        """获取与数组相关的约束"""
        array_constraints = []
        
        for array_name, elements in array_symbols.items():
            for idx, element_info in elements.items():
                symbol = element_info['symbol']
                            
                for constraint in state.solver.constraints:
                    if symbol in constraint.variables:
                        array_constraints.append({
                            'array': array_name,
                            'index': idx,
                            'constraint': str(constraint),
                            'symbol': element_info['name']
                        })
        
        return array_constraints

class ImprovedPathAnalyzer:
    """改进的路径分析器 - 支持数组符号化"""
    
    def __init__(self, binary_path, output_prefix=None, timeout=120, 
                 enable_array_symbolization=True, array_configs=None):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        self.enable_array_symbolization = enable_array_symbolization
        self.array_symbolizer = None
        
                  
        self.start_time = None
        self.end_time = None
        self.setup_time = 0.0
        self.exploration_time = 0.0
        self.analysis_time = 0.0
        self.total_time = 0.0
        
                
        self.array_configs = array_configs or [
            {'name': 'a', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 16)},
            {'name': 'b', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 16)},
            {'name': 'c', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 8)},
            {'name': 'd', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 8)},
            {'name': 'e', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 8)},
        ]
        
                
        if output_prefix is None:
            binary_name = os.path.basename(binary_path)
            self.output_prefix = binary_name
        else:
            self.output_prefix = output_prefix
    
    def setup_project(self):
        """设置angr项目"""
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        
                          
        scanf_symbols = ['scanf', '__isoc99_scanf', '__isoc23_scanf', '__scanf_chk']
        for symbol in scanf_symbols:
            if self.project.loader.find_symbol(symbol):
                self.project.hook_symbol(symbol, ScanfSymProc())
                print(f"已hook符号: {symbol}")
        
                   
        if self.enable_array_symbolization:
            self.array_symbolizer = ArraySymbolizer(self.project)
            print("数组符号化已启用")
    
    def extract_path_signature(self, state):
        """提取路径的多维签名"""
        signature = {}
        
                         
        global scanf_variables, array_symbols
        variable_values = {}
        for var_name, sym_var in scanf_variables.items():
            try:
                         
                if state.solver.satisfiable():
                    val = state.solver.eval(sym_var, cast_to=int)
                    variable_values[var_name] = val
                else:
                    variable_values[var_name] = None
            except:
                variable_values[var_name] = None
        signature['variables'] = variable_values
        
                       
        array_initial_values = {}
        array_final_values = {}
        array_final_expressions = {}
        
        for array_name, elements in array_symbols.items():
            array_initial_values[array_name] = {}
            array_final_values[array_name] = {}
            array_final_expressions[array_name] = {}
            
            for idx, element_info in elements.items():
                try:
                                
                    if state.solver.satisfiable():
                        initial_val = state.solver.eval(element_info['symbol'], cast_to=int)
                        array_initial_values[array_name][idx] = initial_val
                    else:
                        array_initial_values[array_name][idx] = None
                        
                                
                    final_expr = state.memory.load(
                        element_info['address'], 
                        4,         
                        endness=state.arch.memory_endness
                    )
                    
                               
                    if state.solver.satisfiable():
                        final_val = state.solver.eval(final_expr, cast_to=int)
                        array_final_values[array_name][idx] = final_val
                                       
                        array_final_expressions[array_name][idx] = str(final_expr)
                    else:
                        array_final_values[array_name][idx] = None
                        array_final_expressions[array_name][idx] = "unsatisfiable"
                        
                except Exception as e:
                    array_initial_values[array_name][idx] = None
                    array_final_values[array_name][idx] = None
                    array_final_expressions[array_name][idx] = f"error: {str(e)}"
                    
        signature['array_initial_values'] = array_initial_values
        signature['array_final_values'] = array_final_values
        signature['array_final_expressions'] = array_final_expressions
        
                 
        signature['array_values'] = array_initial_values
        
                     
        constraint_info = {
            'count': len(state.solver.constraints),
            'types': [],
            'array_related_count': 0
        }
        
                    
        array_symbols_set = set()
        for array_name, elements in array_symbols.items():
            for element_info in elements.values():
                array_symbols_set.add(element_info['symbol'])
        
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
            
                         
            if any(sym in constraint.variables for sym in array_symbols_set):
                constraint_info['array_related_count'] += 1
        
        signature['constraints'] = constraint_info
        
                     
        if self.array_symbolizer:
            signature['array_constraints'] = self.array_symbolizer.get_array_constraints(state)
        else:
            signature['array_constraints'] = []
        
                 
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            signature['output'] = output
        except:
            signature['output'] = ""
        
                         
        try:
                           
            constraint_hash = hash(str(state.solver.constraints)[:200])
            array_hash = hash(str(array_final_values)[:100])
            signature['memory_hash'] = constraint_hash ^ array_hash
        except:
            signature['memory_hash'] = 0
        
        return signature
    
    def run_symbolic_execution(self):
        """运行符号执行"""
        print(f"开始符号执行: {self.binary_path}")
        print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
                 
        self.start_time = time.time()
        
                
        global scanf_counter, scanf_variables, array_symbols, symbolized_arrays
        scanf_counter = 0
        scanf_variables = {}
        array_symbols = {}
        symbolized_arrays = []
        
                       
        setup_start = time.time()
        self.setup_project()
        
        if self.project is None:
            print("项目初始化失败")
            return []
        
                
        initial_state = self.project.factory.entry_state()
        
                     
        if self.enable_array_symbolization and self.array_symbolizer:
            print("正在符号化关键数组...")
            self.array_symbolizer.symbolize_global_arrays(initial_state, self.array_configs)
            print(f"已符号化 {len(symbolized_arrays)} 个数组")
        
        self.setup_time = time.time() - setup_start
        print(f"项目设置完成，耗时: {self.setup_time:.3f} 秒")
        
                 
        simgr = self.project.factory.simulation_manager(initial_state)
        
                         
        print("开始探索路径...")
        exploration_start = time.time()
        simgr.run(timeout=self.timeout)
        self.exploration_time = time.time() - exploration_start
        
        print(f"路径探索完成，耗时: {self.exploration_time:.3f} 秒")
        print(f"符号执行完成：")
        print(f"  终止路径数: {len(simgr.deadended)}")
        print(f"  活跃路径数: {len(simgr.active)}")
        print(f"  错误路径数: {len(simgr.errored)}")
        
                           
        print("开始分析路径状态...")
        analysis_start = time.time()
        self.analyze_deadended_states(simgr.deadended)
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
        
                
        self.generate_timing_report()
        
        return self.paths_info
    
    def analyze_deadended_states(self, deadended_states):
        """分析所有终止状态"""
        for i, state in enumerate(deadended_states):
            print(f"\n分析路径 {i + 1}...")
            
                    
            signature = self.extract_path_signature(state)
            
                     
            smt_constraints = self.generate_smt_constraints(state)
            
                    
            path_info = {
                'index': i + 1,
                'signature': signature,
                'smt_constraints': smt_constraints,
                'state': state                
            }
            
            self.paths_info.append(path_info)
            
                   
            self.save_path_to_file(path_info)
            
                  
            print(f"  输入变量值: {signature['variables']}")
            if signature.get('array_initial_values'):
                print(f"  数组初始值: {signature['array_initial_values']}")
            if signature.get('array_final_values'):
                print(f"  数组最终值: {signature['array_final_values']}")
            if signature.get('array_final_expressions') and any(signature['array_final_expressions'].values()):
                               
                changed_expressions = {}
                for array_name, expressions in signature['array_final_expressions'].items():
                    for idx, expr in expressions.items():
                        if expr and not expr.startswith('0x') and expr != '0':
                            if array_name not in changed_expressions:
                                changed_expressions[array_name] = {}
                            changed_expressions[array_name][idx] = expr
                if changed_expressions:
                    print(f"  数组符号表达式: {changed_expressions}")
            print(f"  约束数量: {signature['constraints']['count']} "
                  f"(数组相关: {signature['constraints']['array_related_count']})")
            if signature['array_constraints']:
                print(f"  数组约束数: {len(signature['array_constraints'])}")
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
        filename = f"{self.output_prefix}_path_{path_info['index']}.txt"
        
        with open(filename, "w", encoding='utf-8') as f:
            f.write(path_info['smt_constraints'])
            f.write("\n; 路径签名信息:\n")
            f.write(f"; 输入变量值: {path_info['signature']['variables']}\n")
            if path_info['signature'].get('array_initial_values'):
                f.write(f"; 数组初始值: {path_info['signature']['array_initial_values']}\n")
            if path_info['signature'].get('array_final_values'):
                f.write(f"; 数组最终值: {path_info['signature']['array_final_values']}\n")
            if path_info['signature'].get('array_final_expressions'):
                f.write(f"; 数组符号表达式: {path_info['signature']['array_final_expressions']}\n")
            f.write(f"; 约束信息: {path_info['signature']['constraints']}\n")
            if path_info['signature']['array_constraints']:
                f.write(f"; 数组约束数量: {len(path_info['signature']['array_constraints'])}\n")
                f.write(f"; 数组约束详情:\n")
                for i, ac in enumerate(path_info['signature']['array_constraints'][:5]):          
                    f.write(f";   {i+1}. {ac['array']}[{ac['index']}]: {ac['constraint'][:100]}...\n")
            f.write(f"; 内存哈希: {path_info['signature']['memory_hash']}\n")
            
                    
            f.write(f"; \n")
            f.write(f"; 时间信息:\n")
            f.write(f"; 符号执行开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S') if self.start_time else 'N/A'}\n")
            f.write(f"; 总探索时间: {self.total_time:.3f} 秒\n")
            f.write(f"; 项目设置时间: {self.setup_time:.3f} 秒\n")
            f.write(f"; 路径探索时间: {self.exploration_time:.3f} 秒\n")
            f.write(f"; 状态分析时间: {self.analysis_time:.3f} 秒\n")
            f.write(f"; 路径索引: {path_info['index']}/{len(self.paths_info)}\n")
            
            f.write(f"; 程序输出:\n")
            f.write(path_info['signature']['output'])
        
        print(f"  已保存到: {filename}")

    def generate_timing_report(self):
        """生成详细的时间报告"""
        report_filename = f"{self.output_prefix}_timing_report.txt"
        
        with open(report_filename, "w", encoding='utf-8') as f:
            f.write("符号执行时间报告\n")
            f.write("=" * 50 + "\n\n")
            
            f.write(f"分析程序: {self.binary_path}\n")
            f.write(f"输出前缀: {self.output_prefix}\n")
            f.write(f"超时设置: {self.timeout} 秒\n")
            f.write(f"数组符号化: {'启用' if self.enable_array_symbolization else '禁用'}\n\n")
            
            f.write("时间统计:\n")
            f.write("-" * 30 + "\n")
            f.write(f"开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"结束时间: {datetime.datetime.fromtimestamp(self.end_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"项目设置时间: {self.setup_time:.3f} 秒 ({self.setup_time/self.total_time*100:.1f}%)\n")
            f.write(f"路径探索时间: {self.exploration_time:.3f} 秒 ({self.exploration_time/self.total_time*100:.1f}%)\n")
            f.write(f"状态分析时间: {self.analysis_time:.3f} 秒 ({self.analysis_time/self.total_time*100:.1f}%)\n")
            f.write(f"总计时间: {self.total_time:.3f} 秒\n\n")
            
            f.write("分析结果:\n")
            f.write("-" * 30 + "\n")
            f.write(f"发现路径数: {len(self.paths_info)}\n")
            f.write(f"探索效率: {len(self.paths_info)/max(1, self.exploration_time):.2f} 路径/秒\n")
            f.write(f"平均路径分析时间: {self.analysis_time/max(1, len(self.paths_info)):.3f} 秒/路径\n\n")
            
            if self.enable_array_symbolization:
                f.write("数组符号化信息:\n")
                f.write("-" * 30 + "\n")
                for i, array_info in enumerate(symbolized_arrays):
                    f.write(f"{i+1}. {array_info['name']}: "
                           f"{array_info['symbolized_count']}/{array_info['total_size']} 个元素\n")
                f.write("\n")
            
            f.write("生成的文件:\n")
            f.write("-" * 30 + "\n")
            for i in range(len(self.paths_info)):
                f.write(f"{self.output_prefix}_path_{i+1}.txt\n")
        
        print(f"📄 时间报告已保存到: {report_filename}")
        
    def get_timing_info(self):
        """获取时间统计信息（供外部调用）"""
        return {
            'start_time': self.start_time,
            'end_time': self.end_time,
            'setup_time': self.setup_time,
            'exploration_time': self.exploration_time,
            'analysis_time': self.analysis_time,
            'total_time': self.total_time,
            'paths_count': len(self.paths_info),
            'exploration_efficiency': len(self.paths_info)/max(1, self.exploration_time)
        }

class BenchmarkAnalyzer:
    """benchmark批量分析器"""
    
    def __init__(self, benchmark_dir, timeout=120):
        self.benchmark_dir = benchmark_dir
        self.timeout = timeout
        self.results = {}
        self.timing_stats = {}          
        self.total_start_time = None
        self.total_end_time = None
    
    def find_binary_files(self):
        """查找benchmark目录中的二进制文件"""
                        
        pattern = os.path.join(self.benchmark_dir, "*_O[0123]")
        binary_files = glob.glob(pattern)
        
                 
        binary_files = [f for f in binary_files if not f.endswith('.c')]
        
        return sorted(binary_files)
    
    def analyze_all_binaries(self):
        """分析所有二进制文件"""
        self.total_start_time = time.time()
        print(f"批量分析开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        binary_files = self.find_binary_files()
        
        if not binary_files:
            print(f"在 {self.benchmark_dir} 中未找到二进制文件")
            return
        
        print(f"发现 {len(binary_files)} 个二进制文件:")
        for binary in binary_files:
            print(f"  {binary}")
        
                        
        for i, binary_path in enumerate(binary_files, 1):
            print(f"\n{'='*60}")
            print(f"正在分析 ({i}/{len(binary_files)}): {binary_path}")
            print(f"{'='*60}")
            
                        
            basename = os.path.basename(binary_path)
            output_prefix = basename
            
                        
            single_start_time = time.time()
            
            try:
                        
                global scanf_counter, scanf_variables
                scanf_counter = 0
                scanf_variables = {}
                
                analyzer = ImprovedPathAnalyzer(binary_path, output_prefix, self.timeout)
                results = analyzer.run_symbolic_execution()
                self.results[basename] = results
                
                        
                single_end_time = time.time()
                single_total_time = single_end_time - single_start_time
                timing_info = analyzer.get_timing_info()
                timing_info['single_total_time'] = single_total_time
                self.timing_stats[basename] = timing_info
                
                print(f"✅ 完成分析 {basename}: 共 {len(results)} 条路径，耗时 {single_total_time:.3f} 秒")
                
            except Exception as e:
                print(f"❌ 分析 {basename} 时出错: {e}")
                self.results[basename] = []
                self.timing_stats[basename] = {
                    'error': str(e),
                    'single_total_time': time.time() - single_start_time
                }
        
        self.total_end_time = time.time()
        total_batch_time = self.total_end_time - self.total_start_time
        
        print(f"\n📊 批量分析完成!")
        print(f"总耗时: {total_batch_time:.3f} 秒")
        print(f"平均每个程序: {total_batch_time/len(binary_files):.3f} 秒")
        print(f"结束时间: {datetime.datetime.fromtimestamp(self.total_end_time).strftime('%Y-%m-%d %H:%M:%S')}")
        
        return self.results
    
    def generate_summary_report(self):
        """生成分析摘要报告"""
        report_file = os.path.join(self.benchmark_dir, "symbolic_execution_summary.txt")
        
        with open(report_file, "w", encoding='utf-8') as f:
            f.write("符号执行批量分析摘要报告\n")
            f.write("=" * 50 + "\n\n")
            
            f.write(f"分析目录: {self.benchmark_dir}\n")
            f.write(f"分析的二进制文件数量: {len(self.results)}\n")
            if self.total_start_time and self.total_end_time:
                total_time = self.total_end_time - self.total_start_time
                f.write(f"批量分析开始时间: {datetime.datetime.fromtimestamp(self.total_start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"批量分析结束时间: {datetime.datetime.fromtimestamp(self.total_end_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"批量分析总耗时: {total_time:.3f} 秒\n")
                f.write(f"平均每个程序耗时: {total_time/max(1, len(self.results)):.3f} 秒\n")
            f.write("\n")
            
                         
            f.write("各程序分析详情:\n")
            f.write("-" * 50 + "\n")
            
            total_paths = 0
            total_exploration_time = 0
            successful_analyses = 0
            
            for binary_name, paths in self.results.items():
                f.write(f"\n程序: {binary_name}\n")
                f.write(f"  发现路径数: {len(paths)}\n")
                f.write(f"  生成的文件: {binary_name}_path_*.txt\n")
                
                      
                if binary_name in self.timing_stats:
                    timing = self.timing_stats[binary_name]
                    if 'error' in timing:
                        f.write(f"  ❌ 分析失败: {timing['error']}\n")
                        f.write(f"  失败前耗时: {timing['single_total_time']:.3f} 秒\n")
                    else:
                        f.write(f"  ✅ 分析成功\n")
                        f.write(f"  总耗时: {timing['single_total_time']:.3f} 秒\n")
                        f.write(f"    - 项目设置: {timing['setup_time']:.3f} 秒\n")
                        f.write(f"    - 路径探索: {timing['exploration_time']:.3f} 秒\n")
                        f.write(f"    - 状态分析: {timing['analysis_time']:.3f} 秒\n")
                        f.write(f"  探索效率: {timing['exploration_efficiency']:.2f} 路径/秒\n")
                        
                        total_paths += len(paths)
                        total_exploration_time += timing['exploration_time']
                        successful_analyses += 1
                
                f.write(f"  时间报告文件: {binary_name}_timing_report.txt\n")
            
                  
            f.write(f"\n总体统计:\n")
            f.write("-" * 30 + "\n")
            f.write(f"成功分析的程序数: {successful_analyses}/{len(self.results)}\n")
            f.write(f"总共发现路径数: {total_paths}\n")
            if successful_analyses > 0:
                f.write(f"平均每个程序路径数: {total_paths/successful_analyses:.1f}\n")
            if total_exploration_time > 0:
                f.write(f"总路径探索时间: {total_exploration_time:.3f} 秒\n")
                f.write(f"总体探索效率: {total_paths/total_exploration_time:.2f} 路径/秒\n")
            
            f.write(f"\n下一步分析建议:\n")
            f.write("-" * 30 + "\n")
            f.write("使用 semantic_equivalence_analyzer.py 进行等价性分析\n")
            f.write("例如: python semantic_equivalence_analyzer.py program1_O1_path_ program1_O2_path_\n")
        
        print(f"📄 摘要报告已保存到: {report_file}")

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
                          
            if path1['signature']['variables'] == path2['signature']['variables']:
                matches['exact_variable_matches'].append((path1['index'], path2['index']))
                best_match = path2['index']
                best_match_type = 'exact_variable'
                break
            
                         
            if (path1['signature']['output'] == path2['signature']['output'] and 
                path1['signature']['output'] != ""):
                if best_match_type != 'exact_variable':
                    matches['exact_output_matches'].append((path1['index'], path2['index']))
                    best_match = path2['index']
                    best_match_type = 'exact_output'
            
                          
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
    
            
    print(f"\n路径匹配结果:")
    print(f"  精确变量匹配: {len(matches['exact_variable_matches'])} 对")
    print(f"  精确输出匹配: {len(matches['exact_output_matches'])} 对")
    print(f"  约束结构匹配: {len(matches['constraint_structure_matches'])} 对")
    print(f"  无匹配路径: {len(matches['no_matches'])} 个")
    
    return matches

def main():
    """主函数 - 支持单个文件分析和批量分析"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='符号执行分析工具')
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
        analyzer = ImprovedPathAnalyzer(args.binary, args.output_prefix, args.timeout)
        results = analyzer.run_symbolic_execution()
        print(f"分析完成！共发现 {len(results)} 条路径")
        
    else:
                   
        if len(sys.argv) >= 2 and not sys.argv[1].startswith('--'):
            binary_path = sys.argv[1]
            analyzer = ImprovedPathAnalyzer(binary_path)
            results = analyzer.run_symbolic_execution()
            print(f"分析完成！共发现 {len(results)} 条路径")
        else:
            parser.print_help()

if __name__ == "__main__":
    main() 