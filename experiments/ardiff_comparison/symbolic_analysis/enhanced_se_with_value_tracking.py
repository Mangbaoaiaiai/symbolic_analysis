                      
"""
增强的符号执行脚本，专门用于追踪函数返回值的来源
基于se_script.py修改，添加值来源分析功能
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
value_traces = []           

class ScanfSymProc(angr.SimProcedure):
    """改进的scanf符号化过程"""
    
    def run(self, fmt_ptr, *args):
        global scanf_counter, scanf_variables
        
                 
        try:
            fmt_str = self.state.mem[fmt_ptr].string.concrete.decode('utf-8')
        except:
            fmt_str = "%d"        
        
        print(f"scanf格式字符串: {fmt_str}")
        
                     
        param_count = fmt_str.count('%d') + fmt_str.count('%lf') + fmt_str.count('%f')
        if param_count == 0:
            param_count = 1          
            
        print(f"需要符号化参数数量: {param_count}")
        
                     
        for i in range(min(param_count, len(args))):
                                 
            sym_var_bv = claripy.BVS(f'scanf_{scanf_counter}', 32)
            
                        
            self.state.solver.add(sym_var_bv >= 0)
            self.state.solver.add(sym_var_bv <= 15)
            
            print(f"创建符号变量: scanf_{scanf_counter} (范围: 0-15)")
            
                      
            scanf_variables[f'scanf_{scanf_counter}'] = sym_var_bv
            scanf_counter += 1
            
                            
            if i < len(args):
                self.state.memory.store(
                    args[i],
                    sym_var_bv,
                    endness=self.state.arch.memory_endness
                )
                print(f"  写入int(32位)到地址 {args[i]}")
        
                     
        return claripy.BVV(min(param_count, len(args)), self.state.arch.bits)

class ValueTracker:
    """值追踪器 - 分析值的来源"""
    
    def __init__(self):
        self.traces = []
        self.function_calls = []
        self.return_values = []
        
    def track_function_call(self, state, function_name, args, return_value):
        """追踪函数调用和返回值"""
        trace = {
            'type': 'function_call',
            'function': function_name,
            'args': args,
            'return_value': return_value,
            'return_value_analysis': self.analyze_value_source(return_value),
            'timestamp': time.time()
        }
        
        self.traces.append(trace)
        self.function_calls.append(trace)
        self.return_values.append(return_value)
        
        print(f"🔍 追踪函数调用: {function_name}")
        print(f"   参数: {args}")
        print(f"   返回值: {return_value}")
        print(f"   值来源分析: {trace['return_value_analysis']}")
    
    def analyze_value_source(self, value):
        """分析值的来源"""
        analysis = {
            'is_symbolic': False,
            'is_concrete': False,
            'is_constant': False,
            'symbolic_vars': [],
            'expression_type': 'unknown',
            'source_type': 'unknown'
        }
        
        if hasattr(value, 'op'):
                   
            analysis['is_symbolic'] = True
            analysis['expression_type'] = value.op
            
                    
            symbolic_vars = self.find_symbolic_vars(value)
            analysis['symbolic_vars'] = symbolic_vars
            
            if symbolic_vars:
                analysis['source_type'] = 'symbolic_computation'
            else:
                analysis['source_type'] = 'concrete_computation'
                
        elif hasattr(value, 'value'):
                 
            analysis['is_concrete'] = True
            analysis['is_constant'] = True
            analysis['source_type'] = 'constant'
            
        return analysis
    
    def find_symbolic_vars(self, expr):
        """递归查找表达式中的符号变量"""
        vars_found = set()
        
        if hasattr(expr, 'op'):
            for arg in expr.args:
                vars_found.update(self.find_symbolic_vars(arg))
        else:
            if hasattr(expr, 'name') and 'scanf' in str(expr):
                vars_found.add(expr.name)
        
        return vars_found
    
    def get_traces_summary(self):
        """获取追踪摘要"""
        return {
            'total_traces': len(self.traces),
            'function_calls': len(self.function_calls),
            'return_values': len(self.return_values),
            'symbolic_returns': sum(1 for trace in self.function_calls 
                                  if trace['return_value_analysis']['is_symbolic']),
            'concrete_returns': sum(1 for trace in self.function_calls 
                                  if trace['return_value_analysis']['is_concrete'])
        }

class EnhancedPathAnalyzer:
    """增强的路径分析器 - 支持值追踪"""
    
    def __init__(self, binary_path, output_prefix=None, timeout=120):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        self.value_tracker = ValueTracker()
        
                  
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
        self.project = angr.Project(self.binary_path, auto_load_libs=False)
        
                          
        scanf_symbols = ['scanf', '__isoc99_scanf', '__isoc23_scanf', '__scanf_chk']
        for symbol in scanf_symbols:
            if self.project.loader.find_symbol(symbol):
                self.project.hook_symbol(symbol, ScanfSymProc())
                print(f"已hook符号: {symbol}")
        
                  
        self.setup_function_hooks()
    
    def setup_function_hooks(self):
        """设置函数调用钩子"""
                     
        snippet_symbol = self.project.loader.find_symbol('snippet')
        if snippet_symbol:
            print(f"找到snippet函数 at 0x{snippet_symbol.rebased_addr:x}")
            self.project.hook(snippet_symbol.rebased_addr, self.snippet_hook, length=0)
        else:
            print("警告: 未找到snippet函数")
    
    def snippet_hook(self, state):
        """snippet函数的钩子"""
        print(f"\n🔍 进入snippet函数")
        
                
        rdi = state.regs.rdi         
        print(f"   参数x (RDI): {rdi}")
        
                
        param_analysis = self.value_tracker.analyze_value_source(rdi)
        print(f"   参数来源分析: {param_analysis}")
        
                 
                                        
        return None
    
    def run_symbolic_execution(self):
        """运行符号执行"""
        print(f"开始增强的符号执行: {self.binary_path}")
        print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
                 
        self.start_time = time.time()
        
                
        global scanf_counter, scanf_variables
        scanf_counter = 0
        scanf_variables = {}
        
                       
        setup_start = time.time()
        self.setup_project()
        
        if self.project is None:
            print("项目初始化失败")
            return []
        
                
        initial_state = self.project.factory.entry_state(
            add_options={
                angr.options.SYMBOL_FILL_UNCONSTRAINED_MEMORY,
                angr.options.SYMBOL_FILL_UNCONSTRAINED_REGISTERS
            }
        )
        
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
        
                 
        self.print_value_tracking_summary()
        
                
        self.generate_timing_report()
        
        return self.paths_info
    
    def analyze_deadended_states(self, deadended_states):
        """分析所有终止状态"""
        for i, state in enumerate(deadended_states):
            print(f"\n分析路径 {i + 1}...")
            
                    
            signature = self.extract_path_signature(state)
            
                     
            return_value_analysis = self.analyze_return_value(state)
            signature['return_value_analysis'] = return_value_analysis
            
                     
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
            print(f"  程序输出: {signature['output']}")
            print(f"  返回值分析: {return_value_analysis}")
    
    def analyze_return_value(self, state):
        """分析返回值来源"""
                            
        rax = state.regs.rax
        
        analysis = {
            'return_value': rax,
            'is_symbolic': False,
            'is_concrete': False,
            'is_constant': False,
            'symbolic_vars': [],
            'expression_type': 'unknown',
            'source_type': 'unknown',
            'computation_trace': []
        }
        
        if hasattr(rax, 'op'):
                   
            analysis['is_symbolic'] = True
            analysis['expression_type'] = rax.op
            
                    
            symbolic_vars = self.value_tracker.find_symbolic_vars(rax)
            analysis['symbolic_vars'] = symbolic_vars
            
            if symbolic_vars:
                analysis['source_type'] = 'symbolic_computation'
                print(f"  返回值是符号表达式，包含变量: {symbolic_vars}")
            else:
                analysis['source_type'] = 'concrete_computation'
                print(f"  返回值是具体计算表达式")
                
        elif hasattr(rax, 'value'):
                 
            analysis['is_concrete'] = True
            analysis['is_constant'] = True
            analysis['source_type'] = 'constant'
            print(f"  返回值是常量: {rax.value}")
        
        return analysis
    
    def extract_path_signature(self, state):
        """提取路径的多维签名"""
        signature = {}
        
                         
        global scanf_variables
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
        
                 
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            signature['output'] = output
        except:
            signature['output'] = ""
        
        return signature
    
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
                           
        binary_dir = os.path.dirname(os.path.abspath(self.binary_path))
        filename = os.path.join(binary_dir, f"{self.output_prefix}_path_{path_info['index']}.txt")
        
        with open(filename, "w", encoding='utf-8') as f:
            f.write(path_info['smt_constraints'])
            f.write("\n; 路径签名信息:\n")
            f.write(f"; 输入变量值: {path_info['signature']['variables']}\n")
            f.write(f"; 约束信息: {path_info['signature']['constraints']}\n")
            f.write(f"; 程序输出: {path_info['signature']['output']}\n")
            
                       
            if 'return_value_analysis' in path_info['signature']:
                analysis = path_info['signature']['return_value_analysis']
                f.write(f"; 返回值分析:\n")
                f.write(f";   返回值: {analysis['return_value']}\n")
                f.write(f";   是否符号: {analysis['is_symbolic']}\n")
                f.write(f";   是否具体: {analysis['is_concrete']}\n")
                f.write(f";   是否常量: {analysis['is_constant']}\n")
                f.write(f";   符号变量: {analysis['symbolic_vars']}\n")
                f.write(f";   表达式类型: {analysis['expression_type']}\n")
                f.write(f";   来源类型: {analysis['source_type']}\n")
            
            f.write(f"; \n")
            f.write(f"; 时间信息:\n")
            f.write(f"; 符号执行开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S') if self.start_time else 'N/A'}\n")
            f.write(f"; 总探索时间: {self.total_time:.3f} 秒\n")
            f.write(f"; 项目设置时间: {self.setup_time:.3f} 秒\n")
            f.write(f"; 路径探索时间: {self.exploration_time:.3f} 秒\n")
            f.write(f"; 状态分析时间: {self.analysis_time:.3f} 秒\n")
            f.write(f"; 路径索引: {path_info['index']}/{len(self.paths_info)}\n")
        
        print(f"  已保存到: {filename}")
    
    def print_value_tracking_summary(self):
        """打印值追踪摘要"""
        summary = self.value_tracker.get_traces_summary()
        print(f"\n🔍 值追踪摘要:")
        print(f"  总追踪记录: {summary['total_traces']}")
        print(f"  函数调用: {summary['function_calls']}")
        print(f"  返回值: {summary['return_values']}")
        print(f"  符号返回值: {summary['symbolic_returns']}")
        print(f"  具体返回值: {summary['concrete_returns']}")
    
    def generate_timing_report(self):
        """生成详细的时间报告"""
                          
        binary_dir = os.path.dirname(os.path.abspath(self.binary_path))
        report_filename = os.path.join(binary_dir, f"{self.output_prefix}_timing_report.txt")
        
        with open(report_filename, "w", encoding='utf-8') as f:
            f.write("增强符号执行时间报告（含值追踪）\n")
            f.write("=" * 50 + "\n\n")
            
            f.write(f"分析程序: {self.binary_path}\n")
            f.write(f"输出前缀: {self.output_prefix}\n")
            f.write(f"超时设置: {self.timeout} 秒\n\n")
            
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
            
                   
            summary = self.value_tracker.get_traces_summary()
            f.write("值追踪信息:\n")
            f.write("-" * 30 + "\n")
            f.write(f"总追踪记录: {summary['total_traces']}\n")
            f.write(f"函数调用: {summary['function_calls']}\n")
            f.write(f"返回值: {summary['return_values']}\n")
            f.write(f"符号返回值: {summary['symbolic_returns']}\n")
            f.write(f"具体返回值: {summary['concrete_returns']}\n\n")
            
            f.write("生成的文件:\n")
            f.write("-" * 30 + "\n")
            for i in range(len(self.paths_info)):
                f.write(f"{self.output_prefix}_path_{i+1}.txt\n")
        
        print(f"📄 时间报告已保存到: {report_filename}")

def main():
    """主函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='增强的符号执行分析工具（含值追踪）')
    parser.add_argument('--binary', required=True, help='二进制文件路径')
    parser.add_argument('--timeout', type=int, default=120, help='符号执行超时时间(秒)')
    parser.add_argument('--output-prefix', help='输出文件前缀')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.binary):
        print(f"❌ 文件不存在: {args.binary}")
        sys.exit(1)
    
    print(f"开始增强的符号执行分析: {args.binary}")
    analyzer = EnhancedPathAnalyzer(args.binary, args.output_prefix, args.timeout)
    results = analyzer.run_symbolic_execution()
    print(f"分析完成！共发现 {len(results)} 条路径")

if __name__ == "__main__":
    main()
