                      
"""
增强的符号执行脚本，专门追踪程序输出与scanf符号变量的关系
基于se_script.py修改
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
output_traces = []            

class ScanfSymProc(angr.SimProcedure):
    """改进的scanf符号化过程，确保生成有效约束"""
    
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

class OutputTracker:
    """输出追踪器 - 分析程序输出与符号变量的关系"""
    
    def __init__(self):
        self.traces = []
        self.output_variable_relations = []
        
    def track_output(self, state, output, path_id):
        """追踪程序输出与符号变量的关系"""
        global scanf_variables
        
        print(f"\n🔍 追踪路径 {path_id} 的输出:")
        print(f"  程序输出: {output}")
        
                  
        output_values = self.extract_output_values(output)
        print(f"  提取的数值: {output_values}")
        
                         
        relations = []
        for value in output_values:
            relation = self.analyze_value_relation(state, value, scanf_variables)
            relations.append(relation)
            print(f"  数值 {value} 的关系分析: {relation}")
        
                
        trace = {
            'path_id': path_id,
            'output': output,
            'output_values': output_values,
            'relations': relations,
            'scanf_variables': {name: str(var) for name, var in scanf_variables.items()},
            'timestamp': time.time()
        }
        
        self.traces.append(trace)
        self.output_variable_relations.extend(relations)
        
        return trace
    
    def extract_output_values(self, output):
        """从程序输出中提取数值"""
        values = []
        
                     
                                
        result_match = re.search(r'Result:\s*(-?\d+)', output)
        if result_match:
            values.append(int(result_match.group(1)))
        
                     
        number_matches = re.findall(r'-?\d+', output)
        for match in number_matches:
            try:
                value = int(match)
                if value not in values:        
                    values.append(value)
            except ValueError:
                continue
        
        return values
    
    def analyze_value_relation(self, state, value, scanf_variables):
        """分析输出值与符号变量的关系"""
        relation = {
            'value': value,
            'is_direct_symbolic': False,
            'is_constraint_derived': False,
            'symbolic_vars_involved': [],
            'constraint_analysis': {},
            'solver_analysis': {}
        }
        
                          
        for var_name, var in scanf_variables.items():
            try:
                if state.solver.satisfiable():
                    var_value = state.solver.eval(var, cast_to=int)
                    if var_value == value:
                        relation['is_direct_symbolic'] = True
                        relation['symbolic_vars_involved'].append(var_name)
                        print(f"    ✅ 发现直接符号变量关系: {var_name} = {value}")
            except:
                continue
        
                         
        if not relation['is_direct_symbolic']:
            relation['is_constraint_derived'] = self.check_constraint_derivation(state, value, scanf_variables)
        
                       
        relation['constraint_analysis'] = self.analyze_constraints_for_value(state, value, scanf_variables)
        
                    
        relation['solver_analysis'] = self.solve_for_value(state, value, scanf_variables)
        
        return relation
    
    def check_constraint_derivation(self, state, value, scanf_variables):
        """检查值是否通过约束推导得出"""
        try:
                     
            target_constraint = claripy.BVV(value, 32) == claripy.BVV(value, 32)
            
                         
            if state.solver.satisfiable(extra_constraints=[target_constraint]):
                print(f"    ✅ 值 {value} 与现有约束一致")
                return True
            else:
                print(f"    ❌ 值 {value} 与现有约束不一致")
                return False
        except:
            return False
    
    def analyze_constraints_for_value(self, state, value, scanf_variables):
        """分析约束中与目标值相关的部分"""
        analysis = {
            'relevant_constraints': [],
            'symbolic_vars_in_constraints': set(),
            'constraint_types': {}
        }
        
        for i, constraint in enumerate(state.solver.constraints):
            constraint_str = str(constraint)
            
                         
            if str(value) in constraint_str:
                analysis['relevant_constraints'].append((i, constraint_str))
                print(f"    📊 发现相关约束 {i}: {constraint_str[:100]}...")
            
                        
            for var_name, var in scanf_variables.items():
                if var_name in constraint_str:
                    analysis['symbolic_vars_in_constraints'].add(var_name)
        
        return analysis
    
    def solve_for_value(self, state, value, scanf_variables):
        """使用求解器分析如何得到目标值"""
        analysis = {
            'can_solve': False,
            'solution': {},
            'error': None
        }
        
        try:
                           
            for var_name, var in scanf_variables.items():
                try:
                                    
                    value_constraint = var == value
                    
                    if state.solver.satisfiable(extra_constraints=[value_constraint]):
                        solution = state.solver.eval(var, extra_constraints=[value_constraint], cast_to=int)
                        analysis['solution'][var_name] = solution
                        analysis['can_solve'] = True
                        print(f"    🎯 求解结果: {var_name} = {solution} 时输出 {value}")
                except Exception as e:
                    analysis['error'] = str(e)
        except Exception as e:
            analysis['error'] = str(e)
        
        return analysis

class EnhancedPathAnalyzer:
    """增强的路径分析器 - 支持输出追踪"""
    
    def __init__(self, binary_path, output_prefix=None, timeout=120):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        self.output_tracker = OutputTracker()
        
                  
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
        
                  
        self.print_output_tracking_summary()
        
                
        self.generate_timing_report()
        
        return self.paths_info
    
    def analyze_deadended_states(self, deadended_states):
        """分析所有终止状态"""
        for i, state in enumerate(deadended_states):
            print(f"\n分析路径 {i + 1}...")
            
                    
            signature = self.extract_path_signature(state)
            
                    
            try:
                output = state.posix.dumps(1).decode(errors='ignore').strip()
                signature['output'] = output
            except:
                output = ""
                signature['output'] = ""
            
                          
            output_trace = self.output_tracker.track_output(state, output, i + 1)
            signature['output_trace'] = output_trace
            
                     
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
            if output_trace['relations']:
                print(f"  输出关系分析: {len(output_trace['relations'])} 个关系")
    
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
        filename = os.path.join(binary_dir, f"{self.output_prefix}_output_tracking_path_{path_info['index']}.txt")
        
        with open(filename, "w", encoding='utf-8') as f:
            f.write(path_info['smt_constraints'])
            f.write("\n; 路径签名信息:\n")
            f.write(f"; 输入变量值: {path_info['signature']['variables']}\n")
            f.write(f"; 约束信息: {path_info['signature']['constraints']}\n")
            f.write(f"; 程序输出: {path_info['signature']['output']}\n")
            
                      
            if 'output_trace' in path_info['signature']:
                trace = path_info['signature']['output_trace']
                f.write(f"; 输出追踪分析:\n")
                f.write(f";   路径ID: {trace['path_id']}\n")
                f.write(f";   程序输出: {trace['output']}\n")
                f.write(f";   提取的数值: {trace['output_values']}\n")
                f.write(f";   符号变量: {trace['scanf_variables']}\n")
                f.write(f";   关系分析:\n")
                for i, relation in enumerate(trace['relations']):
                    f.write(f";     关系 {i+1}:\n")
                    f.write(f";       数值: {relation['value']}\n")
                    f.write(f";       直接符号关系: {relation['is_direct_symbolic']}\n")
                    f.write(f";       约束推导: {relation['is_constraint_derived']}\n")
                    f.write(f";       涉及符号变量: {relation['symbolic_vars_involved']}\n")
                    f.write(f";       约束分析: {relation['constraint_analysis']}\n")
                    f.write(f";       求解器分析: {relation['solver_analysis']}\n")
            
            f.write(f"; \n")
            f.write(f"; 时间信息:\n")
            f.write(f"; 符号执行开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S') if self.start_time else 'N/A'}\n")
            f.write(f"; 总探索时间: {self.total_time:.3f} 秒\n")
            f.write(f"; 项目设置时间: {self.setup_time:.3f} 秒\n")
            f.write(f"; 路径探索时间: {self.exploration_time:.3f} 秒\n")
            f.write(f"; 状态分析时间: {self.analysis_time:.3f} 秒\n")
            f.write(f"; 路径索引: {path_info['index']}/{len(self.paths_info)}\n")
        
        print(f"  已保存到: {filename}")
    
    def print_output_tracking_summary(self):
        """打印输出追踪摘要"""
        print(f"\n🔍 输出追踪摘要:")
        print(f"  总追踪记录: {len(self.output_tracker.traces)}")
        print(f"  输出关系: {len(self.output_tracker.output_variable_relations)}")
        
                  
        direct_relations = sum(1 for trace in self.output_tracker.traces 
                             for relation in trace['relations'] 
                             if relation['is_direct_symbolic'])
        print(f"  直接符号关系: {direct_relations}")
        
                  
        constraint_relations = sum(1 for trace in self.output_tracker.traces 
                                 for relation in trace['relations'] 
                                 if relation['is_constraint_derived'])
        print(f"  约束推导关系: {constraint_relations}")
    
    def generate_timing_report(self):
        """生成详细的时间报告"""
                          
        binary_dir = os.path.dirname(os.path.abspath(self.binary_path))
        report_filename = os.path.join(binary_dir, f"{self.output_prefix}_output_tracking_timing_report.txt")
        
        with open(report_filename, "w", encoding='utf-8') as f:
            f.write("增强符号执行时间报告（含输出追踪）\n")
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
            
                    
            f.write("输出追踪信息:\n")
            f.write("-" * 30 + "\n")
            f.write(f"总追踪记录: {len(self.output_tracker.traces)}\n")
            f.write(f"输出关系: {len(self.output_tracker.output_variable_relations)}\n")
            
            direct_relations = sum(1 for trace in self.output_tracker.traces 
                                 for relation in trace['relations'] 
                                 if relation['is_direct_symbolic'])
            f.write(f"直接符号关系: {direct_relations}\n")
            
            constraint_relations = sum(1 for trace in self.output_tracker.traces 
                                     for relation in trace['relations'] 
                                     if relation['is_constraint_derived'])
            f.write(f"约束推导关系: {constraint_relations}\n\n")
            
            f.write("生成的文件:\n")
            f.write("-" * 30 + "\n")
            for i in range(len(self.paths_info)):
                f.write(f"{self.output_prefix}_output_tracking_path_{i+1}.txt\n")
        
        print(f"📄 时间报告已保存到: {report_filename}")

def main():
    """主函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='增强的符号执行分析工具（含输出追踪）')
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
