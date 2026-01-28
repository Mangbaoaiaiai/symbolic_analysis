                      
"""
Benchmark分析自动化脚本

自动运行符号执行和语义等价性分析的完整流程
使用改进的符号执行脚本处理没有输入的benchmark程序
"""

import os
import sys
import subprocess
import time
import argparse

def run_command(cmd, description):
    """运行命令并显示进度"""
    print(f"\n{'='*60}")
    print(f"正在执行: {description}")
    print(f"命令: {cmd}")
    print(f"{'='*60}")
    
    start_time = time.time()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    end_time = time.time()
    
    print(f"执行时间: {end_time - start_time:.2f} 秒")
    
    if result.returncode == 0:
        print("✓ 执行成功")
        if result.stdout:
            print("输出:")
            print(result.stdout)
    else:
        print("❌ 执行失败")
        print("错误输出:")
        print(result.stderr)
        return False
    
    return True

def analyze_benchmark(benchmark_dir, timeout=120, use_improved=True):
    """分析整个benchmark"""
    print(f"开始分析benchmark: {benchmark_dir}")
    
    if not os.path.exists(benchmark_dir):
        print(f"错误: benchmark目录 '{benchmark_dir}' 不存在")
        return False
    
              
    se_script = "se_script_improved.py" if use_improved else "se_script.py"
    
                 
    print(f"\n第一步: 使用{se_script}对所有优化等级运行符号执行")
    se_cmd = f"python {se_script} --benchmark {benchmark_dir} --timeout {timeout}"
    if not run_command(se_cmd, "改进的符号执行分析"):
        return False
    
                    
    print("\n第二步: 进行语义等价性分析")
    equiv_cmd = f"python semantic_equivalence_analyzer.py --benchmark {benchmark_dir}"
    if not run_command(equiv_cmd, "语义等价性分析"):
        return False
    
                 
    print("\n第三步: 显示分析结果")
    summary_file = os.path.join(benchmark_dir, "optimization_equivalence_summary.txt")
    if os.path.exists(summary_file):
        print(f"分析完成！结果摘要:")
        with open(summary_file, 'r', encoding='utf-8') as f:
            content = f.read()
            print(content)
            
                   
        if "✓ 所有优化等级在语义上完全等价" in content:
            print("\n🎉 结论: 所有优化等级保持语义等价，编译器优化是安全的！")
        elif "⚠ 大部分优化等级在语义上等价" in content:
            print("\n⚠️  结论: 大部分优化等价，但需要检查差异部分")
        else:
            print("\n🔍 结论: 发现优化差异，这可能表明：")
            print("   1. 编译器优化改变了程序行为")
            print("   2. 需要进一步分析具体差异")
            print("   3. 对于benchmark程序，这种差异可能是正常的")
            
    else:
        print("未找到分析摘要文件")
    
    return True

def main():
    parser = argparse.ArgumentParser(description='Benchmark分析自动化工具')
    parser.add_argument('benchmark_dir', help='benchmark目录路径')
    parser.add_argument('--timeout', type=int, default=120, help='符号执行超时时间(秒)')
    parser.add_argument('--step', choices=['se', 'equiv', 'all'], default='all', 
                       help='执行的步骤: se(仅符号执行), equiv(仅等价性分析), all(全部)')
    parser.add_argument('--use-original', action='store_true', 
                       help='使用原始符号执行脚本(适合有输入的程序)')
    
    args = parser.parse_args()
    
    use_improved = not args.use_original
    se_script = "se_script.py" if args.use_original else "se_script_improved.py"
    
    if args.step in ['se', 'all']:
                
        print(f"使用脚本: {se_script}")
        se_cmd = f"python {se_script} --benchmark {args.benchmark_dir} --timeout {args.timeout}"
        if not run_command(se_cmd, "符号执行分析"):
            return
    
    if args.step in ['equiv', 'all']:
                 
        equiv_cmd = f"python semantic_equivalence_analyzer.py --benchmark {args.benchmark_dir}"
        if not run_command(equiv_cmd, "语义等价性分析"):
            return
    
          
    summary_file = os.path.join(args.benchmark_dir, "optimization_equivalence_summary.txt")
    if os.path.exists(summary_file):
        print(f"\n分析完成！结果摘要在: {summary_file}")
        
                 
        print(f"\n生成的关键文件:")
        
                
        path_files = subprocess.run(f"find {args.benchmark_dir} -name '*_path_*.txt' -type f 2>/dev/null", 
                                   shell=True, capture_output=True, text=True)
        if path_files.stdout:
            print("路径约束文件:")
            for file in sorted(path_files.stdout.strip().split('\n')):
                if file:
                    print(f"  {file}")
        
                 
        report_files = subprocess.run(f"find {args.benchmark_dir} -name 'equivalence_report_*.txt' -type f 2>/dev/null", 
                                     shell=True, capture_output=True, text=True)
        if report_files.stdout:
            print("等价性分析报告:")
            for file in sorted(report_files.stdout.strip().split('\n')):
                if file:
                    print(f"  {file}")
                    
              
        summary_files = subprocess.run(f"find {args.benchmark_dir} -name '*summary*.txt' -type f 2>/dev/null", 
                                      shell=True, capture_output=True, text=True)
        if summary_files.stdout:
            print("摘要报告:")
            for file in sorted(summary_files.stdout.strip().split('\n')):
                if file:
                    print(f"  {file}")

if __name__ == "__main__":
    main() 