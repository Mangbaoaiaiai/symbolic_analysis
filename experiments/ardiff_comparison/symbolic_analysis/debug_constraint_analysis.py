                      
"""
调试约束等价性分析
专门分析Airy MAX Eq程序的约束为什么不等价
"""

import z3
import re
import os

def load_constraints(file_path):
    """加载约束文件"""
    with open(file_path, 'r') as f:
        content = f.read()
    
            
    variables = {}
    var_pattern = r'\(declare-fun\s+(\w+)\s+\(\)\s+\(_\s+BitVec\s+(\d+)\)\)'
    for match in re.finditer(var_pattern, content):
        var_name, bit_width = match.groups()
        variables[var_name] = int(bit_width)
    
          
    constraints = []
    constraint_pattern = r'\(assert\s+(.*?)\)(?=\s*(?:\(assert|\(check-sat|$))'
    for match in re.finditer(constraint_pattern, content, re.DOTALL):
        constraint = match.group(1).strip()
        constraints.append(constraint)
    
    return variables, constraints

def analyze_constraint_differences():
    """分析约束差异"""
    print("🔍 详细分析Airy MAX Eq程序的约束差异")
    print("=" * 60)
    
          
    base_dir = "/root/ardiff/symbolic_analysis/benchmarks/Airy/MAX/Eq"
    newV_path1 = os.path.join(base_dir, "symbolic_newV_path_1.txt")
    newV_path2 = os.path.join(base_dir, "symbolic_newV_path_2.txt")
    oldV_path1 = os.path.join(base_dir, "symbolic_oldV_path_1.txt")
    oldV_path2 = os.path.join(base_dir, "symbolic_oldV_path_2.txt")
    
            
    print("📂 加载约束文件...")
    newV_vars1, newV_cons1 = load_constraints(newV_path1)
    newV_vars2, newV_cons2 = load_constraints(newV_path2)
    oldV_vars1, oldV_cons1 = load_constraints(oldV_path1)
    oldV_vars2, oldV_cons2 = load_constraints(oldV_path2)
    
    print(f"newV路径1: {len(newV_vars1)} 变量, {len(newV_cons1)} 约束")
    print(f"newV路径2: {len(newV_vars2)} 变量, {len(newV_cons2)} 约束")
    print(f"oldV路径1: {len(oldV_vars1)} 变量, {len(oldV_cons1)} 约束")
    print(f"oldV路径2: {len(oldV_vars2)} 变量, {len(oldV_cons2)} 约束")
    
    print(f"\n🔍 约束内容分析:")
    print("newV路径1约束:", newV_cons1)
    print("newV路径2约束:", newV_cons2)
    print("oldV路径1约束:", oldV_cons1)
    print("oldV路径2约束:", oldV_cons2)
    
                   
    print(f"\n🧮 Z3求解器详细分析:")
    
          
    a = z3.BitVec('a', 32)
    b = z3.BitVec('b', 32)
    
               
    newV_result = z3.If(b < a, a, b)
    oldV_result = z3.If(b > a, b, a)
    
           
    solver = z3.Solver()
    solver.add(newV_result != oldV_result)
    
    result = solver.check()
    
    if result == z3.sat:
        print("❌ 程序不等价！找到反例:")
        model = solver.model()
        a_val = model[a].as_long()
        b_val = model[b].as_long()
        
        print(f"  反例: a={a_val}, b={b_val}")
        
                       
        newV_val = a_val if b_val < a_val else b_val
        oldV_val = b_val if b_val > a_val else a_val
        
        print(f"  newV结果: {newV_val}")
        print(f"  oldV结果: {oldV_val}")
        print(f"  差异: {abs(newV_val - oldV_val)}")
        
                 
        print(f"\n�� 反例条件分析:")
        print(f"  b < a: {b_val < a_val}")
        print(f"  b > a: {b_val > a_val}")
        print(f"  a == b: {a_val == b_val}")
        
    elif result == z3.unsat:
        print("✅ 程序等价！")
    else:
        print("⚠️  无法确定")
    
                
    print(f"\n🔍 路径约束等价性分析:")
    
            
    newV_path1_cond = a >= b               
    newV_path2_cond = a < b                
    oldV_path1_cond = a <= b               
    oldV_path2_cond = a > b                
    
                           
    print("\n1. 检查 newV路径1 vs oldV路径2:")
    print("   newV路径1: a >= b (返回b)")
    print("   oldV路径2: a > b (返回b)")
    
    solver2 = z3.Solver()
              
    solver2.add(z3.Not(z3.ForAll([a, b], newV_path1_cond == oldV_path2_cond)))
    result2 = solver2.check()
    
    if result2 == z3.unsat:
        print("   ✅ 条件等价: a >= b ≡ a > b")
    else:
        print("   ❌ 条件不等价: a >= b ≠ a > b")
              
        solver3 = z3.Solver()
        solver3.add(z3.And(newV_path1_cond, z3.Not(oldV_path2_cond)))
        if solver3.check() == z3.sat:
            model = solver3.model()
            a_val = model[a].as_long()
            b_val = model[b].as_long()
            print(f"   差异: a={a_val}, b={b_val} 时 a>=b为真但 a>b为假")
    
                           
    print("\n2. 检查 newV路径2 vs oldV路径1:")
    print("   newV路径2: a < b (返回a)")
    print("   oldV路径1: a <= b (返回a)")
    
    solver4 = z3.Solver()
    solver4.add(z3.Not(z3.ForAll([a, b], newV_path2_cond == oldV_path1_cond)))
    result4 = solver4.check()
    
    if result4 == z3.unsat:
        print("   ✅ 条件等价: a < b ≡ a <= b")
    else:
        print("   ❌ 条件不等价: a < b ≠ a <= b")
              
        solver5 = z3.Solver()
        solver5.add(z3.And(newV_path2_cond, z3.Not(oldV_path1_cond)))
        if solver5.check() == z3.sat:
            model = solver5.model()
            a_val = model[a].as_long()
            b_val = model[b].as_long()
            print(f"   差异: a={a_val}, b={b_val} 时 a<b为真但 a<=b为假")
    
    print(f"\n📋 结论:")
    print("这两个程序在逻辑上应该是等价的，都实现max(a,b)函数")
    print("但是路径约束的表示方式不同，导致约束匹配失败")
    print("问题在于边界情况 a==b 的处理方式不同")

if __name__ == "__main__":
    analyze_constraint_differences()
