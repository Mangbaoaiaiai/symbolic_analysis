                      
"""
批量符号执行脚本 - 对所有符号化程序进行符号执行获取约束公式
专门针对symbolic_*可执行文件进行符号执行
"""

import os
import subprocess
import sys
import time
from pathlib import Path
import glob
import re

class BatchSymbolicExecutor:
    def __init__(self, base_dir="/root/ardiff/symbolic_analysis"):
        self.base_dir = Path(base_dir)
        self.se_script = self.base_dir / "se_script.py"
        self.successful_executions = 0
        self.failed_executions = 0
        self.meaningful_constraints = 0
        self.execution_log = []
        
    def find_symbolic_executables(self):
        """查找所有符号化可执行文件"""
        pattern = str(self.base_dir / "benchmarks" / "**" / "symbolic_*")
        executables = []
        
        for file_path in glob.glob(pattern, recursive=True):
            if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                                 
                if not file_path.endswith('.c'):
                    executables.append(file_path)
        
        return sorted(executables)
    
    def run_symbolic_execution(self, executable_path):
        """对单个可执行文件运行符号执行"""
        try:
            print(f"🔍 正在分析: {executable_path}")
            
                              
            cmd = [sys.executable, str(self.se_script), "--binary", executable_path]
            
                    
            start_time = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120         
            )
            end_time = time.time()
            
            execution_time = end_time - start_time
            
            if result.returncode == 0:
                self.successful_executions += 1
                constraint_quality = self.check_constraint_quality(executable_path)
                
                log_entry = {
                    'executable': executable_path,
                    'status': 'success',
                    'execution_time': execution_time,
                    'constraint_quality': constraint_quality,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }
                
                if constraint_quality:
                    self.meaningful_constraints += 1
                    print(f"  ✅ 成功生成有意义约束 (耗时: {execution_time:.2f}秒)")
                else:
                    print(f"  ⚠️  生成空约束 (耗时: {execution_time:.2f}秒)")
                    
            else:
                self.failed_executions += 1
                log_entry = {
                    'executable': executable_path,
                    'status': 'failed',
                    'execution_time': execution_time,
                    'constraint_quality': False,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'returncode': result.returncode
                }
                print(f"  ❌ 执行失败 (返回码: {result.returncode}, 耗时: {execution_time:.2f}秒)")
                if result.stderr:
                    print(f"     错误信息: {result.stderr[:200]}...")
            
            self.execution_log.append(log_entry)
            return True
            
        except subprocess.TimeoutExpired:
            self.failed_executions += 1
            print(f"  ⏱️  执行超时 (>120秒)")
            self.execution_log.append({
                'executable': executable_path,
                'status': 'timeout',
                'execution_time': 120,
                'constraint_quality': False
            })
            return False
            
        except Exception as e:
            self.failed_executions += 1
            print(f"  💥 执行异常: {str(e)}")
            self.execution_log.append({
                'executable': executable_path,
                'status': 'error',
                'execution_time': 0,
                'constraint_quality': False,
                'error': str(e)
            })
            return False

    def check_constraint_quality(self, executable_path):
        """检查生成的约束文件质量"""
        exec_dir = os.path.dirname(executable_path)
        exec_name = os.path.basename(executable_path)
        
                   
        constraint_files = glob.glob(os.path.join(exec_dir, f"se_{exec_name}_path_*.txt"))
        
        if not constraint_files:
            return False
            
        for constraint_file in constraint_files:
            try:
                with open(constraint_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                            
                indicators = [
                    'scanf_' in content,             
                    'count: 0' not in content,           
                    '(assert' in content,           
                    'variables\': {}' not in content,         
                ]
                
                               
                if sum(indicators) >= 2:
                    return True
                    
            except Exception as e:
                print(f"读取约束文件失败: {constraint_file}, 错误: {e}")
                continue
                
        return False

    def generate_report(self):
        """生成执行报告"""
        total_executables = self.successful_executions + self.failed_executions
        
        if total_executables == 0:
            print("❌ 没有找到可执行文件进行分析")
            return
            
        success_rate = (self.successful_executions / total_executables) * 100
        constraint_quality_rate = (self.meaningful_constraints / max(self.successful_executions, 1)) * 100
        
        report = f"""
🎯 批量符号执行完成报告
{'='*50}

📊 执行统计:
  • 总可执行文件数: {total_executables}
  • 成功执行数: {self.successful_executions}
  • 失败执行数: {self.failed_executions}
  • 成功率: {success_rate:.1f}%

🔍 约束质量分析:
  • 有意义约束数: {self.meaningful_constraints}
  • 空约束数: {self.successful_executions - self.meaningful_constraints}
  • 约束质量率: {constraint_quality_rate:.1f}%

📁 结果文件位置:
  • 约束文件: 各测试目录下的 se_symbolic_*_path_*.txt
  • 时间报告: 各测试目录下的 se_symbolic_*_timing_report.txt

💡 有意义约束的测试用例:
"""
        
                      
        meaningful_tests = []
        for log_entry in self.execution_log:
            if log_entry.get('constraint_quality', False):
                test_name = self.extract_test_name(log_entry['executable'])
                meaningful_tests.append(test_name)
                
        if meaningful_tests:
            for test in meaningful_tests:
                report += f"  ✅ {test}\n"
        else:
            report += "  ❌ 暂无生成有意义约束的测试用例\n"
            
        report += f"\n⏱️  执行完成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        
              
        report_file = self.base_dir / "batch_symbolic_execution_final_report.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
            
        print(report)
        print(f"\n📄 详细报告已保存至: {report_file}")
        
        return report

    def extract_test_name(self, executable_path):
        """从可执行文件路径提取测试名称"""
        path_parts = Path(executable_path).parts
        if 'benchmarks' in path_parts:
            idx = path_parts.index('benchmarks')
            if len(path_parts) > idx + 3:
                return '/'.join(path_parts[idx+1:idx+4])                   
        return os.path.basename(executable_path)

    def run_all(self):
        """运行所有符号化程序的符号执行"""
        print("🚀 开始批量符号执行任务...")
        print("🎯 目标: 对所有符号化程序生成约束公式\n")
        
                      
        executables = self.find_symbolic_executables()
        
        if not executables:
            print("❌ 未找到任何符号化可执行文件")
            return False
            
        print(f"📋 找到 {len(executables)} 个符号化可执行文件")
        print("🔧 开始逐个进行符号执行...\n")
        
                  
        for i, executable in enumerate(executables, 1):
            print(f"[{i}/{len(executables)}] ", end="")
            self.run_symbolic_execution(executable)
            
                
        print("\n" + "="*60)
        print("🎉 批量符号执行任务完成!")
        self.generate_report()
        
        return True

if __name__ == "__main__":
    executor = BatchSymbolicExecutor()
    executor.run_all() 