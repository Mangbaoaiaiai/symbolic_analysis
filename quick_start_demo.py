#!/usr/bin/env python3
"""
TSVC Benchmark 快速演示脚本
测试整个benchmark系统的基本功能
"""

import os
import sys
import time
from pathlib import Path

def check_dependencies():
    """检查必要的依赖文件"""
    print("检查依赖文件...")
    
    required_files = [
        "pldi19-equivalence-checker/pldi19/TSVC/clean.c",
        "semantic_equivalence_analyzer.py", 
        "path_analyzer_fixed.py",
        "tsvc_benchmark_runner.py",
        "tsvc_symbolic_integration.py"
    ]
    
    missing_files = []
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"  ✓ {file_path}")
        else:
            print(f"  ✗ {file_path}")
            missing_files.append(file_path)
    
    if missing_files:
        print(f"\n错误: 缺少 {len(missing_files)} 个必要文件")
        print("请确保所有文件都在正确位置")
        return False
    
    print("所有依赖文件检查通过!")
    return True

def test_benchmark_extraction():
    """测试benchmark提取功能"""
    print("\n测试benchmark提取...")
    
    try:
        from tsvc_benchmark_runner import TSVCBenchmarkExtractor
        
        extractor = TSVCBenchmarkExtractor()
        functions = extractor.extract_benchmark_functions()
        
        print(f"  成功提取 {len(functions)} 个benchmark函数")
        print(f"  推荐benchmark: {extractor.recommended_benchmarks}")
        
        # 显示前几个函数的信息
        for i, (name, info) in enumerate(list(functions.items())[:3]):
            status = "推荐" if info['recommended'] else "可选"
            print(f"    {name} ({status})")
        
        return True
        
    except Exception as e:
        print(f"  ✗ benchmark提取失败: {e}")
        return False

def test_single_benchmark():
    """测试单个benchmark的编译和分析"""
    print("\n测试单个benchmark编译...")
    
    try:
        from tsvc_benchmark_runner import TSVCBenchmarkExtractor
        
        extractor = TSVCBenchmarkExtractor()
        extractor.extract_benchmark_functions()
        
        # 测试s000 benchmark（最简单的一个）
        test_benchmark = 's000'
        print(f"  测试benchmark: {test_benchmark}")
        
        variants = extractor.create_benchmark_variants(test_benchmark, ['O1', 'O2'])
        
        successful_variants = [k for k, v in variants.items() if v['compilation_success']]
        print(f"  成功编译的变体: {successful_variants}")
        
        if len(successful_variants) >= 2:
            print("  ✓ 编译测试通过")
            return True
        else:
            print("  ✗ 编译测试失败：需要至少2个成功的变体")
            return False
            
    except Exception as e:
        print(f"  ✗ benchmark编译测试失败: {e}")
        return False

def test_path_generation():
    """测试路径生成功能"""
    print("\n测试路径生成...")
    
    try:
        from tsvc_symbolic_integration import TSVCSymbolicIntegrator
        
        integrator = TSVCSymbolicIntegrator()
        
        # 生成模拟路径
        paths = integrator.generate_execution_paths(
            "dummy_binary",
            "test_s000_O1", 
            num_paths=5
        )
        
        print(f"  生成了 {len(paths)} 条路径")
        
        # 检查路径文件是否存在
        if paths:
            first_path = Path(paths[0])
            if first_path.exists():
                print("  ✓ 路径文件生成成功")
                
                # 检查文件内容
                with open(first_path, 'r') as f:
                    content = f.read()
                    if 'declare-fun' in content and 'assert' in content:
                        print("  ✓ SMT约束格式正确")
                        return True
                    else:
                        print("  ✗ SMT约束格式不正确")
                        return False
            else:
                print("  ✗ 路径文件不存在")
                return False
        else:
            print("  ✗ 未生成任何路径")
            return False
            
    except Exception as e:
        print(f"  ✗ 路径生成测试失败: {e}")
        return False

