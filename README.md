# Symbolicana

Symbolicana 是一个用于二进制等价性验证实验的符号分析项目。它的目标是回答一个问题：

> 给定两个版本的程序，能不能自动判断它们在语义上是否等价，并比较不同路径匹配算法的效果？

项目的核心流程分为三步：

1. 用 angr 对二进制做符号执行，生成每条执行路径的 SMT 路径约束。
2. 对 old/new 两边的路径进行排序匹配，减少需要调用 Z3 的路径对数量。
3. 用 Z3 按三层语义验证路径和程序是否等价。

当前维护的等价性定义是：

1. 输入空间等价。
2. 在兼容输入区域上，函数返回值等价。
3. heap/global 等非局部状态等价。

只有这三层都满足时，才认为对应语义区域等价。验证报告里会通过 `semantic_definition` 字段记录这套语义定义。

## 目录说明

常用目录如下：

```text
symbolic_analysis/
  README.md
  requirements.txt
  pyproject.toml
  setup.py

  src/symbolic_analysis/
    analysis/              11维路径特征、cosine 排序、hybrid 匹配
    equivalence/           等价性分析相关代码
    symbolic_execution/    符号执行相关封装
    tracing.py             时间和 SMT 调用 tracing
    cli.py                 命令行入口

  scripts/
    se_script_improved.py              angr 符号执行脚本
    verify_ranked_path_equivalence.py  三层语义验证脚本
    generate_path_feature_vectors.py   生成路径特征向量
    path_similarity_batch.py           批量 cosine 排序
    hybrid_path_similarity_batch.py    hybrid 排序

  experiments/ardiff_comparison/
    benchmarks/            原始 ARDiff benchmark
    benchmarks_typed/      尽量保留 Java 原类型翻译出的 C benchmark

  benchmarks/
    ardiff_paths/          已生成的 ARDiff 路径 benchmark
    ardiff_paths_typed/    typed C 版本路径 benchmark
    tsvc_paths/            TSVC 路径 benchmark

  evaluation_results*/
    results.csv
    results.json
    summary.md
    subset_summary.md
    final_summary.md
```

外部对比工具不放在本目录内，默认路径是：

```text
../VeriBin
../pldi19-equivalence-checker
```

本项目可以独立运行自己的方法和评测脚本；如果要调用 VeriBin 的真实逻辑，需要父目录存在 `VeriBin`。

## 环境准备

推荐 Python 3.12。项目里如果已有 `.venv312`，可以直接用它；否则重新创建环境：

```bash
cd /Users/zzk/Desktop/symbolicana/symbolic_analysis
python3.12 -m venv .venv312
source .venv312/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -e .
```

检查依赖是否可用：

```bash
PYTHONPATH=src .venv312/bin/python -m symbolic_analysis.cli check-deps
```

正常情况下会看到：

```text
angr: ok
claripy: ok
z3: ok
```

如果没有安装成命令行工具，可以一直使用下面这种形式运行：

```bash
PYTHONPATH=src .venv312/bin/python -m symbolic_analysis.cli <command>
```

安装成功后，也可以直接用：

```bash
symbolicana <command>
```

## 最快上手：直接跑已有路径 benchmark

如果你只是想确认项目能跑，不想重新做符号执行，可以直接使用已经生成好的路径 benchmark。

运行 typed ARDiff benchmark 的 dry run：

```bash
cd /Users/zzk/Desktop/symbolicana/symbolic_analysis

.venv312/bin/python run_evaluation.py \
  --benchmarks benchmarks/ardiff_paths_typed \
  --ground-truth benchmarks/ardiff_paths_typed/groundtruth.json \
  --output-dir /tmp/symbolicana_eval_dry
```

这个命令不会真正调用验证器，只会检查 manifest、ground truth、路径解析和评测表格生成逻辑。

真正执行评测：

```bash
.venv312/bin/python run_evaluation.py \
  --benchmarks benchmarks/ardiff_paths_typed \
  --ground-truth benchmarks/ardiff_paths_typed/groundtruth.json \
  --output-dir evaluation_results_ardiff_typed \
  --execute
```

