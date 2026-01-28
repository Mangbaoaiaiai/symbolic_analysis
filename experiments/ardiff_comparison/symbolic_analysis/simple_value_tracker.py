                      
"""
简单的值追踪符号执行脚本
专门用于分析函数返回值的来源
"""

import angr
import claripy
import os
import time
import datetime
from claripy.backends.backend_z3 import claripy_solver_to_smt2
import logging

        
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

      
scanf_variables = {}

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

def analyze_return_value_source(state):
    """分析返回值来源"""
    rax = state.regs.rax
    
    print(f"\n🔍 返回值分析:")
    print(f"  RAX值: {rax}")
    print(f"  RAX类型: {type(rax)}")
    
    if hasattr(rax, 'op'):
        print(f"  表达式操作符: {rax.op}")
        print(f"  表达式操作数: {rax.args}")
        
                
        symbolic_vars = find_symbolic_vars(rax)
        if symbolic_vars:
            print(f"  包含符号变量: {symbolic_vars}")
            print(f"  ✅ 返回值基于符号变量计算")
        else:
            print(f"  ❌ 返回值不包含符号变量")
            print(f"  ✅ 返回值是常量或具体计算")
    else:
        print(f"  具体值: {rax}")
        print(f"  ✅ 返回值是常量")

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

def analyze_binary(binary_path, timeout=30):
    """分析二进制文件"""
    print(f"🚀 开始分析: {binary_path}")
    print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
          
    project = angr.Project(binary_path, auto_load_libs=False)
    
                
    project.hook_symbol('scanf', ScanfSymProc())
    print("已hook scanf函数")
    
            
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
    print(f"活跃路径数: {len(simgr.active)}")
    print(f"错误路径数: {len(simgr.errored)}")
    
              
    for i, state in enumerate(simgr.deadended):
        print(f"\n{'='*60}")
        print(f"分析路径 {i+1}:")
        print(f"{'='*60}")
        
                
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            print(f"程序输出: {output}")
        except:
            print("程序输出: 无法获取")
        
                
        global scanf_variables
        if scanf_variables:
            for var_name, var in scanf_variables.items():
                try:
                    value = state.solver.eval(var, cast_to=int)
                    print(f"输入变量 {var_name}: {value}")
                except:
                    print(f"输入变量 {var_name}: 无法求解")
        
                 
        analyze_return_value_source(state)
        
              
        constraints = state.solver.constraints
        print(f"\n约束信息:")
        print(f"  约束数量: {len(constraints)}")
        for j, constraint in enumerate(constraints):
            print(f"  约束 {j+1}: {constraint}")
        
                 
        try:
            solver = claripy.Solver()
            for constraint in constraints:
                solver.add(constraint)
            smt2_text = claripy_solver_to_smt2(solver)
            
                   
            binary_dir = os.path.dirname(os.path.abspath(binary_path))
            filename = os.path.join(binary_dir, f"value_tracking_path_{i+1}.txt")
            
            with open(filename, "w", encoding='utf-8') as f:
                f.write(smt2_text)
                f.write(f"\n; 路径 {i+1} 分析结果:\n")
                f.write(f"; 程序输出: {output}\n")
                f.write(f"; 输入变量: {scanf_variables}\n")
                f.write(f"; 约束数量: {len(constraints)}\n")
                f.write(f"; 分析时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            
            print(f"📄 已保存到: {filename}")
            
        except Exception as e:
            print(f"❌ 生成SMT约束失败: {e}")

def main():
    """主函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='简单的值追踪符号执行工具')
    parser.add_argument('--binary', required=True, help='二进制文件路径')
    parser.add_argument('--timeout', type=int, default=30, help='超时时间(秒)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.binary):
        print(f"❌ 文件不存在: {args.binary}")
        sys.exit(1)
    
    analyze_binary(args.binary, args.timeout)

if __name__ == "__main__":
    main()
