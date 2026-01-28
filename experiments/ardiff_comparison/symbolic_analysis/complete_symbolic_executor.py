                      
"""
完整符号执行器 - 为所有符号化程序生成约束公式
确保每个程序都能生成像 se_symbolic_newV_path_1.txt 这样的约束文件
"""

import os
import subprocess
import sys
import glob
from pathlib import Path
import time

class CompleteSymbolicExecutor:
    def __init__(self):
        self.base_dir = "/root/ardiff/symbolic_analysis"
        self.se_script = os.path.join(self.base_dir, "se_script.py")
        self.results = {
            'total_files': 0,
            'success_execution': 0,
            'meaningful_constraints': 0,
            'failed_execution': 0,
            'empty_constraints': 0,
            'detailed_results': []
        }
        
    def find_all_symbolic_executables(self):
        """查找所有符号化可执行文件"""
        pattern = os.path.join(self.base_dir, "benchmarks", "**", "symbolic_*")
        executables = []
        
        for file_path in glob.glob(pattern, recursive=True):
            if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                executables.append(file_path)
                
        print(f"🔍 找到 {len(executables)} 个符号化可执行文件")
        return sorted(executables)
    
    def run_symbolic_execution_single(self, executable_path):
        """对单个可执行文件运行符号执行"""
        try:
            print(f"\n🚀 正在处理: {executable_path}")
            
                          
            work_dir = os.path.dirname(executable_path)
            exe_name = os.path.basename(executable_path)
            
                    
            cmd = [
                "python3", self.se_script,
                os.path.join(work_dir, exe_name)
            ]
            
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=120         
            )
            
            if result.returncode == 0:
                print(f"✅ 执行成功: {exe_name}")
                return True, "执行成功"
            else:
                print(f"❌ 执行失败: {exe_name}")
                print(f"错误输出: {result.stderr}")
                return False, f"执行失败: {result.stderr}"
                
        except subprocess.TimeoutExpired:
            print(f"⏰ 执行超时: {executable_path}")
            return False, "执行超时"
        except Exception as e:
            print(f"💥 执行异常: {executable_path} - {str(e)}")
            return False, f"执行异常: {str(e)}"
    
    def check_constraint_quality(self, executable_path):
        """检查生成的约束文件质量"""
        work_dir = os.path.dirname(executable_path)
        exe_name = os.path.basename(executable_path)
        
                   
        path_files = glob.glob(os.path.join(work_dir, f"se_{exe_name}_path_*.txt"))
        
        if not path_files:
            return False, "未找到路径文件"
        
        meaningful_files = 0
        for path_file in path_files:
            try:
                with open(path_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                              
                has_scanf_vars = 'scanf_' in content
                has_assertions = '(assert' in content
                has_declare_fun = '(declare-fun' in content
                non_empty_vars = "输入变量值: {}" not in content
                
                if has_scanf_vars and has_assertions and has_declare_fun and non_empty_vars:
                    meaningful_files += 1
                    print(f"  ✅ 有意义约束: {os.path.basename(path_file)}")
                else:
                    print(f"  ❌ 空约束: {os.path.basename(path_file)}")
                    
            except Exception as e:
                print(f"  💥 文件读取错误: {path_file} - {str(e)}")
        
        return meaningful_files > 0, f"找到 {meaningful_files} 个有意义约束文件"
    
    def process_all_executables(self):
        """处理所有符号化可执行文件"""
        executables = self.find_all_symbolic_executables()
        self.results['total_files'] = len(executables)
        
        print(f"\n🎯 开始处理 {len(executables)} 个符号化程序...")
        print("=" * 80)
        
        for i, executable in enumerate(executables, 1):
            print(f"\n📋 进度: {i}/{len(executables)}")
            
                    
            success, message = self.run_symbolic_execution_single(executable)
            
            if success:
                self.results['success_execution'] += 1
                
                        
                has_meaningful, constraint_msg = self.check_constraint_quality(executable)
                
                if has_meaningful:
                    self.results['meaningful_constraints'] += 1
                else:
                    self.results['empty_constraints'] += 1
                    
                self.results['detailed_results'].append({
                    'file': executable,
                    'execution': 'success',
                    'constraints': 'meaningful' if has_meaningful else 'empty',
                    'message': constraint_msg
                })
            else:
                self.results['failed_execution'] += 1
                self.results['detailed_results'].append({
                    'file': executable,
                    'execution': 'failed',
                    'constraints': 'none',
                    'message': message
                })
            
                        
            time.sleep(0.5)
    
    def generate_report(self):
        """生成详细报告"""
        print("\n" + "=" * 80)
        print("🎯 符号执行完整报告")
        print("=" * 80)
        
        print(f"\n📊 总体统计:")
        print(f"  • 总文件数: {self.results['total_files']}")
        print(f"  • 执行成功: {self.results['success_execution']}")
        print(f"  • 执行失败: {self.results['failed_execution']}")
        print(f"  • 有意义约束: {self.results['meaningful_constraints']}")
        print(f"  • 空约束: {self.results['empty_constraints']}")
        
        success_rate = (self.results['success_execution'] / self.results['total_files']) * 100 if self.results['total_files'] > 0 else 0
        meaningful_rate = (self.results['meaningful_constraints'] / self.results['total_files']) * 100 if self.results['total_files'] > 0 else 0
        
        print(f"\n📈 成功率:")
        print(f"  • 执行成功率: {success_rate:.1f}%")
        print(f"  • 有意义约束率: {meaningful_rate:.1f}%")
        
              
        print(f"\n📋 详细结果:")
        
                  
        meaningful_files = [r for r in self.results['detailed_results'] if r['constraints'] == 'meaningful']
        if meaningful_files:
            print(f"\n✅ 生成有意义约束的文件 ({len(meaningful_files)}个):")
            for result in meaningful_files:
                print(f"  • {result['file']} - {result['message']}")
        
                
        empty_files = [r for r in self.results['detailed_results'] if r['constraints'] == 'empty']
        if empty_files:
            print(f"\n⚠️  生成空约束的文件 ({len(empty_files)}个):")
            for result in empty_files[:10]:           
                print(f"  • {result['file']}")
            if len(empty_files) > 10:
                print(f"  ... 还有 {len(empty_files) - 10} 个文件")
        
                 
        failed_files = [r for r in self.results['detailed_results'] if r['execution'] == 'failed']
        if failed_files:
            print(f"\n❌ 执行失败的文件 ({len(failed_files)}个):")
            for result in failed_files[:5]:          
                print(f"  • {result['file']} - {result['message']}")
            if len(failed_files) > 5:
                print(f"  ... 还有 {len(failed_files) - 5} 个文件")
        
        return self.results

def main():
    print("🚀 启动完整符号执行器...")
    
    executor = CompleteSymbolicExecutor()
    
                        
    if not os.path.exists(executor.se_script):
        print(f"❌ 错误: 找不到符号执行脚本 {executor.se_script}")
        return 1
    
    try:
                   
        executor.process_all_executables()
        
              
        results = executor.generate_report()
        
                 
        report_file = "/root/ardiff/symbolic_analysis/complete_symbolic_execution_report.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"完整符号执行报告\n")
            f.write(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"=" * 50 + "\n\n")
            f.write(f"总体统计:\n")
            f.write(f"总文件数: {results['total_files']}\n")
            f.write(f"执行成功: {results['success_execution']}\n")
            f.write(f"执行失败: {results['failed_execution']}\n")
            f.write(f"有意义约束: {results['meaningful_constraints']}\n")
            f.write(f"空约束: {results['empty_constraints']}\n\n")
            
            for result in results['detailed_results']:
                f.write(f"{result['file']}: {result['execution']} - {result['constraints']} - {result['message']}\n")
        
        print(f"\n📝 详细报告已保存到: {report_file}")
        
        if results['meaningful_constraints'] > 0:
            print(f"\n🎉 成功! 生成了 {results['meaningful_constraints']} 个有意义的约束文件!")
        else:
            print(f"\n⚠️  警告: 没有生成有意义的约束文件，需要进一步调试")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n⏹️  用户中断执行")
        return 1
    except Exception as e:
        print(f"\n💥 执行异常: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 