                      
"""
增强符号执行分析：比较不同符号化策略对约束捕获的影响
实现程序最终状态关键变量值的比较
"""

from z3 import *

class EnhancedSymbolicExecution:
    """增强的符号执行分析器"""
    
    def __init__(self):
        self.ctx = Context()
        
    def analyze_current_symbolization(self):
        """分析当前符号化策略的局限性"""
        print("=" * 80)
        print("当前符号化策略分析")
        print("=" * 80)
        
        print("1. 当前符号化范围")
        print("-" * 40)
        print("✓ 符号化输入: scanf_0_1_32 (count参数)")
        print("✗ 未符号化: 数组a[]的初始值")
        print("✗ 未符号化: 数组b[]的初始值")
        print("✗ 未符号化: 数组元素的计算过程")
        
        print("\n2. 导致的问题")
        print("-" * 40)
        print("• 只能捕获控制流约束（循环边界、分支条件）")
        print("• 无法捕获数据流约束（变量间的计算关系）")
        print("• 丢失了程序的核心计算逻辑")
        print("• 无法区分不同的计算模式")
        
        print("\n3. 具体表现")
        print("-" * 40)
        print("s000和s121的当前约束:")
        print("  • 都只关注: count ∈ [0,10] 且 count*8的边界检查")
        print("  • 忽略了: a[i] = b[i] + 1 vs a[i] = a[i+1] + b[i]")
        print("  • 结果: 错误地认为两个程序等价")

    def propose_enhanced_symbolization(self):
        """提出增强的符号化策略"""
        print(f"\n" + "=" * 80)
        print("增强符号化策略方案")
        print("=" * 80)
        
        print("方案1: 完全符号化")
        print("-" * 40)
        print("• 符号化所有输入变量")
        print("• 符号化数组的初始状态")
        print("• 跟踪每个数组元素的符号表达式")
        print("• 建立完整的数据依赖图")
        
        print("\n方案2: 部分符号化（推荐）")
        print("-" * 40)
        print("• 符号化输入参数")
        print("• 符号化关键数组区域（受影响的部分）")
        print("• 使用符号常量表示初始值")
        print("• 重点关注计算逻辑差异")
        
        print("\n方案3: 混合符号化")
        print("-" * 40)
        print("• 具体值 + 符号值混合")
        print("• 对关键路径使用符号化")
        print("• 对边界条件使用具体值测试")

    def demonstrate_enhanced_symbolization(self):
        """演示增强符号化的效果"""
        print(f"\n" + "=" * 80)
        print("增强符号化演示：s000 vs s121")
        print("=" * 80)
        
                
        count = BitVec('count', 32, ctx=self.ctx)
        
                         
        print("1. 符号化策略")
        print("-" * 40)
        print("• count: 输入参数（符号化）")
        print("• a_init[i]: 数组a的初始值（符号化）")
        print("• b_init[i]: 数组b的初始值（符号化）")
        
                          
        array_size = 8
        a_init = [BitVec(f'a_init_{i}', 32, ctx=self.ctx) for i in range(array_size)]
        b_init = [BitVec(f'b_init_{i}', 32, ctx=self.ctx) for i in range(array_size)]
        
        print(f"\n2. 建立符号约束")
        print("-" * 40)
        
              
        base_constraints = [
            UGE(count, 0),
            ULE(count, 10)
        ]
        
        print("基础约束:")
        for i, constraint in enumerate(base_constraints):
            print(f"  {i+1}. {constraint}")
        
                     
        print(f"\n3. s000程序符号执行")
        print("-" * 40)
        
        s000_final_a = []
        s000_constraints = base_constraints.copy()
        
        print("循环逻辑: for (i = 0; i < count*8; i++)")
        print("循环体: a[i] = b_init[i] + 1")
        
        for i in range(array_size):
                           
            in_loop = ULT(i, count * 8)
            
                       
            s000_value = If(in_loop, b_init[i] + 1, a_init[i])
            s000_final_a.append(s000_value)
            
            print(f"  a_final[{i}] = If({i} < count*8, b_init[{i}] + 1, a_init[{i}])")
        
                     
        print(f"\n4. s121程序符号执行")
        print("-" * 40)
        
        s121_final_a = []
        s121_constraints = base_constraints.copy()
        
        print("循环逻辑: for (i = 0; i < count*8-1; i++)")
        print("循环体: a[i] = a_init[i+1] + b_init[i]")
        
        for i in range(array_size):
                           
            in_loop = ULT(i, count * 8 - 1)
            
                                 
            if i + 1 < array_size:
                s121_value = If(in_loop, a_init[i+1] + b_init[i], a_init[i])
            else:
                s121_value = a_init[i]             
            
            s121_final_a.append(s121_value)
            
            if i + 1 < array_size:
                print(f"  a_final[{i}] = If({i} < count*8-1, a_init[{i+1}] + b_init[{i}], a_init[{i}])")
            else:
                print(f"  a_final[{i}] = a_init[{i}] (超出范围)")
        
        return s000_final_a, s121_final_a, s000_constraints, s121_constraints

    def compare_final_states(self, s000_final, s121_final, s000_constraints, s121_constraints):
        """比较两个程序的最终状态"""
        print(f"\n" + "=" * 80)
        print("最终状态比较分析")
        print("=" * 80)
        
        print("1. 逐元素等价性检查")
        print("-" * 40)
        
        solver = Solver(ctx=self.ctx)
        solver.add(s000_constraints)
        solver.add(s121_constraints)
        
        differences_found = []
        
        for i in range(len(s000_final)):
            print(f"\n检查 a[{i}] 的等价性:")
            print(f"  s000: {s000_final[i]}")
            print(f"  s121: {s121_final[i]}")
            
                               
            solver.push()
            difference_constraint = Not(s000_final[i] == s121_final[i])
            solver.add(difference_constraint)
            
            result = solver.check()
            
            if result == sat:
                model = solver.model()
                print(f"  结果: 不等价 ❌")
                print(f"  反例:")
                
                          
                count_val = model.eval(BitVec('count', 32, ctx=self.ctx))
                print(f"    count = {count_val}")
                
                             
                s000_val = model.eval(s000_final[i])
                s121_val = model.eval(s121_final[i])
                print(f"    s000.a[{i}] = {s000_val}")
                print(f"    s121.a[{i}] = {s121_val}")
                
                differences_found.append((i, model))
            else:
                print(f"  结果: 等价 ✅")
            
            solver.pop()
        
        print(f"\n2. 整体等价性分析")
        print("-" * 40)
        
        if differences_found:
            print(f"发现 {len(differences_found)} 个数组元素不等价")
            print("结论: 两个程序在计算语义上不等价 ❌")
        else:
            print("所有数组元素都等价")
            print("结论: 两个程序在符号层面等价 ✅")
        
        return differences_found

    def implement_concrete_state_comparison(self):
        """实现具体状态比较方法"""
        print(f"\n" + "=" * 80)
        print("具体状态比较方法")
        print("=" * 80)
        
        print("方法1: 符号表达式比较")
        print("-" * 40)
        print("• 将程序状态表示为符号表达式")
        print("• 使用SMT求解器检查表达式等价性")
        print("• 适用于程序逻辑分析")
        
        print("\n方法2: 测试用例生成")
        print("-" * 40)
        print("• 生成多个测试输入")
        print("• 比较程序在各输入下的输出")
        print("• 适用于快速验证")
        
        print("\n方法3: 状态空间抽象")
        print("-" * 40)
        print("• 定义关键变量的抽象域")
        print("• 比较抽象状态的等价性")
        print("• 适用于大规模程序")
        
                      
        print(f"\n演示：测试用例生成验证")
        print("-" * 30)
        
        def simulate_s000(count, a_init, b_init):
            a = a_init.copy()
            for i in range(min(count * 8, len(a))):
                if i < len(b_init):
                    a[i] = b_init[i] + 1
            return a
        
        def simulate_s121(count, a_init, b_init):
            a = a_init.copy()
            for i in range(min(count * 8 - 1, len(a))):
                if i + 1 < len(a) and i < len(b_init):
                    a[i] = a[i+1] + b_init[i]
            return a
        
                
        test_cases = [
            (0, [0, 1, 2, 3, 4, 5, 6, 7], [10, 11, 12, 13, 14, 15, 16, 17]),
            (1, [0, 1, 2, 3, 4, 5, 6, 7], [10, 11, 12, 13, 14, 15, 16, 17]),
            (2, [0, 1, 2, 3, 4, 5, 6, 7], [10, 11, 12, 13, 14, 15, 16, 17]),
        ]
        
        for count, a_init, b_init in test_cases:
            result_s000 = simulate_s000(count, a_init, b_init)
            result_s121 = simulate_s121(count, a_init, b_init)
            
            print(f"\n测试 count={count}:")
            print(f"  初始a: {a_init}")
            print(f"  初始b: {b_init}")
            print(f"  s000结果: {result_s000}")
            print(f"  s121结果: {result_s121}")
            
            if result_s000 == result_s121:
                print(f"  状态比较: 相同 ✅")
            else:
                differences = [(i, result_s000[i], result_s121[i]) 
                             for i in range(len(result_s000)) 
                             if result_s000[i] != result_s121[i]]
                print(f"  状态比较: 不同 ❌ ({len(differences)}个差异)")

def main():
    analyzer = EnhancedSymbolicExecution()
    
                  
    analyzer.analyze_current_symbolization()
    
            
    analyzer.propose_enhanced_symbolization()
    
             
    s000_final, s121_final, s000_constraints, s121_constraints = analyzer.demonstrate_enhanced_symbolization()
    
            
    differences = analyzer.compare_final_states(s000_final, s121_final, s000_constraints, s121_constraints)
    
              
    analyzer.implement_concrete_state_comparison()

if __name__ == "__main__":
    main() 