输出文件包括：

```text
evaluation_results_ardiff_typed/results.csv
evaluation_results_ardiff_typed/results.json
evaluation_results_ardiff_typed/summary.md
evaluation_results_ardiff_typed/subset_summary.md
evaluation_results_ardiff_typed/final_summary.md
```

其中：

- `summary.md`：路径匹配指标汇总。
- `subset_summary.md`：按 benchmark 子集分组的匹配效果。
- `final_summary.md`：最终等价性验证结果表。
- `results.json`：最完整的机器可读结果。

## 完整流程：从源码重新生成路径 benchmark

如果要从 ARDiff benchmark 的 C 程序开始，重新编译、符号执行、生成路径文件和 ranking：

```bash
cd /Users/zzk/Desktop/symbolicana/symbolic_analysis

.venv312/bin/python build_ardiff_path_benchmarks.py \
  --python .venv312/bin/python \
  --timeout 120 \
  --out-dir benchmarks/ardiff_paths_typed \
  --eval-output-dir evaluation_results_ardiff_typed
```

如果只想重新生成 benchmark 文件，不自动跑 evaluation：

```bash
.venv312/bin/python build_ardiff_path_benchmarks.py \
  --python .venv312/bin/python \
  --timeout 120 \
  --out-dir benchmarks/ardiff_paths_typed \
  --eval-output-dir evaluation_results_ardiff_typed \
  --skip-evaluation
```

如果路径文件已经存在，只想重建 manifest、ground truth、ranking：

```bash
.venv312/bin/python build_ardiff_path_benchmarks.py \
  --python .venv312/bin/python \
  --skip-symbolic-exec \
  --skip-evaluation \
  --out-dir benchmarks/ardiff_paths_typed
```

## 单个二进制怎么跑

### 1. 符号执行生成路径

```bash
PYTHONPATH=src .venv312/bin/python -m symbolic_analysis.cli symbolic-exec \
  --binary /path/to/symbolic_oldV \
  --output-prefix outputs/symbolic_oldV \
  --signature 'double(double,double)' \
  --timeout 120
```

输出类似：

```text
outputs/symbolic_oldV_path_1.txt
outputs/symbolic_oldV_path_2.txt
```

对 new 版本也做一次：

```bash
PYTHONPATH=src .venv312/bin/python -m symbolic_analysis.cli symbolic-exec \
  --binary /path/to/symbolic_newV \
  --output-prefix outputs/symbolic_newV \
  --signature 'double(double,double)' \
  --timeout 120
```

### 2. 生成 11 维路径特征

```bash
PYTHONPATH=src .venv312/bin/python -m symbolic_analysis.cli vectors \
  --paths-dir outputs \
  --normalize \
  --include-min-max \
  --out outputs/path_vectors.json
```

### 3. 对 old/new 路径排序

```bash
PYTHONPATH=src .venv312/bin/python -m symbolic_analysis.cli rank \
  --old-paths-dir outputs \
  --new-paths-dir outputs \
  --old-prefix symbolic_oldV \
  --new-prefix symbolic_newV \
  --out outputs/ranking.json
```

如果有 BinDiff/VeriBin 风格的基本块匹配信息，可以作为图证据输入：

```bash
PYTHONPATH=src .venv312/bin/python -m symbolic_analysis.cli rank \
  --old-paths-dir outputs \
  --new-paths-dir outputs \
  --old-prefix symbolic_oldV \
  --new-prefix symbolic_newV \
  --matching-bb-map bindiff_basic_block_map.json \
  --out outputs/ranking.json
```

### 4. 三层语义验证

```bash
PYTHONPATH=src .venv312/bin/python -m symbolic_analysis.cli verify \
  --paths-dir outputs \
  --ranking outputs/ranking.json \
  --out outputs/verification_report.json \
  --program-ground-truth true
```

暴力 all-vs-all baseline：

```bash
PYTHONPATH=src .venv312/bin/python -m symbolic_analysis.cli verify \
  --paths-dir outputs \
  --naive \
  --out outputs/naive_report.json \
  --program-ground-truth true
```

## 评测方法说明

