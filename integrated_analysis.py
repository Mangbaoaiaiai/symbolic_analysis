#!/usr/bin/env python3
"""
集成的符号执行和等价性分析工具

结合符号执行和语义等价性分析，提供完整的分析流程和详细时间统计
"""

import os
import time
import datetime
import argparse
import glob
from collections import defaultdict
import re # Added for ProgramSpecificEquivalenceAnalyzer

# 导入现有模块
from se_script import BenchmarkAnalyzer, ImprovedPathAnalyzer
from semantic_equivalence_analyzer import BenchmarkEquivalenceAnalyzer, PathClusterAnalyzer

class ProgramSpecificEquivalenceAnalyzer:
    """针对特定程序的等价性分析器"""
    
    def __init__(self, benchmark_dir, program_name):
        self.benchmark_dir = benchmark_dir
        self.program_name = program_name
        self.analyzer = PathClusterAnalyzer()
        
    def find_program_optimization_levels(self):
        """查找指定程序的所有优化等级路径文件"""
        optimization_levels = {}
        
        # 只查找指定程序的路径文件
        pattern = os.path.join(self.benchmark_dir, f"{self.program_name}_O*_path_*.txt")
        path_files = glob.glob(pattern)
        
        print(f"查找模式: {pattern}")
        print(f"找到路径文件: {len(path_files)} 个")
        
        for file_path in path_files:
            basename = os.path.basename(file_path)
            # 提取优化等级前缀 (例如: s121_O1_path_1.txt -> s121_O1)
            match = re.match(rf'{self.program_name}_(O[0-3])_path_\d+\.txt', basename)
            if match:
                opt_level = match.group(1)
                opt_prefix = f"{self.program_name}_{opt_level}"
                if opt_prefix not in optimization_levels:
                    optimization_levels[opt_prefix] = []
                optimization_levels[opt_prefix].append(file_path)
        
        return optimization_levels
    
    def compare_program_optimization_pairs(self):
        """比较指定程序的所有优化等级对"""
        
        optimization_levels = self.find_program_optimization_levels()
        
        if len(optimization_levels) < 2:
            print(f"程序 {self.program_name} 的优化等级数量不足以进行比较 (找到 {len(optimization_levels)} 个)")
            print("发现的优化等级:", list(optimization_levels.keys()))
            return None
        
        print(f"程序 {self.program_name} 发现 {len(optimization_levels)} 个优化等级:")
        for opt_level in sorted(optimization_levels.keys()):
            print(f"  {opt_level}: {len(optimization_levels[opt_level])} 个路径文件")
        
        # 生成所有优化等级对
        opt_levels = sorted(optimization_levels.keys())
        comparison_results = {}
        
        for i, opt1 in enumerate(opt_levels):
            for j, opt2 in enumerate(opt_levels):
                if i >= j:  # 避免重复比较和自比较
                    continue
                
                print(f"\n{'='*60}")
                print(f"比较 {opt1} vs {opt2}")
                print(f"{'='*60}")
                
                # 使用路径前缀而不是完整目录
                prefix1 = os.path.join(self.benchmark_dir, f"{opt1}_path_")
                prefix2 = os.path.join(self.benchmark_dir, f"{opt2}_path_")
                
                try:
                    results = self.analyzer.analyze_path_clusters(prefix1, prefix2)
                    comparison_results[(opt1, opt2)] = results
                    
                    # 生成单独的报告
                    report_file = os.path.join(
                        self.benchmark_dir, 
                        f"equivalence_report_{opt1}_vs_{opt2}.txt"
                    )
                    self.analyzer.generate_report(results, report_file)
                    print(f"报告已保存到: {report_file}")
                    
                except Exception as e:
                    print(f"比较 {opt1} vs {opt2} 时发生错误: {e}")
                    comparison_results[(opt1, opt2)] = {
                        'error': str(e),
                        'status': 'failed'
                    }
        
        # 生成针对程序的摘要报告
        self.generate_program_summary_report(comparison_results)
        
        return comparison_results
    
    def generate_program_summary_report(self, comparison_results):
        """生成针对特定程序的摘要报告"""
        summary_file = os.path.join(self.benchmark_dir, f"{self.program_name}_equivalence_summary.txt")
        
        with open(summary_file, "w", encoding='utf-8') as f:
            f.write(f"程序 {self.program_name} 优化等级等价性分析摘要\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"分析目录: {self.benchmark_dir}\n")
            f.write(f"目标程序: {self.program_name}\n")
            f.write(f"比较的优化等级对数: {len(comparison_results)}\n\n")
            
            for (opt1, opt2), results in comparison_results.items():
                f.write(f"比较 {opt1} vs {opt2}:\n")
                if 'error' in results:
                    f.write(f"  状态: 失败\n")
                    f.write(f"  错误: {results['error']}\n")
                else:
                    f.write(f"  状态: 成功\n")
                    if 'equivalent_pairs' in results:
                        f.write(f"  等价路径对: {len(results['equivalent_pairs'])}\n")
                    if 'non_equivalent_pairs' in results:
                        f.write(f"  非等价路径对: {len(results['non_equivalent_pairs'])}\n")
                f.write("\n")
        
        print(f"程序特定摘要报告已保存到: {summary_file}")

class IntegratedAnalysisFramework:
    """集成分析框架"""
    
    def __init__(self, benchmark_dir, timeout=120, force_rerun=False, target_program=None):
        self.benchmark_dir = benchmark_dir
        self.timeout = timeout
        self.force_rerun = force_rerun
        self.target_program = target_program  # 添加目标程序参数
        self.timing_data = {
            'total_start_time': None,
            'total_end_time': None,
            'symbolic_execution': {},
            'equivalence_analysis': {},
            'phase_times': {}
        }
        
    def run_complete_analysis(self, binary_patterns=None):
        """运行完整的分析流程"""
        print("=" * 80)
        print("开始集成分析：符号执行 + 等价性分析")
        if self.target_program:
            print(f"目标程序: {self.target_program}")
        print("=" * 80)
        
        self.timing_data['total_start_time'] = time.time()
        
        # 阶段1：符号执行
        print(f"\n📊 阶段1：符号执行")
        print("-" * 50)
        se_start_time = time.time()
        
        if binary_patterns:
            # 分析指定的二进制文件
            se_results = self.run_targeted_symbolic_execution(binary_patterns)
        else:
            # 批量分析
            se_results = self.run_batch_symbolic_execution()
        
        se_end_time = time.time()
        se_duration = se_end_time - se_start_time
        
        self.timing_data['phase_times']['symbolic_execution'] = se_duration
        self.timing_data['symbolic_execution'] = se_results
        
        print(f"\n✅ 符号执行阶段完成，耗时: {se_duration:.3f} 秒")
        
        # 阶段2：等价性分析
        print(f"\n🔍 阶段2：等价性分析")
        print("-" * 50)
        eq_start_time = time.time()
        
        eq_results = self.run_equivalence_analysis()
        
        eq_end_time = time.time()
        eq_duration = eq_end_time - eq_start_time
        
        self.timing_data['phase_times']['equivalence_analysis'] = eq_duration
        self.timing_data['equivalence_analysis'] = eq_results
        
        print(f"\n✅ 等价性分析阶段完成，耗时: {eq_duration:.3f} 秒")
        
        # 完成分析
        self.timing_data['total_end_time'] = time.time()
        total_duration = self.timing_data['total_end_time'] - self.timing_data['total_start_time']
        self.timing_data['phase_times']['total'] = total_duration
        
        print(f"\n🎉 完整分析流程完成，总耗时: {total_duration:.3f} 秒")
        
        # 生成综合报告
        self.generate_comprehensive_report()
        
        return {
            'symbolic_execution_results': se_results,
            'equivalence_analysis_results': eq_results,
            'timing_data': self.timing_data
        }
    
    def run_batch_symbolic_execution(self):
        """批量运行符号执行"""
        print("正在查找二进制文件...")
        
        analyzer = BenchmarkAnalyzer(self.benchmark_dir, self.timeout)
        results = analyzer.analyze_all_binaries()
        
        # 收集详细的时间信息
        se_timing = {}
        for binary_name, paths in results.items():
            # 这里应该从analyzer中获取时间信息，但现有代码没有返回
            # 我们可以估算每个二进制文件的分析时间
            se_timing[binary_name] = {
                'path_count': len(paths),
                'estimated_time': len(paths) * 0.1  # 估算时间
            }
        
        analyzer.generate_summary_report()
        
        return {
            'results': results,
            'timing': se_timing,
            'summary_file': os.path.join(self.benchmark_dir, "symbolic_execution_summary.txt")
        }
    
    def run_targeted_symbolic_execution(self, binary_patterns):
        """运行针对特定二进制文件的符号执行"""
        results = {}
        se_timing = {}
        
        for pattern in binary_patterns:
            # 查找二进制文件（不是路径文件）
            all_files = glob.glob(os.path.join(self.benchmark_dir, pattern))
            binary_files = [f for f in all_files if not f.endswith('.txt') and not f.endswith('.c')]
            
            for binary_path in binary_files:
                print(f"检查二进制文件: {binary_path}")
                
                basename = os.path.basename(binary_path)
                
                # 检查是否已存在路径文件（在当前目录和benchmark目录中查找）
                current_dir_paths = glob.glob(f"{basename}_path_*.txt")
                benchmark_dir_paths = glob.glob(os.path.join(self.benchmark_dir, f"{basename}_path_*.txt"))
                
                existing_paths = current_dir_paths + benchmark_dir_paths
                
                if existing_paths and not self.force_rerun:
                    print(f"发现已存在的路径文件: {len(existing_paths)} 个")
                    print("跳过符号执行，使用现有路径文件")
                    
                    # 模拟结果结构
                    mock_paths = []
                    for i, path_file in enumerate(existing_paths):
                        mock_paths.append({
                            'index': i + 1,
                            'signature': {'output': f'路径{i+1}'},
                            'smt_constraints': f'来自文件: {path_file}',
                            'state': None
                        })
                    
                    results[basename] = mock_paths
                    se_timing[basename] = {
                        'path_count': len(existing_paths),
                        'actual_time': 0.0,  # 没有实际执行时间
                        'skipped': True
                    }
                    
                    print(f"使用现有路径: {basename} - {len(existing_paths)} 条路径")
                else:
                    if existing_paths and self.force_rerun:
                        print(f"强制重新执行模式: 删除 {len(existing_paths)} 个现有路径文件")
                        for path_file in existing_paths:
                            try:
                                os.remove(path_file)
                                print(f"  删除: {path_file}")
                            except OSError as e:
                                print(f"  删除失败 {path_file}: {e}")
                        print("现有路径文件已删除")
                    
                    print(f"分析二进制文件: {binary_path}")
                    
                    binary_start = time.time()
                    
                    analyzer = ImprovedPathAnalyzer(binary_path, basename, self.timeout)
                    paths = analyzer.run_symbolic_execution()
                    
                    binary_end = time.time()
                    binary_duration = binary_end - binary_start
                    
                    results[basename] = paths
                    se_timing[basename] = {
                        'path_count': len(paths),
                        'actual_time': binary_duration,
                        'skipped': False
                    }
                    
                    print(f"完成 {basename}: {len(paths)} 条路径，耗时 {binary_duration:.3f} 秒")
        
        return {
            'results': results,
            'timing': se_timing
        }
    
    def run_equivalence_analysis(self):
        """运行等价性分析"""
        print("开始等价性分析...")
        
        # 检查路径文件的实际位置
        current_dir_files = glob.glob("*_path_*.txt")
        benchmark_dir_files = glob.glob(os.path.join(self.benchmark_dir, "*_path_*.txt"))
        
        # 决定在哪个目录运行等价性分析
        if current_dir_files and not benchmark_dir_files:
            print(f"在当前目录找到路径文件，切换分析目录到当前目录")
            analysis_dir = "."
        else:
            analysis_dir = self.benchmark_dir
        
        # 如果指定了目标程序，使用程序特定的分析器
        if self.target_program:
            print(f"使用程序特定分析器分析: {self.target_program}")
            program_analyzer = ProgramSpecificEquivalenceAnalyzer(analysis_dir, self.target_program)
            comparison_results = program_analyzer.compare_program_optimization_pairs()
        else:
            print("使用通用分析器分析所有程序")
            benchmark_analyzer = BenchmarkEquivalenceAnalyzer(analysis_dir)
            comparison_results = benchmark_analyzer.compare_all_optimization_pairs()
        
        # 检查是否成功获得比较结果
        if comparison_results is None:
            error_msg = f"未找到足够的优化等级或路径文件"
            if self.target_program:
                error_msg += f" (目标程序: {self.target_program})"
            print(f"❌ 等价性分析失败：{error_msg}")
            return {
                'comparison_results': {},
                'timing': {},
                'summary_file': None,
                'error': error_msg
            }
        
        # 收集等价性分析的时间信息
        eq_timing = {}
        for (opt1, opt2), results in comparison_results.items():
            comparison_name = f"{opt1}_vs_{opt2}"
            if 'timing_info' in results:
                eq_timing[comparison_name] = results['timing_info']
        
        # 确定摘要文件名
        if self.target_program:
            summary_file = os.path.join(analysis_dir, f"{self.target_program}_equivalence_summary.txt")
        else:
            summary_file = os.path.join(analysis_dir, "optimization_equivalence_summary.txt")
        
        return {
            'comparison_results': comparison_results,
            'timing': eq_timing,
            'summary_file': summary_file
        }
    
    def generate_comprehensive_report(self):
        """生成综合分析报告"""
        report_file = os.path.join(self.benchmark_dir, "integrated_analysis_report.txt")
        
        with open(report_file, "w", encoding='utf-8') as f:
            f.write("集成分析综合报告\n")
            f.write("=" * 60 + "\n\n")
            
            # 总体时间统计
            f.write("总体时间统计:\n")
            f.write("-" * 40 + "\n")
            
            total_time = self.timing_data['phase_times']['total']
            se_time = self.timing_data['phase_times']['symbolic_execution']
            eq_time = self.timing_data['phase_times']['equivalence_analysis']
            
            f.write(f"  总分析时间: {total_time:.3f} 秒\n\n")
            
            f.write("各阶段时间分布:\n")
            f.write("-" * 40 + "\n")
            f.write(f"  符号执行阶段: {se_time:.3f} 秒 ({se_time/total_time*100:.1f}%)\n")
            f.write(f"  等价性分析阶段: {eq_time:.3f} 秒 ({eq_time/total_time*100:.1f}%)\n\n")
            
            # 符号执行详细信息
            if 'timing' in self.timing_data['symbolic_execution']:
                f.write("符号执行详细统计:\n")
                f.write("-" * 40 + "\n")
                
                se_timing = self.timing_data['symbolic_execution']['timing']
                if se_timing:
                    total_paths = sum(info['path_count'] for info in se_timing.values())
                    skipped_count = sum(1 for info in se_timing.values() if info.get('skipped', False))
                    actual_analyzed = len(se_timing) - skipped_count
                    
                    f.write(f"  分析的二进制文件数: {len(se_timing)}\n")
                    f.write(f"  跳过符号执行的文件数: {skipped_count}\n")
                    f.write(f"  实际执行符号执行的文件数: {actual_analyzed}\n")
                    f.write(f"  生成的总路径数: {total_paths}\n")
                    
                    if len(se_timing) > 0:
                        f.write(f"  平均每个文件路径数: {total_paths/len(se_timing):.1f}\n")
                    
                    if actual_analyzed > 0:
                        actual_times = [info['actual_time'] for info in se_timing.values() if 'actual_time' in info and not info.get('skipped', False)]
                        if actual_times:
                            avg_time = sum(actual_times) / len(actual_times)
                            f.write(f"  平均每个文件分析时间: {avg_time:.3f} 秒\n")
                    
                    if total_paths > 0 and se_time > 0:
                        f.write(f"  平均每条路径生成时间: {se_time/total_paths:.4f} 秒\n")
                    
                    # 检查路径质量问题
                    empty_path_files = 0
                    if self.target_program:
                        # 检查目标程序的路径文件质量
                        pattern = f"{self.target_program}_O*_path_*.txt"
                        path_files = glob.glob(pattern) + glob.glob(os.path.join(self.benchmark_dir, pattern))
                        
                        for path_file in path_files:
                            try:
                                with open(path_file, 'r') as pf:
                                    content = pf.read()
                                    if "'count': 0" in content or "约束信息: {'count': 0}" in content:
                                        empty_path_files += 1
                            except:
                                pass
                        
                        if empty_path_files > 0:
                            f.write(f"\n  ⚠️  路径质量诊断:\n")
                            f.write(f"     发现 {empty_path_files} 个空约束路径文件\n")
                            f.write(f"     可能原因: 程序使用固定输入，缺少符号化变量\n")
                            f.write(f"     建议: 检查符号执行配置，确保正确设置符号化输入\n")
                    
                    f.write("\n")
                else:
                    f.write("  没有进行符号执行（使用现有路径文件）\n\n")
                
                # 各文件详细信息
                f.write("各二进制文件分析详情:\n")
                for binary_name, timing_info in se_timing.items():
                    f.write(f"  {binary_name}:\n")
                    f.write(f"    路径数: {timing_info['path_count']}\n")
                    
                    if timing_info.get('skipped', False):
                        f.write(f"    状态: 使用现有路径文件\n")
                    else:
                        if 'actual_time' in timing_info:
                            f.write(f"    分析时间: {timing_info['actual_time']:.3f} 秒\n")
                            if timing_info['path_count'] > 0:
                                f.write(f"    每路径时间: {timing_info['actual_time']/timing_info['path_count']:.4f} 秒\n")
                        f.write(f"    状态: 新执行完成\n")
                    f.write("\n")
            
            # 等价性分析详细信息
            if 'timing' in self.timing_data['equivalence_analysis']:
                eq_timing = self.timing_data['equivalence_analysis']['timing']
                
                if eq_timing:  # 检查是否有时间数据
                    f.write("等价性分析详细统计:\n")
                    f.write("-" * 40 + "\n")
                    
                    total_comparisons = len(eq_timing)
                    total_z3_time = sum(timing.get('z3_total_time', 0) for timing in eq_timing.values())
                    total_z3_calls = sum(timing.get('z3_call_count', 0) for timing in eq_timing.values())
                    
                    f.write(f"  优化级别对比较数: {total_comparisons}\n")
                    f.write(f"  Z3求解总时间: {total_z3_time:.3f} 秒 ({total_z3_time/eq_time*100:.1f}%)\n")
                    f.write(f"  Z3求解总调用次数: {total_z3_calls}\n")
                    if total_z3_calls > 0:
                        f.write(f"  平均每次Z3求解时间: {total_z3_time/total_z3_calls:.4f} 秒\n")
                    f.write(f"  非Z3处理时间: {eq_time - total_z3_time:.3f} 秒 ({(eq_time - total_z3_time)/eq_time*100:.1f}%)\n\n")
                    
                    # 等价性统计
                    total_equiv_pairs = 0
                    total_non_equiv_pairs = 0
                    
                    # 从比较结果中提取等价性信息
                    if 'comparison_results' in self.timing_data['equivalence_analysis']:
                        comp_results = self.timing_data['equivalence_analysis']['comparison_results']
                        for (opt1, opt2), results in comp_results.items():
                            if 'equivalent_pairs' in results:
                                total_equiv_pairs += len(results['equivalent_pairs'])
                            if 'non_equivalent_pairs' in results:
                                total_non_equiv_pairs += len(results['non_equivalent_pairs'])
                    
                    if total_equiv_pairs + total_non_equiv_pairs > 0:
                        equiv_rate = total_equiv_pairs / (total_equiv_pairs + total_non_equiv_pairs) * 100
                        f.write(f"  等价路径对总数: {total_equiv_pairs}\n")
                        f.write(f"  非等价路径对总数: {total_non_equiv_pairs}\n")
                        f.write(f"  等价性验证率: {equiv_rate:.1f}%\n\n")
                    
                    # 各比较对详细信息
                    f.write("各优化级别对比较详情:\n")
                    for comparison_name, timing_info in eq_timing.items():
                        f.write(f"  {comparison_name}:\n")
                        f.write(f"    总时间: {timing_info.get('total_time', 0):.3f} 秒\n")
                        f.write(f"    文件加载: {timing_info.get('load_time', 0):.3f} 秒\n")
                        f.write(f"    路径比较: {timing_info.get('comparison_time', 0):.3f} 秒\n")
                        f.write(f"    Z3求解: {timing_info.get('z3_total_time', 0):.3f} 秒\n")
                        f.write(f"    Z3调用: {timing_info.get('z3_call_count', 0)} 次\n")
                        f.write("\n")
                else:
                    f.write("等价性分析状态:\n")
                    f.write("-" * 40 + "\n")
                    error_msg = self.timing_data['equivalence_analysis'].get('error', '未知错误')
                    f.write(f"  ❌ 等价性分析失败: {error_msg}\n")
                    
                    # 提供诊断建议
                    if self.target_program:
                        f.write(f"  🔍 针对程序 {self.target_program} 的诊断建议:\n")
                        f.write(f"    1. 检查是否存在有效的路径文件\n")
                        f.write(f"    2. 验证路径文件包含有意义的约束\n")
                        f.write(f"    3. 确保至少有2个不同的优化级别\n")
                    else:
                        f.write(f"  🔍 诊断建议:\n")
                        f.write(f"    1. 检查路径文件是否正确生成\n")
                        f.write(f"    2. 验证文件命名格式正确\n")
                        f.write(f"    3. 确保目录中有足够的优化级别\n")
                    f.write("\n")
            
            # 性能分析和建议
            f.write("性能分析和优化建议:\n")
            f.write("-" * 40 + "\n")
            
            if se_time > eq_time:
                f.write("  符号执行是主要时间瓶颈\n")
                f.write("  建议优化方向:\n")
                f.write("    - 优化约束求解策略\n")
                f.write("    - 调整路径探索深度\n")
                f.write("    - 并行化符号执行\n")
            else:
                f.write("  等价性分析是主要时间瓶颈\n")
                f.write("  建议优化方向:\n")
                f.write("    - 优化Z3求解器配置\n")
                f.write("    - 改进路径匹配算法\n")
                f.write("    - 并行化等价性检查\n")
            
            if 'timing' in self.timing_data['equivalence_analysis']:
                eq_timing = self.timing_data['equivalence_analysis']['timing']
                if eq_timing:
                    total_z3_time = sum(timing.get('z3_total_time', 0) for timing in eq_timing.values())
                    total_comparison_time = sum(timing.get('total_time', 0) for timing in eq_timing.values())
                    
                    if total_comparison_time > 0:
                        z3_ratio = total_z3_time / total_comparison_time
                        f.write(f"\n  Z3求解占等价性分析时间比例: {z3_ratio*100:.1f}%\n")
                        if z3_ratio > 0.8:
                            f.write("    Z3求解是等价性分析的主要瓶颈\n")
                        elif z3_ratio < 0.5:
                            f.write("    路径匹配和预处理耗时较多\n")
                else:
                    f.write(f"\n  ⚠️  等价性分析未成功完成\n")
                    if self.target_program:
                        f.write(f"     这可能是因为程序 {self.target_program} 的路径约束为空\n")
                        f.write(f"     建议检查符号执行配置或程序输入设置\n")
        
        print(f"\n📄 综合分析报告已保存到: {report_file}")
        
        # 打印关键统计信息
        print(f"\n📊 关键性能指标:")
        print(f"   总分析时间: {self.timing_data['phase_times']['total']:.3f} 秒")
        print(f"   符号执行: {self.timing_data['phase_times']['symbolic_execution']:.3f} 秒 ({self.timing_data['phase_times']['symbolic_execution']/self.timing_data['phase_times']['total']*100:.1f}%)")
        print(f"   等价性分析: {self.timing_data['phase_times']['equivalence_analysis']:.3f} 秒 ({self.timing_data['phase_times']['equivalence_analysis']/self.timing_data['phase_times']['total']*100:.1f}%)")
        
        # 添加特定诊断信息
        if self.target_program:
            print(f"   目标程序: {self.target_program}")
            # 检查路径文件质量
            pattern = f"{self.target_program}_O*_path_*.txt"
            path_files = glob.glob(pattern) + glob.glob(os.path.join(self.benchmark_dir, pattern))
            
            empty_constraint_files = 0
            for path_file in path_files:
                try:
                    with open(path_file, 'r') as pf:
                        content = pf.read()
                        if "'count': 0" in content:
                            empty_constraint_files += 1
                except:
                    pass
            
            if empty_constraint_files > 0:
                print(f"   ⚠️  发现 {empty_constraint_files} 个空约束路径文件")
                print(f"   💡 建议: 检查程序是否使用符号化输入")

class QuickAnalysisMode:
    """快速分析模式 - 针对特定程序的分析"""
    
    def __init__(self, program_name, benchmark_dir, timeout=120, force_rerun=False):
        self.program_name = program_name
        self.benchmark_dir = benchmark_dir
        self.timeout = timeout
        self.force_rerun = force_rerun
        
    def run_quick_analysis(self):
        """运行快速分析 - 只分析指定程序的所有优化级别"""
        print(f"🚀 快速分析模式: {self.program_name}")
        print("=" * 60)
        
        # 查找所有相关的二进制文件
        binary_patterns = [f"{self.program_name}_O*"]
        
        framework = IntegratedAnalysisFramework(self.benchmark_dir, self.timeout, self.force_rerun, self.program_name)
        results = framework.run_complete_analysis(binary_patterns)
        
        return results

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='集成的符号执行和等价性分析工具')
    parser.add_argument('--benchmark', default='.', help='benchmark目录路径')
    parser.add_argument('--timeout', type=int, default=120, help='符号执行超时时间(秒)')
    parser.add_argument('--program', help='指定程序名进行快速分析 (例如: s000)')
    parser.add_argument('--quick', action='store_true', help='启用快速分析模式')
    parser.add_argument('--force-rerun', '-f', action='store_true', help='强制重新执行符号执行，删除现有路径文件')
    
    args = parser.parse_args()
    
    if args.quick and args.program:
        # 快速分析模式
        quick_analyzer = QuickAnalysisMode(args.program, args.benchmark, args.timeout, args.force_rerun)
        results = quick_analyzer.run_quick_analysis()
    else:
        # 完整分析模式
        framework = IntegratedAnalysisFramework(args.benchmark, args.timeout, args.force_rerun)
        results = framework.run_complete_analysis()
    
    print("\n🎯 分析完成！查看以下文件获取详细结果:")
    print(f"   📄 综合报告: {os.path.join(args.benchmark, 'integrated_analysis_report.txt')}")
    print(f"   📊 符号执行报告: {os.path.join(args.benchmark, 'symbolic_execution_summary.txt')}")
    print(f"   🔍 等价性分析报告: {os.path.join(args.benchmark, 'optimization_equivalence_summary.txt')}")

if __name__ == "__main__":
    main() 