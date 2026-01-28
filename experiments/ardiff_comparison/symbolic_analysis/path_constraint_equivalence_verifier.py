                      
"""
路径约束等价性验证器
使用Z3求解器直接验证两个不同路径约束的等价性
包含正例和反例的验证测试
"""

import sys
import time
from z3 import *

class PathConstraintEquivalenceVerifier:
    """路径约束等价性验证器"""
    
    def __init__(self, timeout=30000):
        """
        初始化验证器
        :param timeout: Z3求解器超时时间（毫秒）
        """
        self.timeout = timeout
        
    def create_test_constraints(self):
        """创建测试用的路径约束"""
        print("创建测试约束文件...")
        
                             
        constraint1_a = """
; 等价测试约束1A
(set-info :status unknown)
(declare-fun x () (_ BitVec 32))
(assert (bvuge x (_ bv5 32)))
(assert (bvule x (_ bv10 32)))
(check-sat)
"""
        
        constraint1_b = """
; 等价测试约束1B
(set-info :status unknown)
(declare-fun x () (_ BitVec 32))
(assert (and (bvuge x (_ bv5 32)) (bvule x (_ bv10 32))))
(check-sat)
"""
        
                               
        constraint2_a = """
; 等价测试约束2A
(set-info :status unknown)
(declare-fun y () (_ BitVec 32))
(assert (or (bvult y (_ bv3 32)) (bvugt y (_ bv7 32))))
(check-sat)
"""
        
        constraint2_b = """
; 等价测试约束2B
(set-info :status unknown)
(declare-fun y () (_ BitVec 32))
(assert (not (and (bvuge y (_ bv3 32)) (bvule y (_ bv7 32)))))
(check-sat)
"""
        
                              
        constraint3_a = """
; 不等价测试约束3A
(set-info :status unknown)
(declare-fun z () (_ BitVec 32))
(assert (bvuge z (_ bv5 32)))
(assert (bvule z (_ bv10 32)))
(check-sat)
"""
        
        constraint3_b = """
; 不等价测试约束3B
(set-info :status unknown)
(declare-fun z () (_ BitVec 32))
(assert (bvuge z (_ bv6 32)))
(assert (bvule z (_ bv10 32)))
(check-sat)
"""
        
                              
        constraint4_a = """
; 不等价测试约束4A
(set-info :status unknown)
(declare-fun w () (_ BitVec 32))
(assert (= w (_ bv0 32)))
(check-sat)
"""
        
        constraint4_b = """
; 不等价测试约束4B
(set-info :status unknown)
(declare-fun w () (_ BitVec 32))
(assert (= w (_ bv1 32)))
(check-sat)
"""
        
                
        test_files = [
            ("test_constraint_1a.smt", constraint1_a),
            ("test_constraint_1b.smt", constraint1_b),
            ("test_constraint_2a.smt", constraint2_a),
            ("test_constraint_2b.smt", constraint2_b),
            ("test_constraint_3a.smt", constraint3_a),
            ("test_constraint_3b.smt", constraint3_b),
            ("test_constraint_4a.smt", constraint4_a),
            ("test_constraint_4b.smt", constraint4_b),
        ]
        
        for filename, content in test_files:
            with open(filename, 'w') as f:
                f.write(content)
                
        print(f"成功创建 {len(test_files)} 个测试约束文件")
        return test_files
    
    def parse_smt_constraint(self, file_path):
        """
        解析SMT约束文件
        :param file_path: SMT文件路径
        :return: Z3约束表达式
        """
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
                     
            ctx = Context()
            
                        
            lines = []
            for line in content.split('\n'):
                line = line.strip()
                                
                if (line.startswith('(') and not line.startswith(';')) or line == ')':
                    lines.append(line)
            
            smt_content = '\n'.join(lines)
            
                    
            formulas = parse_smt2_string(smt_content, ctx=ctx)
            
            if len(formulas) == 0:
                return BoolVal(True, ctx=ctx), ctx
            elif len(formulas) == 1:
                return formulas[0], ctx
            else:
                return And(*formulas), ctx
                
        except Exception as e:
            print(f"解析约束文件 {file_path} 失败: {e}")
            return None, None
    
    def verify_equivalence(self, file1, file2, description=""):
        """
        验证两个约束文件的等价性
        :param file1: 第一个约束文件
        :param file2: 第二个约束文件
        :param description: 测试描述
        :return: 等价性验证结果
        """
        print(f"\n{'='*60}")
        print(f"验证路径约束等价性: {description}")
        print(f"约束文件1: {file1}")
        print(f"约束文件2: {file2}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
                  
        print("步骤1: 解析约束文件...")
        constraint1, ctx1 = self.parse_smt_constraint(file1)
        constraint2, ctx2 = self.parse_smt_constraint(file2)
        
        if constraint1 is None or constraint2 is None:
            print("错误: 约束解析失败")
            return None
        
                   
        ctx = Context()
        
                        
        with open(file1, 'r') as f:
            content1 = f.read()
        with open(file2, 'r') as f:
            content2 = f.read()
        
                    
        def clean_smt_content(content):
            lines = []
            for line in content.split('\n'):
                line = line.strip()
                if (line.startswith('(') and not line.startswith(';')) or line == ')':
                    if not line.startswith('(check-sat)'):
                        lines.append(line)
            return '\n'.join(lines)
        
        clean_content1 = clean_smt_content(content1)
        clean_content2 = clean_smt_content(content2)
        
        try:
            formulas1 = parse_smt2_string(clean_content1, ctx=ctx)
            formulas2 = parse_smt2_string(clean_content2, ctx=ctx)
            
                  
            if len(formulas1) == 0:
                formula1 = BoolVal(True, ctx=ctx)
            elif len(formulas1) == 1:
                formula1 = formulas1[0]
            else:
                formula1 = And(*formulas1)
                
            if len(formulas2) == 0:
                formula2 = BoolVal(True, ctx=ctx)
            elif len(formulas2) == 1:
                formula2 = formulas2[0]
            else:
                formula2 = And(*formulas2)
                
        except Exception as e:
            print(f"错误: 约束解析失败 - {e}")
            return None
        
        parse_time = time.time() - start_time
        print(f"约束解析完成，耗时: {parse_time:.3f} 秒")
        
                
        print(f"\n步骤2: 约束信息分析")
        print(f"约束1: {formula1}")
        print(f"约束2: {formula2}")
        
               
        print(f"\n步骤3: 等价性验证")
        print("使用逻辑等价检查方法: (C1 ∧ ¬C2) ∨ (¬C1 ∧ C2)")
        print("如果此公式不可满足(UNSAT)，则C1 ≡ C2")
        
        verification_start = time.time()
        
               
        solver = Solver(ctx=ctx)
        solver.set("timeout", self.timeout)
        
                   
        equivalence_check = Or(
            And(formula1, Not(formula2)),
            And(Not(formula1), formula2)
        )
        
        solver.add(equivalence_check)
        
        print("正在求解...")
        result = solver.check()
        
        verification_time = time.time() - verification_start
        total_time = time.time() - start_time
        
              
        print(f"\n步骤4: 验证结果")
        print(f"求解状态: {result}")
        print(f"验证耗时: {verification_time:.3f} 秒")
        print(f"总耗时: {total_time:.3f} 秒")
        
        if result == unsat:
            print("🟢 结论: 两个路径约束在逻辑上等价")
            print("   解释: 等价检查公式不可满足，表明不存在使两约束真值不同的赋值")
            return True
        elif result == sat:
            print("🔴 结论: 两个路径约束在逻辑上不等价")
            print("   解释: 找到反例，存在使两约束真值不同的赋值")
            
                  
            model = solver.model()
            print(f"   反例模型:")
            for decl in model.decls():
                print(f"     {decl.name()} = {model[decl]}")
            
                  
            print(f"   反例验证:")
            eval1 = simplify(substitute(formula1, [(decl(), model[decl]) for decl in model.decls()]))
            eval2 = simplify(substitute(formula2, [(decl(), model[decl]) for decl in model.decls()]))
            print(f"     约束1在反例下的值: {eval1}")
            print(f"     约束2在反例下的值: {eval2}")
            
            return False
        else:
            print("🟡 结论: 无法确定等价性（求解超时或未知状态）")
            return None
    
    def run_comprehensive_test(self):
        """运行完整的测试套件"""
        print("路径约束等价性验证器 - 完整测试")
        print("=" * 80)
        
                
        test_files = self.create_test_constraints()
        
                
        test_cases = [
            {
                "file1": "test_constraint_1a.smt",
                "file2": "test_constraint_1b.smt",
                "description": "正例1 - 分离约束vs合并约束",
                "expected": True
            },
            {
                "file1": "test_constraint_2a.smt", 
                "file2": "test_constraint_2b.smt",
                "description": "正例2 - 德摩根定律等价变换",
                "expected": True
            },
            {
                "file1": "test_constraint_3a.smt",
                "file2": "test_constraint_3b.smt", 
                "description": "反例1 - 不同数值范围约束",
                "expected": False
            },
            {
                "file1": "test_constraint_4a.smt",
                "file2": "test_constraint_4b.smt",
                "description": "反例2 - 完全不同的等值约束", 
                "expected": False
            }
        ]
        
              
        results = []
        passed_tests = 0
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n测试用例 {i}/{len(test_cases)}")
            
            result = self.verify_equivalence(
                test_case["file1"],
                test_case["file2"], 
                test_case["description"]
            )
            
                    
            if result == test_case["expected"]:
                test_status = "✅ 通过"
                passed_tests += 1
            elif result is None:
                test_status = "⚠️  无法确定"
            else:
                test_status = "❌ 失败"
                
            results.append({
                "test": test_case["description"],
                "expected": test_case["expected"],
                "actual": result,
                "status": test_status
            })
            
            print(f"测试状态: {test_status}")
        
                
        print(f"\n{'='*80}")
        print(f"测试总结")
        print(f"{'='*80}")
        print(f"总测试数: {len(test_cases)}")
        print(f"通过测试: {passed_tests}")
        print(f"成功率: {passed_tests/len(test_cases)*100:.1f}%")
        
        print(f"\n详细结果:")
        for i, result in enumerate(results, 1):
            print(f"{i}. {result['test']}")
            print(f"   期望: {'等价' if result['expected'] else '不等价'}")
            print(f"   实际: {'等价' if result['actual'] else '不等价' if result['actual'] is False else '无法确定'}")
            print(f"   状态: {result['status']}")
        
        return results

def main():
    """主函数"""
    print("路径约束等价性验证器")
    print("使用Z3求解器验证两个路径约束的逻辑等价性")
    print("-" * 50)
    
    if len(sys.argv) == 1:
                     
        print("未提供参数，运行完整测试套件...")
        verifier = PathConstraintEquivalenceVerifier()
        verifier.run_comprehensive_test()
        
    elif len(sys.argv) == 3:
                        
        file1, file2 = sys.argv[1], sys.argv[2]
        print(f"验证指定文件: {file1} vs {file2}")
        
        verifier = PathConstraintEquivalenceVerifier()
        result = verifier.verify_equivalence(file1, file2, "用户指定文件")
        
        print(f"\n最终结论:")
        if result is True:
            print("✅ 两个路径约束在逻辑上等价")
        elif result is False:
            print("❌ 两个路径约束在逻辑上不等价")
        else:
            print("⚠️  无法确定等价性")
            
    else:
        print("用法:")
        print("  python path_constraint_equivalence_verifier.py                    # 运行完整测试")
        print("  python path_constraint_equivalence_verifier.py <file1> <file2>   # 验证两个文件")
        sys.exit(1)

if __name__ == "__main__":
    main() 