`run_evaluation.py` 会比较三组方法：

```text
Naive    所有 old path 和 new path 两两比较
VERIBIN  使用 VeriBin/BinDiff 风格 ranking，或已生成的 veribin ranking
Ours     11维路径特征 + cosine + hybrid 图证据 rerank
```

主要指标：

```text
ACC %          按 ground truth 判断最终等价/不等价结果的准确率
Hit@1 %        正确路径是否排在第 1 位
Hit@3 %        正确路径是否排在前 3 位
MRR            Mean Reciprocal Rank，正确路径排名越靠前越高
T_se           符号执行时间
T_align        路径排序/匹配时间
T_smt          Z3 求解时间
T_total        T_se + T_align + T_smt
Pruning %      相比 all-vs-all，减少 SMT 调用的比例
```

注意：`summary.md` 和 `final_summary.md` 里的时间单位都是秒。

## typed ARDiff benchmark

`experiments/ardiff_comparison/benchmarks_typed` 是从原始 Java benchmark 翻译出的 C 程序，尽量保留原变量类型，例如 `double`、`float`、`long`、`int`。

如果要重新翻译：

```bash
.venv312/bin/python translate_ardiff_java_to_typed_c.py --clean
```

翻译后的每个 case 通常包含：

```text
symbolic_oldV.c
symbolic_newV.c
```

主逻辑函数名是：

```text
snippet(...)
```

## 三层验证的具体逻辑

维护中的三层验证在：

```text
scripts/verify_ranked_path_equivalence.py
```

验证流程大致是：

1. 检查 old 所有路径输入空间和 new 所有路径输入空间是否双向一致。
2. 按 ranking 对每条 old path 查找语义兼容的 new path。
3. 如果某个 new path 或多个 new path 的输入区域与 old path 存在重叠，则在重叠区域验证：
   - return 是否等价；
   - heap/global 状态是否等价。
4. 反向再做 new -> old，避免只证明单向覆盖。
5. 没有 unknown 且双向都成功时，最终判定等价。

验证报告中的关键字段：

```text
input_space_equal
old_input_subset_new
new_input_subset_old
semantic_definition
semantic_modes
matches
reverse_matches
smt_calls
t_smt
t_align
t_total
```

## 常见问题

### 1. `angr` 或 `claripy` import 失败

说明当前 Python 环境没有装完整依赖。先确认使用的是项目虚拟环境：

```bash
which python
.venv312/bin/python -c "import angr, claripy, z3; print('ok')"
```

### 2. `Python interpreter not found`

构建脚本里的 `--python` 要传真实存在、且安装了 angr 的解释器：

```bash
.venv312/bin/python build_ardiff_path_benchmarks.py \
  --python .venv312/bin/python
```

### 3. evaluation 只输出 dry-run，没有真实结果

需要加 `--execute`：

```bash
.venv312/bin/python run_evaluation.py ... --execute
```

### 4. VeriBin 没有跑起来

本项目默认只保存对 VeriBin 风格 ranking 的适配逻辑。真实 VeriBin 工具在父目录：

```text
../VeriBin
```

如果该目录不存在，或者没有对应配置，`run_evaluation.py` 会使用 benchmark 里已有的 `veribin_ranking_path`。

### 5. PLDI19 工具为什么不在这里

`pldi19-equivalence-checker` 是另一个外部工具，保留在父目录：

```text
../pldi19-equivalence-checker
```

它依赖 x86-64 Linux/STOKE/Pin 环境，Apple Silicon 上的 Docker amd64 模拟通常跑不通。

## 推荐阅读顺序

第一次看项目，可以按这个顺序：

1. `README.md`
2. `scripts/verify_ranked_path_equivalence.py`
3. `src/symbolic_analysis/analysis/path_constraint_features.py`
4. `src/symbolic_analysis/analysis/hybrid_path_matching.py`
5. `build_ardiff_path_benchmarks.py`
6. `run_evaluation.py`

这样可以从“项目怎么跑”逐步看到“路径特征怎么提取、ranking 怎么生成、三层语义怎么验证、最终表格怎么统计”。
