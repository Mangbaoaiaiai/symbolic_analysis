                      
"""
分析符号执行中输出差异的工具
专门用于理解为什么等价的路径会产生不同的程序输出
"""

import angr
import claripy
import sys
import os
import re
from collections import defaultdict

class OutputDifferenceAnalyzer:
    def __init__(self, binary_path):
        self.project = angr.Project(binary_path, auto_load_libs=False)
        self.symbolic_vars = {}
        
    def analyze_output_differences(self, target_outputs):
        """分析输出差异"""
        print(f"🔍 分析输出差异: {target_outputs}")
        print("=" * 60)
        
                
        state = self.setup_symbolic_execution()
        
                
        simgr = self.project.factory.simulation_manager(state)
        simgr.run()
        
                  
        if simgr.deadended:
            print(f"✅ 找到 {len(simgr.deadended)} 个终止状态")
            
                    
            for i, state in enumerate(simgr.deadended):
                print(f"\n📊 状态 {i+1} 分析:")
                self._analyze_state(state, i+1)
            
                       
            if len(simgr.deadended) > 1:
                self._compare_states(simgr.deadended)
        else:
            print("❌ 没有找到终止状态")
    
    def setup_symbolic_execution(self):
        """设置符号执行环境"""
                
        state = self.project.factory.entry_state()
        
                
        a = claripy.BVS('scanf_0', 32)
        b = claripy.BVS('scanf_1', 32)
        self.symbolic_vars = {'a': a, 'b': b}
        
                     
        state.memory.store(state.regs.rsp + 0x10, a)
        state.memory.store(state.regs.rsp + 0x14, b)
        
        return state
    
    def _analyze_state(self, state, state_id):
        """分析单个状态"""
                
        rax = state.regs.rax
        
        print(f"   程序输出 (RAX): {rax}")
        
                  
        if hasattr(rax, 'op'):
            print(f"   输出类型: 符号表达式")
            print(f"   表达式操作: {rax.op}")
            print(f"   表达式操作数: {rax.args}")
            
                        
            symbolic_vars = self._find_symbolic_vars(rax)
            if symbolic_vars:
                print(f"   包含符号变量: {symbolic_vars}")
            else:
                print(f"   纯数值表达式")
        else:
            print(f"   输出类型: 常量值")
            print(f"   值: {rax}")
        
                
        constraints = state.solver.constraints
        print(f"   路径约束数量: {len(constraints)}")
        
        if constraints:
            print(f"   约束详情:")
            for i, constraint in enumerate(constraints):
                print(f"     约束 {i+1}: {constraint}")
        
               
        print(f"   输入值求解:")
        for name, var in self.symbolic_vars.items():
            try:
                value = state.solver.eval(var)
                print(f"     {name} = {value} (0x{value:x})")
            except Exception as e:
                print(f"     {name} = 无法求解 ({e})")
    
    def _find_symbolic_vars(self, expr):
        """查找表达式中的符号变量"""
        vars_found = set()
        
        if hasattr(expr, 'op'):
            for arg in expr.args:
                vars_found.update(self._find_symbolic_vars(arg))
        else:
            if hasattr(expr, 'name') and 'scanf' in str(expr):
                vars_found.add(expr.name)
        
        return vars_found
    
    def _compare_states(self, states):
        """比较不同状态"""
        print(f"\n🔄 状态比较分析")
        print("=" * 50)
        
              
        outputs = []
        for i, state in enumerate(states):
            rax = state.regs.rax
            outputs.append(rax)
            print(f"状态 {i+1} 输出: {rax}")
        
                
        if len(outputs) > 1:
            print(f"\n输出差异分析:")
            for i in range(len(outputs)):
                for j in range(i+1, len(outputs)):
                    self._analyze_output_difference(outputs[i], outputs[j], i+1, j+1)
        
              
        print(f"\n约束比较:")
        for i, state in enumerate(states):
            constraints = state.solver.constraints
            print(f"状态 {i+1} 约束数量: {len(constraints)}")
            
            if constraints:
                print(f"状态 {i+1} 约束详情:")
                for j, constraint in enumerate(constraints):
                    print(f"  约束 {j+1}: {constraint}")
    
    def _analyze_output_difference(self, output1, output2, state1_id, state2_id):
        """分析两个输出的差异"""
        print(f"\n状态 {state1_id} vs 状态 {state2_id}:")
        print(f"  输出1: {output1}")
        print(f"  输出2: {output2}")
        
                    
        if hasattr(output1, 'op') and hasattr(output2, 'op'):
            print(f"  两个输出都是符号表达式")
            
                     
            if output1.op == output2.op:
                print(f"  表达式操作符相同: {output1.op}")
            else:
                print(f"  表达式操作符不同: {output1.op} vs {output2.op}")
            
                   
            if output1.args == output2.args:
                print(f"  表达式操作数相同")
            else:
                print(f"  表达式操作数不同:")
                print(f"    输出1操作数: {output1.args}")
                print(f"    输出2操作数: {output2.args}")
        
        elif hasattr(output1, 'op') and not hasattr(output2, 'op'):
            print(f"  输出1是符号表达式，输出2是常量")
        elif not hasattr(output1, 'op') and hasattr(output2, 'op'):
            print(f"  输出1是常量，输出2是符号表达式")
        else:
            print(f"  两个输出都是常量")
            if hasattr(output1, 'value') and hasattr(output2, 'value'):
                diff = output1.value - output2.value
                print(f"  数值差异: {diff}")
    
    def analyze_specific_outputs(self, outputs):
        """分析特定的输出值"""
        print(f"🎯 分析特定输出值: {outputs}")
        print("=" * 60)
        
                
        state = self.setup_symbolic_execution()
        
                     
        for i, target_output in enumerate(outputs):
            print(f"\n分析输出 {i+1}: {target_output}")
            print("-" * 30)
            
                  
            constraint = state.regs.rax == target_output
            
                      
            if state.solver.satisfiable(extra_constraints=[constraint]):
                print(f"✅ 输出 {target_output} 在当前约束下可满足")
                
                       
                print(f"输入值求解:")
                for name, var in self.symbolic_vars.items():
                    try:
                        value = state.solver.eval(var, extra_constraints=[constraint])
                        print(f"  {name} = {value} (0x{value:x})")
                    except Exception as e:
                        print(f"  {name} = 无法求解 ({e})")
            else:
                print(f"❌ 输出 {target_output} 在当前约束下不可满足")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python3 analyze_output_differences.py <binary_path> [output1] [output2] ...")
        sys.exit(1)
    
    binary_path = sys.argv[1]
    
    if not os.path.exists(binary_path):
        print(f"❌ 文件不存在: {binary_path}")
        sys.exit(1)
    
    analyzer = OutputDifferenceAnalyzer(binary_path)
    
    if len(sys.argv) > 2:
                
        outputs = [int(x) for x in sys.argv[2:]]
        analyzer.analyze_specific_outputs(outputs)
    else:
                   
        analyzer.analyze_output_differences([])

if __name__ == "__main__":
    main()
