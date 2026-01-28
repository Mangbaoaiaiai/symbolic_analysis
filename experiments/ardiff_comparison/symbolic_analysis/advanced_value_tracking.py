                      
"""
高级Angr值追踪分析工具
专门用于分析符号执行中值的来源和计算过程
"""

import angr
import claripy
import sys
import os
import re
from collections import defaultdict

class AdvancedValueTracker:
    def __init__(self, binary_path):
        self.project = angr.Project(binary_path, auto_load_libs=False)
        self.state = None
        self.symbolic_vars = {}
        self.value_history = []
        self.constraint_history = []
        
    def setup_symbolic_execution(self):
        """设置符号执行环境"""
                
        self.state = self.project.factory.entry_state()
        
                
        a = claripy.BVS('scanf_0', 32)
        b = claripy.BVS('scanf_1', 32)
        self.symbolic_vars = {'a': a, 'b': b}
        
                     
                        
        self.state.memory.store(self.state.regs.rsp + 0x10, a)
        self.state.memory.store(self.state.regs.rsp + 0x14, b)
        
        return self.state
    
    def trace_value_computation(self, target_value):
        """追踪值的计算过程"""
        print(f"🔍 追踪值计算过程: {target_value}")
        print("=" * 60)
        
                   
        self._constraint_analysis(target_value)
        
                    
        self._expression_decomposition(target_value)
        
                  
        self._input_solving(target_value)
        
                   
        self._path_constraint_analysis(target_value)
    
    def _constraint_analysis(self, target_value):
        """约束分析"""
        print("📊 约束分析")
        print("-" * 30)
        
        solver = self.state.solver
        
                 
        target_constraint = self.state.regs.rax == target_value
        
                  
        if solver.satisfiable(extra_constraints=[target_constraint]):
            print(f"✅ 值 {target_value} 在当前约束下可满足")
            
                    
            all_constraints = solver.constraints
            print(f"当前约束数量: {len(all_constraints)}")
            
                    
            constraint_types = defaultdict(int)
            for constraint in all_constraints:
                if hasattr(constraint, 'op'):
                    constraint_types[constraint.op] += 1
            
            print("约束类型分布:")
            for op, count in constraint_types.items():
                print(f"  {op}: {count}个")
                
        else:
            print(f"❌ 值 {target_value} 在当前约束下不可满足")
    
    def _expression_decomposition(self, target_value):
        """符号表达式分解"""
        print("\n🔬 符号表达式分解")
        print("-" * 30)
        
        rax_expr = self.state.regs.rax
        print(f"RAX表达式: {rax_expr}")
        
                 
        self._decompose_expression(rax_expr, 0)
    
    def _decompose_expression(self, expr, depth):
        """递归分解表达式"""
        indent = "  " * depth
        
        if hasattr(expr, 'op'):
            print(f"{indent}操作: {expr.op}")
            print(f"{indent}操作数数量: {len(expr.args)}")
            
            for i, arg in enumerate(expr.args):
                print(f"{indent}  操作数 {i}:")
                self._decompose_expression(arg, depth + 1)
        else:
            print(f"{indent}叶子节点: {expr}")
            if hasattr(expr, 'name'):
                print(f"{indent}  变量名: {expr.name}")
            if hasattr(expr, 'value'):
                print(f"{indent}  值: {expr.value}")
    
    def _input_solving(self, target_value):
        """输入值求解"""
        print("\n🎯 输入值求解")
        print("-" * 30)
        
        solver = self.state.solver
        
                
        target_constraint = self.state.regs.rax == target_value
        
        try:
                        
            solution = {}
            for name, var in self.symbolic_vars.items():
                try:
                    value = solver.eval(var, extra_constraints=[target_constraint])
                    solution[name] = value
                    print(f"{name} = {value} (0x{value:x})")
                except Exception as e:
                    print(f"{name} = 无法求解 ({e})")
            
                     
            if solution:
                print(f"\n验证求解结果:")
                self._verify_solution(solution, target_value)
                
        except Exception as e:
            print(f"❌ 求解失败: {e}")
    
    def _verify_solution(self, solution, target_value):
        """验证求解结果"""
                   
        test_state = self.project.factory.entry_state()
        
                  
        for name, value in solution.items():
            if name == 'a':
                test_state.memory.store(test_state.regs.rsp + 0x10, claripy.BVV(value, 32))
            elif name == 'b':
                test_state.memory.store(test_state.regs.rsp + 0x14, claripy.BVV(value, 32))
        
              
        try:
            simgr = self.project.factory.simulation_manager(test_state)
            simgr.run()
            
            if simgr.deadended:
                final_state = simgr.deadended[0]
                actual_output = final_state.regs.rax.concrete_value
                print(f"  期望输出: {target_value}")
                print(f"  实际输出: {actual_output}")
                print(f"  匹配: {'✅' if actual_output == target_value else '❌'}")
            else:
                print("  ⚠️  程序未正常结束")
                
        except Exception as e:
            print(f"  ❌ 验证失败: {e}")
    
    def _path_constraint_analysis(self, target_value):
        """路径约束分析"""
        print("\n🛤️  路径约束分析")
        print("-" * 30)
        
        solver = self.state.solver
        
                
        constraints = solver.constraints
        print(f"路径约束数量: {len(constraints)}")
        
                     
        var_dependencies = defaultdict(set)
        for constraint in constraints:
            vars_in_constraint = self._extract_variables(constraint)
            for var in vars_in_constraint:
                var_dependencies[var].add(constraint)
        
        print("约束依赖关系:")
        for var, deps in var_dependencies.items():
            print(f"  {var}: {len(deps)}个约束")
    
    def _extract_variables(self, expr):
        """提取表达式中的变量"""
        variables = set()
        
        if hasattr(expr, 'op'):
            for arg in expr.args:
                variables.update(self._extract_variables(arg))
        else:
            if hasattr(expr, 'name'):
                variables.add(expr.name)
        
        return variables
    
    def compare_different_outputs(self, output1, output2):
        """比较两个不同输出的差异"""
        print(f"\n🔄 输出差异分析")
        print("=" * 60)
        print(f"输出1: {output1}")
        print(f"输出2: {output2}")
        print(f"数值差异: {output1 - output2}")
        print(f"位差异: {bin(output1 ^ output2)}")
        
                     
        print(f"\n分析输出1的计算路径:")
        self.trace_value_computation(output1)
        
        print(f"\n分析输出2的计算路径:")
        self.trace_value_computation(output2)
        
                
        print(f"\n比较输入要求:")
        self._compare_input_requirements(output1, output2)
    
    def _compare_input_requirements(self, output1, output2):
        """比较产生不同输出所需的输入条件"""
        print("输入条件比较:")
        print("-" * 30)
        
        solver = self.state.solver
        
                    
        constraint1 = self.state.regs.rax == output1
        try:
            solution1 = {}
            for name, var in self.symbolic_vars.items():
                try:
                    value = solver.eval(var, extra_constraints=[constraint1])
                    solution1[name] = value
                except:
                    solution1[name] = "无法求解"
        except:
            solution1 = {"error": "约束不可满足"}
        
                    
        constraint2 = self.state.regs.rax == output2
        try:
            solution2 = {}
            for name, var in self.symbolic_vars.items():
                try:
                    value = solver.eval(var, extra_constraints=[constraint2])
                    solution2[name] = value
                except:
                    solution2[name] = "无法求解"
        except:
            solution2 = {"error": "约束不可满足"}
        
        print(f"输出1的输入条件: {solution1}")
        print(f"输出2的输入条件: {solution2}")
        
              
        if "error" not in solution1 and "error" not in solution2:
            print(f"\n输入差异:")
            for name in self.symbolic_vars.keys():
                if name in solution1 and name in solution2:
                    diff = solution1[name] - solution2[name] if isinstance(solution1[name], int) and isinstance(solution2[name], int) else "N/A"
                    print(f"  {name}: {solution1[name]} vs {solution2[name]} (差异: {diff})")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python3 advanced_value_tracking.py <binary_path> [output1] [output2]")
        sys.exit(1)
    
    binary_path = sys.argv[1]
    
    if not os.path.exists(binary_path):
        print(f"❌ 文件不存在: {binary_path}")
        sys.exit(1)
    
    tracker = AdvancedValueTracker(binary_path)
    tracker.setup_symbolic_execution()
    
    if len(sys.argv) >= 4:
                   
        output1 = int(sys.argv[2])
        output2 = int(sys.argv[3])
        tracker.compare_different_outputs(output1, output2)
    elif len(sys.argv) >= 3:
                
        output = int(sys.argv[2])
        tracker.trace_value_computation(output)
    else:
              
        print("🔍 开始值追踪分析...")
        tracker.trace_value_computation(0)

if __name__ == "__main__":
    main()
