                      
"""
专门追踪printf语句中值的工具
用于理解程序输出的真正来源
"""

import angr
import claripy
import os
import time
import datetime
import logging

        
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

      
scanf_variables = {}
printf_traces = []

class ScanfSymProc(angr.SimProcedure):
    """scanf符号化过程"""
    
    def run(self, fmt_ptr, *args):
        global scanf_variables
        
                 
        try:
            fmt_str = self.state.mem[fmt_ptr].string.concrete.decode('utf-8')
        except:
            fmt_str = "%d"
        
        print(f"scanf格式字符串: {fmt_str}")
        
                
        sym_var = claripy.BVS('input_x', 32)
        
              
        self.state.solver.add(sym_var >= 0)
        self.state.solver.add(sym_var <= 15)
        
        print(f"创建符号变量: input_x (范围: 0-15)")
        
                
        scanf_variables['input_x'] = sym_var
        
              
        if len(args) > 0:
            self.state.memory.store(
                args[0],
                sym_var,
                endness=self.state.arch.memory_endness
            )
            print(f"写入符号变量到地址 {args[0]}")
        
        return claripy.BVV(1, self.state.arch.bits)

class PrintfHook(angr.SimProcedure):
    """printf钩子过程 - 追踪printf参数"""
    
    def run(self, fmt_ptr, *args):
        global printf_traces
        
                 
        try:
            fmt_str = self.state.mem[fmt_ptr].string.concrete.decode('utf-8')
        except:
            fmt_str = "Result: %d"
        
        print(f"\n🔍 追踪printf调用:")
        print(f"  格式字符串: {fmt_str}")
        print(f"  参数数量: {len(args)}")
        
                
        for i, arg in enumerate(args):
            print(f"  参数 {i+1}: {arg}")
            
                      
            try:
                if hasattr(arg, 'op'):
                    print(f"    类型: 符号表达式")
                    print(f"    操作符: {arg.op}")
                    print(f"    操作数: {arg.args}")
                    
                            
                    symbolic_vars = find_symbolic_vars(arg)
                    if symbolic_vars:
                        print(f"    包含符号变量: {symbolic_vars}")
                    else:
                        print(f"    不包含符号变量")
                        
                             
                    try:
                        value = self.state.solver.eval(arg, cast_to=int)
                        print(f"    求解值: {value}")
                    except:
                        print(f"    无法求解具体值")
                else:
                    print(f"    类型: 常量值")
                    print(f"    值: {arg}")
            except Exception as e:
                print(f"    分析失败: {e}")
        
                    
        printf_trace = {
            'format': fmt_str,
            'args': [str(arg) for arg in args],
            'timestamp': time.time()
        }
        printf_traces.append(printf_trace)
        
                     
        return self.inline_call(angr.SIM_PROCEDURES['libc']['printf'], fmt_ptr, *args).ret_expr

def find_symbolic_vars(expr):
    """递归查找表达式中的符号变量"""
    vars_found = set()
    
    if hasattr(expr, 'op'):
        for arg in expr.args:
            vars_found.update(find_symbolic_vars(arg))
    else:
        if hasattr(expr, 'name') and 'input' in str(expr):
            vars_found.add(expr.name)
    
    return vars_found

def analyze_printf_values(binary_path, timeout=30):
    """分析printf中的值"""
    print(f"🔍 开始printf值追踪分析: {binary_path}")
    print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
          
    project = angr.Project(binary_path, auto_load_libs=False)
    
                       
    project.hook_symbol('scanf', ScanfSymProc())
    project.hook_symbol('printf', PrintfHook())
    print("已hook scanf和printf函数")
    
            
    state = project.factory.entry_state(
        add_options={
            angr.options.SYMBOL_FILL_UNCONSTRAINED_MEMORY,
            angr.options.SYMBOL_FILL_UNCONSTRAINED_REGISTERS
        }
    )
    
            
    simgr = project.factory.simulation_manager(state)
    
    start_time = time.time()
    simgr.run(timeout=timeout)
    end_time = time.time()
    
    print(f"\n⏱️  符号执行完成，耗时: {end_time - start_time:.3f} 秒")
    print(f"终止路径数: {len(simgr.deadended)}")
    print(f"printf调用次数: {len(printf_traces)}")
    
                     
    for i, state in enumerate(simgr.deadended):
        print(f"\n{'='*80}")
        print(f"分析路径 {i+1} 的printf调用:")
        print(f"{'='*80}")
        
                
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            print(f"程序输出: {output}")
        except:
            print("程序输出: 无法获取")
        
                       
        rax = state.regs.rax
        print(f"RAX寄存器值: {rax}")
        
              
        constraints = state.solver.constraints
        print(f"约束数量: {len(constraints)}")
        
                
        global scanf_variables
        if scanf_variables:
            for var_name, var in scanf_variables.items():
                try:
                    value = state.solver.eval(var, cast_to=int)
                    print(f"输入变量 {var_name}: {value}")
                except:
                    print(f"输入变量 {var_name}: 无法求解")
    
                
    print(f"\n{'='*80}")
    print(f"printf调用总结:")
    print(f"{'='*80}")
    
    for i, trace in enumerate(printf_traces):
        print(f"调用 {i+1}:")
        print(f"  格式: {trace['format']}")
        print(f"  参数: {trace['args']}")
    
    return printf_traces

def main():
    """主函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='printf值追踪工具')
    parser.add_argument('--binary', required=True, help='二进制文件路径')
    parser.add_argument('--timeout', type=int, default=30, help='超时时间(秒)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.binary):
        print(f"❌ 文件不存在: {args.binary}")
        sys.exit(1)
    
    analyze_printf_values(args.binary, args.timeout)

if __name__ == "__main__":
    main()
