                      
"""
分析Airy MAX Eq程序的等价性
通过求解器验证两个程序的路径约束是否等价
"""

import z3
import os

def load_smt_constraints(file_path):
    """加载SMT约束文件"""
    with open(file_path, 'r') as f:
        content = f.read()
    
                  
    lines = content.split('\n')
    constraints = []
    for line in lines:
        line = line.strip()
        if line.startswith('(assert') and not line.startswith(';'):
            constraints.append(line)
    
    return constraints

def analyze_program_equivalence():
    """分析两个程序的等价性"""
    
    print("🔍 分析Airy MAX Eq程序的等价性")
    print("=" * 50)
    
          
    base_dir = "/root/ardiff/symbolic_analysis/benchmarks/Airy/MAX/Eq"
    newV_path1 = os.path.join(base_dir, "symbolic_newV_path_1.txt")
    newV_path2 = os.path.join(base_dir, "symbolic_newV_path_2.txt")
    oldV_path1 = os.path.join(base_dir, "symbolic_oldV_path_1.txt")
    oldV_path2 = os.path.join(base_dir, "symbolic_oldV_path_2.txt")
    
    print("📋 程序逻辑分析:")
    print("newV: if (b < a) return a; else return b;")
    print("oldV: if (b > a) return b; else return a;")
    print()
    
          
    print("📂 加载路径约束...")
    newV_constraints = []
    oldV_constraints = []
    
    for path_file in [newV_path1, newV_path2]:
        if os.path.exists(path_file):
            constraints = load_smt_constraints(path_file)
            newV_constraints.extend(constraints)
            print(f"  newV: 加载了 {len(constraints)} 个约束")
    
    for path_file in [oldV_path1, oldV_path2]:
        if os.path.exists(path_file):
            constraints = load_smt_constraints(path_file)
            oldV_constraints.extend(constraints)
            print(f"  oldV: 加载了 {len(constraints)} 个约束")
    
    print(f"\n📊 约束统计:")
    print(f"  newV总约束数: {len(newV_constraints)}")
    print(f"  oldV总约束数: {len(oldV_constraints)}")
    
            
    print(f"\n🔍 约束内容分析:")
    print("newV约束:")
    for i, constraint in enumerate(newV_constraints, 1):
        print(f"  {i}. {constraint}")
    
    print("\noldV约束:")
    for i, constraint in enumerate(oldV_constraints, 1):
        print(f"  {i}. {constraint}")
    
                    
    print(f"\n🧮 使用Z3求解器验证等价性...")
    
             
    solver = z3.Solver()
    
          
    a = z3.BitVec('a', 32)
    b = z3.BitVec('b', 32)
    
               
                                               
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
        a_val = model[a].as_long()
        b_val = model[b].as_long()
        
        print(f"   反例: a={a_val}, b={b_val}")
        
                       
        newV_val = a_val if b_val < a_val else b_val
        oldV_val = b_val if b_val > a_val else a_val
        
        print(f"   newV结果: {newV_val}")
        print(f"   oldV结果: {oldV_val}")
    else:
        print("⚠️  结果: 无法确定（求解器超时或出错）")
    
    solver.pop()
    
               
    print(f"\n🔍 路径约束分析:")
    print("newV路径1约束: bvsge mem_7fffffffffeff20_1_32 mem_7fffffffffeff1c_2_32")
    print("  (即: a >= b, 对应 b < a 为假，返回 b)")
    print("newV路径2约束: bvslt mem_7fffffffffeff20_1_32 mem_7fffffffffeff1c_2_32")
    print("  (即: a < b, 对应 b < a 为真，返回 a)")
    print()
    print("oldV路径1约束: bvsle mem_7fffffffffeff20_1_32 mem_7fffffffffeff1c_2_32")
    print("  (即: a <= b, 对应 b > a 为假，返回 a)")
    print("oldV路径2约束: bvsgt mem_7fffffffffeff20_1_32 mem_7fffffffffeff1c_2_32")
    print("  (即: a > b, 对应 b > a 为真，返回 b)")
    
                
    print(f"\n🔍 路径约束等价性验证:")
    
            
                           
    newV_path1_cond = a >= b
    newV_path1_result = b
    
                            
    newV_path2_cond = a < b
    newV_path2_result = a
    
                           
    oldV_path1_cond = a <= b
    oldV_path1_result = a
    
                          
    oldV_path2_cond = a > b
    oldV_path2_result = b
    
                
    print("验证路径覆盖...")
    
                           
    solver.push()
    path1_eq = z3.ForAll([a, b], 
        z3.Implies(newV_path1_cond, 
                  z3.And(oldV_path2_cond, newV_path1_result == oldV_path2_result)))
    solver.add(z3.Not(path1_eq))
    result1 = solver.check()
    solver.pop()
    
    if result1 == z3.unsat:
        print("✅ newV路径1 ≈ oldV路径2 (a>=b时都返回b)")
    else:
        print("❌ newV路径1 ≠ oldV路径2")
    
                           
    solver.push()
    path2_eq = z3.ForAll([a, b], 
        z3.Implies(newV_path2_cond, 
                  z3.And(oldV_path1_cond, newV_path2_result == oldV_path1_result)))
    solver.add(z3.Not(path2_eq))
    result2 = solver.check()
    solver.pop()
    
    if result2 == z3.unsat:
        print("✅ newV路径2 ≈ oldV路径1 (a<b时都返回a)")
    else:
        print("❌ newV路径2 ≠ oldV路径1")
    
    print(f"\n📋 结论:")
    print("这两个程序在逻辑上是等价的，都实现了max(a,b)函数")
    print("但是符号执行生成的路径约束在形式上不完全匹配")
    print("等价性分析失败的原因可能是:")
    print("1. 路径约束的表示方式不同 (bvsge vs bvsgt)")
    print("2. 路径顺序不同 (newV先检查b<a, oldV先检查b>a)")
    print("3. 约束匹配算法需要更智能的等价性判断")

if __name__ == "__main__":
    analyze_program_equivalence()
