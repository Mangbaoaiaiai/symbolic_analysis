                      
"""
批量符号执行脚本
使用增强的 se_script.py 对所有 benchmark 进行符号执行分析

功能：
1. 自动发现所有 benchmark_temp_* 目录
2. 对每个目录中的二进制文件运行符号执行
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
from pathlib import Path
import argparse

class BatchSymbolicExecutor:
    """批量符号执行管理器"""
    
    def __init__(self, root_dir=".", timeout=60, se_script="se_script.py"):
        self.root_dir = root_dir
        self.timeout = timeout
        self.se_script = se_script
        self.results = {}
        self.total_start_time = None
        self.total_end_time = None
        self.failed_analyses = []
        self.successful_analyses = []
        
    def find_benchmark_directories(self):
        """查找所有 benchmark 目录"""
        pattern = os.path.join(self.root_dir, "benchmark_temp_*")
        benchmark_dirs = glob.glob(pattern)
        benchmark_dirs = [d for d in benchmark_dirs if os.path.isdir(d)]
        return sorted(benchmark_dirs)
    
    def find_binary_files(self, benchmark_dir):
        """在指定目录中查找二进制文件"""
                       
        patterns = [
            "*_O0", "*_O1", "*_O2", "*_O3",
            "*_Ofast", "*_Os", "*_Oz"
        ]
        
        binary_files = []
        for pattern in patterns:
            matches = glob.glob(os.path.join(benchmark_dir, pattern))
                            
            matches = [f for f in matches if not f.endswith(('.c', '.h', '.txt', '.md'))]
            binary_files.extend(matches)
        
                  
        executable_files = []
        for file_path in binary_files:
            if os.access(file_path, os.X_OK) or self.is_binary_file(file_path):
                executable_files.append(file_path)
                
        return sorted(executable_files)
    
    def is_binary_file(self, file_path):
        """检查文件是否为二进制文件"""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(1024)
                             
                if chunk.startswith(b'\x7fELF'):
                    return True
                              
                text_ratio = sum(1 for byte in chunk if 32 <= byte <= 126) / len(chunk)
                return text_ratio < 0.7
        except:
            return False
    
    def run_symbolic_execution(self, binary_path, output_dir=None):
        """对单个二进制文件运行符号执行"""
        binary_name = os.path.basename(binary_path)
        print(f"  正在分析: {binary_name}")
        
        start_time = time.time()
        
        try:
                           
            abs_binary_path = os.path.abspath(binary_path)
            abs_se_script = os.path.abspath(self.se_script)
            
            cmd = [
                "python", abs_se_script,
                "--binary", abs_binary_path,
                "--timeout", str(self.timeout)
            ]
            
            print(f"    执行命令: {' '.join(cmd)}")
            
                                             
            result = subprocess.run(
                cmd,
                cwd=os.getcwd(),            
                capture_output=True,
                text=True,
                timeout=self.timeout + 30             
            )
            
            end_time = time.time()
            execution_time = end_time - start_time
            
                  
            stdout_lines = result.stdout.split('\n')
            stderr_lines = result.stderr.split('\n')
            
                    
            paths_found = 0
            exploration_time = 0
            setup_time = 0
            analysis_time = 0
            
            for line in stdout_lines:
                if "分析完成！共发现" in line and "条路径" in line:
                    try:
                        paths_found = int(line.split("共发现")[1].split("条路径")[0].strip())
                    except:
                        pass
                elif "路径探索:" in line and "秒" in line:
                    try:
                        exploration_time = float(line.split("路径探索:")[1].split("秒")[0].strip())
                    except:
                        pass
                elif "项目设置:" in line and "秒" in line:
                    try:
                        setup_time = float(line.split("项目设置:")[1].split("秒")[0].strip())
                    except:
                        pass
                elif "状态分析:" in line and "秒" in line:
                    try:
                        analysis_time = float(line.split("状态分析:")[1].split("秒")[0].strip())
                    except:
                        pass
            
            analysis_result = {
                'binary_path': binary_path,
                'binary_name': binary_name,
                'success': result.returncode == 0,
                'execution_time': execution_time,
                'paths_found': paths_found,
                'setup_time': setup_time,
                'exploration_time': exploration_time,
                'analysis_time': analysis_time,
                'return_code': result.returncode,
                'stdout_lines': len(stdout_lines),
                'stderr_lines': len(stderr_lines),
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            if result.returncode == 0:
                print(f"    ✅ 成功: 发现 {paths_found} 条路径 (耗时: {execution_time:.1f}s)")
                self.successful_analyses.append(analysis_result)
            else:
                print(f"    ❌ 失败: 返回码 {result.returncode} (耗时: {execution_time:.1f}s)")
                analysis_result['error_output'] = result.stderr[:500]                  
                self.failed_analyses.append(analysis_result)
            
            return analysis_result
            
        except subprocess.TimeoutExpired:
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"    ⏰ 超时: {execution_time:.1f}s")
            
            timeout_result = {
                'binary_path': binary_path,
                'binary_name': binary_name,
                'success': False,
                'execution_time': execution_time,
                'paths_found': 0,
                'return_code': -1,
                'error': 'timeout',
                'timestamp': datetime.datetime.now().isoformat()
            }
            self.failed_analyses.append(timeout_result)
            return timeout_result
            
        except Exception as e:
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"    💥 异常: {str(e)} (耗时: {execution_time:.1f}s)")
            
            exception_result = {
                'binary_path': binary_path,
                'binary_name': binary_name,
                'success': False,
                'execution_time': execution_time,
                'paths_found': 0,
                'return_code': -2,
                'error': str(e),
                'timestamp': datetime.datetime.now().isoformat()
            }
            self.failed_analyses.append(exception_result)
            return exception_result
    
    def analyze_benchmark(self, benchmark_dir):
        """分析单个 benchmark 目录"""
        benchmark_name = os.path.basename(benchmark_dir)
        print(f"\n📁 分析 benchmark: {benchmark_name}")
        print("=" * 60)
        
                 
        binary_files = self.find_binary_files(benchmark_dir)
        
        if not binary_files:
            print(f"  ⚠️  未找到二进制文件")
            return []
        
        print(f"  发现 {len(binary_files)} 个二进制文件:")
        for binary in binary_files:
            print(f"    - {os.path.basename(binary)}")
        
                   
        benchmark_results = []
        for binary_path in binary_files:
            result = self.run_symbolic_execution(binary_path)
            benchmark_results.append(result)
        
        self.results[benchmark_name] = benchmark_results
        return benchmark_results
    
    def preview_analysis(self):
        """预览要分析的文件，不实际执行"""
        print("🔍 预览模式 - 扫描要分析的文件")
        print("=" * 60)
        
                           
        benchmark_dirs = self.find_benchmark_directories()
        
        if not benchmark_dirs:
            print("❌ 未找到任何 benchmark 目录")
            return
        
        print(f"📋 发现 {len(benchmark_dirs)} 个 benchmark 目录:")
        
        total_files = 0
        total_estimated_time = 0
        
        for i, benchmark_dir in enumerate(benchmark_dirs, 1):
            benchmark_name = os.path.basename(benchmark_dir)
            print(f"\n{i}. 📁 {benchmark_name}")
            
                     
            binary_files = self.find_binary_files(benchmark_dir)
            
            if not binary_files:
                print(f"    ⚠️  未找到二进制文件")
                continue
            
            print(f"    发现 {len(binary_files)} 个二进制文件:")
            for binary in binary_files:
                binary_name = os.path.basename(binary)
                file_size = os.path.getsize(binary)
                print(f"      - {binary_name} ({file_size/1024:.1f} KB)")
            
            total_files += len(binary_files)
                            
            estimated_time = len(binary_files) * 30
            total_estimated_time += estimated_time
            print(f"    预估分析时间: {estimated_time/60:.1f} 分钟")
        
        print(f"\n📊 总体预览:")
        print(f"  总benchmark数: {len(benchmark_dirs)}")
        print(f"  总二进制文件数: {total_files}")
        print(f"  预估总时间: {total_estimated_time/60:.1f} 分钟 ({total_estimated_time/3600:.1f} 小时)")
        print(f"  使用超时设置: {self.timeout} 秒/文件")
        print(f"  符号执行脚本: {self.se_script}")
        
        print(f"\n💡 要开始实际分析，请运行:")
        print(f"   python batch_symbolic_execution.py --timeout {self.timeout}")
        
        if total_estimated_time > 3600:         
            print(f"\n⚠️  预估时间较长，建议后台运行:")
            print(f"   nohup python batch_symbolic_execution.py --timeout {self.timeout} > batch_analysis.log 2>&1 &")
    
    def run_batch_analysis(self):
        """运行批量分析"""
        print("🚀 开始批量符号执行分析")
        print("=" * 60)
        
        self.total_start_time = time.time()
        start_datetime = datetime.datetime.now()
        print(f"开始时间: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
                           
        benchmark_dirs = self.find_benchmark_directories()
        
        if not benchmark_dirs:
            print("❌ 未找到任何 benchmark 目录")
            return
        
        print(f"📋 发现 {len(benchmark_dirs)} 个 benchmark 目录:")
        for i, benchmark_dir in enumerate(benchmark_dirs, 1):
            print(f"  {i}. {os.path.basename(benchmark_dir)}")
        
                        
        for i, benchmark_dir in enumerate(benchmark_dirs, 1):
            print(f"\n🔄 进度: {i}/{len(benchmark_dirs)}")
            self.analyze_benchmark(benchmark_dir)
        
        self.total_end_time = time.time()
        total_time = self.total_end_time - self.total_start_time
        end_datetime = datetime.datetime.now()
        
        print(f"\n🎉 批量分析完成!")
        print(f"总耗时: {total_time:.1f} 秒 ({total_time/60:.1f} 分钟)")
        print(f"结束时间: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
              
        self.generate_comprehensive_report()
    
    def generate_comprehensive_report(self):
        """生成综合分析报告"""
        report_file = "batch_symbolic_execution_report.txt"
        
        total_time = self.total_end_time - self.total_start_time if self.total_end_time else 0
        successful_count = len(self.successful_analyses)
        failed_count = len(self.failed_analyses)
        total_count = successful_count + failed_count
        
              
        total_paths = sum(result['paths_found'] for result in self.successful_analyses)
        total_exploration_time = sum(result.get('exploration_time', 0) for result in self.successful_analyses)
        total_setup_time = sum(result.get('setup_time', 0) for result in self.successful_analyses)
        total_analysis_time = sum(result.get('analysis_time', 0) for result in self.successful_analyses)
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("批量符号执行分析报告\n")
            f.write("=" * 60 + "\n\n")
            
                  
            f.write("📊 总体统计:\n")
            f.write("-" * 30 + "\n")
            f.write(f"开始时间: {datetime.datetime.fromtimestamp(self.total_start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"结束时间: {datetime.datetime.fromtimestamp(self.total_end_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总耗时: {total_time:.1f} 秒 ({total_time/60:.1f} 分钟)\n")
            f.write(f"分析的benchmark数: {len(self.results)}\n")
            f.write(f"分析的二进制文件数: {total_count}\n")
            f.write(f"成功分析: {successful_count}\n")
            f.write(f"失败分析: {failed_count}\n")
            f.write(f"成功率: {successful_count/total_count*100:.1f}%\n")
            f.write(f"发现的总路径数: {total_paths}\n")
            if successful_count > 0:
                f.write(f"平均每个程序路径数: {total_paths/successful_count:.1f}\n")
            f.write(f"总探索时间: {total_exploration_time:.1f} 秒\n")
            f.write(f"总设置时间: {total_setup_time:.1f} 秒\n")
            f.write(f"总分析时间: {total_analysis_time:.1f} 秒\n")
            if total_exploration_time > 0:
                f.write(f"总体探索效率: {total_paths/total_exploration_time:.2f} 路径/秒\n")
            f.write("\n")
            
                          
            f.write("📋 各Benchmark分析详情:\n")
            f.write("-" * 50 + "\n")
            
            for benchmark_name, results in self.results.items():
                f.write(f"\n🔹 {benchmark_name}:\n")
                f.write(f"  二进制文件数: {len(results)}\n")
                
                successful_in_benchmark = [r for r in results if r['success']]
                failed_in_benchmark = [r for r in results if not r['success']]
                
                f.write(f"  成功: {len(successful_in_benchmark)}\n")
                f.write(f"  失败: {len(failed_in_benchmark)}\n")
                
                if successful_in_benchmark:
                    benchmark_paths = sum(r['paths_found'] for r in successful_in_benchmark)
                    benchmark_time = sum(r['execution_time'] for r in successful_in_benchmark)
                    f.write(f"  总路径数: {benchmark_paths}\n")
                    f.write(f"  总耗时: {benchmark_time:.1f} 秒\n")
                    f.write(f"  平均耗时: {benchmark_time/len(successful_in_benchmark):.1f} 秒/程序\n")
                
                      
                for result in results:
                    status = "✅" if result['success'] else "❌"
                    f.write(f"    {status} {result['binary_name']}: ")
                    if result['success']:
                        f.write(f"{result['paths_found']} 路径, {result['execution_time']:.1f}s\n")
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
                    f.write(f"  {error_type}: {len(failures)} 个文件\n")
                    for failure in failures[:3]:          
                        f.write(f"    - {failure['binary_name']}\n")
                    if len(failures) > 3:
                        f.write(f"    - ... 还有 {len(failures)-3} 个\n")
            
                  
            if successful_count >= 3:
                f.write(f"\n🏆 性能排行:\n")
                f.write("-" * 30 + "\n")
                
                        
                top_paths = sorted(self.successful_analyses, key=lambda x: x['paths_found'], reverse=True)[:5]
                f.write("路径数TOP5:\n")
                for i, result in enumerate(top_paths, 1):
                    f.write(f"  {i}. {result['binary_name']}: {result['paths_found']} 路径\n")
                
                       
                speed_analyses = [r for r in self.successful_analyses if r.get('exploration_time', 0) > 0]
                if speed_analyses:
                    top_speed = sorted(speed_analyses, 
                                     key=lambda x: x['paths_found']/max(x.get('exploration_time', 1), 0.1), 
                                     reverse=True)[:5]
                    f.write("\n探索效率TOP5:\n")
                    for i, result in enumerate(top_speed, 1):
                        efficiency = result['paths_found']/max(result.get('exploration_time', 1), 0.1)
                        f.write(f"  {i}. {result['binary_name']}: {efficiency:.2f} 路径/秒\n")
        
        print(f"📄 综合报告已保存到: {report_file}")
        
                     
        json_file = "batch_symbolic_execution_data.json"
        detailed_data = {
            'summary': {
                'start_time': self.total_start_time,
                'end_time': self.total_end_time,
                'total_time': total_time,
                'successful_count': successful_count,
                'failed_count': failed_count,
                'total_paths': total_paths
            },
            'results': self.results,
            'successful_analyses': self.successful_analyses,
            'failed_analyses': self.failed_analyses
        }
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(detailed_data, f, indent=2, ensure_ascii=False)
        
        print(f"📊 详细数据已保存到: {json_file}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='批量符号执行分析工具')
    parser.add_argument('--root-dir', default='.', help='benchmark根目录路径')
    parser.add_argument('--timeout', type=int, default=60, help='单个分析的超时时间(秒)')
    parser.add_argument('--se-script', default='se_script.py', help='符号执行脚本路径')
    parser.add_argument('--benchmarks', nargs='*', help='指定要分析的benchmark（如不指定则分析全部）')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，只显示要分析的文件，不实际执行')
    
    args = parser.parse_args()
    
                     
    if not args.dry_run and not os.path.exists(args.se_script):
        print(f"❌ 符号执行脚本不存在: {args.se_script}")
        sys.exit(1)
    
             
    executor = BatchSymbolicExecutor(
        root_dir=args.root_dir,
        timeout=args.timeout,
        se_script=args.se_script
    )
    
                             
    if args.benchmarks:
        print(f"🎯 指定分析 benchmark: {', '.join(args.benchmarks)}")
                    
    
               
    if args.dry_run:
        executor.preview_analysis()
    else:
                
        executor.run_batch_analysis()

if __name__ == "__main__":
    main() 