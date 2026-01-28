                      
"""
测试约束条件的解读
"""

import z3

def test_constraints():
    print("=== 测试约束条件解读 ===")
    
          
    x = z3.BitVec('x', 32)
    
                   
    constraint1 = z3.BVGE(x, 8)
    print(f"路径1约束: x >= 8")
    
                             
    constraint2 = z3.And(z3.BVLT(x, 8), z3.BVLT(x, 11))
    print(f"路径2约束: x < 8 AND x < 11")
    
                              
    constraint3 = z3.And(z3.BVLT(x, 8), z3.BVGE(x, 11))
    print(f"路径3约束: x < 8 AND x >= 11")
    
                 
    solver1 = z3.Solver()
    solver1.add(constraint1)
    print(f"路径1可满足: {solver1.check()}")
    if solver1.check() == z3.sat:
        print(f"  解: {solver1.model()}")
    
    solver2 = z3.Solver()
    solver2.add(constraint2)
    print(f"路径2可满足: {solver2.check()}")
    if solver2.check() == z3.sat:
        print(f"  解: {solver2.model()}")
    
    solver3 = z3.Solver()
    solver3.add(constraint3)
    print(f"路径3可满足: {solver3.check()}")
    if solver3.check() == z3.sat:
        print(f"  解: {solver3.model()}")
    
              
    print(f"\n=== 约束覆盖分析 ===")
    print(f"路径1: x >= 8 (覆盖: 8,9,10,11,12,...)")
    print(f"路径2: x < 8 (覆盖: 0,1,2,3,4,5,6,7)")
    print(f"路径3: 矛盾约束 (无解)")
    print(f"缺失: x = 8,9,10,11 的情况")

if __name__ == "__main__":
    test_constraints()
