                      
"""
处理能成功执行的剩余程序
基于超时分析结果，跳过已知超时的程序类型
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

def is_likely_successful(executable):
    """根据分析结果判断程序是否可能成功执行"""
                           
    successful_categories = ['caldat', 'dart', 'gam', 'power']
    
    for category in successful_categories:
        if category in executable:
            return True
    
                      
    if 'ModDiff' in executable or 'Ran' in executable:
        return False
    
    return True

def run_single_execution(executable, timeout=120):
    """运行单个程序的符号执行，给足够时间"""
    try:
        print(f"🔍 处理: {os.path.relpath(executable, '/root/ardiff/symbolic_analysis')}")
        
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
            return True, len(constraint_files)
        else:
            print(f"  ❌ 失败 - 返回码 {result.returncode} ({execution_time:.1f}s)")
            return False, 0
            
    except subprocess.TimeoutExpired:
        print(f"  ⏱️  超时 (>{timeout}s)")
        return False, 0
    except Exception as e:
        print(f"  💥 异常: {e}")
        return False, 0

def main():
    print("🚀 处理可能成功的剩余程序...")
    print("跳过已知超时的ModDiff和Ran程序")
    print("=" * 60)
    
    all_remaining = find_remaining_executables()
    
                
    likely_successful = [exe for exe in all_remaining if is_likely_successful(exe)]
    skipped_programs = [exe for exe in all_remaining if not is_likely_successful(exe)]
    
    print(f"📊 程序分析:")
    print(f"  • 总剩余程序数: {len(all_remaining)}")
    print(f"  • 可能成功程序数: {len(likely_successful)}")
    print(f"  • 跳过超时程序数: {len(skipped_programs)}")
    
    if not likely_successful:
        print("✅ 没有可能成功的剩余程序需要处理")
        return
    
    print(f"\n🔧 开始处理可能成功的程序...")
    
    success_count = 0
    total_new_constraints = 0
    
    for i, executable in enumerate(likely_successful, 1):
        print(f"\n[{i}/{len(likely_successful)}] ", end="")
        
        success, constraint_count = run_single_execution(executable)
        if success:
            success_count += 1
            total_new_constraints += constraint_count
    
    print(f"\n" + "="*60)
    print("🎯 处理完成统计:")
    print(f"  • 尝试处理: {len(likely_successful)} 个程序")
    print(f"  • 成功处理: {success_count} 个程序")
    print(f"  • 新生成约束文件: {total_new_constraints} 个")
    print(f"  • 成功率: {(success_count/len(likely_successful)*100):.1f}%")
    
            
    all_constraints = glob.glob("/root/ardiff/symbolic_analysis/benchmarks/**/*_path_*.txt", recursive=True)
    print(f"  • 最终总约束文件数: {len(all_constraints)} 个")
    
    print(f"\n📋 跳过的超时程序类别:")
    skipped_categories = {}
    for exe in skipped_programs:
        if 'ModDiff' in exe:
            category = 'ModDiff'
        elif 'Ran' in exe:
            category = 'Ran'
        else:
            category = 'Other'
        
        if category not in skipped_categories:
            skipped_categories[category] = 0
        skipped_categories[category] += 1
    
    for category, count in skipped_categories.items():
        print(f"  • {category}: {count} 个程序 (已知超时)")

if __name__ == "__main__":
    main() 