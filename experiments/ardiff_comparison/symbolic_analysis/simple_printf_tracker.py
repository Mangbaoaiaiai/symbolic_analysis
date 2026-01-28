                      
"""
简单的printf追踪工具
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

def analyze_program_flow(binary_path, timeout=30):
    """分析程序流程"""
    print(f"🔍 开始程序流程分析: {binary_path}")
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
    
            
    for i, state in enumerate(simgr.deadended):
        print(f"\n{'='*80}")
        print(f"分析路径 {i+1}:")
        print(f"{'='*80}")
        
                
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            print(f"程序输出: {output}")
        except:
            print("程序输出: 无法获取")
        
                   
        print(f"\n🔍 寄存器分析:")
        print(f"  RAX (返回值): {state.regs.rax}")
        print(f"  RBX: {state.regs.rbx}")
        print(f"  RCX: {state.regs.rcx}")
        print(f"  RDX: {state.regs.rdx}")
        
                 
        print(f"\n🔍 内存分析:")
        try:
                      
            rsp = state.regs.rsp
            print(f"  RSP: {rsp}")
            
                      
            for offset in [0, 4, 8, 12, 16]:
                try:
                    addr = rsp + offset
                    value = state.memory.load(addr, 4, endness=state.arch.memory_endness)
                    print(f"  栈[{offset}]: {value}")
                except:
                    print(f"  栈[{offset}]: 无法读取")
        except:
            print("  内存分析失败")
        
              
        constraints = state.solver.constraints
        print(f"\n📊 约束分析:")
        print(f"  约束数量: {len(constraints)}")
        
                
        global scanf_variables
        if scanf_variables:
            print(f"  输入变量:")
            for var_name, var in scanf_variables.items():
                try:
                    value = state.solver.eval(var, cast_to=int)
                    print(f"    {var_name}: {value}")
                except:
                    print(f"    {var_name}: 无法求解")
        
                
        print(f"  关键约束:")
        for j, constraint in enumerate(constraints):
            constraint_str = str(constraint)
            if 'scanf_d_1_32' in constraint_str and ('bvsge' in constraint_str or 'bvsle' in constraint_str or '==' in constraint_str):
                print(f"    约束 {j+1}: {constraint_str[:100]}...")
                if j >= 4:          
                    break

def main():
    """主函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='简单程序流程分析工具')
    parser.add_argument('--binary', required=True, help='二进制文件路径')
    parser.add_argument('--timeout', type=int, default=30, help='超时时间(秒)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.binary):
        print(f"❌ 文件不存在: {args.binary}")
        sys.exit(1)
    
    analyze_program_flow(args.binary, args.timeout)

if __name__ == "__main__":
    main()
