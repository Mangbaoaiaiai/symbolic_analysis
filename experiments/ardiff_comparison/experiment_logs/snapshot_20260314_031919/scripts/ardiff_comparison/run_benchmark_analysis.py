#!/usr/bin/env python3
"""
ARDiff benchmark automation script
=================================

在整个 `symbolic_analysis` 项目中，一键完成：
1. 为所有 ardiff_comparison benchmark case 编译 `symbolic_oldV` / `symbolic_newV`
2. 运行改进版符号执行（`se_script_improved.py`）
3. 运行增强版语义等价性分析（`semantic_equivalence_analyzer_enhanced.py`）

实现思路与 `evaluation-with-ardiff/symbolic_analysis/run_benchmark_analysis.py`
基本一致，只是这里复用已有的
`experiments/ardiff_comparison/run_one_benchmark.sh` 来完成单个 case 的流水线。

用法（从仓库根目录运行）：

  # 对所有 Eq+NEq case 运行
  python3 scripts/ardiff_comparison/run_benchmark_analysis.py

  # 只跑 Eq 或 NEq
  python3 scripts/ardiff_comparison/run_benchmark_analysis.py --type Eq
  python3 scripts/ardiff_comparison/run_benchmark_analysis.py --type NEq
"""

import os
import sys
import subprocess
import time
import argparse
from typing import List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BENCH_ROOT = os.path.join(
    REPO_ROOT, "experiments", "ardiff_comparison", "benchmarks"
)
RUN_ONE_SCRIPT = os.path.join(
    REPO_ROOT, "experiments", "ardiff_comparison", "run_one_benchmark.sh"
)

# User-selected benchmark subset (from provided experiment table)
# Paths are relative to experiments/ardiff_comparison/benchmarks
TARGET_CASES = {
    "Airy/MAX/Eq",
    "Airy/MAX/NEq",
    "Airy/Sign/Eq",
    "Airy/Sign/NEq",
    "Bess/SIGN/Eq",
    "Bess/SIGN/NEq",
    "Bess/SQR/Eq",
    "Bess/SQR/NEq",
    "Bess/bessi0/Eq",
    "Bess/bessi0/NEq",
    "Bess/bessi1/Eq",
    "Bess/bessi1/NEq",
    "Bess/probks/Eq",
    "Bess/probks/NEq",
    "Ell/rc/Eq",
    "Ell/rc/NEq",
    "ModDiff/Add/Eq",
    "ModDiff/Comp/Eq",
    "ModDiff/Const/Eq",
    "ModDiff/LoopMult10/Eq",
    "ModDiff/LoopMult10/NEq",
    "ModDiff/LoopMult15/Eq",
    "ModDiff/LoopMult15/NEq",
    "ModDiff/LoopMult20/Eq",
    "ModDiff/LoopMult20/NEq",
    "ModDiff/LoopMult5/Eq",
    "ModDiff/LoopMult5/NEq",
    "ModDiff/LoopSub/Eq",
    "ModDiff/LoopSub/NEq",
    "ModDiff/LoopUnreach10/Eq",
    "ModDiff/LoopUnreach10/NEq",
    "ModDiff/LoopUnreach15/Eq",
    "ModDiff/LoopUnreach15/NEq",
    "ModDiff/LoopUnreach2/Eq",
    "ModDiff/LoopUnreach2/NEq",
    "ModDiff/LoopUnreach20/Eq",
    "ModDiff/LoopUnreach20/NEq",
    "ModDiff/LoopUnreach5/Eq",
    "ModDiff/LoopUnreach5/NEq",
    "ModDiff/Sub/Eq",
    "Ran/gammln/Eq",
    "Ran/gammln/NEq",
    "Ran/ranzero/Eq",
    "Ran/ranzero/NEq",
    "caldat/julday/Eq",
    "caldat/julday/NEq",
    "dart/test/Eq",
    "dart/test/NEq",
    "gam/ei/Eq",
    "gam/ei/NEq",
    "gam/erfcc/Eq",
    "gam/erfcc/NEq",
    "power/test/Eq",
    "power/test/NEq",
}


