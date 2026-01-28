                      
"""
批量符号执行脚本 - 专门针对符号化可执行文件
对所有 symbolic_* 可执行文件进行符号执行，生成有意义的约束公式
"""

import os
import subprocess
import time
import datetime
import glob
import sys
from pathlib import Path

class SymbolicBatchExecutor:
    """符号化文件批量执行器"""
    
    def __init__(self, benchmark_dir="benchmarks", timeout=60):
        self.benchmark_dir = benchmark_dir
        self.timeout = timeout
        self.results = {}
        self.failed_executions = []
        self.successful_executions = []
        
              
        self.start_time = None
        self.end_time = None
        self.total_files = 0
        self.processed_files = 0
        
    def find_all_symbolic_executables(self):
        """查找所有符号化可执行文件"""
        print("🔍 正在查找所有符号化可执行文件...")
        
        executables = []
        
                               
        for root, dirs, files in os.walk(self.benchmark_dir):
            for file in files:
                if file.startswith('symbolic_') and not file.endswith(('.c', '.java', '.txt', '.md', '.py')):
                    file_path = os.path.join(root, file)
                                
                    if os.access(file_path, os.X_OK):
                        executables.append(file_path)
        
        print(f"📂 发现 {len(executables)} 个符号化可执行文件")
        return sorted(executables)
    
    def group_executables_by_test(self):
        """按测试组对符号化可执行文件进行分组"""
        executables = self.find_all_symbolic_executables()
        
        grouped = {}
        for exe in executables:
                          
                                                                     
            path_parts = Path(exe).parts
            if len(path_parts) >= 4:
                                     
                benchmark_idx = path_parts.index('benchmarks')
                test_group = '/'.join(path_parts[benchmark_idx+1:-1])         
                filename = path_parts[-1]                                 
                
                        
                if filename.startswith('symbolic_'):
                    version = filename[9:]                     
                else:
                    version = filename
                
                if test_group not in grouped:
                    grouped[test_group] = {}
                grouped[test_group][version] = exe
        
        return grouped
    
    def run_symbolic_execution_single(self, executable_path):
        """对单个符号化可执行文件运行符号执行"""
                
        exe_name = os.path.basename(executable_path)
        exe_dir = os.path.dirname(executable_path)
        output_prefix = os.path.join(exe_dir, f"se_{exe_name}")
        
        print(f"  🔬 分析: {executable_path}")
        print(f"     输出前缀: {output_prefix}")
        
        try:
                      
            cmd = [
                sys.executable, "se_script.py",
                "--binary", executable_path,
                "--timeout", str(self.timeout),
                "--output-prefix", output_prefix
            ]
            
                    
            start_time = time.time()
            
                    
            result = subprocess.run(
                cmd,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
                timeout=self.timeout + 30            
            )
            
                  
            execution_time = time.time() - start_time
            
            if result.returncode == 0:
                    
                print(f"     ✅ 成功 (耗时: {execution_time:.2f}s)")
                
                         
                pattern = f"{output_prefix}_path_*.txt"
                generated_files = glob.glob(pattern)
                
                                   
                meaningful_constraints = 0
                for constraint_file in generated_files:
                    if self.check_constraint_quality(constraint_file):
                        meaningful_constraints += 1
                
                self.successful_executions.append({
                    'executable': executable_path,
                    'output_prefix': output_prefix,
                    'execution_time': execution_time,
                    'generated_files': len(generated_files),
                    'meaningful_constraints': meaningful_constraints,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                })
                
                print(f"     📄 生成约束文件: {len(generated_files)} 个")
                print(f"     🎯 有意义约束: {meaningful_constraints} 个")
                
                return True, len(generated_files), meaningful_constraints, execution_time
            else:
                    
                print(f"     ❌ 失败 (耗时: {execution_time:.2f}s)")
                print(f"        错误: {result.stderr[:200]}...")
                
                self.failed_executions.append({
                    'executable': executable_path,
                    'execution_time': execution_time,
                    'return_code': result.returncode,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                })
                
                return False, 0, 0, execution_time
                
        except subprocess.TimeoutExpired:
            print(f"     ⏰ 超时 (>{self.timeout}s)")
            self.failed_executions.append({
                'executable': executable_path,
                'execution_time': self.timeout,
                'return_code': -1,
                'error': 'timeout'
            })
            return False, 0, 0, self.timeout
            
        except Exception as e:
            print(f"     💥 异常: {str(e)}")
            self.failed_executions.append({
                'executable': executable_path,
                'execution_time': 0,
                'return_code': -2,
                'error': str(e)
            })
            return False, 0, 0, 0
    
    def check_constraint_quality(self, constraint_file):
        """检查约束文件是否包含有意义的约束"""
        try:
            with open(constraint_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
                          
            indicators = [
                'scanf_' in content,             
                'count: 0' not in content,           
                '(assert' in content,           
                'variables\': {}' not in content,         
            ]
            
                             
            return sum(indicators) >= 2
            
        except Exception as e:
            print(f"检查约束文件失败: {e}")
            return False
    
    def run_batch_analysis(self):
        """运行批量分析"""
        print("🚀 开始批量符号执行分析 (符号化版本)")
        print("=" * 60)
        
        self.start_time = time.time()
        start_datetime = datetime.datetime.now()
        print(f"开始时间: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
                
        grouped_executables = self.group_executables_by_test()
        self.total_files = sum(len(versions) for versions in grouped_executables.values())
        
        print(f"测试组数量: {len(grouped_executables)}")
        print(f"符号化可执行文件总数: {self.total_files}")
        print()
        
        total_meaningful_constraints = 0
        
                   
        for test_group, versions in grouped_executables.items():
            print(f"\n📋 测试组: {test_group}")
            print("-" * 40)
            
            test_results = {}
            
            for version, executable_path in versions.items():
                self.processed_files += 1
                progress = (self.processed_files / self.total_files) * 100
                
                print(f"进度: [{self.processed_files}/{self.total_files}] {progress:.1f}%")
                
                success, paths_count, meaningful_count, exec_time = self.run_symbolic_execution_single(executable_path)
                
                test_results[version] = {
                    'success': success,
                    'paths_count': paths_count,
                    'meaningful_constraints': meaningful_count,
                    'execution_time': exec_time,
                    'executable_path': executable_path
                }
                
                total_meaningful_constraints += meaningful_count
            
            self.results[test_group] = test_results
        
        self.end_time = time.time()
        total_time = self.end_time - self.start_time
        
        print("\n" + "=" * 60)
        print("🎉 批量符号执行完成!")
        print(f"总耗时: {total_time:.2f} 秒")
        print(f"平均每个文件: {total_time/self.total_files:.2f} 秒")
        print(f"成功: {len(self.successful_executions)}/{self.total_files}")
        print(f"失败: {len(self.failed_executions)}/{self.total_files}")
        print(f"总有意义约束: {total_meaningful_constraints} 个")
        
        return self.results
    
    def generate_comprehensive_report(self):
        """生成综合分析报告"""
        report_file = "symbolic_execution_fixed_report.txt"
        
        total_meaningful_constraints = sum(exe['meaningful_constraints'] 
                                         for exe in self.successful_executions)
        
        with open(report_file, "w", encoding='utf-8') as f:
            f.write("符号化文件批量符号执行分析报告\n")
            f.write("=" * 60 + "\n\n")
            
                  
            f.write("基本信息:\n")
            f.write("-" * 30 + "\n")
            f.write(f"分析目录: {self.benchmark_dir}\n")
            f.write(f"超时设置: {self.timeout} 秒\n")
            f.write(f"总文件数: {self.total_files}\n")
            if self.start_time and self.end_time:
                f.write(f"开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"结束时间: {datetime.datetime.fromtimestamp(self.end_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"总耗时: {self.end_time - self.start_time:.2f} 秒\n\n")
            
                  
            f.write("执行统计:\n")
            f.write("-" * 30 + "\n")
            f.write(f"成功执行: {len(self.successful_executions)} 个\n")
            f.write(f"失败执行: {len(self.failed_executions)} 个\n")
            f.write(f"成功率: {len(self.successful_executions)/self.total_files*100:.1f}%\n")
            f.write(f"总有意义约束: {total_meaningful_constraints} 个\n\n")
            
                    
            if self.successful_executions:
                f.write("成功案例详情:\n")
                f.write("-" * 30 + "\n")
                total_paths = 0
                total_time = 0
                
                for exe_info in self.successful_executions:
                    f.write(f"{exe_info['executable']}:\n")
                    f.write(f"  生成路径数: {exe_info['generated_files']}\n")
                    f.write(f"  有意义约束: {exe_info['meaningful_constraints']}\n")
                    f.write(f"  执行时间: {exe_info['execution_time']:.2f} 秒\n")
                    f.write(f"  输出前缀: {exe_info['output_prefix']}\n\n")
                    
                    total_paths += exe_info['generated_files']
                    total_time += exe_info['execution_time']
                
                f.write(f"总计生成路径数: {total_paths}\n")
                f.write(f"平均路径数/文件: {total_paths/len(self.successful_executions):.1f}\n")
                f.write(f"平均执行时间: {total_time/len(self.successful_executions):.2f} 秒\n")
                f.write(f"约束质量率: {total_meaningful_constraints/total_paths*100:.1f}%\n\n")
            
                     
            f.write("测试组结果:\n")
            f.write("-" * 30 + "\n")
            
            for test_group, versions in self.results.items():
                f.write(f"\n{test_group}:\n")
                for version, result in versions.items():
                    status = "✅" if result['success'] else "❌"
                    f.write(f"  {version}: {status} ")
                    f.write(f"路径数={result['paths_count']} ")
                    f.write(f"有效约束={result['meaningful_constraints']} ")
                    f.write(f"时间={result['execution_time']:.2f}s\n")
            
            f.write("\n生成的约束文件:\n")
            f.write("-" * 30 + "\n")
            f.write("每个成功分析的符号化文件都生成了以下文件:\n")
            f.write("- se_symbolic_{exe_name}_path_*.txt  - 路径约束文件\n")
            f.write("- se_symbolic_{exe_name}_timing_report.txt  - 时间统计报告\n")
            f.write("\n查看有意义约束文件示例:\n")
            f.write("find . -name 'se_symbolic_*_path_*.txt' | head -5\n")
            
        print(f"📄 综合报告已保存到: {report_file}")
    
    def get_statistics(self):
        """获取统计信息"""
        if not self.start_time or not self.end_time:
            return None
            
        total_paths = sum(exe['generated_files'] for exe in self.successful_executions)
        total_meaningful = sum(exe['meaningful_constraints'] for exe in self.successful_executions)
        
        return {
            'total_files': self.total_files,
            'successful': len(self.successful_executions),
            'failed': len(self.failed_executions),
            'success_rate': len(self.successful_executions) / self.total_files * 100,
            'total_time': self.end_time - self.start_time,
            'avg_time_per_file': (self.end_time - self.start_time) / self.total_files,
            'total_paths_generated': total_paths,
            'total_meaningful_constraints': total_meaningful,
            'constraint_quality_rate': total_meaningful / total_paths * 100 if total_paths > 0 else 0,
            'avg_paths_per_file': total_paths / max(1, len(self.successful_executions))
        }

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='符号化文件批量符号执行分析工具')
    parser.add_argument('--benchmark-dir', default='benchmarks', help='benchmark目录路径')
    parser.add_argument('--timeout', type=int, default=60, help='单个文件的超时时间(秒)')
    
    args = parser.parse_args()
    
          
    if not os.path.exists('se_script.py'):
        print("❌ 找不到 se_script.py，请确保文件存在")
        return 1
    
    if not os.path.exists(args.benchmark_dir):
        print(f"❌ 找不到benchmark目录: {args.benchmark_dir}")
        return 1
    
             
    executor = SymbolicBatchExecutor(
        benchmark_dir=args.benchmark_dir,
        timeout=args.timeout
    )
    
    try:
                
        results = executor.run_batch_analysis()
        
              
        executor.generate_comprehensive_report()
        
                
        stats = executor.get_statistics()
        if stats:
            print("\n📊 最终统计:")
            print(f"  总文件数: {stats['total_files']}")
            print(f"  成功率: {stats['success_rate']:.1f}%")
            print(f"  总路径数: {stats['total_paths_generated']}")
            print(f"  有意义约束数: {stats['total_meaningful_constraints']}")
            print(f"  约束质量率: {stats['constraint_quality_rate']:.1f}%")
            print(f"  平均路径数: {stats['avg_paths_per_file']:.1f}")
            print(f"  总耗时: {stats['total_time']:.2f} 秒")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n⛔ 用户中断了批量分析")
        return 1
    except Exception as e:
        print(f"\n💥 批量分析过程中发生异常: {e}")
        return 1

if __name__ == "__main__":
    exit(main()) 