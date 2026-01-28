                      
"""
简单批量符号执行脚本
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

def run_se_on_file(exe_path, timeout=60):
    """对单个文件运行符号执行"""
    print(f"分析: {exe_path}")
    
    cmd = ["python3", "se_script.py", "--binary", exe_path, "--timeout", str(timeout)]
    
    try:
        start = time.time()
        result = subprocess.run(cmd, timeout=timeout+10, capture_output=True, text=True)
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
            print(f"  ✅ 成功 - {paths} 路径 ({elapsed:.1f}s)")
            return "success", paths
        else:
            print(f"  ❌ 失败 - 错误码: {result.returncode}")
            return "failed", 0
    except subprocess.TimeoutExpired:
        print(f"  ⏰ 超时")
        return "timeout", 0
    except Exception as e:
        print(f"  💥 异常: {e}")
        return "exception", 0

def main():
    print("🚀 简单批量符号执行开始...")
    
    executables = find_symbolic_executables()
    print(f"找到 {len(executables)} 个可执行文件")
    
    stats = {"success": 0, "failed": 0, "timeout": 0, "exception": 0, "total_paths": 0}
    
    for i, exe in enumerate(executables, 1):
        print(f"\n[{i}/{len(executables)}] ", end="")
        status, paths = run_se_on_file(exe, timeout=60)
        
        stats[status] += 1
        if status == "success":
            stats["total_paths"] += paths
    
    print(f"\n" + "="*50)
    print("批量执行完成统计:")
    print(f"  成功: {stats['success']}")
    print(f"  失败: {stats['failed']}")
    print(f"  超时: {stats['timeout']}")
    print(f"  异常: {stats['exception']}")
    print(f"  总路径: {stats['total_paths']}")
    
            
    constraint_files = glob.glob("benchmarks/**/*_path_*.txt", recursive=True)
    print(f"  约束文件: {len(constraint_files)} 个")

if __name__ == "__main__":
    main() 