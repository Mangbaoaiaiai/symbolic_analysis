                      
"""
批量符号执行脚本
对所有symbolic_*可执行文件进行符号执行
"""

import os
import glob
import subprocess
import time
from pathlib import Path

class BatchSymbolicExecution:
    def __init__(self, base_dir="/root/ardiff/symbolic_analysis"):
        self.base_dir = Path(base_dir)
        
    def find_all_executables(self):
        """查找所有symbolic_*可执行文件"""
        executables = []
        
                                   
        pattern = str(self.base_dir / "benchmarks" / "**" / "symbolic_*")
        all_symbolic_files = glob.glob(pattern, recursive=True)
        
                              
        for file_path in all_symbolic_files:
            if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                if not file_path.endswith('.c') and not file_path.endswith('.txt'):
                    executables.append(file_path)
        
        return sorted(executables)
    
    def run_symbolic_execution(self, executable_path, timeout=60):
        """运行单个可执行文件的符号执行"""
        print(f"🔍 分析: {os.path.relpath(executable_path, self.base_dir)}")
            
            cmd = [
            "python3", "se_script.py",
            "--binary", executable_path,
            "--timeout", str(timeout)
            ]
            
        try:
            start_time = time.time()
            result = subprocess.run(
                cmd,
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                timeout=timeout + 10               
            )
            elapsed_time = time.time() - start_time
            
            if result.returncode == 0:
                    
                output_lines = result.stdout.split('\n')
            paths_found = 0
                for line in output_lines:
                    if "共发现" in line and "条路径" in line:
                    try:
                        paths_found = int(line.split("共发现")[1].split("条路径")[0].strip())
                    except:
                        pass
                
                print(f"  ✅ 成功 - {paths_found} 条路径 ({elapsed_time:.1f}s)")
                return {"status": "success", "paths": paths_found, "time": elapsed_time}
            else:
                print(f"  ❌ 失败 - 返回码: {result.returncode} ({elapsed_time:.1f}s)")
                if result.stderr:
                    print(f"  错误: {result.stderr[:100]}...")
                return {"status": "failed", "error": result.stderr, "time": elapsed_time}
            
        except subprocess.TimeoutExpired:
            print(f"  ⏰ 超时 - {timeout}s")
            return {"status": "timeout", "time": timeout}
        except Exception as e:
            print(f"  💥 异常: {str(e)}")
            return {"status": "exception", "error": str(e), "time": 0}
    
    def run_batch_execution(self, timeout=60):
        """批量执行符号执行"""
        print("🚀 开始批量符号执行...")
        print("=" * 60)
        
                   
        executables = self.find_all_executables()
        
        if not executables:
            print("❌ 未找到任何symbolic_*可执行文件")
            return
        
        print(f"📊 发现 {len(executables)} 个可执行文件")
        print()
        
              
        results = {
            "success": 0,
            "failed": 0,
            "timeout": 0,
            "exception": 0,
            "total_paths": 0,
            "total_time": 0
        }
        
        successful_programs = []
        failed_programs = []
        
              
        for i, executable in enumerate(executables, 1):
            print(f"[{i}/{len(executables)}] ", end="")
            
            result = self.run_symbolic_execution(executable, timeout)
            
            results["total_time"] += result["time"]
            
            if result["status"] == "success":
                results["success"] += 1
                results["total_paths"] += result.get("paths", 0)
                successful_programs.append(executable)
            elif result["status"] == "failed":
                results["failed"] += 1
                failed_programs.append(executable)
            elif result["status"] == "timeout":
                results["timeout"] += 1
                failed_programs.append(executable)
            else:             
                results["exception"] += 1
                failed_programs.append(executable)
        
        print()
        print("=" * 60)
        print("🎯 批量执行完成统计:")
        print(f"  成功分析: {results['success']} 个程序")
        print(f"  分析失败: {results['failed']} 个程序")
        print(f"  执行超时: {results['timeout']} 个程序")
        print(f"  发生异常: {results['exception']} 个程序")
        print(f"  总路径数: {results['total_paths']} 条")
        print(f"  总用时: {results['total_time']:.1f} 秒")
        print(f"  成功率: {results['success']/len(executables)*100:.1f}%")
        
                    
        constraint_files = glob.glob(str(self.base_dir / "benchmarks" / "**" / "*_path_*.txt"), recursive=True)
        print(f"  约束文件: {len(constraint_files)} 个")
        
        if failed_programs:
            print(f"\n❌ 失败的程序 ({len(failed_programs)} 个):")
            for prog in failed_programs[:10]:           
                print(f"  - {os.path.relpath(prog, self.base_dir)}")
            if len(failed_programs) > 10:
                print(f"  ... 还有 {len(failed_programs) - 10} 个")
        
        return results

def main():
    """主函数"""
    print("🔧 启动批量符号执行...")
    
    executor = BatchSymbolicExecution()
    
            
    results = executor.run_batch_execution(timeout=60)
    
    print(f"\n✅ 批量符号执行完成!")
    print(f"📄 现在可以进行等价性分析")

if __name__ == "__main__":
    main() 