                      
"""
处理剩余benchmark符号化程序的约束路径
"""

import os
import subprocess
import sys
import time
import glob
from pathlib import Path

def find_remaining_executables():
    """查找没有约束文件的符号化可执行文件"""
    base_dir = Path("/root/ardiff/symbolic_analysis")
    remaining = []
    
               
    pattern = str(base_dir / "benchmarks" / "**" / "symbolic_*")
    for file_path in glob.glob(pattern, recursive=True):
        if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
            if not file_path.endswith('.c'):
                           
                exec_dir = os.path.dirname(file_path)
                exec_name = os.path.basename(file_path)
                constraint_files = glob.glob(os.path.join(exec_dir, f"{exec_name}_path_*.txt"))
                
                if not constraint_files:
                    remaining.append(file_path)
    
    return sorted(remaining)

def run_single_execution(executable, timeout=60):
    """运行单个程序的符号执行"""
    try:
        print(f"🔍 处理: {os.path.basename(executable)}")
        
        cmd = [sys.executable, "/root/ardiff/symbolic_analysis/se_script.py", "--binary", executable]
        
        start_time = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        end_time = time.time()
        
        execution_time = end_time - start_time
        
        if result.returncode == 0:
                       
            exec_dir = os.path.dirname(executable)
            exec_name = os.path.basename(executable)
            constraint_files = glob.glob(os.path.join(exec_dir, f"{exec_name}_path_*.txt"))
            
            print(f"  ✅ 成功 - 生成 {len(constraint_files)} 个约束文件 ({execution_time:.1f}s)")
            return True
        else:
            print(f"  ❌ 失败 - 返回码 {result.returncode}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"  ⏱️  超时 (>{timeout}s)")
        return False
    except Exception as e:
        print(f"  💥 异常: {e}")
        return False

def main():
    print("🚀 开始处理剩余的符号化程序...")
    
    remaining = find_remaining_executables()
    
    if not remaining:
        print("✅ 所有程序都已有约束文件")
        return
    
    print(f"📋 找到 {len(remaining)} 个剩余程序")
    
    success_count = 0
    timeout_count = 0
    
    for i, executable in enumerate(remaining, 1):
        print(f"\n[{i}/{len(remaining)}] ", end="")
        
                          
        if 'ModDiff' in executable or 'Ran' in executable:
            timeout = 30         
        else:
            timeout = 60         
        
        if run_single_execution(executable, timeout):
            success_count += 1
        else:
            timeout_count += 1
    
    print(f"\n🎯 处理完成:")
    print(f"  • 成功: {success_count}")
    print(f"  • 失败/超时: {timeout_count}")
    
            
    all_constraints = glob.glob("/root/ardiff/symbolic_analysis/benchmarks/**/*_path_*.txt", recursive=True)
    print(f"  • 总约束文件数: {len(all_constraints)}")

if __name__ == "__main__":
    main() 