                      
"""
批量生成所有benchmark符号化程序的约束路径
对所有symbolic_*可执行文件进行符号执行
"""

import os
import subprocess
import sys
import time
import glob
from pathlib import Path

class ComprehensiveConstraintGenerator:
    def __init__(self, base_dir="/root/ardiff/symbolic_analysis"):
        self.base_dir = Path(base_dir)
        self.se_script = self.base_dir / "se_script.py"
        self.successful_executions = 0
        self.failed_executions = 0
        self.meaningful_constraints = 0
        self.total_constraint_files = 0
        self.execution_log = []
        
    def find_all_symbolic_executables(self):
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
            print(f"🔍 正在分析: {os.path.relpath(executable_path, self.base_dir)}")
            
                              
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
                
                           
                constraint_info = self.analyze_generated_constraints(executable_path, result.stdout)
                
                log_entry = {
                    'executable': executable_path,
                    'status': 'success',
                    'execution_time': execution_time,
                    'constraint_info': constraint_info,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }
                
                if constraint_info['meaningful_count'] > 0:
                    self.meaningful_constraints += constraint_info['meaningful_count']
                    print(f"  ✅ 成功生成 {constraint_info['total_files']} 个约束文件 ({constraint_info['meaningful_count']} 个有意义)")
                else:
                    print(f"  ⚠️  生成 {constraint_info['total_files']} 个约束文件 (均为空约束)")
                    
            else:
                self.failed_executions += 1
                log_entry = {
                    'executable': executable_path,
                    'status': 'failed',
                    'execution_time': execution_time,
                    'constraint_info': {'total_files': 0, 'meaningful_count': 0},
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'returncode': result.returncode
                }
                print(f"  ❌ 执行失败 (返回码: {result.returncode})")
                if result.stderr:
                    print(f"     错误信息: {result.stderr[:100]}...")
            
            self.execution_log.append(log_entry)
            return True
            
        except subprocess.TimeoutExpired:
            self.failed_executions += 1
            print(f"  ⏱️  执行超时 (>120秒)")
            self.execution_log.append({
                'executable': executable_path,
                'status': 'timeout',
                'execution_time': 120,
                'constraint_info': {'total_files': 0, 'meaningful_count': 0}
            })
            return False
            
        except Exception as e:
            self.failed_executions += 1
            print(f"  💥 执行异常: {str(e)}")
            self.execution_log.append({
                'executable': executable_path,
                'status': 'error',
                'execution_time': 0,
                'constraint_info': {'total_files': 0, 'meaningful_count': 0},
                'error': str(e)
            })
            return False

    def analyze_generated_constraints(self, executable_path, stdout):
        """分析生成的约束文件"""
        exec_dir = os.path.dirname(executable_path)
        exec_name = os.path.basename(executable_path)
        
                   
        constraint_files = glob.glob(os.path.join(exec_dir, f"{exec_name}_path_*.txt"))
        
        meaningful_count = 0
        total_files = len(constraint_files)
        
        for constraint_file in constraint_files:
            try:
                with open(constraint_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                         
                has_constraints = '(assert' in content
                has_variables = 'scanf_' in content or 'mem_' in content
                
                if has_constraints and has_variables:
                    meaningful_count += 1
                    
            except Exception as e:
                print(f"    警告: 读取约束文件失败: {constraint_file}, 错误: {e}")
                continue
        
        self.total_constraint_files += total_files
        
        return {
            'total_files': total_files,
            'meaningful_count': meaningful_count,
            'constraint_files': constraint_files
        }

    def generate_comprehensive_report(self):
        """生成综合报告"""
        total_executables = self.successful_executions + self.failed_executions
        
        if total_executables == 0:
            print("❌ 没有找到可执行文件进行分析")
            return
            
        success_rate = (self.successful_executions / total_executables) * 100
        
                      
        meaningful_tests = []
        for log_entry in self.execution_log:
            if log_entry.get('constraint_info', {}).get('meaningful_count', 0) > 0:
                test_name = self.extract_test_name(log_entry['executable'])
                meaningful_tests.append({
                    'test': test_name,
                    'executable': os.path.basename(log_entry['executable']),
                    'constraint_count': log_entry['constraint_info']['meaningful_count']
                })
        
        report = f"""
🎯 所有Benchmark符号化程序约束生成完成报告
{'='*70}

📊 执行统计:
  • 总符号化程序数: {total_executables}
  • 成功执行数: {self.successful_executions}
  • 失败执行数: {self.failed_executions}
  • 成功率: {success_rate:.1f}%

🔍 约束生成统计:
  • 总约束文件数: {self.total_constraint_files}
  • 有意义约束文件数: {self.meaningful_constraints}
  • 空约束文件数: {self.total_constraint_files - self.meaningful_constraints}
  • 约束质量率: {(self.meaningful_constraints/max(1, self.total_constraint_files))*100:.1f}%

💡 有意义约束的测试用例 ({len(meaningful_tests)}个):
"""
        
        if meaningful_tests:
            for i, test in enumerate(meaningful_tests, 1):
                report += f"  {i}. {test['test']}/{test['executable']} - {test['constraint_count']}个约束\n"
        else:
            report += "  ❌ 暂无生成有意义约束的测试用例\n"
            
        report += f"""
📁 约束文件查看方法:
  • 查看所有约束文件: find benchmarks/ -name "*_path_*.txt"
  • 查看有意义约束: find benchmarks/ -name "*_path_*.txt" -exec grep -l "(assert" {{}} \\;
  • 统计约束类型: grep -h "(assert" benchmarks/**/*_path_*.txt | sort | uniq -c

🎯 使用建议:
"""
        
        if self.meaningful_constraints > 0:
            report += f"""  ✅ 您现在拥有 {self.meaningful_constraints} 个有效的SMT约束文件！
  📖 使用方法:
    1. 查看约束内容: cat benchmarks/路径/symbolic_*_path_*.txt
    2. 使用Z3求解: z3 约束文件名.txt
    3. SMT-LIB格式可直接用于其他SMT求解器
"""
        else:
            report += f"""  ⚠️  当前生成的约束多为空约束，可能原因:
    1. 程序逻辑过于简单，缺少分支条件
    2. 符号变量未在程序中实际使用
    3. 需要更复杂的输入来触发不同路径
"""
        
        report += f"""
⏱️  生成完成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
📄 约束文件位置: benchmarks/**/symbolic_*_path_*.txt
"""
        
              
        report_file = self.base_dir / "all_constraints_generation_report.txt"
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
        return os.path.dirname(executable_path)

    def run_all_constraint_generation(self):
        """运行所有符号化程序的约束生成"""
        print("🚀 开始为所有benchmark符号化程序生成约束路径...")
        print("🎯 目标: 对所有symbolic_*可执行文件进行符号执行\n")
        
                      
        executables = self.find_all_symbolic_executables()
        
        if not executables:
            print("❌ 未找到任何符号化可执行文件")
            return False
            
        print(f"📋 找到 {len(executables)} 个符号化可执行文件")
        print("🔧 开始逐个进行符号执行...\n")
        
                  
        for i, executable in enumerate(executables, 1):
            print(f"[{i}/{len(executables)}] ", end="")
            self.run_symbolic_execution(executable)
            
                
        print("\n" + "="*70)
        print("🎉 所有benchmark符号化程序约束生成完成!")
        self.generate_comprehensive_report()
        
        return True

if __name__ == "__main__":
    generator = ComprehensiveConstraintGenerator()
    generator.run_all_constraint_generation() 