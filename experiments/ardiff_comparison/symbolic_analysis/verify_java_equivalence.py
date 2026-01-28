                      
"""
验证两个Java程序的等价性
"""

import z3

def verify_java_equivalence():
    """验证newV和oldV程序的等价性"""
    print("🔍 验证Java程序等价性")
    print("=" * 50)
    
             
    solver = z3.Solver()
    
                                    
    a = z3.Real('a')
    b = z3.Real('b')
    
    print("📋 程序逻辑:")
    print("newV: if (b < a) return a; else return b;")
    print("oldV: if (b > a) return b; else return a;")
    print()
    
               
    newV_result = z3.If(b < a, a, b)
    oldV_result = z3.If(b > a, b, a)
    
                              
    equivalence = z3.ForAll([a, b], newV_result == oldV_result)
    
    print("🔍 验证公式: ∀a,b. newV(a,b) = oldV(a,b)")
    
           
    solver.push()
    solver.add(z3.Not(equivalence))
    
    result = solver.check()
    
    if result == z3.unsat:
        print("✅ 结果: 程序等价！")
        print("   对于所有可能的输入值，两个程序产生相同的结果")
    elif result == z3.sat:
        print("❌ 结果: 程序不等价！")
        print("   存在输入值使得两个程序产生不同的结果")
        
              
        model = solver.model()
        a_val = float(model[a].as_fraction())
        b_val = float(model[b].as_fraction())
        
        print(f"   反例: a={a_val}, b={b_val}")
        
                       
        newV_val = a_val if b_val < a_val else b_val
        oldV_val = b_val if b_val > a_val else a_val
        
        print(f"   newV结果: {newV_val}")
        print(f"   oldV结果: {oldV_val}")
    else:
        print("⚠️  结果: 无法确定（求解器超时或出错）")
    
    solver.pop()
    
                
    print(f"\n🔍 逻辑等价性分析:")
    print("newV逻辑: if (b < a) return a; else return b;")
    print("oldV逻辑: if (b > a) return b; else return a;")
    print()
    print("等价性分析:")
    print("1. 当 b < a 时:")
    print("   - newV: 条件为真，返回 a")
    print("   - oldV: 条件为假，返回 a")
    print("   - 结果相同: 都返回 a")
    print()
    print("2. 当 b > a 时:")
    print("   - newV: 条件为假，返回 b")
    print("   - oldV: 条件为真，返回 b")
    print("   - 结果相同: 都返回 b")
    print()
    print("3. 当 b = a 时:")
    print("   - newV: 条件为假，返回 b (即 a)")
    print("   - oldV: 条件为假，返回 a")
    print("   - 结果相同: 都返回 a (因为 a = b)")
    print()
    print("📋 结论: 两个程序在逻辑上完全等价，都实现了 max(a,b) 函数")

if __name__ == "__main__":
    verify_java_equivalence()
