                      
"""
测试增强的程序等价性分析器
演示三步验证流程的使用
"""

import subprocess
import time
import os
from semantic_equivalence_analyzer import EnhancedPathAnalyzer

def test_enhanced_analyzer():
    """测试增强的分析器功能"""
    print("🧪 测试增强的程序等价性分析器")
    print("=" * 50)
    
                           
    print("\n📝 测试案例1: s000 vs s121")
    print("-" * 30)
    
    analyzer = EnhancedPathAnalyzer()
    analyzer.set_symbolic_execution_time(15.0)                
    
                
    s000_files = len([f for f in os.listdir('.') if f.startswith('s000_O1_path_') and f.endswith('.txt')])
    s121_files = len([f for f in os.listdir('.') if f.startswith('s121_O1_path_') and f.endswith('.txt')])
    
    if s000_files > 0 and s121_files > 0:
        print(f"找到路径文件: s000({s000_files}个) vs s121({s121_files}个)")
        
        results = analyzer.analyze_program_equivalence('s000_O1_path_', 's121_O1_path_')
        
        print(f"\n🔍 分析结果:")
        print(f"  程序等价性: {'✅ 等价' if results['program_equivalent'] else '❌ 不等价'}")
        print(f"  完全等价路径对: {len(results['equivalent_pairs'])}")
        print(f"  部分等价路径对: {len(results['partial_equivalent_pairs'])}")
        
              
        analyzer.generate_comprehensive_report(results, "test_s000_vs_s121_report.txt")
        print(f"📄 报告已生成: test_s000_vs_s121_report.txt")
        
    else:
        print("❌ 未找到足够的路径文件进行测试")
        print(f"   s000路径文件: {s000_files}个")
        print(f"   s121路径文件: {s121_files}个")
        print("   请先运行符号执行生成路径文件")

def test_with_command_line():
    """测试命令行接口"""
    print("\n🖥️  测试命令行接口")
    print("-" * 30)
    
               
    if os.path.exists('s000_O1_path_1.txt') and os.path.exists('s121_O1_path_1.txt'):
        print("使用命令行接口运行分析...")
        
        cmd = [
            'python', 'semantic_equivalence_analyzer.py',
            's000_O1_path_', 's121_O1_path_',
            '--output', 'cmdline_test_report.txt',
            '--se-time', '15.5',
            '--timeout', '60000'
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print("✅ 命令行测试成功")
                print("📄 报告已生成: cmdline_test_report.txt")
            else:
                print("❌ 命令行测试失败")
                print(f"错误信息: {result.stderr}")
        except Exception as e:
            print(f"❌ 运行命令行时出错: {e}")
    else:
        print("❌ 缺少测试文件，跳过命令行测试")

def demonstrate_three_step_process():
    """演示三步验证流程"""
    print("\n📚 三步验证流程演示")
    print("-" * 30)
    
    print("本程序实现的三步验证流程：")
    print("  1️⃣  约束语义等价性验证")
    print("     - 使用Z3求解器验证SMT约束的逻辑等价性")
    print("     - 检查公式 (F1 ∧ ¬F2) ∨ (¬F1 ∧ F2) 的可满足性")
    print("     - 如果不可满足，则F1 ≡ F2")
    
    print("\n  2️⃣  数组初始状态一致性检查")
    print("     - 比较路径执行前的数组初始值")
    print("     - 确保两条路径从相同的数组状态开始")
    
    print("\n  3️⃣  数组最终状态一致性检查")
    print("     - 比较路径执行后的数组最终值")
    print("     - 确保两条路径产生相同的数组结果")
    
    print("\n✅ 只有三步都通过，才认为两条路径完全等价")
    print("📊 程序等价性：所有路径都有对应等价路径时，程序等价")

def show_usage_examples():
    """展示使用示例"""
    print("\n📖 使用示例")
    print("-" * 30)
    
    print("1. 基本用法:")
    print("   python semantic_equivalence_analyzer.py prog1_path_ prog2_path_")
    
    print("\n2. 指定输出文件和符号执行时间:")
    print("   python semantic_equivalence_analyzer.py prog1_path_ prog2_path_ \\")
    print("          --output my_report.txt --se-time 20.5")
    
    print("\n3. 设置Z3超时时间:")
    print("   python semantic_equivalence_analyzer.py prog1_path_ prog2_path_ \\")
    print("          --timeout 60000")
    
    print("\n4. 完整示例:")
    print("   python semantic_equivalence_analyzer.py s000_O1_path_ s121_O1_path_ \\")
    print("          --output equivalence_analysis.txt \\")
    print("          --se-time 15.3 \\")
    print("          --timeout 30000")

def main():
    """主测试函数"""
    print("🚀 增强的程序等价性分析器测试套件")
    print("=" * 60)
    
              
    demonstrate_three_step_process()
    
            
    show_usage_examples()
    
            
    test_enhanced_analyzer()
    
             
    test_with_command_line()
    
    print("\n" + "=" * 60)
    print("🎯 测试完成！")
    print("📝 要点总结:")
    print("  ✅ 实现了三步验证流程")
    print("  ✅ 支持约束、数组初始和最终状态比较")
    print("  ✅ 详细的时间统计和性能分析")
    print("  ✅ 完整的程序等价性判断")
    print("  ✅ 生成详细的分析报告")
    print("=" * 60)

if __name__ == "__main__":
    main() 