                      
"""
Benchmark时间分析脚本

整理和统计每个benchmark验证过程的用时，包括：
1. 符号执行时间
2. 等价性分析时间
3. 总体统计
"""

import json
import glob
import re
import os
from collections import defaultdict
from datetime import datetime

class BenchmarkTimingAnalyzer:
    def __init__(self):
        self.equivalence_data = None
        self.symbolic_execution_data = {}
        self.combined_stats = defaultdict(dict)
    
    def load_equivalence_data(self):
        """加载等价性分析数据"""
        try:
            with open('batch_equivalence_analysis_data.json', 'r', encoding='utf-8') as f:
                self.equivalence_data = json.load(f)
            print("✅ 成功加载等价性分析数据")
            return True
        except FileNotFoundError:
            print("❌ 未找到等价性分析数据文件")
            return False
    
    def load_symbolic_execution_data(self):
        """加载符号执行数据"""
        try:
                            
            if os.path.exists('batch_symbolic_execution_data.json'):
                with open('batch_symbolic_execution_data.json', 'r', encoding='utf-8') as f:
                    se_json = json.load(f)
                self.parse_symbolic_execution_json(se_json)
                print("✅ 成功加载符号执行JSON数据")
                return True
            
                                   
            se_files = glob.glob("*symbolic_execution_report.txt")
            if not se_files:
                print("⚠️  未找到符号执行数据文件")
                return False
            
            for file in se_files:
                self.parse_symbolic_execution_file(file)
            
            print(f"✅ 成功加载 {len(se_files)} 个符号执行报告")
            return True
        except Exception as e:
            print(f"❌ 加载符号执行数据失败: {e}")
            return False
    
    def parse_symbolic_execution_json(self, se_json):
        """解析符号执行JSON数据"""
        try:
            for benchmark, binaries in se_json['results'].items():
                                                               
                benchmark_name = benchmark.replace('benchmark_temp_', '')
                
                                   
                total_time = 0.0
                total_paths = 0
                optimization_levels = {}
                
                for binary_data in binaries:
                    binary_name = binary_data['binary_name']
                                              
                    if '_' in binary_name:
                        opt_level = binary_name.split('_')[-1]
                        optimization_levels[opt_level] = {
                            'execution_time': binary_data['execution_time'],
                            'paths_found': binary_data['paths_found'],
                            'setup_time': binary_data.get('setup_time', 0),
                            'exploration_time': binary_data.get('exploration_time', 0),
                            'analysis_time': binary_data.get('analysis_time', 0)
                        }
                    
                    total_time += binary_data['execution_time']
                    total_paths += binary_data['paths_found']
                
                        
                avg_time = total_time / len(binaries) if binaries else 0
                
                self.symbolic_execution_data[benchmark_name] = {
                    'total_execution_time': total_time,
                    'average_execution_time': avg_time,
                    'total_paths_found': total_paths,
                    'optimization_levels': optimization_levels,
                    'binary_count': len(binaries)
                }
                
        except Exception as e:
            print(f"⚠️  解析符号执行JSON数据失败: {e}")
    
    def parse_symbolic_execution_file(self, filename):
        """解析符号执行报告文件"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            
                         
            programs = re.findall(r'程序: (.+?)\n', content)
            execution_times = re.findall(r'执行时间: ([0-9.]+) 秒', content)
            
                         
            sections = content.split('=' * 60)
            for section in sections:
                if '分析结果:' in section and '程序:' in section:
                    program_match = re.search(r'程序: (.+?)\n', section)
                    time_match = re.search(r'执行时间: ([0-9.]+) 秒', section)
                    paths_match = re.search(r'发现路径: (\d+)', section)
                    
                    if program_match and time_match:
                        program = program_match.group(1).strip()
                        time = float(time_match.group(1))
                        paths = int(paths_match.group(1)) if paths_match else 0
                        
                        self.symbolic_execution_data[program] = {
                            'execution_time': time,
                            'paths_found': paths,
                            'source_file': filename
                        }
        
        except Exception as e:
            print(f"⚠️  解析 {filename} 失败: {e}")
    
    def combine_timing_data(self):
        """合并符号执行和等价性分析的时间数据"""
        if not self.equivalence_data:
            return
        

                   
        for program, comparisons in self.equivalence_data['results'].items():
            if program not in self.combined_stats:
                self.combined_stats[program] = {
                    'symbolic_execution_time': 0.0,
                    'equivalence_comparisons': [],
                    'total_equivalence_time': 0.0,
                    'total_paths': 0,
                    'comparison_count': 0
                }
            
            total_eq_time = 0.0
            total_paths = 0
            
            for comparison in comparisons:
                self.combined_stats[program]['equivalence_comparisons'].append({
                    'opt1': comparison['opt1'],
                    'opt2': comparison['opt2'],
                    'time': comparison['execution_time'],
                    'equivalent_pairs': comparison['equivalent_pairs'],
                    'paths_compared': comparison['total_paths_compared']
                })
                total_eq_time += comparison['execution_time']
                total_paths = max(total_paths, comparison['total_paths_compared'])
            
            self.combined_stats[program]['total_equivalence_time'] = total_eq_time
            self.combined_stats[program]['total_paths'] = total_paths
            self.combined_stats[program]['comparison_count'] = len(comparisons)
        
                  
        for program, se_data in self.symbolic_execution_data.items():
                      
            matched_program = None
                      
            if program in self.combined_stats:
                matched_program = program
            else:
                                 
                possible_matches = []
                for combined_program in self.combined_stats.keys():
                    if program in combined_program or combined_program in program:
                        possible_matches.append((combined_program, len(combined_program)))
                                  
                if possible_matches:
                    matched_program = min(possible_matches, key=lambda x: x[1])[0]
            
            if matched_program:
                          
                if 'total_execution_time' in se_data:
                              
                    self.combined_stats[matched_program]['symbolic_execution_time'] = se_data['total_execution_time']
                    self.combined_stats[matched_program]['average_se_time'] = se_data['average_execution_time']
                    self.combined_stats[matched_program]['se_optimization_levels'] = se_data['optimization_levels']
                    self.combined_stats[matched_program]['se_binary_count'] = se_data['binary_count']
                    if se_data['total_paths_found'] > 0:
                        self.combined_stats[matched_program]['total_paths'] = se_data['total_paths_found']
                else:
                            
                    self.combined_stats[matched_program]['symbolic_execution_time'] = se_data['execution_time']
                    if se_data['paths_found'] > 0:
                        self.combined_stats[matched_program]['total_paths'] = se_data['paths_found']
    
    def generate_timing_report(self):
        """生成时间统计报告"""
        if not self.combined_stats:
            print("❌ 没有可用的时间数据")
            return
        
        print("\n🕐 Benchmark验证过程时间统计报告")
        print("=" * 80)
        
              
        total_se_time = sum(stats['symbolic_execution_time'] for stats in self.combined_stats.values())
        total_eq_time = sum(stats['total_equivalence_time'] for stats in self.combined_stats.values())
        total_programs = len(self.combined_stats)
        total_comparisons = sum(stats['comparison_count'] for stats in self.combined_stats.values())
        
        print(f"\n📊 总体统计:")
        print(f"  分析程序数: {total_programs}")
        print(f"  等价性比较次数: {total_comparisons}")
        print(f"  符号执行总时间: {total_se_time:.2f} 秒")
        print(f"  等价性分析总时间: {total_eq_time:.2f} 秒")
        print(f"  验证总时间: {total_se_time + total_eq_time:.2f} 秒")
        
                   
        print(f"\n📋 各程序详细统计:")
        print("-" * 80)
        print(f"{'程序名':<12} {'符号执行':<10} {'等价性分析':<12} {'总时间':<10} {'路径数':<8} {'比较次数':<8}")
        print("-" * 80)
        
        sorted_programs = sorted(self.combined_stats.items(), 
                               key=lambda x: x[1]['symbolic_execution_time'] + x[1]['total_equivalence_time'], 
                               reverse=True)
        
        for program, stats in sorted_programs:
            se_time = stats['symbolic_execution_time']
            eq_time = stats['total_equivalence_time']
            total_time = se_time + eq_time
            paths = stats['total_paths']
            comparisons = stats['comparison_count']
            
            print(f"{program:<12} {se_time:<10.2f} {eq_time:<12.2f} {total_time:<10.2f} {paths:<8} {comparisons:<8}")
        
                
        print(f"\n⚡ 时间分布分析:")
        se_percentage = (total_se_time / (total_se_time + total_eq_time)) * 100 if (total_se_time + total_eq_time) > 0 else 0
        eq_percentage = (total_eq_time / (total_se_time + total_eq_time)) * 100 if (total_se_time + total_eq_time) > 0 else 0
        
        print(f"  符号执行占比: {se_percentage:.1f}%")
        print(f"  等价性分析占比: {eq_percentage:.1f}%")
        
        avg_se_time = total_se_time / total_programs if total_programs > 0 else 0
        avg_eq_time = total_eq_time / total_comparisons if total_comparisons > 0 else 0
        
        print(f"  平均符号执行时间: {avg_se_time:.2f} 秒/程序")
        print(f"  平均等价性分析时间: {avg_eq_time:.2f} 秒/比较")
    
    def generate_detailed_breakdown(self):
        """生成详细的时间分解报告"""
        print(f"\n🔍 详细时间分解:")
        print("=" * 80)
        
        for program, stats in sorted(self.combined_stats.items()):
            print(f"\n📁 {program}:")
            print(f"  符号执行总时间: {stats['symbolic_execution_time']:.2f} 秒")
            
                            
            if 'se_optimization_levels' in stats:
                print(f"  符号执行详情 ({stats.get('se_binary_count', 0)} 个二进制文件):")
                for opt_level, opt_data in stats['se_optimization_levels'].items():
                    print(f"    {opt_level}: {opt_data['execution_time']:.2f}s "
                          f"(设置: {opt_data.get('setup_time', 0):.3f}s, "
                          f"探索: {opt_data.get('exploration_time', 0):.3f}s, "
                          f"分析: {opt_data.get('analysis_time', 0):.3f}s, "
                          f"路径: {opt_data['paths_found']})")
                print(f"    平均时间: {stats.get('average_se_time', 0):.2f} 秒/二进制")
            
            print(f"  发现路径总数: {stats['total_paths']} 条")
            print(f"  等价性比较 ({stats['comparison_count']} 次):")
            
            for comp in stats['equivalence_comparisons']:
                print(f"    {comp['opt1']} vs {comp['opt2']}: {comp['time']:.3f}s "
                      f"({comp['equivalent_pairs']} 等价对, {comp['paths_compared']} 路径)")
            
            print(f"  等价性分析总时间: {stats['total_equivalence_time']:.2f} 秒")
            total_time = stats['symbolic_execution_time'] + stats['total_equivalence_time']
            print(f"  🕐 总耗时: {total_time:.2f} 秒")
    
    def save_timing_summary(self):
        """保存时间统计摘要到文件"""
        summary = {
            'generated_time': datetime.now().isoformat(),
            'total_programs': len(self.combined_stats),
            'total_symbolic_execution_time': sum(stats['symbolic_execution_time'] for stats in self.combined_stats.values()),
            'total_equivalence_time': sum(stats['total_equivalence_time'] for stats in self.combined_stats.values()),
            'program_details': dict(self.combined_stats)
        }
        
        with open('benchmark_timing_summary.json', 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 时间统计摘要已保存到: benchmark_timing_summary.json")

def main():
    """主函数"""
    analyzer = BenchmarkTimingAnalyzer()
    
          
    if not analyzer.load_equivalence_data():
        return
    
    analyzer.load_symbolic_execution_data()
    
             
    analyzer.combine_timing_data()
    
          
    analyzer.generate_timing_report()
    analyzer.generate_detailed_breakdown()
    analyzer.save_timing_summary()

if __name__ == "__main__":
    main() 