                      
"""
Angr值追踪分析工具
用于追踪程序中某个值是如何通过符号变量计算得到的
"""

import angr
import claripy
import sys
import os

class ValueTracker:
    def __init__(self, binary_path):
        self.project = angr.Project(binary_path, auto_load_libs=False)
        self.state = None
        self.symbolic_vars = {}
        
    def setup_symbolic_state(self, input_values=None):
        """设置符号执行状态"""
                
        self.state = self.project.factory.entry_state()
        
                
        if input_values is None:
                           
            a = claripy.BVS('scanf_0', 32)
            b = claripy.BVS('scanf_1', 32)
            self.symbolic_vars = {'a': a, 'b': b}
        else:
                      
            self.symbolic_vars = input_values
            
                                 
        for name, var in self.symbolic_vars.items():
                       
            self.state.memory.store(self.state.regs.rsp + 0x10, var)
            
        return self.state
    
    def track_value_origin(self, target_value, max_depth=10):
        """追踪目标值的来源"""
        print(f"🔍 追踪值: {target_value}")
        print("=" * 50)
        
                          
        self._solve_for_inputs(target_value)
        
                      
        self._analyze_symbolic_expression(target_value)
        
                    
        self._trace_data_flow(target_value)
    
    def _solve_for_inputs(self, target_value):
        """通过约束求解找到能产生目标值的输入"""
        print("📊 方法1: 约束求解分析")
        print("-" * 30)
        
               
        solver = self.state.solver
        
                        
        output_constraint = self.state.regs.rax == target_value
        
                 
        if solver.satisfiable(extra_constraints=[output_constraint]):
            print(f"✅ 值 {target_value} 可以通过某些输入产生")
            
                      
            try:
                solution = solver.eval_one(output_constraint)
                print(f"   可能的输入组合: {solution}")
                
                          
                for name, var in self.symbolic_vars.items():
                    try:
                        var_value = solver.eval(var, extra_constraints=[output_constraint])
                        print(f"   {name} = {var_value}")
                    except:
                        print(f"   {name} = 无法确定")
                        
            except Exception as e:
                print(f"   ⚠️  求解失败: {e}")
        else:
            print(f"❌ 值 {target_value} 无法通过任何输入产生")
    
    def _analyze_symbolic_expression(self, target_value):
        """分析符号表达式"""
        print("\n🔬 方法2: 符号表达式分析")
        print("-" * 30)
        
                        
        rax_expr = self.state.regs.rax
        
        print(f"RAX的符号表达式: {rax_expr}")
        print(f"表达式类型: {type(rax_expr)}")
        
                    
        if hasattr(rax_expr, 'op'):
            print(f"操作符: {rax_expr.op}")
            print(f"操作数数量: {len(rax_expr.args)}")
            
            for i, arg in enumerate(rax_expr.args):
                print(f"  操作数 {i}: {arg}")
                if hasattr(arg, 'op'):
                    print(f"    类型: {arg.op}")
                else:
                    print(f"    类型: 叶子节点")
    
    def _trace_data_flow(self, target_value):
        """追踪数据流"""
        print("\n�� 方法3: 数据流追踪")
        print("-" * 30)
        
                          
        rax_expr = self.state.regs.rax
        
                       
        symbolic_vars_in_expr = self._find_symbolic_vars(rax_expr)
        
        print(f"表达式中包含的符号变量: {symbolic_vars_in_expr}")
        
                     
        for var_name in symbolic_vars_in_expr:
            if var_name in self.symbolic_vars:
                var = self.symbolic_vars[var_name]
                print(f"\n分析变量 {var_name}:")
                print(f"  变量表达式: {var}")
                print(f"  变量约束: {self.state.solver.constraints}")
    
    def _find_symbolic_vars(self, expr):
        """递归查找表达式中的符号变量"""
        vars_found = set()
        
        if hasattr(expr, 'op'):
            for arg in expr.args:
                vars_found.update(self._find_symbolic_vars(arg))
        else:
                  
            if hasattr(expr, 'name') and 'scanf' in str(expr):
                vars_found.add(expr.name)
        
        return vars_found
    
    def compare_outputs(self, output1, output2):
        """比较两个输出的差异"""
        print(f"\n🔄 输出比较分析")
        print("=" * 50)
        print(f"输出1: {output1}")
        print(f"输出2: {output2}")
        print(f"差异: {output1 - output2}")
        
                      
        print(f"\n输出1的符号表达式:")
        self._analyze_symbolic_expression(output1)
        
        print(f"\n输出2的符号表达式:")
        self._analyze_symbolic_expression(output2)

def analyze_binary(binary_path, target_values=None):
    """分析二进制文件"""
    print(f"�� 开始分析: {binary_path}")
    
    tracker = ValueTracker(binary_path)
    state = tracker.setup_symbolic_state()
    
    if target_values:
        for value in target_values:
            tracker.track_value_origin(value)
            print("\n" + "="*60 + "\n")
    
    return tracker

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python3 value_tracking_analysis.py <binary_path> [target_value1] [target_value2] ...")
        sys.exit(1)
    
    binary_path = sys.argv[1]
    target_values = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else None
    
    if not os.path.exists(binary_path):
        print(f"❌ 文件不存在: {binary_path}")
        sys.exit(1)
    
    tracker = analyze_binary(binary_path, target_values)
    
                  
    if len(sys.argv) >= 4:
        output1 = int(sys.argv[2])
        output2 = int(sys.argv[3])
        tracker.compare_outputs(output1, output2)

if __name__ == "__main__":
    main()
