# 批量符号执行分析工具使用说明

## 概述

`batch_symbolic_execution.py` 是一个自动化批量符号执行分析工具，能够：

1. 自动发现所有 `benchmark_temp_*` 目录
2. 对每个目录中的二进制文件运行符号执行分析
3. 记录详细的时间统计信息
4. 生成综合分析报告

## 基本用法

### 分析所有benchmark
```bash
python batch_symbolic_execution.py
```

### 设置超时时间（默认60秒）
```bash
python batch_symbolic_execution.py --timeout 120
```

### 指定符号执行脚本路径
```bash
python batch_symbolic_execution.py --se-script ./se_script.py
```

### 指定根目录
```bash
python batch_symbolic_execution.py --root-dir /path/to/benchmarks
```

## 高级用法

### 组合参数
```bash
# 设置2分钟超时，使用自定义脚本
python batch_symbolic_execution.py --timeout 120 --se-script enhanced_se_script.py

# 分析特定目录下的benchmark
python batch_symbolic_execution.py --root-dir ./custom_benchmarks --timeout 90
```

### 后台运行
```bash
# 后台运行并记录日志
nohup python batch_symbolic_execution.py --timeout 180 > batch_analysis.log 2>&1 &

# 查看进度
tail -f batch_analysis.log
```

## 输出文件

### 1. 综合报告 (`batch_symbolic_execution_report.txt`)
包含：
- 总体统计信息（成功率、总路径数、时间等）
- 各benchmark详细分析结果
- 失败分析总结
- 性能排行榜

### 2. 详细数据 (`batch_symbolic_execution_data.json`)
包含：
- 所有分析结果的结构化数据
- 可用于后续数据分析和可视化

### 3. 各程序的符号执行结果
- 路径约束文件：`{program}_path_{N}.txt`
- 时间报告：`{program}_timing_report.txt`

## 示例输出

```
🚀 开始批量符号执行分析
============================================================
开始时间: 2025-08-03 22:20:15
📋 发现 12 个 benchmark 目录:
  1. benchmark_temp_s000
  2. benchmark_temp_s121
  ...

🔄 进度: 1/12
📁 分析 benchmark: benchmark_temp_s000
============================================================
  发现 4 个二进制文件:
    - s000_O0
    - s000_O1
    - s000_O2
    - s000_O3
  正在分析: s000_O0
    执行命令: python se_script.py --binary benchmark_temp_s000/s000_O0 --timeout 60
    ✅ 成功: 发现 16 条路径 (耗时: 25.3s)
  ...
```

## 监控和调试

### 查看实时进度
在另一个终端中：
```bash
# 查看当前正在分析的文件
ps aux | grep se_script.py

# 查看生成的路径文件数量
find . -name "*_path_*.txt" | wc -l

# 监控内存使用
top -p $(pgrep -f batch_symbolic_execution.py)
```

### 处理异常情况

#### 超时问题
如果某些程序分析时间过长：
```bash
# 增加超时时间
python batch_symbolic_execution.py --timeout 300
```

#### 内存不足
```bash
# 限制并发，一个一个分析（脚本已经这样设计）
# 或者分批处理大型benchmark

# 清理临时文件
find . -name "*_path_*.txt" -size +100M -delete
```

#### 中断恢复
脚本被中断后，可以删除已完成的benchmark目录，只分析剩余的：
```bash
# 移动已完成的目录
mkdir completed_benchmarks
mv benchmark_temp_s000 completed_benchmarks/

# 重新运行
python batch_symbolic_execution.py
```

## 结果分析

### 查看总体统计
```bash
head -30 batch_symbolic_execution_report.txt
```

### 找出表现最好的程序
```bash
grep -A10 "路径数TOP5" batch_symbolic_execution_report.txt
```

### 查看失败的分析
```bash
grep -A20 "失败分析总结" batch_symbolic_execution_report.txt
```

### 用JSON数据进行深度分析
```python
import json

# 加载数据
with open('batch_symbolic_execution_data.json') as f:
    data = json.load(f)

# 分析成功率
successful = data['successful_analyses']
failed = data['failed_analyses']
print(f"成功率: {len(successful)/(len(successful)+len(failed))*100:.1f}%")

# 分析路径数分布
path_counts = [r['paths_found'] for r in successful]
print(f"平均路径数: {sum(path_counts)/len(path_counts):.1f}")
```

## 注意事项

1. **磁盘空间**：确保有足够空间存储生成的路径文件（每个路径文件可能几KB到几MB）

2. **时间规划**：大型benchmark可能需要数小时完成，建议：
   - 先用小超时时间测试
   - 使用 `nohup` 后台运行
   - 定期检查进度

3. **系统资源**：符号执行是CPU和内存密集型任务：
   - 监控系统负载
   - 避免同时运行其他重型任务
   - 考虑在空闲时间运行

4. **错误恢复**：如果脚本崩溃：
   - 检查 `batch_analysis.log` 日志
   - 清理可能损坏的输出文件
   - 重新运行（会跳过已完成的）

## 自定义和扩展

### 修改分析参数
编辑 `se_script.py` 中的参数：
- 数组符号化范围
- 约束求解超时
- 输入变量范围

### 添加新的分析指标
在 `batch_symbolic_execution.py` 中的 `run_symbolic_execution` 方法中添加解析逻辑。

### 过滤特定benchmark
```python
# 在脚本中添加过滤逻辑
benchmark_dirs = [d for d in benchmark_dirs if 's000' in d]
``` 