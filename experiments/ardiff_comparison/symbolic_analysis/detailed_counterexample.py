                      
"""
详细分析边界情况反例
"""

import z3

def analyze_boundary_case():
    """分析边界情况 a==b"""
    print("🔍 详细分析边界情况 a==b 的反例")
    print("=" * 60)
    
             
    solver = z3.Solver()
    
          
    a = z3.BitVec('a', 32)
    b = z3.BitVec('b', 32)
    
               
    newV_result = z3.If(b < a, a, b)                                       
    oldV_result = z3.If(b > a, b, a)                                       
    
    print("📋 程序逻辑:")
    print("newV: if (b < a) return a; else return b;")
    print("oldV: if (b > a) return b; else return a;")
    print()
    
                   
    print("🔍 边界情况分析 (a == b):")
    solver.push()
    solver.add(a == b)
    
                     
    newV_result_eq = z3.If(b < a, a, b)                    
    oldV_result_eq = z3.If(b > a, b, a)                    
    
              
    result_eq = z3.ForAll([a, b], z3.Implies(a == b, newV_result_eq == oldV_result_eq))
    solver.add(z3.Not(result_eq))
    result_boundary = solver.check()
    
    if result_boundary == z3.sat:
        print("❌ 边界情况不等价！找到反例:")
        model = solver.model()
        a_val = model[a].as_long()
        b_val = model[b].as_long()
        
        print(f"  反例: a={a_val}, b={b_val}")
        print(f"  a == b: {a_val == b_val}")
        
                       
        newV_val = a_val if b_val < a_val else b_val
        oldV_val = b_val if b_val > a_val else a_val
        
        print(f"  newV结果: {newV_val}")
        print(f"  oldV结果: {oldV_val}")
        print(f"  结果相同: {newV_val == oldV_val}")
    else:
        print("✅ 边界情况等价: 当a==b时，两个程序返回相同结果")
    
    solver.pop()
    
               
    print(f"\n🔍 路径约束差异分析:")
    
            
    newV_path1_cond = a >= b                           
    newV_path2_cond = a < b                           
    oldV_path1_cond = a <= b                           
    oldV_path2_cond = a > b                           
    
    print("路径条件:")
    print("  newV路径1: a >= b (返回b)")
    print("  newV路径2: a < b (返回a)")
    print("  oldV路径1: a <= b (返回a)")
    print("  oldV路径2: a > b (返回b)")
    
                       
    print(f"\n🔍 边界情况 a==b 的路径分配:")
    solver.push()
    solver.add(a == b)
    
                 
    solver.add(newV_path1_cond)          
    if solver.check() == z3.sat:
        print("  newV: a==b 时走路径1 (a>=b为真，返回b)")
    solver.pop()
    
    solver.push()
    solver.add(a == b)
    solver.add(newV_path2_cond)         
    if solver.check() == z3.sat:
        print("  newV: a==b 时走路径2 (a<b为真，返回a)")
    solver.pop()
    
    solver.push()
    solver.add(a == b)
    solver.add(oldV_path1_cond)          
    if solver.check() == z3.sat:
        print("  oldV: a==b 时走路径1 (a<=b为真，返回a)")
    solver.pop()
    
    solver.push()
    solver.add(a == b)
    solver.add(oldV_path2_cond)         
    if solver.check() == z3.sat:
        print("  oldV: a==b 时走路径2 (a>b为真，返回b)")
    solver.pop()
    
               
    print(f"\n🔍 约束差异分析:")
    
                           
    solver.push()
    solver.add(z3.And(a >= b, z3.Not(a > b)))
    if solver.check() == z3.sat:
        model = solver.model()
        a_val = model[a].as_long()
        b_val = model[b].as_long()
        print(f"  a >= b 但 a > b 为假的情况: a={a_val}, b={b_val}")
        print(f"  这种情况: a==b={a_val == b_val}")
    solver.pop()
    
                           
    solver.push()
    solver.add(z3.And(a < b, z3.Not(a <= b)))
    if solver.check() == z3.sat:
        model = solver.model()
        a_val = model[a].as_long()
        b_val = model[b].as_long()
        print(f"  a < b 但 a <= b 为假的情况: a={a_val}, b={b_val}")
        print(f"  这种情况: a==b={a_val == b_val}")
    else:
        print("  a < b 但 a <= b 为假的情况: 不存在")
    
    print(f"\n📋 关键发现:")
    print("1. 两个程序在逻辑上完全等价，都实现max(a,b)函数")
    print("2. 但是路径约束的表示方式不同:")
    print("   - newV使用 a>=b 和 a<b")
    print("   - oldV使用 a<=b 和 a>b")
    print("3. 边界情况 a==b 的处理:")
    print("   - newV: a>=b为真，走路径1，返回b")
    print("   - oldV: a<=b为真，走路径1，返回a")
    print("   - 结果相同: 都返回a(或b，因为a==b)")
    print("4. 约束匹配失败的原因:")
    print("   - a>=b 和 a>b 在a==b时行为不同")
    print("   - a<b 和 a<=b 在a==b时行为不同")
    print("   - 需要更智能的约束规范化算法")

if __name__ == "__main__":
    analyze_boundary_case()
