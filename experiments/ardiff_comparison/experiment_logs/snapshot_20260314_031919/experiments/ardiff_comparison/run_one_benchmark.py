#!/usr/bin/env python3
"""
Benchmark分析自动化脚本

自动运行符号执行和语义等价性分析的完整流程。
"""

import os
import sys
import subprocess
import time
import argparse


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
SE_SCRIPT = os.path.join(SCRIPTS_DIR, "se_script.py")
EQUIV_SCRIPT = os.path.join(SCRIPTS_DIR, "ardiff_comparison", "semantic_equivalence_analyzer_enhanced.py")


def run_command(cmd, description, cwd=None):
    """运行命令并显示进度"""
    print(f"\n{'='*60}")
    print(f"正在执行: {description}")
    print(f"命令: {cmd}")
    print(f"{'='*60}")

    start_time = time.time()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd or REPO_ROOT)
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


def resolve_benchmark_dir(path_text):
    """Resolve benchmark dir from absolute/repo-relative/bench-relative path."""
    if os.path.isdir(path_text):
        return os.path.abspath(path_text)
    repo_rel = os.path.join(REPO_ROOT, path_text)
    if os.path.isdir(repo_rel):
        return os.path.abspath(repo_rel)
    bench_rel = os.path.join(SCRIPT_DIR, "benchmarks", path_text)
    if os.path.isdir(bench_rel):
        return os.path.abspath(bench_rel)
    return None


def _extract_total_time_from_timing_report(report_path):
    """从 *_timing_report.txt 中解析总计时间（秒），解析失败返回 0.0"""
    if not os.path.isfile(report_path):
        return 0.0

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("总计时间:"):
                    try:
                        parts = line.split("总计时间:", 1)[1].strip()
                        num_str = parts.split()[0]
                        return float(num_str)
                    except Exception:
                        return 0.0
    except Exception:
        return 0.0

    return 0.0


def compile_case_if_needed(benchmark_dir):
    """若目录内有 symbolic_oldV.c/newV.c，则先编译。"""
    old_c = os.path.join(benchmark_dir, "symbolic_oldV.c")
    new_c = os.path.join(benchmark_dir, "symbolic_newV.c")
    if not (os.path.isfile(old_c) and os.path.isfile(new_c)):
        return True

    cmd_old = "gcc -o symbolic_oldV symbolic_oldV.c -lm"
    cmd_new = "gcc -o symbolic_newV symbolic_newV.c -lm"
    if not run_command(cmd_old, "编译 symbolic_oldV", cwd=benchmark_dir):
        return False
    if not run_command(cmd_new, "编译 symbolic_newV", cwd=benchmark_dir):
        return False
    return True


def run_symbolic_execution_for_case(benchmark_dir, timeout):
    """对单 case（oldV/newV）运行符号执行。"""
    old_bin = os.path.join(benchmark_dir, "symbolic_oldV")
    new_bin = os.path.join(benchmark_dir, "symbolic_newV")
    if not (os.path.isfile(old_bin) and os.path.isfile(new_bin)):
        # 回退到你给的 batch 形式（用于 *_O0 类目录）
        se_cmd = f"{sys.executable} \"{SE_SCRIPT}\" --benchmark \"{benchmark_dir}\" --timeout {timeout}"
        return run_command(se_cmd, "符号执行分析（benchmark目录）", cwd=REPO_ROOT)

    se_old = f"{sys.executable} \"{SE_SCRIPT}\" --binary \"{old_bin}\" --timeout {timeout}"
    se_new = f"{sys.executable} \"{SE_SCRIPT}\" --binary \"{new_bin}\" --timeout {timeout}"
    if not run_command(se_old, "符号执行 oldV", cwd=benchmark_dir):
        return False
    if not run_command(se_new, "符号执行 newV", cwd=benchmark_dir):
        return False
    return True


def run_equivalence_for_benchmarks(benchmark_dir, timeout=120):
    """遍历benchmark目录，对每个包含oldV/newV路径文件的case做等价性分析"""
    print("\n第二步: 对各 benchmark case 进行语义等价性分析")

    if not os.path.isdir(benchmark_dir):
        print(f"错误: benchmark目录 '{benchmark_dir}' 不存在")
        return False

    cases = []
    for root, dirs, files in os.walk(benchmark_dir):
        has_old = any(f.startswith("symbolic_oldV_path") and f.endswith(".txt") for f in files)
        has_new = any(f.startswith("symbolic_newV_path") and f.endswith(".txt") for f in files)
        if has_old and has_new:
            cases.append(root)

    if not cases:
        print(
            "在 benchmark 目录中未找到成对的路径文件 "
            "(symbolic_oldV_path_*.txt / symbolic_newV_path_*.txt)，跳过等价性分析。"
        )
        return True

    cases.sort()
    all_ok = True

    for case_dir in cases:
        case_name = os.path.relpath(case_dir, benchmark_dir)
        print(f"\n=== 等价性分析: {case_name} ===")

        prefix_new = os.path.join(case_dir, "symbolic_newV_path")
        prefix_old = os.path.join(case_dir, "symbolic_oldV_path")
        output_file = os.path.join(case_dir, "enhanced_equivalence_report.txt")

        old_timing = os.path.join(case_dir, "symbolic_oldV_timing_report.txt")
        new_timing = os.path.join(case_dir, "symbolic_newV_timing_report.txt")
        se_time = _extract_total_time_from_timing_report(old_timing) + _extract_total_time_from_timing_report(new_timing)

        equiv_cmd = (
            f"{sys.executable} \"{EQUIV_SCRIPT}\" "
            f"\"{prefix_old}\" \"{prefix_new}\" "
            f"--output \"{output_file}\" --timeout {timeout * 1000} "
            f"--se-time {se_time}"
        )

        if not run_command(equiv_cmd, f"语义等价性分析: {case_name}", cwd=REPO_ROOT):
            all_ok = False

    return all_ok


def main():
    parser = argparse.ArgumentParser(description='Benchmark分析自动化工具')
    parser.add_argument('benchmark_dir', help='benchmark目录路径')
    parser.add_argument('--timeout', type=int, default=120, help='符号执行超时时间(秒)')
    parser.add_argument('--step', choices=['se', 'equiv', 'all'], default='all',
                        help='执行的步骤: se(仅符号执行), equiv(仅等价性分析), all(全部)')
    parser.add_argument('--use-original', action='store_true',
                        help='保留参数（当前默认使用 se_script.py）')
    args = parser.parse_args()

    benchmark_dir = resolve_benchmark_dir(args.benchmark_dir)
    if benchmark_dir is None:
        print(f"错误: benchmark目录 '{args.benchmark_dir}' 不存在")
        sys.exit(1)

    if args.step in ['se', 'all']:
        if not compile_case_if_needed(benchmark_dir):
            sys.exit(1)
        if not run_symbolic_execution_for_case(benchmark_dir, args.timeout):
            sys.exit(1)

    if args.step in ['equiv', 'all']:
        if not run_equivalence_for_benchmarks(benchmark_dir, args.timeout):
            sys.exit(1)

    print(f"\n分析完成: {benchmark_dir}")


if __name__ == "__main__":
    main()
