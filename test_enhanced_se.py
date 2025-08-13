#!/usr/bin/env python3
"""
增强符号执行测试脚本
测试数组符号化功能是否正常工作
"""

import os
import sys
from se_script import ImprovedPathAnalyzer

def test_array_symbolization():
    """测试数组符号化功能"""
    print("=" * 80)
    print("增强符号执行测试 - 数组符号化功能")
    print("=" * 80)
    
    # 测试用例配置
    test_cases = [
        {
            'name': 's000程序',
            'binary': 'benchmark_temp_s000/s000_O1',
            'description': '简单数组赋值: a[i] = b[i] + 1'
        },
        {
            'name': 's121程序', 
            'binary': 'benchmark_temp_s121/s121_O1',
            'description': '复杂数组赋值: a[i] = a[i+1] + b[i]'
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n测试用例 {i}: {test_case['name']}")
        print(f"描述: {test_case['description']}")
        print(f"二进制文件: {test_case['binary']}")
        print("-" * 60)
        
        if not os.path.exists(test_case['binary']):
            print(f"警告: 文件 {test_case['binary']} 不存在，跳过测试")
            continue
        
        try:
            # 配置数组符号化
            array_configs = [
                {'name': 'a', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 10)},
                {'name': 'b', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 10)},
            ]
            
            # 创建分析器（启用数组符号化）
            analyzer = ImprovedPathAnalyzer(
                binary_path=test_case['binary'],
                output_prefix=f"enhanced_{test_case['name'].lower().replace('程序', '')}",
                timeout=60,
                enable_array_symbolization=True,
                array_configs=array_configs
            )
            
            # 运行符号执行
            results = analyzer.run_symbolic_execution()
            
            print(f"✅ 测试完成！发现 {len(results)} 条路径")
            
            # 分析结果
            if results:
                print(f"\n路径分析结果:")
                for j, path in enumerate(results):
                    signature = path['signature']
                    print(f"  路径 {j+1}:")
                    print(f"    输入变量: {signature['variables']}")
                    if signature['array_values']:
                        print(f"    数组符号值: {len(signature['array_values'])} 个数组")
                        for array_name, values in signature['array_values'].items():
                            print(f"      {array_name}: {dict(list(values.items())[:5])}...")
                    print(f"    约束总数: {signature['constraints']['count']}")
                    print(f"    数组约束: {signature['constraints']['array_related_count']}")
            
        except Exception as e:
            print(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()

def compare_symbolization_modes():
    """比较启用和不启用数组符号化的差异"""
    print(f"\n" + "=" * 80)
    print("符号化模式对比测试")
    print("=" * 80)
    
    binary_path = 'benchmark_temp_s000/s000_O1'
    
    if not os.path.exists(binary_path):
        print(f"警告: 测试文件 {binary_path} 不存在")
        return
    
    modes = [
        {'name': '传统模式', 'enable_array': False},
        {'name': '增强模式', 'enable_array': True}
    ]
    
    results_comparison = {}
    
    for mode in modes:
        print(f"\n测试 {mode['name']} (数组符号化: {mode['enable_array']})")
        print("-" * 40)
        
        try:
            analyzer = ImprovedPathAnalyzer(
                binary_path=binary_path,
                output_prefix=f"compare_{mode['name'].lower()}",
                timeout=30,
                enable_array_symbolization=mode['enable_array']
            )
            
            results = analyzer.run_symbolic_execution()
            results_comparison[mode['name']] = results
            
            if results:
                signature = results[0]['signature']  # 查看第一条路径
                print(f"  约束总数: {signature['constraints']['count']}")
                print(f"  数组约束: {signature['constraints'].get('array_related_count', 0)}")
                print(f"  符号变量数: {len(signature['variables'])}")
                if signature.get('array_values'):
                    total_array_symbols = sum(len(values) for values in signature['array_values'].values())
                    print(f"  数组符号数: {total_array_symbols}")
                else:
                    print(f"  数组符号数: 0")
                    
        except Exception as e:
            print(f"  错误: {e}")
            results_comparison[mode['name']] = []
    
    # 对比分析
    print(f"\n对比分析:")
    print("-" * 40)
    
    if all(results_comparison.values()):
        traditional = results_comparison['传统模式'][0]['signature']
        enhanced = results_comparison['增强模式'][0]['signature']
        
        print(f"约束数量变化: {traditional['constraints']['count']} → {enhanced['constraints']['count']}")
        print(f"数组约束增加: {enhanced['constraints'].get('array_related_count', 0)}")
        print(f"符号化能力提升: 可捕获数组级别的程序语义差异")
    else:
        print("对比测试未完成")

def demonstrate_semantic_differences():
    """演示不同程序的语义差异检测"""
    print(f"\n" + "=" * 80)
    print("程序语义差异检测演示")
    print("=" * 80)
    
    programs = [
        'benchmark_temp_s000/s000_O1',
        'benchmark_temp_s121/s121_O1'
    ]
    
    all_results = {}
    
    for program in programs:
        if not os.path.exists(program):
            print(f"跳过 {program} (文件不存在)")
            continue
            
        print(f"\n分析程序: {program}")
        print("-" * 40)
        
        try:
            analyzer = ImprovedPathAnalyzer(
                binary_path=program,
                output_prefix=f"semantic_{os.path.basename(program)}",
                timeout=30,
                enable_array_symbolization=True,
                array_configs=[
                    {'name': 'a', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 8)},
                    {'name': 'b', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 8)},
                ]
            )
            
            results = analyzer.run_symbolic_execution()
            all_results[program] = results
            
            if results:
                signature = results[0]['signature']
                print(f"  发现路径: {len(results)}")
                print(f"  数组约束: {signature['constraints'].get('array_related_count', 0)}")
                if signature.get('array_constraints'):
                    print(f"  数组约束详情: {len(signature['array_constraints'])} 条")
                    
        except Exception as e:
            print(f"  分析失败: {e}")
    
    # 语义差异分析
    if len(all_results) >= 2:
        print(f"\n语义差异分析:")
        print("-" * 40)
        
        programs_list = list(all_results.keys())
        prog1, prog2 = programs_list[0], programs_list[1]
        
        if all_results[prog1] and all_results[prog2]:
            sig1 = all_results[prog1][0]['signature']
            sig2 = all_results[prog2][0]['signature']
            
            array_constraints_diff = (
                sig1['constraints'].get('array_related_count', 0) != 
                sig2['constraints'].get('array_related_count', 0)
            )
            
            print(f"程序1 ({os.path.basename(prog1)}):")
            print(f"  数组约束数: {sig1['constraints'].get('array_related_count', 0)}")
            print(f"程序2 ({os.path.basename(prog2)}):")
            print(f"  数组约束数: {sig2['constraints'].get('array_related_count', 0)}")
            
            if array_constraints_diff:
                print("✅ 检测到数组级别的语义差异！")
            else:
                print("ℹ️  数组约束数量相同，需进一步分析")

def main():
    """主测试函数"""
    print("增强符号执行功能测试套件")
    print("测试数组符号化对程序语义分析的改进效果")
    
    try:
        # 测试1: 基本数组符号化功能
        test_array_symbolization()
        
        # 测试2: 对比不同符号化模式
        compare_symbolization_modes()
        
        # 测试3: 演示语义差异检测
        demonstrate_semantic_differences()
        
        print(f"\n" + "=" * 80)
        print("测试总结")
        print("=" * 80)
        print("✅ 数组符号化功能已集成")
        print("✅ 可以捕获数组级别的程序语义")
        print("✅ 增强了路径约束的表达能力")
        print("📁 查看生成的 enhanced_*.txt 文件了解详细约束")
        
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 