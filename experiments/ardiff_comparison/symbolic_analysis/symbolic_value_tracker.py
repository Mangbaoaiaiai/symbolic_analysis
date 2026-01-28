                      
"""
符号执行值追踪工具
专门用于分析Angr符号执行过程中值的来源和计算过程
"""

import angr
import claripy
import sys
import os
import re
from collections import defaultdict

class SymbolicValueTracker:
    def __init__(self, binary_path):
        self.project = angr.Project(binary_path, auto_load_libs=False)
        self.symbolic_vars = {}
        self.value_traces = []
        
    def setup_symbolic_execution(self):
        """设置符号执行环境"""
                
        state = self.project.factory.entry_state()
        
                
        a = claripy.BVS('scanf_0', 32)
        b = claripy.BVS('scanf_1', 32)
        self.symbolic_vars = {'a': a, 'b': b}
        
                     
        state.memory.store(state.regs.rsp + 0x10, a)
        state.memory.store(state.regs.rsp + 0x14, b)
        
        return state
    
    def trace_execution_with_hooks(self):
        """使用钩子函数追踪执行过程"""
        print("🔍 开始符号执行追踪...")
        
                
        self._setup_hooks()
        
                   
        state = self.setup_symbolic_execution()
        simgr = self.project.factory.simulation_manager(state)
        
                
        simgr.run()
        
              
        self._analyze_results(simgr)
    
    def _setup_hooks(self):
        """设置钩子函数"""
                           
        def instruction_hook(state):
                    
            pc = state.addr
            instruction = self.project.factory.block(pc).capstone.insns[0] if self.project.factory.block(pc).capstone.insns else None
            
            if instruction:
                print(f"📍 指令: {instruction.mnemonic} {instruction.op_str} @ 0x{pc:x}")
                
                         
                if instruction.mnemonic in ['mov', 'add', 'sub', 'mul', 'div']:
                    self._record_register_state(state, instruction)
        
                       
        def call_hook(state):
            print(f"📞 函数调用 @ 0x{state.addr:x}")
            self._record_function_call(state)
        
                     
        def branch_hook(state):
            print(f"🌿 分支 @ 0x{state.addr:x}")
            self._record_branch(state)
        
                
        self.project.hook(0x400000, instruction_hook, length=0)        
        self.project.hook(0x400100, call_hook, length=0)        
        self.project.hook(0x400200, branch_hook, length=0)        
    
    def _record_register_state(self, state, instruction):
        """记录寄存器状态"""
                   
        rax = state.regs.rax
        rbx = state.regs.rbx
        rcx = state.regs.rcx
        rdx = state.regs.rdx
        
        print(f"   寄存器状态:")
        print(f"     RAX: {rax}")
        print(f"     RBX: {rbx}")
        print(f"     RCX: {rcx}")
        print(f"     RDX: {rdx}")
        
                 
        self._analyze_symbolic_expression(rax, "RAX")
    
    def _record_function_call(self, state):
        """记录函数调用"""
                
        rdi = state.regs.rdi
        rsi = state.regs.rsi
        rdx = state.regs.rdx
        
        print(f"   函数参数:")
        print(f"     RDI: {rdi}")
        print(f"     RSI: {rsi}")
        print(f"     RDX: {rdx}")
    
    def _record_branch(self, state):
        """记录分支信息"""
                
        zf = state.regs.zf
        sf = state.regs.sf
        of = state.regs.of
        cf = state.regs.cf
        
        print(f"   标志位:")
        print(f"     ZF: {zf}")
        print(f"     SF: {sf}")
        print(f"     OF: {of}")
        print(f"     CF: {cf}")
    
    def _analyze_symbolic_expression(self, expr, name):
        """分析符号表达式"""
        if hasattr(expr, 'op'):
            print(f"   {name} 表达式分析:")
            print(f"     操作符: {expr.op}")
            print(f"     操作数: {expr.args}")
            
                        
            symbolic_vars = self._find_symbolic_vars(expr)
            if symbolic_vars:
                print(f"     包含符号变量: {symbolic_vars}")
            else:
                print(f"     纯数值表达式")
        else:
            print(f"   {name}: {expr}")
    
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
    
    def _analyze_results(self, simgr):
        """分析符号执行结果"""
        print("\n📊 符号执行结果分析")
        print("=" * 50)
        
        if simgr.deadended:
            print(f"✅ 找到 {len(simgr.deadended)} 个终止状态")
            
            for i, state in enumerate(simgr.deadended):
                print(f"\n状态 {i+1}:")
                self._analyze_final_state(state)
        else:
            print("❌ 没有找到终止状态")
        
        if simgr.active:
            print(f"⚠️  还有 {len(simgr.active)} 个活跃状态")
    
    def _analyze_final_state(self, state):
        """分析最终状态"""
                
        rax = state.regs.rax
        
        print(f"   程序输出 (RAX): {rax}")
        
                  
        self._trace_output_origin(state, rax)
        
              
        constraints = state.solver.constraints
        print(f"   路径约束数量: {len(constraints)}")
        
               
        self._solve_inputs(state)
    
    def _trace_output_origin(self, state, output_expr):
        """追踪输出值的来源"""
        print(f"   输出值来源分析:")
        
        if hasattr(output_expr, 'op'):
            print(f"     表达式类型: {output_expr.op}")
            print(f"     操作数: {output_expr.args}")
            
                        
            input_vars = self._find_symbolic_vars(output_expr)
            if input_vars:
                print(f"     直接依赖输入变量: {input_vars}")
            else:
                print(f"     不直接依赖输入变量")
        else:
            print(f"     常量值: {output_expr}")
    
    def _solve_inputs(self, state):
        """求解输入值"""
        print(f"   输入值求解:")
        
        solver = state.solver
        
        for name, var in self.symbolic_vars.items():
            try:
                            
                value = solver.eval(var)
                print(f"     {name} = {value} (0x{value:x})")
            except Exception as e:
                print(f"     {name} = 无法求解 ({e})")
    
    def compare_paths(self, path1_state, path2_state):
        """比较两个路径的差异"""
        print("\n🔄 路径差异比较")
        print("=" * 50)
        
              
        output1 = path1_state.regs.rax
        output2 = path2_state.regs.rax
        
        print(f"路径1输出: {output1}")
        print(f"路径2输出: {output2}")
        
              
        constraints1 = path1_state.solver.constraints
        constraints2 = path2_state.solver.constraints
        
        print(f"路径1约束数量: {len(constraints1)}")
        print(f"路径2约束数量: {len(constraints2)}")
        
                
        print(f"\n输入要求比较:")
        self._compare_input_requirements(path1_state, path2_state)
    
    def _compare_input_requirements(self, state1, state2):
        """比较输入要求"""
        solver1 = state1.solver
        solver2 = state2.solver
        
        print(f"路径1输入要求:")
        for name, var in self.symbolic_vars.items():
            try:
                value = solver1.eval(var)
                print(f"  {name} = {value}")
            except:
                print(f"  {name} = 无法求解")
        
        print(f"路径2输入要求:")
        for name, var in self.symbolic_vars.items():
            try:
                value = solver2.eval(var)
                print(f"  {name} = {value}")
            except:
                print(f"  {name} = 无法求解")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python3 symbolic_value_tracker.py <binary_path>")
        sys.exit(1)
    
    binary_path = sys.argv[1]
    
    if not os.path.exists(binary_path):
        print(f"❌ 文件不存在: {binary_path}")
        sys.exit(1)
    
    tracker = SymbolicValueTracker(binary_path)
    tracker.trace_execution_with_hooks()

if __name__ == "__main__":
    main()