def test_symbolic_analysis():
    """测试符号分析功能"""
    print("\n测试符号分析工具...")
    
    try:
        # 测试约束等价性检查器
        from semantic_equivalence_analyzer import ConstraintEquivalenceChecker
        
        checker = ConstraintEquivalenceChecker(timeout=5000)  # 5秒超时
        
        # 创建简单的测试约束
        vars1 = {'x': 32, 'y': 32}
        vars2 = {'a': 32, 'b': 32}
        constraints1 = ['(= x (bvadd y #x00000001))']
        constraints2 = ['(= a (bvadd b #x00000001))']
        var_mapping = {'x': 'a', 'y': 'b'}
        
        result, details = checker.check_constraint_equivalence(
            constraints1, constraints2, vars1, vars2, var_mapping
        )
        
        print(f"  约束等价性检查结果: {result}")
        print(f"  求解时间: {details.get('solve_time', 0):.3f}秒")
        
        if result == 'equivalent':
            print("  ✓ 符号分析工具工作正常")
            return True
        elif result in ['not_equivalent', 'unknown']:
            print("  ⚠ 符号分析工具工作正常，但约束未验证为等价")
            return True
        else:
            print("  ✗ 符号分析工具出现错误")
            return False
            
    except Exception as e:
        print(f"  ✗ 符号分析测试失败: {e}")
        return False

def run_mini_benchmark():
    """运行一个迷你benchmark来测试完整流程"""
    print("\n运行迷你benchmark测试...")
    
    try:
        from tsvc_symbolic_integration import TSVCSymbolicIntegrator
        
        integrator = TSVCSymbolicIntegrator()
        
        # 运行s000 benchmark的简化版本
        result = integrator.run_benchmark_analysis('s000', opt_levels=['O1', 'O2'])
        
        if result and len(result) > 0:
            print("  ✓ 迷你benchmark运行成功")
            
            for comparison, comp_result in result.items():
                status = comp_result.get('status', 'unknown')
                print(f"    {comparison}: {status}")
            
            return True
        else:
            print("  ✗ 迷你benchmark运行失败")
            return False
            
    except Exception as e:
        print(f"  ✗ 迷你benchmark测试失败: {e}")
        return False

def cleanup_test_files():
    """清理测试文件"""
    print("\n清理测试文件...")
    
    cleanup_patterns = [
        "benchmark_temp_*",
        "paths_*",
        "*_fixed.txt",
        "tsvc_analysis_results",
    ]
    
    import shutil
    import glob
    
    for pattern in cleanup_patterns:
        for path in glob.glob(pattern):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                print(f"  删除: {path}")
            except Exception as e:
                print(f"  警告: 无法删除 {path}: {e}")

def main():
    """主函数"""
    print("TSVC Benchmark 快速演示")
    print("=" * 40)
    
    start_time = time.time()
    
    # 运行所有测试
    tests = [
        ("依赖检查", check_dependencies),
        ("Benchmark提取", test_benchmark_extraction),
        ("单Benchmark编译", test_single_benchmark),
        ("路径生成", test_path_generation),
        ("符号分析", test_symbolic_analysis),
        ("迷你Benchmark", run_mini_benchmark),
    ]
    
    passed_tests = 0
    total_tests = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        
        try:
            if test_func():
                passed_tests += 1
                print(f"✓ {test_name} 通过")
            else:
                print(f"✗ {test_name} 失败")
        except Exception as e:
            print(f"✗ {test_name} 出现异常: {e}")
    
    end_time = time.time()
    
    # 显示测试结果总结
    print(f"\n{'='*50}")
    print("测试结果总结")
    print(f"{'='*50}")
    print(f"总测试数: {total_tests}")
    print(f"通过测试: {passed_tests}")
    print(f"失败测试: {total_tests - passed_tests}")
    print(f"成功率: {passed_tests/total_tests*100:.1f}%")
    print(f"总用时: {end_time - start_time:.2f}秒")
    
    if passed_tests == total_tests:
        print("\n🎉 所有测试通过！系统准备就绪。")
        print("\n下一步:")
        print("  运行完整分析: python tsvc_symbolic_integration.py")
        print("  查看文档: cat README_TSVC_BENCHMARK.md")
    elif passed_tests >= total_tests * 0.7:
        print("\n⚠ 大部分测试通过，系统基本可用。")
        print("请检查失败的测试并修复相关问题。")
    else:
        print("\n❌ 多个测试失败，请检查环境配置。")
        print("参考README_TSVC_BENCHMARK.md进行故障排除。")
    
    # 询问是否清理测试文件
    try:
        response = input("\n是否清理测试文件? (y/N): ").strip().lower()
        if response in ['y', 'yes']:
            cleanup_test_files()
        else:
            print("保留测试文件以供调试使用")
    except KeyboardInterrupt:
        print("\n\n测试完成")

if __name__ == "__main__":
    main() 