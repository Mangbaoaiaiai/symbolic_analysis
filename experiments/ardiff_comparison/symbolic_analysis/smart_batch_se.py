                      
"""
智能批量符号执行脚本
- 跳过已经生成约束文件的程序
- 跳过已知容易超时的程序
- 使用较短的超时时间避免卡死
"""

import os
import glob
import subprocess
import time

def find_symbolic_executables():
    """查找所有symbolic_*可执行文件"""
    pattern = "benchmarks/**/symbolic_*"
    all_files = glob.glob(pattern, recursive=True)
    
    executables = []
    for f in all_files:
        if os.path.isfile(f) and os.access(f, os.X_OK):
            if not f.endswith('.c') and not f.endswith('.txt'):
                executables.append(f)
    
    return sorted(executables)

def has_constraint_files(exe_path):
    """检查可执行文件是否已经生成了约束文件"""
    exe_dir = os.path.dirname(exe_path)
    exe_name = os.path.basename(exe_path)
    
               
    pattern = os.path.join(exe_dir, f"{exe_name}_path_*.txt")
    constraint_files = glob.glob(pattern)
    
    return len(constraint_files) > 0

def is_problematic_program(exe_path):
    """检查是否是已知的问题程序"""
    problematic_patterns = [
        "bessj0",        
        "bessj1",        
        "probks",        
        "ModDiff/.*Loop.*",               
        "gammln",          
        "ran"             
    ]
    
    for pattern in problematic_patterns:
        if pattern in exe_path:
            return True
    return False

def run_se_on_file(exe_path, timeout=30):
    """对单个文件运行符号执行，使用较短超时"""
    cmd = ["python3", "se_script.py", "--binary", exe_path, "--timeout", str(timeout)]
    
    try:
        start = time.time()
        result = subprocess.run(cmd, timeout=timeout+15, capture_output=True, text=True)
        elapsed = time.time() - start
        
        if result.returncode == 0:
                    
            lines = result.stdout.split('\n')
            paths = 0
            for line in lines:
                if "共发现" in line and "条路径" in line:
                    try:
                        paths = int(line.split("共发现")[1].split("条路径")[0].strip())
                    except:
                        pass
            return "success", paths, elapsed
        else:
            return "failed", 0, elapsed
    except subprocess.TimeoutExpired:
        return "timeout", 0, timeout
    except Exception as e:
        return "exception", 0, 0

def main():
    print("🧠 智能批量符号执行开始...")
    
               
    all_executables = find_symbolic_executables()
    print(f"总共找到 {len(all_executables)} 个可执行文件")
    
                 
    to_process = []
    already_done = []
    problematic = []
    
    for exe in all_executables:
        if has_constraint_files(exe):
            already_done.append(exe)
        elif is_problematic_program(exe):
            problematic.append(exe)
        else:
            to_process.append(exe)
    
    print(f"📊 程序分类:")
    print(f"  已完成: {len(already_done)} 个")
    print(f"  问题程序(跳过): {len(problematic)} 个")
    print(f"  待处理: {len(to_process)} 个")
    
    if len(to_process) == 0:
        print("✅ 所有非问题程序都已处理完成!")
        
                  
        constraint_files = glob.glob("benchmarks/**/*_path_*.txt", recursive=True)
        print(f"📄 当前约束文件总数: {len(constraint_files)} 个")
        return
    
    print(f"\n🚀 开始处理 {len(to_process)} 个程序...")
    
    stats = {"success": 0, "failed": 0, "timeout": 0, "exception": 0, "total_paths": 0}
    
    for i, exe in enumerate(to_process, 1):
        print(f"\n[{i}/{len(to_process)}] 分析: {exe}")
        status, paths, elapsed = run_se_on_file(exe, timeout=30)
        
        stats[status] += 1
        if status == "success":
            stats["total_paths"] += paths
            print(f"  ✅ 成功 - {paths} 路径 ({elapsed:.1f}s)")
        elif status == "failed":
            print(f"  ❌ 失败 ({elapsed:.1f}s)")
        elif status == "timeout":
            print(f"  ⏰ 超时 (30s)")
        else:
            print(f"  💥 异常")
    
    print(f"\n" + "="*50)
    print("智能批量执行完成统计:")
    print(f"  成功: {stats['success']}")
    print(f"  失败: {stats['failed']}")
    print(f"  超时: {stats['timeout']}")
    print(f"  异常: {stats['exception']}")
    print(f"  新增路径: {stats['total_paths']}")
    
              
    constraint_files = glob.glob("benchmarks/**/*_path_*.txt", recursive=True)
    print(f"  约束文件总数: {len(constraint_files)} 个")
    
                
    program_pairs = set()
    for cf in constraint_files:
                       
        prog_dir = os.path.dirname(cf)
        program_pairs.add(prog_dir)
    
    print(f"  成功处理的程序目录: {len(program_pairs)} 个")

if __name__ == "__main__":
    main() 