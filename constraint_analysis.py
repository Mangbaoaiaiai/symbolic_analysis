#!/usr/bin/env python3
"""
路径约束深度分析
详细分析s121和s000约束为什么等价
"""

from z3 import *

def analyze_constraint_semantics():
    """分析约束的语义含义"""
    print("=" * 80)
    print("路径约束深度分析: s121_O1_path_1.txt vs s000_O1_path_1.txt")
    print("=" * 80)
    
    # 创建变量
    scanf_0_1_32 = BitVec('scanf_0_1_32', 32)
    
    # 基础约束（两个文件都有）
    base_constraint1 = UGE(scanf_0_1_32, 0)
    base_constraint2 = ULE(scanf_0_1_32, 10)
    
    print("基础约束（两个文件共有）:")
    print(f"  1. scanf_0_1_32 >= 0")
    print(f"  2. scanf_0_1_32 <= 10")
    print(f"  即: scanf_0_1_32 ∈ [0, 10]")
    
    # 关键表达式
    x38 = ZeroExt(32, scanf_0_1_32)  # 64位扩展
    x41 = x38 << 3                   # 左移3位（乘以8）
    x42 = Extract(31, 0, x41)        # 取低32位
    
    print(f"\n关键表达式分析:")
    print(f"  x38 = ZeroExt(32, scanf_0_1_32)  // 扩展为64位")
    print(f"  x41 = x38 << 3                   // 左移3位，相当于乘以8")
    print(f"  x42 = Extract(31, 0, x41)        // 取低32位")
    print(f"  因此: x42 = scanf_0_1_32 * 8 (在32位范围内)")
    
    # 差异约束
    s121_constraint = 1 >= x42  # s121的第三个约束
    s000_constraint = 0 >= x42  # s000的第三个约束
    
    print(f"\n差异约束:")
    print(f"  s121: 1 >= x42  即  x42 <= 1")
    print(f"  s000: 0 >= x42  即  x42 <= 0")
    
    # 分析可能的x42值
    print(f"\n在输入范围[0,10]内，x42的可能值:")
    possible_values = []
    for i in range(11):
        val = i * 8
        possible_values.append((i, val))
        print(f"  scanf_0_1_32 = {i:2d} → x42 = {val:2d}")
    
    print(f"\n约束满足性分析:")
    
    # 分析s000约束 (0 >= x42)
    print(f"  s000约束 (x42 <= 0):")
    s000_satisfying = []
    for input_val, x42_val in possible_values:
        if x42_val <= 0:
            s000_satisfying.append(input_val)
            print(f"    ✓ scanf_0_1_32 = {input_val} (x42 = {x42_val}) 满足 x42 <= 0")
        else:
            print(f"    ✗ scanf_0_1_32 = {input_val} (x42 = {x42_val}) 不满足 x42 <= 0")
    
    # 分析s121约束 (1 >= x42)
    print(f"  s121约束 (x42 <= 1):")
    s121_satisfying = []
    for input_val, x42_val in possible_values:
        if x42_val <= 1:
            s121_satisfying.append(input_val)
            print(f"    ✓ scanf_0_1_32 = {input_val} (x42 = {x42_val}) 满足 x42 <= 1")
        else:
            print(f"    ✗ scanf_0_1_32 = {input_val} (x42 = {x42_val}) 不满足 x42 <= 1")
    
    print(f"\n结论:")
    print(f"  s000约束的满足解集: {s000_satisfying}")
    print(f"  s121约束的满足解集: {s121_satisfying}")
    
    if s000_satisfying == s121_satisfying:
        print(f"  ✅ 两个约束的解集相同，因此逻辑等价！")
    else:
        print(f"  ❌ 两个约束的解集不同，不等价")
    
    # 使用Z3验证
    print(f"\n使用Z3验证分析结果:")
    
    solver = Solver()
    
    # 验证s000约束的解
    print(f"  验证s000约束解集:")
    for val in range(11):
        solver.push()
        solver.add(base_constraint1, base_constraint2, s000_constraint)
        solver.add(scanf_0_1_32 == val)
        
        result = solver.check()
        if result == sat:
            print(f"    scanf_0_1_32 = {val}: SAT")
        else:
            print(f"    scanf_0_1_32 = {val}: UNSAT")
        solver.pop()
    
    # 验证s121约束的解
    print(f"  验证s121约束解集:")
    for val in range(11):
        solver.push()
        solver.add(base_constraint1, base_constraint2, s121_constraint)
        solver.add(scanf_0_1_32 == val)
        
        result = solver.check()
        if result == sat:
            print(f"    scanf_0_1_32 = {val}: SAT")
        else:
            print(f"    scanf_0_1_32 = {val}: UNSAT")
        solver.pop()

def verify_equivalence_step_by_step():
    """逐步验证等价性"""
    print(f"\n" + "=" * 80)
    print("逐步等价性验证")
    print("=" * 80)
    
    # 创建变量
    scanf_0_1_32 = BitVec('scanf_0_1_32', 32)
    
    # 构建完整约束
    base_constraints = And(
        UGE(scanf_0_1_32, 0),
        ULE(scanf_0_1_32, 10)
    )
    
    x38 = ZeroExt(32, scanf_0_1_32)
    x41 = x38 << 3
    x42 = Extract(31, 0, x41)
    
    s000_full = And(base_constraints, 0 >= x42)
    s121_full = And(base_constraints, 1 >= x42)
    
    print("步骤1: 检查s000约束的可满足性")
    solver = Solver()
    solver.add(s000_full)
    result = solver.check()
    print(f"  结果: {result}")
    if result == sat:
        model = solver.model()
        print(f"  模型: {model}")
    
    print("步骤2: 检查s121约束的可满足性")
    solver = Solver()
    solver.add(s121_full)
    result = solver.check()
    print(f"  结果: {result}")
    if result == sat:
        model = solver.model()
        print(f"  模型: {model}")
    
    print("步骤3: 检查 s000 → s121 (s000蕴含s121)")
    solver = Solver()
    solver.add(And(s000_full, Not(s121_full)))
    result = solver.check()
    print(f"  s000 ∧ ¬s121 可满足性: {result}")
    if result == unsat:
        print("  ✓ s000 → s121 成立")
    else:
        print("  ✗ s000 → s121 不成立")
        
    print("步骤4: 检查 s121 → s000 (s121蕴含s000)")
    solver = Solver()
    solver.add(And(s121_full, Not(s000_full)))
    result = solver.check()
    print(f"  s121 ∧ ¬s000 可满足性: {result}")
    if result == unsat:
        print("  ✓ s121 → s000 成立")
    else:
        print("  ✗ s121 → s000 不成立")
        
    print("步骤5: 双向蕴含检查")
    solver = Solver()
    equivalence_check = Or(
        And(s000_full, Not(s121_full)),
        And(Not(s000_full), s121_full)
    )
    solver.add(equivalence_check)
    result = solver.check()
    print(f"  等价性检查公式可满足性: {result}")
    if result == unsat:
        print("  ✅ s000 ≡ s121 (完全等价)")
    else:
        print("  ❌ s000 ≢ s121 (不等价)")

if __name__ == "__main__":
    analyze_constraint_semantics()
    verify_equivalence_step_by_step() 