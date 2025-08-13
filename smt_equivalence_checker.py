#!/usr/bin/env python3
"""
SMT约束公式等价性验证工具
直接验证两个SMT-LIB格式的约束公式是否逻辑等价
不进行任何简化或预处理
"""

import sys
import time
from z3 import *

class SMTEquivalenceChecker:
    """SMT约束公式等价性检查器"""
    
    def __init__(self, timeout=30000):
        self.timeout = timeout
        
    def parse_smt_file(self, file_path):
        """解析SMT-LIB文件，返回完整的公式"""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # 过滤掉注释和非SMT-LIB格式的内容
            lines = []
            for line in content.split('\n'):
                line = line.strip()
                # 只保留SMT-LIB格式的行
                if (line.startswith('(') and 
                    (line.startswith('(set-') or 
                     line.startswith('(declare-') or 
                     line.startswith('(assert') or 
                     line.startswith('(check-') or
                     line.startswith('(let ') or
                     line.startswith('(bv') or
                     line.startswith('(_ ') or
                     line.startswith(')'))):
                    lines.append(line)
                elif line == '':
                    continue
                else:
                    # 对于多行表达式，继续添加直到遇到完整的括号匹配
                    if lines and not lines[-1].endswith(')'):
                        lines.append(line)
            
            # 重新组合内容
            filtered_content = '\n'.join(lines)
            
            # 创建Z3上下文
            ctx = Context()
            
            # 使用Z3的parse_smt2_string解析文件
            formulas = parse_smt2_string(filtered_content, ctx=ctx)
            
            # 合并所有公式为一个
            if len(formulas) == 0:
                return BoolVal(True, ctx=ctx)
            elif len(formulas) == 1:
                return formulas[0]
            else:
                return And(*formulas)
                
        except Exception as e:
            print(f"解析文件 {file_path} 失败: {e}")
            return None
    
    def check_equivalence(self, file1, file2):
        """检查两个SMT文件的约束是否等价"""
        print(f"验证SMT约束等价性:")
        print(f"  文件1: {file1}")
        print(f"  文件2: {file2}")
        print("-" * 50)
        
        # 解析两个文件
        start_time = time.time()
        
        # 使用相同的上下文
        ctx = Context()
        
        print("解析文件1...")
        formula1 = self.parse_smt_file_with_context(file1, ctx)
        if formula1 is None:
            return False
            
        print("解析文件2...")
        formula2 = self.parse_smt_file_with_context(file2, ctx)
        if formula2 is None:
            return False
            
        parse_time = time.time() - start_time
        print(f"文件解析耗时: {parse_time:.3f} 秒")
        
        # 检查等价性
        print("\n开始等价性验证...")
        verification_start = time.time()
        
        # 创建求解器
        solver = Solver(ctx=ctx)
        solver.set("timeout", self.timeout)
        
        # 构建等价性检查公式: (F1 ∧ ¬F2) ∨ (¬F1 ∧ F2)
        # 如果这个公式不可满足，则F1 ≡ F2
        equivalence_check = Or(
            And(formula1, Not(formula2)),
            And(Not(formula1), formula2)
        )
        
        solver.add(equivalence_check)
        
        print("正在求解...")
        result = solver.check()
        
        verification_time = time.time() - verification_start
        total_time = time.time() - start_time
        
        print(f"\n验证结果:")
        print(f"  求解结果: {result}")
        print(f"  验证耗时: {verification_time:.3f} 秒")
        print(f"  总耗时: {total_time:.3f} 秒")
        
        if result == unsat:
            print("  ✓ 约束公式等价")
            return True
        elif result == sat:
            print("  ✗ 约束公式不等价")
            model = solver.model()
            print(f"  反例模型:")
            for decl in model.decls():
                print(f"    {decl.name()} = {model[decl]}")
            return False
        else:
            print("  ? 无法确定等价性（超时或未知）")
            return None
    
    def parse_smt_file_with_context(self, file_path, ctx):
        """使用指定上下文解析SMT-LIB文件"""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # 过滤掉注释和非SMT-LIB格式的内容
            lines = []
            for line in content.split('\n'):
                line = line.strip()
                # 只保留SMT-LIB格式的行
                if (line.startswith('(') and 
                    (line.startswith('(set-') or 
                     line.startswith('(declare-') or 
                     line.startswith('(assert') or 
                     line.startswith('(check-') or
                     line.startswith('(let ') or
                     line.startswith('(bv') or
                     line.startswith('(_ ') or
                     line.startswith(')'))):
                    lines.append(line)
                elif line == '':
                    continue
                else:
                    # 对于多行表达式，继续添加直到遇到完整的括号匹配
                    if lines and not lines[-1].endswith(')'):
                        lines.append(line)
            
            # 重新组合内容
            filtered_content = '\n'.join(lines)
            
            # 使用Z3的parse_smt2_string解析文件
            formulas = parse_smt2_string(filtered_content, ctx=ctx)
            
            # 合并所有公式为一个
            if len(formulas) == 0:
                return BoolVal(True, ctx=ctx)
            elif len(formulas) == 1:
                return formulas[0]
            else:
                return And(*formulas)
                
        except Exception as e:
            print(f"解析文件 {file_path} 失败: {e}")
            return None
    
    def analyze_constraints(self, file_path):
        """分析单个文件的约束结构"""
        print(f"\n分析文件: {file_path}")
        print("-" * 30)
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # 统计信息
            lines = content.split('\n')
            total_lines = len(lines)
            comment_lines = sum(1 for line in lines if line.strip().startswith(';'))
            declare_lines = sum(1 for line in lines if 'declare-fun' in line)
            assert_lines = sum(1 for line in lines if line.strip().startswith('(assert'))
            
            print(f"总行数: {total_lines}")
            print(f"注释行: {comment_lines}")
            print(f"变量声明: {declare_lines}")
            print(f"约束断言: {assert_lines}")
            
            # 提取变量声明
            variables = []
            for line in lines:
                if 'declare-fun' in line:
                    # 简单的变量名提取
                    import re
                    match = re.search(r'declare-fun\s+(\w+)', line)
                    if match:
                        variables.append(match.group(1))
            
            print(f"变量列表: {variables}")
            
            # 显示约束内容
            print(f"\n约束内容:")
            for i, line in enumerate(lines):
                if line.strip().startswith('(assert'):
                    print(f"  约束{i+1}: {line.strip()}")
            
            # 显示注释信息
            print(f"\n注释信息:")
            for line in lines:
                if line.strip().startswith(';'):
                    print(f"  {line.strip()}")
                    
        except Exception as e:
            print(f"分析失败: {e}")

