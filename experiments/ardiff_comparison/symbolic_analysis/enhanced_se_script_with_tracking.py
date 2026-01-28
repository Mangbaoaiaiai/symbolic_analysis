                      
"""
增强的符号执行脚本，包含值追踪功能
用于分析为什么等价的路径会产生不同的程序输出
"""

import angr
import claripy
import sys
import os
import time
import re
from collections import defaultdict

class EnhancedSymbolicExecutor:
    def __init__(self, binary_path, timeout=30):
        self.project = angr.Project(binary_path, auto_load_libs=False)
        self.timeout = timeout
        self.value_traces = []
        self.constraint_traces = []
        
    def run_symbolic_execution_with_tracking(self):
        """运行带值追踪的符号执行"""
        print(f"🚀 开始增强的符号执行: {self.project.filename}")
        print("=" * 60)
        
                
        state = self.setup_symbolic_state()
        
                
        self.setup_hooks()
        
                
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
        
                
        a = claripy.BVS('scanf_0', 32)
        b = claripy.BVS('scanf_1', 32)
        
                     
        state.memory.store(state.regs.rsp + 0x10, a)
        state.memory.store(state.regs.rsp + 0x14, b)
        
              
        state.add_constraints(a >= -1000, a <= 1000)
        state.add_constraints(b >= -1000, b <= 1000)
        
        return state
    
    def setup_hooks(self):
        """设置钩子函数"""
                     
        def instruction_hook(state):
                      
            pc = state.addr
            
                    
            try:
                block = self.project.factory.block(pc)
                if block.capstone.insns:
                    insn = block.capstone.insns[0]
                    
                            
                    if insn.mnemonic in ['mov', 'add', 'sub', 'mul', 'div', 'cmp', 'test']:
                        self._record_instruction(state, insn)
            except:
                pass
        
                     
        def call_hook(state):
            self._record_function_call(state)
        
                   
        def branch_hook(state):
            self._record_branch(state)
        
                          
        self.project.hook(0x400000, instruction_hook, length=0)
        self.project.hook(0x400100, call_hook, length=0)
        self.project.hook(0x400200, branch_hook, length=0)
    
    def _record_instruction(self, state, insn):
        """记录指令执行"""
        trace = {
            'type': 'instruction',
            'address': state.addr,
            'mnemonic': insn.mnemonic,
            'operands': insn.op_str,
            'registers': {
                'rax': state.regs.rax,
                'rbx': state.regs.rbx,
                'rcx': state.regs.rcx,
                'rdx': state.regs.rdx
            },
            'flags': {
                'zf': state.regs.zf,
                'sf': state.regs.sf,
                'of': state.regs.of,
                'cf': state.regs.cf
            }
        }
        
        self.value_traces.append(trace)
        
                 
        if insn.mnemonic in ['mov', 'add', 'sub', 'mul', 'div']:
            self._analyze_symbolic_expression(state.regs.rax, "RAX")
    
    def _record_function_call(self, state):
        """记录函数调用"""
        trace = {
            'type': 'call',
            'address': state.addr,
            'arguments': {
                'rdi': state.regs.rdi,
                'rsi': state.regs.rsi,
                'rdx': state.regs.rdx,
                'rcx': state.regs.rcx
            }
        }
        
        self.value_traces.append(trace)
    
    def _record_branch(self, state):
        """记录分支"""
        trace = {
            'type': 'branch',
            'address': state.addr,
            'condition': {
                'zf': state.regs.zf,
                'sf': state.regs.sf,
                'of': state.regs.of,
                'cf': state.regs.cf
            }
        }
        
        self.value_traces.append(trace)
    
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
        for name, var in self.symbolic_vars.items():
            try:
                value = state.solver.eval(var)
                print(f"     {name} = {value} (0x{value:x})")
            except Exception as e:
                print(f"     {name} = 无法求解 ({e})")
    
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
        print("用法: python3 enhanced_se_script_with_tracking.py <binary_path>")
        sys.exit(1)
    
    binary_path = sys.argv[1]
    
    if not os.path.exists(binary_path):
        print(f"❌ 文件不存在: {binary_path}")
        sys.exit(1)
    
    executor = EnhancedSymbolicExecutor(binary_path)
    executor.run_symbolic_execution_with_tracking()

if __name__ == "__main__":
    main()
