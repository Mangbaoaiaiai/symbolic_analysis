                      
"""
详细的值分析工具
用于深入分析为什么不同路径会产生不同的程序输出
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

def analyze_path_differences(binary_path, timeout=30):
    """分析路径差异"""
    print(f"🔍 开始详细分析: {binary_path}")
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
    
                 
    path_analysis = []
    
    for i, state in enumerate(simgr.deadended):
        print(f"\n{'='*80}")
        print(f"详细分析路径 {i+1}:")
        print(f"{'='*80}")
        
                
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            print(f"程序输出: {output}")
        except:
            output = "无法获取"
            print("程序输出: 无法获取")
        
                
        global scanf_variables
        input_values = {}
        if scanf_variables:
            for var_name, var in scanf_variables.items():
                try:
                    value = state.solver.eval(var, cast_to=int)
                    input_values[var_name] = value
                    print(f"输入变量 {var_name}: {value}")
                except:
                    input_values[var_name] = None
                    print(f"输入变量 {var_name}: 无法求解")
        
                 
        rax = state.regs.rax
        print(f"\n🔍 返回值详细分析:")
        print(f"  RAX值: {rax}")
        print(f"  RAX类型: {type(rax)}")
        
        if hasattr(rax, 'op'):
            print(f"  表达式操作符: {rax.op}")
            print(f"  表达式操作数: {rax.args}")
            
                    
            symbolic_vars = find_symbolic_vars(rax)
            if symbolic_vars:
                print(f"  ✅ 返回值基于符号变量计算: {symbolic_vars}")
            else:
                print(f"  ❌ 返回值不包含符号变量")
                print(f"  ✅ 返回值是常量或具体计算")
        else:
            print(f"  具体值: {rax}")
            print(f"  ✅ 返回值是常量")
        
              
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
                key_constraints.append((j+1, constraint_str[:100] + "..." if len(constraint_str) > 100 else constraint_str))
        
        if key_constraints:
            print(f"  关键约束:")
            for idx, constraint in key_constraints[:5]:          
                print(f"    约束 {idx}: {constraint}")
        
                  
        path_info = {
            'path_id': i+1,
            'output': output,
            'input_values': input_values,
            'rax_value': str(rax),
            'constraint_count': len(constraints),
            'constraint_types': constraint_types,
            'key_constraints': key_constraints[:5]
        }
        path_analysis.append(path_info)
        
                 
        try:
            solver = claripy.Solver()
            for constraint in constraints:
                solver.add(constraint)
            smt2_text = claripy_solver_to_smt2(solver)
            
                   
            binary_dir = os.path.dirname(os.path.abspath(binary_path))
            filename = os.path.join(binary_dir, f"detailed_analysis_path_{i+1}.txt")
            
            with open(filename, "w", encoding='utf-8') as f:
                f.write(smt2_text)
                f.write(f"\n; 路径 {i+1} 详细分析结果:\n")
                f.write(f"; 程序输出: {output}\n")
                f.write(f"; 输入变量: {input_values}\n")
                f.write(f"; RAX值: {rax}\n")
                f.write(f"; 约束数量: {len(constraints)}\n")
                f.write(f"; 约束类型: {constraint_types}\n")
                f.write(f"; 关键约束:\n")
                for idx, constraint in key_constraints:
                    f.write(f";   {idx}: {constraint}\n")
                f.write(f"; 分析时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            
            print(f"📄 已保存到: {filename}")
            
        except Exception as e:
            print(f"❌ 生成SMT约束失败: {e}")
    
            
    print(f"\n{'='*80}")
    print(f"路径差异比较分析:")
    print(f"{'='*80}")
    
    if len(path_analysis) > 1:
        print(f"发现 {len(path_analysis)} 个不同路径，输出分别为:")
        for path in path_analysis:
            print(f"  路径 {path['path_id']}: {path['output']}")
        
                   
        print(f"\n🔍 输出差异原因分析:")
        
               
        output_groups = {}
        for path in path_analysis:
            output = path['output']
            if output not in output_groups:
                output_groups[output] = []
            output_groups[output].append(path)
        
        print(f"  输出分组: {len(output_groups)} 个不同的输出")
        for output, paths in output_groups.items():
            print(f"    输出 '{output}': {len(paths)} 个路径 {[p['path_id'] for p in paths]}")
        
                
        print(f"\n📊 约束差异分析:")
        for i, path1 in enumerate(path_analysis):
            for j, path2 in enumerate(path_analysis[i+1:], i+1):
                print(f"  路径 {path1['path_id']} vs 路径 {path2['path_id']}:")
                print(f"    输出: '{path1['output']}' vs '{path2['output']}'")
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
    
    return path_analysis

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
    
    parser = argparse.ArgumentParser(description='详细的值分析工具')
    parser.add_argument('--binary', required=True, help='二进制文件路径')
    parser.add_argument('--timeout', type=int, default=30, help='超时时间(秒)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.binary):
        print(f"❌ 文件不存在: {args.binary}")
        sys.exit(1)
    
    analyze_path_differences(args.binary, args.timeout)

if __name__ == "__main__":
    main()