def main():
    """主函数"""
    if len(sys.argv) < 3:
        print("用法: python smt_equivalence_checker.py <file1> <file2>")
        print("       python smt_equivalence_checker.py --analyze <file>")
        sys.exit(1)
    
    checker = SMTEquivalenceChecker()
    
    if sys.argv[1] == '--analyze':
        # 分析模式
        if len(sys.argv) != 3:
            print("分析模式用法: python smt_equivalence_checker.py --analyze <file>")
            sys.exit(1)
        checker.analyze_constraints(sys.argv[2])
    else:
        # 等价性验证模式
        if len(sys.argv) != 3:
            print("验证模式用法: python smt_equivalence_checker.py <file1> <file2>")
            sys.exit(1)
        
        file1 = sys.argv[1]
        file2 = sys.argv[2]
        
        # 先分析两个文件
        checker.analyze_constraints(file1)
        checker.analyze_constraints(file2)
        
        # 然后验证等价性
        result = checker.check_equivalence(file1, file2)
        
        print(f"\n最终结论:")
        if result is True:
            print("  ✓ 两个SMT约束公式在逻辑上等价")
        elif result is False:
            print("  ✗ 两个SMT约束公式在逻辑上不等价")
        else:
            print("  ? 无法确定等价性")

if __name__ == "__main__":
    main() 