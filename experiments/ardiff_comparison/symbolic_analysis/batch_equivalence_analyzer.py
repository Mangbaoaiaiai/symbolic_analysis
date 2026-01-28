                      
"""
批量等价性分析脚本
使用 semantic_equivalence_analyzer.py 对批量符号执行生成的路径进行等价性比较

功能：
1. 自动发现所有程序和优化等级
2. 对每个程序的不同优化等级进行两两比较
3. 记录详细的时间统计信息
4. 生成综合分析报告
"""

import os
import sys
import glob
import time
import datetime
import subprocess
import json
import re
from pathlib import Path
import argparse
from itertools import combinations
from collections import defaultdict

class BatchEquivalenceAnalyzer:
    """批量等价性分析管理器"""
    
    def __init__(self, timeout=120, equivalence_script="semantic_equivalence_analyzer.py"):
        self.timeout = timeout
        self.equivalence_script = equivalence_script
        self.results = {}
        self.total_start_time = None
        self.total_end_time = None
        self.failed_analyses = []
        self.successful_analyses = []
        self.all_comparisons = []
        self.target_programs = None              
        
    def discover_programs_and_optimizations(self):
        """发现所有程序和优化等级"""
                  
        path_files = glob.glob("*_path_*.txt")
        
        if not path_files:
            print("❌ 未找到任何路径文件")
            return {}
        
                     
        programs = defaultdict(set)
        
        for file_path in path_files:
            filename = os.path.basename(file_path)
                                                  
            match = re.match(r'^(.+)_(O\d+)_path_\d+\.txt$', filename)
            if match:
                program, optimization = match.groups()
                programs[program].add(optimization)
        
                       
        result = {}
        for program, optimizations in programs.items():
            result[program] = sorted(list(optimizations))
        
        return result
    
    def get_comparison_pairs(self, optimizations):
        """获取所有需要比较的优化等级对"""
        return list(combinations(optimizations, 2))
    
    def run_equivalence_analysis(self, program, opt1, opt2):
        """运行单次等价性分析"""
        prefix1 = f"{program}_{opt1}_path_"
        prefix2 = f"{program}_{opt2}_path_"
        
        print(f"  比较 {opt1} vs {opt2}")
        print(f"    前缀1: {prefix1}")
        print(f"    前缀2: {prefix2}")
        
                    
        files1 = glob.glob(f"{prefix1}*.txt")
        files2 = glob.glob(f"{prefix2}*.txt")
        
        if not files1:
            print(f"    ❌ 未找到 {opt1} 的路径文件")
            return None
        if not files2:
            print(f"    ❌ 未找到 {opt2} 的路径文件")
            return None
        
        print(f"    发现路径: {len(files1)} vs {len(files2)}")
        
        start_time = time.time()
        
        try:
                  
            output_file = f"{program}_{opt1}_vs_{opt2}_equivalence_report.txt"
            cmd = [
                "python", self.equivalence_script,
                prefix1.rstrip('_'),            
                prefix2.rstrip('_'),
                "--output", output_file,
                "--timeout", str(self.timeout * 1000)         
            ]
            
            print(f"    执行命令: {' '.join(cmd)}")
            
                     
            result = subprocess.run(
                cmd,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
                timeout=self.timeout + 60             
            )
            
            end_time = time.time()
            execution_time = end_time - start_time
            
                  
            stdout_lines = result.stdout.split('\n')
            stderr_lines = result.stderr.split('\n')
            
                    
            program_equivalent = False
            equivalent_pairs = 0
            partial_pairs = 0
            total_paths_compared = 0
            
            for line in stdout_lines:
                if "程序等价性:" in line:
                    program_equivalent = "✅ 等价" in line
                elif "完全等价路径对:" in line:
                    try:
                        equivalent_pairs = int(line.split(":")[-1].strip())
                    except:
                        pass
                elif "部分等价路径对:" in line:
                    try:
                        partial_pairs = int(line.split(":")[-1].strip())
                    except:
                        pass
                elif "总分析路径对:" in line:
                    try:
                        total_paths_compared = int(line.split(":")[-1].strip())
                    except:
                        pass
            
            analysis_result = {
                'program': program,
                'opt1': opt1,
                'opt2': opt2,
                'success': result.returncode == 0,
                'execution_time': execution_time,
                'program_equivalent': program_equivalent,
                'equivalent_pairs': equivalent_pairs,
                'partial_pairs': partial_pairs,
                'total_paths_compared': total_paths_compared,
                'paths1_count': len(files1),
                'paths2_count': len(files2),
                'return_code': result.returncode,
                'output_file': output_file,
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            if result.returncode == 0:
                equiv_status = "✅ 等价" if program_equivalent else "❌ 不等价"
                print(f"    {equiv_status}: {equivalent_pairs} 完全等价对, {partial_pairs} 部分等价对 (耗时: {execution_time:.1f}s)")
                self.successful_analyses.append(analysis_result)
            else:
                print(f"    ❌ 失败: 返回码 {result.returncode} (耗时: {execution_time:.1f}s)")
                analysis_result['error_output'] = result.stderr[:500]
                self.failed_analyses.append(analysis_result)
            
            self.all_comparisons.append(analysis_result)
            return analysis_result
            
        except subprocess.TimeoutExpired:
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"    ⏰ 超时: {execution_time:.1f}s")
            
            timeout_result = {
                'program': program,
                'opt1': opt1,
                'opt2': opt2,
                'success': False,
                'execution_time': execution_time,
                'program_equivalent': False,
                'equivalent_pairs': 0,
                'partial_pairs': 0,
                'total_paths_compared': 0,
                'paths1_count': len(files1),
                'paths2_count': len(files2),
                'return_code': -1,
                'error': 'timeout',
                'timestamp': datetime.datetime.now().isoformat()
            }
            self.failed_analyses.append(timeout_result)
            self.all_comparisons.append(timeout_result)
            return timeout_result
            
        except Exception as e:
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"    💥 异常: {str(e)} (耗时: {execution_time:.1f}s)")
            
            exception_result = {
                'program': program,
                'opt1': opt1,
                'opt2': opt2,
                'success': False,
                'execution_time': execution_time,
                'program_equivalent': False,
                'equivalent_pairs': 0,
                'partial_pairs': 0,
                'total_paths_compared': 0,
                'paths1_count': len(files1) if 'files1' in locals() else 0,
                'paths2_count': len(files2) if 'files2' in locals() else 0,
                'return_code': -2,
                'error': str(e),
                'timestamp': datetime.datetime.now().isoformat()
            }
            self.failed_analyses.append(exception_result)
            self.all_comparisons.append(exception_result)
            return exception_result
    
    def analyze_program(self, program, optimizations):
        """分析单个程序的所有优化等级组合"""
        print(f"\n📁 分析程序: {program}")
        print("=" * 60)
        
        if len(optimizations) < 2:
            print(f"  ⚠️  只有 {len(optimizations)} 个优化等级，跳过")
            return []
        
        comparison_pairs = self.get_comparison_pairs(optimizations)
        print(f"  优化等级: {', '.join(optimizations)}")
        print(f"  需要比较: {len(comparison_pairs)} 对")
        
        program_results = []
        for i, (opt1, opt2) in enumerate(comparison_pairs, 1):
            print(f"\n  🔄 比较 {i}/{len(comparison_pairs)}: {opt1} vs {opt2}")
            result = self.run_equivalence_analysis(program, opt1, opt2)
            if result:
                program_results.append(result)
        
        self.results[program] = program_results
        return program_results
    
    def run_batch_analysis(self):
        """运行批量分析"""
        print("🚀 开始批量等价性分析")
        print("=" * 60)
        
        self.total_start_time = time.time()
        start_datetime = datetime.datetime.now()
        print(f"开始时间: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
                     
        programs_optimizations = self.discover_programs_and_optimizations()
        
        if not programs_optimizations:
            print("❌ 未找到任何程序路径文件")
            return
        
                               
        if self.target_programs:
            programs_to_analyze = {p: o for p, o in programs_optimizations.items() if p in self.target_programs}
            if not programs_to_analyze:
                print(f"❌ 未找到指定程序或优化等级: {', '.join(self.target_programs)}")
                return
            print(f"📋 发现 {len(programs_to_analyze)} 个程序 (基于 --programs 参数):")
        else:
            programs_to_analyze = programs_optimizations
            print(f"📋 发现 {len(programs_optimizations)} 个程序:")
        
        total_comparisons = 0
        for program, optimizations in programs_to_analyze.items():
            pairs_count = len(list(combinations(optimizations, 2))) if len(optimizations) >= 2 else 0
            total_comparisons += pairs_count
            print(f"  {program}: {optimizations} ({pairs_count} 对比较)")
        
        print(f"总计需要进行 {total_comparisons} 次等价性比较")
        
                
        for i, (program, optimizations) in enumerate(programs_to_analyze.items(), 1):
            print(f"\n🔄 进度: {i}/{len(programs_to_analyze)}")
            self.analyze_program(program, optimizations)
        
        self.total_end_time = time.time()
        total_time = self.total_end_time - self.total_start_time
        end_datetime = datetime.datetime.now()
        
        print(f"\n🎉 批量等价性分析完成!")
        print(f"总耗时: {total_time:.1f} 秒 ({total_time/60:.1f} 分钟)")
        print(f"结束时间: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
              
        self.generate_comprehensive_report()
    
    def preview_analysis(self):
        """预览要进行的分析"""
        print("🔍 预览模式 - 扫描要分析的比较")
        print("=" * 60)
        
                     
        programs_optimizations = self.discover_programs_and_optimizations()
        
        if not programs_optimizations:
            print("❌ 未找到任何程序路径文件")
            return
        
                               
        if self.target_programs:
            programs_to_analyze = {p: o for p, o in programs_optimizations.items() if p in self.target_programs}
            if not programs_to_analyze:
                print(f"❌ 未找到指定程序或优化等级: {', '.join(self.target_programs)}")
                return
            print(f"📋 发现 {len(programs_to_analyze)} 个程序 (基于 --programs 参数):")
        else:
            programs_to_analyze = programs_optimizations
            print(f"📋 发现 {len(programs_optimizations)} 个程序:")
        
        total_comparisons = 0
        total_estimated_time = 0
        
        for program, optimizations in programs_to_analyze.items():
            print(f"\n🔹 {program}: {optimizations}")
            
            if len(optimizations) < 2:
                print(f"    ⚠️  只有 {len(optimizations)} 个优化等级，跳过")
                continue
            
            comparison_pairs = self.get_comparison_pairs(optimizations)
            print(f"    需要比较 {len(comparison_pairs)} 对:")
            
            for opt1, opt2 in comparison_pairs:
                files1 = glob.glob(f"{program}_{opt1}_path_*.txt")
                files2 = glob.glob(f"{program}_{opt2}_path_*.txt")
                
                estimated_time = len(files1) * len(files2) * 0.1                
                total_estimated_time += estimated_time
                
                print(f"      - {opt1} vs {opt2}: {len(files1)} vs {len(files2)} 路径 (预估 {estimated_time:.1f}s)")
            
            total_comparisons += len(comparison_pairs)
        
        print(f"\n📊 总体预览:")
        print(f"  总程序数: {len(programs_optimizations)}")
        print(f"  总比较次数: {total_comparisons}")
        print(f"  预估总时间: {total_estimated_time:.1f} 秒 ({total_estimated_time/60:.1f} 分钟)")
        print(f"  使用超时设置: {self.timeout} 秒/比较")
        print(f"  等价性分析脚本: {self.equivalence_script}")
        
        print(f"\n💡 要开始实际分析，请运行:")
        print(f"   python batch_equivalence_analyzer.py --timeout {self.timeout}")
        
        if total_estimated_time > 1800:          
            print(f"\n⚠️  预估时间较长，建议后台运行:")
            print(f"   nohup python batch_equivalence_analyzer.py --timeout {self.timeout} > equivalence_analysis.log 2>&1 &")
    
    def generate_comprehensive_report(self):
        """生成综合分析报告"""
        report_file = "batch_equivalence_analysis_report.txt"
        
        total_time = self.total_end_time - self.total_start_time if self.total_end_time else 0
        successful_count = len(self.successful_analyses)
        failed_count = len(self.failed_analyses)
        total_count = len(self.all_comparisons)
        
              
        total_equivalent_programs = sum(1 for result in self.successful_analyses if result['program_equivalent'])
        total_equivalent_pairs = sum(result['equivalent_pairs'] for result in self.successful_analyses)
        total_partial_pairs = sum(result['partial_pairs'] for result in self.successful_analyses)
        total_paths_compared = sum(result['total_paths_compared'] for result in self.successful_analyses)
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("批量等价性分析报告\n")
            f.write("=" * 60 + "\n\n")
            
                  
            f.write("📊 总体统计:\n")
            f.write("-" * 30 + "\n")
            f.write(f"开始时间: {datetime.datetime.fromtimestamp(self.total_start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"结束时间: {datetime.datetime.fromtimestamp(self.total_end_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总耗时: {total_time:.1f} 秒 ({total_time/60:.1f} 分钟)\n")
            f.write(f"分析的程序数: {len(self.results)}\n")
            f.write(f"总比较次数: {total_count}\n")
            f.write(f"成功比较: {successful_count}\n")
            f.write(f"失败比较: {failed_count}\n")
            f.write(f"成功率: {successful_count/total_count*100:.1f}%\n")
            f.write(f"完全等价的程序对: {total_equivalent_programs}\n")
            f.write(f"完全等价路径对总数: {total_equivalent_pairs}\n")
            f.write(f"部分等价路径对总数: {total_partial_pairs}\n")
            f.write(f"总路径比较数: {total_paths_compared}\n")
            if successful_count > 0:
                f.write(f"平均比较时间: {sum(r['execution_time'] for r in self.successful_analyses)/successful_count:.1f} 秒\n")
            f.write("\n")
            
                   
            f.write("📋 各程序比较详情:\n")
            f.write("-" * 50 + "\n")
            
            for program, results in self.results.items():
                f.write(f"\n🔹 {program}:\n")
                f.write(f"  比较次数: {len(results)}\n")
                
                successful_in_program = [r for r in results if r['success']]
                failed_in_program = [r for r in results if not r['success']]
                equivalent_in_program = [r for r in successful_in_program if r['program_equivalent']]
                
                f.write(f"  成功: {len(successful_in_program)}\n")
                f.write(f"  失败: {len(failed_in_program)}\n")
                f.write(f"  等价的优化对: {len(equivalent_in_program)}\n")
                
                if successful_in_program:
                    program_time = sum(r['execution_time'] for r in successful_in_program)
                    f.write(f"  总耗时: {program_time:.1f} 秒\n")
                    f.write(f"  平均耗时: {program_time/len(successful_in_program):.1f} 秒/比较\n")
                
                      
                for result in results:
                    status = "✅" if result['success'] else "❌"
                    equiv_status = ""
                    if result['success']:
                        equiv_status = " (✅ 等价)" if result['program_equivalent'] else " (❌ 不等价)"
                    
                    f.write(f"    {status} {result['opt1']} vs {result['opt2']}{equiv_status}: ")
                    if result['success']:
                        f.write(f"{result['equivalent_pairs']} 完全等价对, {result['partial_pairs']} 部分等价对, {result['execution_time']:.1f}s\n")
                    else:
                        error_type = result.get('error', f"返回码{result['return_code']}")
                        f.write(f"失败 ({error_type}), {result['execution_time']:.1f}s\n")
            
                    
            if self.failed_analyses:
                f.write(f"\n❌ 失败分析总结:\n")
                f.write("-" * 30 + "\n")
                
                         
                error_types = {}
                for failure in self.failed_analyses:
                    error_type = failure.get('error', f"返回码{failure['return_code']}")
                    if error_type not in error_types:
                        error_types[error_type] = []
                    error_types[error_type].append(failure)
                
                for error_type, failures in error_types.items():
                    f.write(f"  {error_type}: {len(failures)} 次比较\n")
                    for failure in failures[:3]:          
                        f.write(f"    - {failure['program']} {failure['opt1']} vs {failure['opt2']}\n")
                    if len(failures) > 3:
                        f.write(f"    - ... 还有 {len(failures)-3} 次\n")
            
                   
            if successful_count >= 3:
                f.write(f"\n🏆 等价性排行:\n")
                f.write("-" * 30 + "\n")
                
                             
                program_equiv_counts = {}
                for result in self.successful_analyses:
                    program = result['program']
                    if program not in program_equiv_counts:
                        program_equiv_counts[program] = {'equivalent': 0, 'total': 0}
                    program_equiv_counts[program]['total'] += 1
                    if result['program_equivalent']:
                        program_equiv_counts[program]['equivalent'] += 1
                
                       
                for program, counts in program_equiv_counts.items():
                    counts['rate'] = counts['equivalent'] / counts['total'] * 100
                
                    
                top_programs = sorted(program_equiv_counts.items(), 
                                    key=lambda x: (x[1]['equivalent'], x[1]['rate']), 
                                    reverse=True)[:5]
                
                f.write("等价性TOP5:\n")
                for i, (program, counts) in enumerate(top_programs, 1):
                    f.write(f"  {i}. {program}: {counts['equivalent']}/{counts['total']} ({counts['rate']:.1f}%)\n")
        
        print(f"📄 综合报告已保存到: {report_file}")
        
                     
        json_file = "batch_equivalence_analysis_data.json"
        detailed_data = {
            'summary': {
                'start_time': self.total_start_time,
                'end_time': self.total_end_time,
                'total_time': total_time,
                'successful_count': successful_count,
                'failed_count': failed_count,
                'total_equivalent_programs': total_equivalent_programs,
                'total_equivalent_pairs': total_equivalent_pairs,
                'total_partial_pairs': total_partial_pairs
            },
            'results': self.results,
            'successful_analyses': self.successful_analyses,
            'failed_analyses': self.failed_analyses,
            'all_comparisons': self.all_comparisons
        }
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(detailed_data, f, indent=2, ensure_ascii=False)
        
        print(f"📊 详细数据已保存到: {json_file}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='批量等价性分析工具')
    parser.add_argument('--timeout', type=int, default=120, help='单次等价性分析的超时时间(秒)')
    parser.add_argument('--script', default='semantic_equivalence_analyzer.py', help='等价性分析脚本路径')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，只显示要分析的比较，不实际执行')
    parser.add_argument('--programs', nargs='*', help='指定要分析的程序（如不指定则分析全部）')
    
    args = parser.parse_args()
    
              
    if not args.dry_run and not os.path.exists(args.script):
        print(f"❌ 等价性分析脚本不存在: {args.script}")
        sys.exit(1)
    
             
    analyzer = BatchEquivalenceAnalyzer(
        timeout=args.timeout,
        equivalence_script=args.script
    )
    
            
    if args.programs:
        analyzer.target_programs = set(args.programs)
        print(f"🎯 指定分析程序: {', '.join(args.programs)}")
    else:
        analyzer.target_programs = None
    
               
    if args.dry_run:
        analyzer.preview_analysis()
    else:
                
        analyzer.run_batch_analysis()

if __name__ == "__main__":
    main() 