def run_command(cmd: str, description: str, timeout_seconds: int | None = None) -> bool:
    """运行命令并显示进度（在仓库根目录下执行）"""
    print(f"\n{'=' * 60}")
    print(f"正在执行: {description}")
    print(f"命令: {cmd}")
    if timeout_seconds:
        print(f"超时设置: {timeout_seconds} 秒")
    print(f"{'=' * 60}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        end = time.time()
        print(f"执行时间: {end - start:.2f} 秒")
        print("⏰ 执行超时，已跳过该 case")
        # TimeoutExpired.stdout/stderr 可能为 bytes 或 str
        stdout_text = e.stdout.decode("utf-8", errors="ignore") if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr_text = e.stderr.decode("utf-8", errors="ignore") if isinstance(e.stderr, bytes) else (e.stderr or "")
        if stdout_text.strip():
            print("超时前输出:")
            print(stdout_text)
        if stderr_text.strip():
            print("超时前错误输出:")
            print(stderr_text)
        return False
    end = time.time()

    print(f"执行时间: {end - start:.2f} 秒")

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


def _canonical_case_rel(rel: str) -> str:
    """
    Normalize case path to canonical form: Family/Method/Eq|NEq
    Supports:
      - Standard: Family/Method/Eq|NEq
      - ModDiff:  Family/Eq|NEq/Method
    """
    rel = rel.replace("\\", "/")
    parts = [p for p in rel.split("/") if p and p != "."]
    if len(parts) == 3 and parts[1] in ("Eq", "NEq"):
        # Family/Eq|NEq/Method -> Family/Method/Eq|NEq
        return f"{parts[0]}/{parts[2]}/{parts[1]}"
    return rel


def discover_cases(bench_root: str, case_type: str = "all", target_only: bool = True) -> List[str]:
    """
    在 benchmark 根目录下查找所有 case 目录。

    规则：
    - 目录结构：benchmarks/<Family>/<Method>/<Eq|NEq>/
    - 必须同时包含 symbolic_oldV.c 和 symbolic_newV.c
    - 根据 case_type 过滤 Eq / NEq
    """
    cases: List[str] = []

    for root, dirs, files in os.walk(bench_root):
        if "symbolic_oldV.c" in files and "symbolic_newV.c" in files:
            last = os.path.basename(root)
            parent = os.path.basename(os.path.dirname(root))

            # Support both:
            # 1) Family/Method/Eq|NEq  -> last is Eq|NEq
            # 2) Family/Eq|NEq/Method  -> parent is Eq|NEq
            if last in ("Eq", "NEq"):
                eqneq = last
            elif parent in ("Eq", "NEq"):
                eqneq = parent
            else:
                continue

            if case_type in ("Eq", "NEq") and eqneq != case_type:
                continue
            if target_only:
                rel = os.path.relpath(root, bench_root)
                canonical_rel = _canonical_case_rel(rel)
                if canonical_rel not in TARGET_CASES:
                    continue
            cases.append(root)

    cases.sort()
    return cases


def main():
    parser = argparse.ArgumentParser(
        description="ARDiff benchmark 批量分析脚本（编译 + 符号执行 + 等价性分析）"
    )
    parser.add_argument(
        "--bench-root",
        default=DEFAULT_BENCH_ROOT,
        help="benchmark 根目录（默认: experiments/ardiff_comparison/benchmarks）",
    )
    parser.add_argument(
        "--type",
        choices=["Eq", "NEq", "all"],
        default="all",
        help="只分析 Eq / NEq / all（默认 all）",
    )
    parser.add_argument(
        "--case-timeout",
        type=int,
        default=600,
        help="单个 case 的最大执行时间（秒），超时后跳过并继续（默认 600）",
    )
    parser.add_argument(
        "--all-cases",
        action="store_true",
        help="关闭白名单过滤，运行 bench-root 下全部可发现 case",
    )

    args = parser.parse_args()

    bench_root = args.bench_root
    if not os.path.isabs(bench_root):
        bench_root = os.path.join(REPO_ROOT, bench_root)

    if not os.path.isdir(bench_root):
        print(f"错误: benchmark 根目录不存在: {bench_root}")
        sys.exit(1)

    if not os.path.isfile(RUN_ONE_SCRIPT):
        print(f"错误: 未找到 run_one_benchmark.sh: {RUN_ONE_SCRIPT}")
        sys.exit(1)

    print(f"仓库根目录: {REPO_ROOT}")
    print(f"benchmark 根目录: {bench_root}")
    print(f"单 case 脚本: {RUN_ONE_SCRIPT}")

    cases = discover_cases(bench_root, args.type, target_only=(not args.all_cases))
    if not cases:
        print("未在指定目录下找到任何 benchmark case（包含 symbolic_oldV.c / symbolic_newV.c）。")
        sys.exit(1)

    print(f"\n共发现 {len(cases)} 个 case 将被分析:")
    for c in cases:
        rel = os.path.relpath(c, bench_root)
        print(f"  - {rel}")

    success = 0
    failed = 0

    for idx, case_dir in enumerate(cases, 1):
        rel = os.path.relpath(case_dir, bench_root)
        desc = f"[{idx}/{len(cases)}] {rel}"
        cmd = f"\"{RUN_ONE_SCRIPT}\" \"{case_dir}\""
        if run_command(cmd, desc, timeout_seconds=args.case_timeout):
            success += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print("批量分析完成")
    print(f"  成功: {success}")
    print(f"  失败: {failed}")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

