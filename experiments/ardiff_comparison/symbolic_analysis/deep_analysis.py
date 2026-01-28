                      
"""
深度分析工具
用于理解为什么不同路径会产生不同的程序输出
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

def analyze_program_behavior(binary_path, timeout=30):
    """分析程序行为"""
    print(f"🔍 开始深度程序行为分析: {binary_path}")
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
    
            
    path_analyses = []
    
    for i, state in enumerate(simgr.deadended):
        print(f"\n{'='*80}")
        print(f"深度分析路径 {i+1}:")
        print(f"{'='*80}")
        
                
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            print(f"程序输出: {output}")
        except:
            output = "无法获取"
            print("程序输出: 无法获取")
        
                   
        print(f"\n�� 寄存器详细分析:")
        rax = state.regs.rax
        rbx = state.regs.rbx
        rcx = state.regs.rcx
        rdx = state.regs.rdx
        
        print(f"  RAX (返回值): {rax}")
        print(f"  RBX: {rbx}")
        print(f"  RCX: {rcx}")
        print(f"  RDX: {rdx}")
        
                   
        print(f"\n🔍 寄存器值来源分析:")
        for reg_name, reg_value in [("RAX", rax), ("RBX", rbx), ("RCX", rcx), ("RDX", rdx)]:
            if hasattr(reg_value, 'op'):
                print(f"  {reg_name}: 符号表达式")
                print(f"    操作符: {reg_value.op}")
                print(f"    操作数: {reg_value.args}")
                
                        
                symbolic_vars = find_symbolic_vars(reg_value)
                if symbolic_vars:
                    print(f"    包含符号变量: {symbolic_vars}")
                else:
                    print(f"    不包含符号变量")
            else:
                print(f"  {reg_name}: 常量值 {reg_value}")
        
                 
        print(f"\n🔍 内存详细分析:")
        try:
            rsp = state.regs.rsp
            print(f"  RSP: {rsp}")
            
                    
            for offset in [0, 4, 8, 12, 16, 20, 24, 28, 32]:
                try:
                    addr = rsp + offset
                    value = state.memory.load(addr, 4, endness=state.arch.memory_endness)
                    print(f"  栈[{offset:2d}]: {value}")
                    
                            
                    if hasattr(value, 'op'):
                        symbolic_vars = find_symbolic_vars(value)
                        if symbolic_vars:
                            print(f"        包含符号变量: {symbolic_vars}")
                except:
                    print(f"  栈[{offset:2d}]: 无法读取")
        except:
            print("  内存分析失败")
        
              
        constraints = state.solver.constraints
        print(f"\n📊 约束详细分析:")
        print(f"  约束数量: {len(constraints)}")
        
                
        constraint_types = {}
        for constraint in constraints:
            constraint_str = str(constraint)
            if 'scanf_d_1_32' in constraint_str:
                if 'bvsge' in constraint_str or 'bvsle' in constraint_str:
                    constraint_types['signed_comparison'] = constraint_types.get('signed_comparison', 0) + 1
                elif 'bvuge' in constraint_str or 'bvule' in constraint_str:
                    constraint_types['unsigned_comparison'] = constraint_types.get('unsigned_comparison', 0) + 1
                elif '==' in constraint_str:
                    constraint_types['equality'] = constraint_types.get('equality', 0) + 1
                elif '!=' in constraint_str:
                    constraint_types['inequality'] = constraint_types.get('inequality', 0) + 1
                else:
                    constraint_types['other'] = constraint_types.get('other', 0) + 1
        
        print(f"  约束类型分布: {constraint_types}")
        
                
        key_constraints = []
        for j, constraint in enumerate(constraints):
            constraint_str = str(constraint)
            if 'scanf_d_1_32' in constraint_str and ('bvsge' in constraint_str or 'bvsle' in constraint_str or '==' in constraint_str):
                key_constraints.append((j+1, constraint_str))
        
        print(f"  关键约束:")
        for idx, constraint in key_constraints[:10]:          
            print(f"    约束 {idx}: {constraint[:150]}...")
        
                
        global scanf_variables
        input_values = {}
        if scanf_variables:
            print(f"\n🔍 输入变量分析:")
            for var_name, var in scanf_variables.items():
                try:
                    value = state.solver.eval(var, cast_to=int)
                    input_values[var_name] = value
                    print(f"  {var_name}: {value}")
                except:
                    input_values[var_name] = None
                    print(f"  {var_name}: 无法求解")
        
                  
        path_analysis = {
            'path_id': i+1,
            'output': output,
            'rax': str(rax),
            'rbx': str(rbx),
            'rcx': str(rcx),
            'rdx': str(rdx),
            'constraint_count': len(constraints),
            'constraint_types': constraint_types,
            'key_constraints': key_constraints[:10],
            'input_values': input_values
        }
        path_analyses.append(path_analysis)
    
          
    print(f"\n{'='*80}")
    print(f"路径比较分析:")
    print(f"{'='*80}")
    
    if len(path_analyses) > 1:
        print(f"发现 {len(path_analyses)} 个不同路径，输出分别为:")
        for path in path_analyses:
            print(f"  路径 {path['path_id']}: {path['output']}")
        
                   
        print(f"\n🔍 输出差异原因分析:")
        
               
        output_groups = {}
        for path in path_analyses:
            output = path['output']
            if output not in output_groups:
                output_groups[output] = []
            output_groups[output].append(path)
        
        print(f"  输出分组: {len(output_groups)} 个不同的输出")
        for output, paths in output_groups.items():
            print(f"    输出 '{output}': {len(paths)} 个路径 {[p['path_id'] for p in paths]}")
        
                 
        print(f"\n🔍 寄存器差异分析:")
        for i, path1 in enumerate(path_analyses):
            for j, path2 in enumerate(path_analyses[i+1:], i+1):
                print(f"  路径 {path1['path_id']} vs 路径 {path2['path_id']}:")
                print(f"    输出: '{path1['output']}' vs '{path2['output']}'")
                print(f"    RAX: {path1['rax']} vs {path2['rax']}")
                print(f"    RBX: {path1['rbx']} vs {path2['rbx']}")
                print(f"    RCX: {path1['rcx']} vs {path2['rcx']}")
                print(f"    RDX: {path1['rdx']} vs {path2['rdx']}")
                print(f"    约束数量: {path1['constraint_count']} vs {path2['constraint_count']}")
                print(f"    约束类型: {path1['constraint_types']} vs {path2['constraint_types']}")
                
                           
                types1 = set(path1['constraint_types'].keys())
                types2 = set(path2['constraint_types'].keys())
                common_types = types1 & types2
                diff_types = (types1 | types2) - common_types
                
                if diff_types:
                    print(f"    不同约束类型: {diff_types}")
                else:
                    print(f"    约束类型相同，但数量不同")
                print()
    
    return path_analyses

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

def main():
    """主函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='深度程序行为分析工具')
    parser.add_argument('--binary', required=True, help='二进制文件路径')
    parser.add_argument('--timeout', type=int, default=30, help='超时时间(秒)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.binary):
        print(f"❌ 文件不存在: {args.binary}")
        sys.exit(1)
    
    analyze_program_behavior(args.binary, args.timeout)

if __name__ == "__main__":
    main()
