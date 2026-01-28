                      
"""
简化的snippet函数分析工具
专门用于分析snippet(x)函数的返回值来源
"""

import angr
import claripy
import sys
import os
import time

class SimpleSnippetAnalyzer:
    def __init__(self, binary_path):
        self.project = angr.Project(binary_path, auto_load_libs=False)
        
    def analyze_snippet_return_value(self):
        """分析snippet函数的返回值"""
        print(f"🔍 分析snippet函数返回值: {self.project.filename}")
        print("=" * 60)
        
                
        state = self.setup_symbolic_state()
        
                
        simgr = self.project.factory.simulation_manager(state)
        
        start_time = time.time()
        simgr.run()
        end_time = time.time()
        
        print(f"⏱️  符号执行完成，耗时: {end_time - start_time:.3f} 秒")
        
              
        self.analyze_results(simgr)
        
        return simgr
    
    def setup_symbolic_state(self):
        """设置符号状态"""
                
        state = self.project.factory.entry_state()
        
                 
        x = claripy.BVS('scanf_0', 32)
        
                                 
        state.memory.store(state.regs.rsp + 0x10, x)
        
              
        state.add_constraints(x >= -1000, x <= 1000)
        
        print(f"✅ 设置符号变量: x = {x}")
        print(f"✅ 约束范围: -1000 <= x <= 1000")
        
        return state
    
    def analyze_results(self, simgr):
        """分析符号执行结果"""
        print(f"\n📊 符号执行结果分析")
        print("=" * 50)
        
        if simgr.deadended:
            print(f"✅ 找到 {len(simgr.deadended)} 个终止状态")
            
                    
            for i, state in enumerate(simgr.deadended):
                print(f"\n状态 {i+1}:")
                self._analyze_final_state(state, i+1)
            
                    
            if len(simgr.deadended) > 1:
                self._compare_states(simgr.deadended)
        else:
            print("❌ 没有找到终止状态")
        
        if simgr.active:
            print(f"⚠️  还有 {len(simgr.active)} 个活跃状态")
            
                    
            for i, state in enumerate(simgr.active):
                print(f"\n活跃状态 {i+1}:")
                self._analyze_active_state(state, i+1)
    
    def _analyze_final_state(self, state, state_id):
        """分析最终状态"""
                
        rax = state.regs.rax
        
        print(f"   程序输出 (RAX): {rax}")
        
                  
        self._trace_output_origin(state, rax)
        
              
        constraints = state.solver.constraints
        print(f"   路径约束数量: {len(constraints)}")
        
        if constraints:
            print(f"   约束详情:")
            for i, constraint in enumerate(constraints):
                print(f"     约束 {i+1}: {constraint}")
        
               
        print(f"   输入值求解:")
        try:
            x = claripy.BVS('scanf_0', 32)
            value = state.solver.eval(x)
            print(f"     x = {value} (0x{value:x})")
        except Exception as e:
            print(f"     x = 无法求解 ({e})")
    
    def _analyze_active_state(self, state, state_id):
        """分析活跃状态"""
                   
        pc = state.addr
        
        print(f"   程序计数器: 0x{pc:x}")
        
                 
        rax = state.regs.rax
        rbx = state.regs.rbx
        rcx = state.regs.rcx
        rdx = state.regs.rdx
        
        print(f"   寄存器状态:")
        print(f"     RAX: {rax}")
        print(f"     RBX: {rbx}")
        print(f"     RCX: {rcx}")
        print(f"     RDX: {rdx}")
        
                     
        self._analyze_register_expression(rax, "RAX")
        
              
        constraints = state.solver.constraints
        print(f"   路径约束数量: {len(constraints)}")
        
        if constraints:
            print(f"   约束详情:")
            for i, constraint in enumerate(constraints):
                print(f"     约束 {i+1}: {constraint}")
    
    def _analyze_register_expression(self, expr, name):
        """分析寄存器表达式"""
        if hasattr(expr, 'op'):
            print(f"   {name} 表达式分析:")
            print(f"     操作符: {expr.op}")
            print(f"     操作数: {expr.args}")
            
                        
            symbolic_vars = self._find_symbolic_vars(expr)
            if symbolic_vars:
                print(f"     包含符号变量: {symbolic_vars}")
                print(f"     ✅ 返回值基于符号变量计算")
            else:
                print(f"     纯数值表达式")
                print(f"     ❌ 返回值基于常量计算")
        else:
            print(f"   {name}: {expr}")
            print(f"   ❌ 返回值是常量")
    
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
    
    def _trace_output_origin(self, state, output_expr):
        """追踪输出值的来源"""
        print(f"   输出值来源分析:")
        
        if hasattr(output_expr, 'op'):
            print(f"     表达式类型: {output_expr.op}")
            print(f"     操作数: {output_expr.args}")
            
                        
            input_vars = self._find_symbolic_vars(output_expr)
            if input_vars:
                print(f"     直接依赖输入变量: {input_vars}")
                print(f"     ✅ 返回值基于符号变量计算")
            else:
                print(f"     不直接依赖输入变量")
                print(f"     ❌ 返回值基于常量计算")
        else:
            print(f"     常量值: {output_expr}")
            print(f"     ❌ 返回值是常量")
    
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

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python3 simple_snippet_analyzer.py <binary_path>")
        sys.exit(1)
    
    binary_path = sys.argv[1]
    
    if not os.path.exists(binary_path):
        print(f"❌ 文件不存在: {binary_path}")
        sys.exit(1)
    
    analyzer = SimpleSnippetAnalyzer(binary_path)
    analyzer.analyze_snippet_return_value()

if __name__ == "__main__":
    main()
