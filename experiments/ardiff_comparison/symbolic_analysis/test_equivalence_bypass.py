                      
"""
简化的路径等价性测试工具
绕过智能分组，直接比较两个指定的路径文件
"""

import sys
from semantic_equivalence_analyzer import ConstraintEquivalenceChecker

def test_direct_equivalence(file1, file2):
    """直接比较两个路径文件的等价性"""
    checker = ConstraintEquivalenceChecker()
    
    print(f"直接比较: {file1} vs {file2}")
    
    try:
              
        vars1, constraints1 = checker.extract_constraint_formula(file1)
        vars2, constraints2 = checker.extract_constraint_formula(file2)
        
        print(f"文件1: {len(constraints1)} 个约束, {len(vars1)} 个变量")
        print(f"文件2: {len(constraints2)} 个约束, {len(vars2)} 个变量")
        
                
        var_mapping = checker.create_variable_mapping(vars1, vars2)
        print(f"变量映射: {var_mapping}")
        
               
        result, extra_info = checker.check_constraint_equivalence(
            constraints1, constraints2, vars1, vars2, var_mapping
        )
        
        print(f"\n等价性结果: {result}")
        if result == "not_equivalent" and "model" in extra_info:
            print(f"反例模型: {extra_info['model']}")
        elif result == "error":
            print(f"错误信息: {extra_info.get('error', '未知错误')}")
        
        print(f"求解时间: {extra_info.get('solve_time', 0):.3f} 秒")
        
    except Exception as e:
        print(f"分析错误: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python test_equivalence_bypass.py <file1> <file2>")
        sys.exit(1)
    
    test_direct_equivalence(sys.argv[1], sys.argv[2]) 