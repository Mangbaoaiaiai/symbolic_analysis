#!/usr/bin/env python3
"""
改进的符号执行脚本，获取路径签名信息

增强版符号执行脚本
- 修复了angr API兼容性问题，改善了路径标识方法
- 添加了关键数组区域的符号化支持
- 增强了数据流分析能力
- 添加了详细的时间记录功能
"""

import angr
import claripy
import re
import os
import glob
import time
import datetime
from claripy.backends.backend_z3 import claripy_solver_to_smt2
import logging

# 设置日志等级
logging.getLogger('angr').setLevel(logging.WARNING)
logging.getLogger('claripy').setLevel(logging.WARNING)

# 全局计数器和状态
scanf_counter = 0
scanf_variables = {}
array_symbols = {}  # 存储数组符号变量
symbolized_arrays = []  # 记录已符号化的数组


class ScanfSymProc(angr.SimProcedure):
    """改进的scanf符号化过程，确保生成有效约束"""

    def run(self, fmt_ptr, *args):
        global scanf_counter, scanf_variables

        # 读取格式字符串
        try:
            fmt_str = self.state.mem[fmt_ptr].string.concrete.decode('utf-8')
        except Exception:
            fmt_str = "%lf"  # 默认单个浮点数

        print(f"scanf格式字符串: {fmt_str}")

        # 计算需要读取的参数数量
        param_count = fmt_str.count('%lf') + fmt_str.count('%f') + fmt_str.count('%d')
        if param_count == 0:
            param_count = 1  # 默认1个参数

        print(f"需要符号化参数数量: {param_count}")

        # 为每个参数创建符号变量并写入对应内存
        for i in range(min(param_count, len(args))):
            # 统一处理：对所有类型使用32位整数表示
            sym_var_bv = claripy.BVS(f'scanf_{scanf_counter}', 32)

            # 添加有意义的约束范围
            self.state.solver.add(sym_var_bv >= 0)
            self.state.solver.add(sym_var_bv <= 15)

            print(f"创建符号变量: scanf_{scanf_counter} (范围: 0-15)")

            # 存储符号变量引用
            scanf_variables[f'scanf_{scanf_counter}'] = sym_var_bv
            scanf_counter += 1

            # 将符号变量写入对应的内存地址
            if i < len(args):
                if '%lf' in fmt_str or '%f' in fmt_str:
                    # 对于double，创建一个简单的浮点表示
                    # 将32位整数值直接当作IEEE754双精度浮点数的位表示
                    # 但为了简化，我们直接扩展到64位
                    double_bits = sym_var_bv.zero_extend(32)  # 扩展到64位
                    self.state.memory.store(
                        args[i],
                        double_bits,
                        endness=self.state.arch.memory_endness
                    )
                    print(f"  写入double(64位)到地址 {args[i]}")
                else:
                    # 对于int，写入4字节（32位）
                    self.state.memory.store(
                        args[i],
                        sym_var_bv,
                        endness=self.state.arch.memory_endness
                    )
                    print(f"  写入int(32位)到地址 {args[i]}")

        # 返回成功读取的参数数量
        return claripy.BVV(min(param_count, len(args)), self.state.arch.bits)


class ArraySymbolizer:
    """数组符号化管理器"""

    def __init__(self, project):
        self.project = project
        self.symbolized_regions = {}

    def symbolize_global_arrays(self, state, array_configs):
        """符号化全局数组

        Args:
            state: angr状态对象
            array_configs: 数组配置列表，格式为 [{'name': 'a', 'size': 128, 'element_size': 4}, ...]
        """
        global array_symbols, symbolized_arrays

        print("开始符号化全局数组...")

        for config in array_configs:
            array_name = config['name']
            array_size = config.get('size', 128)
            element_size = config.get('element_size', 4)  # 默认4字节(int)
            symbolize_range = config.get('symbolize_range', None)  # 可选的符号化范围

            # 查找数组符号
            array_symbol = self.project.loader.find_symbol(array_name)
            if not array_symbol:
                print(f"警告: 未找到数组符号 '{array_name}'")
                continue

            array_addr = array_symbol.rebased_addr
            print(f"找到数组 {array_name} at 0x{array_addr:x}")

            # 确定符号化范围
            if symbolize_range:
                start_idx, end_idx = symbolize_range
                symbolize_size = min(end_idx - start_idx, array_size - start_idx)
                start_addr = array_addr + start_idx * element_size
            else:
                # 默认符号化前16个元素（平衡精度和性能）
                symbolize_size = min(16, array_size)
                start_addr = array_addr
                start_idx = 0

            # 创建符号数组元素
            array_symbols[array_name] = {}

            for i in range(symbolize_size):
                element_addr = start_addr + i * element_size
                symbol_name = f"{array_name}_init_{start_idx + i}"

                # 创建符号变量
                sym_element = claripy.BVS(symbol_name, element_size * 8)

                # 不在初始阶段添加约束，避免过度约束导致路径不可达
                # 约束将在程序执行过程中自然产生

                # 将符号变量存储到内存中，替换原始数组内容
                state.memory.store(
                    element_addr,
                    sym_element,
                    endness=state.arch.memory_endness
                )

                # 记录符号变量
                array_symbols[array_name][start_idx + i] = {
                    'symbol': sym_element,
                    'address': element_addr,
                    'name': symbol_name
                }

            symbolized_arrays.append({
                'name': array_name,
                'start_index': start_idx,
                'symbolized_count': symbolize_size,
                'total_size': array_size
            })

            print(
                f"  已符号化 {array_name}[{start_idx}:{start_idx + symbolize_size}] "
                f"({symbolize_size}/{array_size} 个元素)"
            )

    def symbolize_stack_arrays(self, state, function_name, local_arrays):
        """符号化栈上的局部数组"""
        print(f"符号化函数 {function_name} 的局部数组...")

        # 这里可以根据需要实现局部数组的符号化
        # 通常需要分析函数的栈帧布局
        pass

    def get_array_constraints(self, state):
        """获取与数组相关的约束"""
        array_constraints = []

        for array_name, elements in array_symbols.items():
            for idx, element_info in elements.items():
                symbol = element_info['symbol']
                # 查找涉及该符号的约束
                for constraint in state.solver.constraints:
                    if symbol in constraint.variables:
                        array_constraints.append({
                            'array': array_name,
                            'index': idx,
                            'constraint': str(constraint),
                            'symbol': element_info['name']
                        })

        return array_constraints


class ImprovedPathAnalyzer:
    """改进的路径分析器 - 支持数组符号化"""

    def __init__(self, binary_path, output_prefix=None, timeout=120,
                 enable_array_symbolization=True, array_configs=None):
        self.binary_path = binary_path
        self.timeout = timeout
        self.project = None
        self.paths_info = []
        self.enable_array_symbolization = enable_array_symbolization
        self.array_symbolizer = None

        # 时间记录相关变量
        self.start_time = None
        self.end_time = None
        self.setup_time = 0.0
        self.exploration_time = 0.0
        self.analysis_time = 0.0
        self.total_time = 0.0

        # 默认数组配置
        self.array_configs = array_configs or [
            {'name': 'a', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 16)},
            {'name': 'b', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 16)},
            {'name': 'c', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 8)},
            {'name': 'd', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 8)},
            {'name': 'e', 'size': 128, 'element_size': 4, 'symbolize_range': (0, 8)},
        ]

        # 设置输出前缀
        if output_prefix is None:
            binary_name = os.path.basename(binary_path)
            self.output_prefix = binary_name
        else:
            self.output_prefix = output_prefix

    def setup_project(self):
        """设置angr项目"""
        self.project = angr.Project(self.binary_path, auto_load_libs=False)

        # Hook所有可能的scanf函数
        scanf_symbols = ['scanf', '__isoc99_scanf', '__isoc23_scanf', '__scanf_chk']
        for symbol in scanf_symbols:
            if self.project.loader.find_symbol(symbol):
                self.project.hook_symbol(symbol, ScanfSymProc())
                print(f"已hook符号: {symbol}")

        # 初始化数组符号化器
        if self.enable_array_symbolization:
            self.array_symbolizer = ArraySymbolizer(self.project)
            print("数组符号化已启用")

    def extract_path_signature(self, state):
        """提取路径的多维签名"""
        signature = {}

        # 1. 符号变量的值（输入参数）
        global scanf_variables, array_symbols
        variable_values = {}
        for var_name, sym_var in scanf_variables.items():
            try:
                # 尝试获取具体值
                if state.solver.satisfiable():
                    val = state.solver.eval(sym_var, cast_to=int)
                    variable_values[var_name] = val
                else:
                    variable_values[var_name] = None
            except Exception:
                variable_values[var_name] = None
        signature['variables'] = variable_values

        # 2. 数组的初始和最终状态
        array_initial_values = {}
        array_final_values = {}
        array_final_expressions = {}

        for array_name, elements in array_symbols.items():
            array_initial_values[array_name] = {}
            array_final_values[array_name] = {}
            array_final_expressions[array_name] = {}

            for idx, element_info in elements.items():
                try:
                    # 获取初始符号变量的值
                    if state.solver.satisfiable():
                        initial_val = state.solver.eval(element_info['symbol'], cast_to=int)
                        array_initial_values[array_name][idx] = initial_val
                    else:
                        array_initial_values[array_name][idx] = None

                    # 从内存中读取最终状态
                    final_expr = state.memory.load(
                        element_info['address'],
                        4,  # 4字节整数
                        endness=state.arch.memory_endness
                    )

                    # 获取最终值和表达式
                    if state.solver.satisfiable():
                        final_val = state.solver.eval(final_expr, cast_to=int)
                        array_final_values[array_name][idx] = final_val
                        # 保存符号表达式的字符串表示
                        array_final_expressions[array_name][idx] = str(final_expr)
                    else:
                        array_final_values[array_name][idx] = None
                        array_final_expressions[array_name][idx] = "unsatisfiable"

                except Exception as e:
                    array_initial_values[array_name][idx] = None
                    array_final_values[array_name][idx] = None
                    array_final_expressions[array_name][idx] = f"error: {str(e)}"

        signature['array_initial_values'] = array_initial_values
        signature['array_final_values'] = array_final_values
        signature['array_final_expressions'] = array_final_expressions

        # 保持向后兼容性
        signature['array_values'] = array_initial_values

        # 3. 约束的数量和类型
        constraint_info = {
            'count': len(state.solver.constraints),
            'types': [],
            'array_related_count': 0
        }

        # 收集所有数组符号变量
        array_symbols_set = set()
        for array_name, elements in array_symbols.items():
            for element_info in elements.values():
                array_symbols_set.add(element_info['symbol'])

        for constraint in state.solver.constraints:
            # 分析约束类型
            constraint_str = str(constraint)
            if 'ULE' in constraint_str or 'ULT' in constraint_str:
                constraint_info['types'].append('unsigned_comparison')
            elif 'SLE' in constraint_str or 'SLT' in constraint_str:
                constraint_info['types'].append('signed_comparison')
            elif '==' in constraint_str:
                constraint_info['types'].append('equality')
            elif '!=' in constraint_str:
                constraint_info['types'].append('inequality')
            else:
                constraint_info['types'].append('other')

            # 检查是否与数组变量相关
            if any(sym in constraint.variables for sym in array_symbols_set):
                constraint_info['array_related_count'] += 1

        signature['constraints'] = constraint_info

        # 4. 数组相关约束详情
        if self.array_symbolizer:
            signature['array_constraints'] = self.array_symbolizer.get_array_constraints(state)
        else:
            signature['array_constraints'] = []

        # 5. 程序输出
        try:
            output = state.posix.dumps(1).decode(errors='ignore').strip()
            signature['output'] = output
        except Exception:
            signature['output'] = ""

        # 6. 内存状态的哈希（增强版）
        try:
            # 获取一些关键内存位置的状态
            constraint_hash = hash(str(state.solver.constraints)[:200])
            array_hash = hash(str(array_final_values)[:100])
            signature['memory_hash'] = constraint_hash ^ array_hash
        except Exception:
            signature['memory_hash'] = 0

        return signature

    def run_symbolic_execution(self):
        """运行符号执行"""
        print(f"开始符号执行: {self.binary_path}")
        print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 记录总开始时间
        self.start_time = time.time()

        # 重置全局变量
        global scanf_counter, scanf_variables, array_symbols, symbolized_arrays
        scanf_counter = 0
        scanf_variables = {}
        array_symbols = {}
        symbolized_arrays = []

        # 设置项目 - 记录设置时间
        setup_start = time.time()
        self.setup_project()

        if self.project is None:
            print("项目初始化失败")
            return []

        # 创建初始状态 - 支持浮点数符号执行
        initial_state = self.project.factory.entry_state(
            add_options={
                angr.options.SYMBOL_FILL_UNCONSTRAINED_MEMORY,
                angr.options.SYMBOL_FILL_UNCONSTRAINED_REGISTERS
            }
        )

        # 符号化数组（如果启用）
        if self.enable_array_symbolization and self.array_symbolizer:
            print("正在符号化关键数组...")
            self.array_symbolizer.symbolize_global_arrays(initial_state, self.array_configs)
            print(f"已符号化 {len(symbolized_arrays)} 个数组")

        self.setup_time = time.time() - setup_start
        print(f"项目设置完成，耗时: {self.setup_time:.3f} 秒")

        # 创建仿真管理器
        simgr = self.project.factory.simulation_manager(initial_state)

        # 运行符号执行 - 记录探索时间
        print("开始探索路径...")
        exploration_start = time.time()
        simgr.run(timeout=self.timeout)
        self.exploration_time = time.time() - exploration_start

        print(f"路径探索完成，耗时: {self.exploration_time:.3f} 秒")
        print(f"符号执行完成：")
        print(f"  终止路径数: {len(simgr.deadended)}")
        print(f"  活跃路径数: {len(simgr.active)}")
        print(f"  错误路径数: {len(simgr.errored)}")

        # 处理所有终止状态 - 记录分析时间
        print("开始分析路径状态...")
        analysis_start = time.time()
        self.analyze_deadended_states(simgr.deadended)
        self.analysis_time = time.time() - analysis_start

        # 记录总结束时间
        self.end_time = time.time()
        self.total_time = self.end_time - self.start_time

        # 打印时间统计
        print(f"\n⏱️  符号执行时间统计:")
        print(f"  开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  结束时间: {datetime.datetime.fromtimestamp(self.end_time).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  项目设置: {self.setup_time:.3f} 秒")
        print(f"  路径探索: {self.exploration_time:.3f} 秒")
        print(f"  状态分析: {self.analysis_time:.3f} 秒")
        print(f"  总计时间: {self.total_time:.3f} 秒")
        print(f"  探索效率: {len(self.paths_info)/max(1, self.exploration_time):.2f} 路径/秒")

        # 生成时间报告
        self.generate_timing_report()

        return self.paths_info

    def analyze_deadended_states(self, deadended_states):
        """分析所有终止状态"""
        for i, state in enumerate(deadended_states):
            print(f"\n分析路径 {i + 1}...")

            # 提取路径签名
            signature = self.extract_path_signature(state)

            # 生成SMT约束
            smt_constraints = self.generate_smt_constraints(state)

            # 保存路径信息
            path_info = {
                'index': i + 1,
                'signature': signature,
                'smt_constraints': smt_constraints,
                'state': state  # 保留状态引用以便后续分析
            }

            self.paths_info.append(path_info)

            # 保存到文件
            self.save_path_to_file(path_info)

            # 打印摘要
            print(f"  输入变量值: {signature['variables']}")
            if signature.get('array_initial_values'):
                print(f"  数组初始值: {signature['array_initial_values']}")
            if signature.get('array_final_values'):
                print(f"  数组最终值: {signature['array_final_values']}")
            if signature.get('array_final_expressions') and any(signature['array_final_expressions'].values()):
                # 只显示非零或有变化的表达式
                changed_expressions = {}
                for array_name, expressions in signature['array_final_expressions'].items():
                    for idx, expr in expressions.items():
                        if expr and not expr.startswith('0x') and expr != '0':
                            if array_name not in changed_expressions:
                                changed_expressions[array_name] = {}
                            changed_expressions[array_name][idx] = expr
                if changed_expressions:
                    print(f"  数组符号表达式: {changed_expressions}")
            print(
                f"  约束数量: {signature['constraints']['count']} "
                f"(数组相关: {signature['constraints']['array_related_count']})"
            )
            if signature['array_constraints']:
                print(f"  数组约束数: {len(signature['array_constraints'])}")
            print(f"  程序输出: {signature['output']}")

    def generate_smt_constraints(self, state):
        """生成SMT约束"""
        try:
            solver = claripy.Solver()
            for constraint in state.solver.constraints:
                solver.add(constraint)
            smt2_text = claripy_solver_to_smt2(solver)
            return smt2_text
        except Exception as e:
            print(f"生成SMT约束失败: {e}")
            return ""

    def save_path_to_file(self, path_info):
        """保存路径信息到文件"""
        # 将约束文件保存在可执行文件所在目录
        binary_dir = os.path.dirname(os.path.abspath(self.binary_path))
        filename = os.path.join(binary_dir, f"{self.output_prefix}_path_{path_info['index']}.txt")

        with open(filename, "w", encoding='utf-8') as f:
            f.write(path_info['smt_constraints'])
            f.write("\n; 路径签名信息:\n")
            f.write(f"; 输入变量值: {path_info['signature']['variables']}\n")
            if path_info['signature'].get('array_initial_values'):
                f.write(f"; 数组初始值: {path_info['signature']['array_initial_values']}\n")
            if path_info['signature'].get('array_final_values'):
                f.write(f"; 数组最终值: {path_info['signature']['array_final_values']}\n")
            if path_info['signature'].get('array_final_expressions'):
                f.write(f"; 数组符号表达式: {path_info['signature']['array_final_expressions']}\n")
            f.write(f"; 约束信息: {path_info['signature']['constraints']}\n")
            if path_info['signature']['array_constraints']:
                f.write(f"; 数组约束数量: {len(path_info['signature']['array_constraints'])}\n")
                f.write("; 数组约束详情:\n")
                for i, ac in enumerate(path_info['signature']['array_constraints'][:5]):  # 只显示前5个
                    f.write(f";   {i+1}. {ac['array']}[{ac['index']}]: {ac['constraint'][:100]}...\n")
            f.write(f"; 内存哈希: {path_info['signature']['memory_hash']}\n")

            # 添加时间信息
            f.write("; \n")
            f.write("; 时间信息:\n")
            f.write(
                "; 符号执行开始时间: "
                f"{datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S') if self.start_time else 'N/A'}\n"
            )
            f.write(f"; 总探索时间: {self.total_time:.3f} 秒\n")
            f.write(f"; 项目设置时间: {self.setup_time:.3f} 秒\n")
            f.write(f"; 路径探索时间: {self.exploration_time:.3f} 秒\n")
            f.write(f"; 状态分析时间: {self.analysis_time:.3f} 秒\n")
            f.write(f"; 路径索引: {path_info['index']}/{len(self.paths_info)}\n")

            f.write("; 程序输出:\n")
            f.write(path_info['signature']['output'])

        print(f"  已保存到: {filename}")

    def generate_timing_report(self):
        """生成详细的时间报告"""
        # 保存时间报告到可执行文件所在目录
        binary_dir = os.path.dirname(os.path.abspath(self.binary_path))
        report_filename = os.path.join(binary_dir, f"{self.output_prefix}_timing_report.txt")

        with open(report_filename, "w", encoding='utf-8') as f:
            f.write("符号执行时间报告\n")
            f.write("=" * 50 + "\n\n")

            f.write(f"分析程序: {self.binary_path}\n")
            f.write(f"输出前缀: {self.output_prefix}\n")
            f.write(f"超时设置: {self.timeout} 秒\n")
            f.write(f"数组符号化: {'启用' if self.enable_array_symbolization else '禁用'}\n\n")

            f.write("时间统计:\n")
            f.write("-" * 30 + "\n")
            f.write(f"开始时间: {datetime.datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"结束时间: {datetime.datetime.fromtimestamp(self.end_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"项目设置时间: {self.setup_time:.3f} 秒 ({self.setup_time/self.total_time*100:.1f}%)\n")
            f.write(f"路径探索时间: {self.exploration_time:.3f} 秒 ({self.exploration_time/self.total_time*100:.1f}%)\n")
            f.write(f"状态分析时间: {self.analysis_time:.3f} 秒 ({self.analysis_time/self.total_time*100:.1f}%)\n")
            f.write(f"总计时间: {self.total_time:.3f} 秒\n\n")

            f.write("分析结果:\n")
            f.write("-" * 30 + "\n")
            f.write(f"发现路径数: {len(self.paths_info)}\n")
            f.write(f"探索效率: {len(self.paths_info)/max(1, self.exploration_time):.2f} 路径/秒\n")
            f.write(f"平均路径分析时间: {self.analysis_time/max(1, len(self.paths_info)):.3f} 秒/路径\n\n")

            if self.enable_array_symbolization:
                f.write("数组符号化信息:\n")
                f.write("-" * 30 + "\n")
                for i, array_info in enumerate(symbolized_arrays):
                    f.write(
                        f"{i+1}. {array_info['name']}: "
                        f"{array_info['symbolized_count']}/{array_info['total_size']} 个元素\n"
                    )
                f.write("\n")

            f.write("生成的文件:\n")
            f.write("-" * 30 + "\n")
            for i in range(len(self.paths_info)):
                f.write(f"{self.output_prefix}_path_{i+1}.txt\n")

        print(f"📄 时间报告已保存到: {report_filename}")

    def get_timing_info(self):
        """获取时间统计信息（供外部调用）"""
        return {
            'start_time': self.start_time,
            'end_time': self.end_time,
            'setup_time': self.setup_time,
            'exploration_time': self.exploration_time,
            'analysis_time': self.analysis_time,
            'total_time': self.total_time,
            'paths_count': len(self.paths_info),
            'exploration_efficiency': len(self.paths_info) / max(1, self.exploration_time)
        }


class BenchmarkAnalyzer:
    """benchmark批量分析器"""

    def __init__(self, benchmark_dir, timeout=120):
        self.benchmark_dir = benchmark_dir
        self.timeout = timeout
        self.results = {}
        self.timing_stats = {}  # 添加时间统计
        self.total_start_time = None
        self.total_end_time = None

    def find_binary_files(self):
        """查找benchmark目录中的二进制文件"""
        # 查找不同优化等级的二进制文件
        pattern = os.path.join(self.benchmark_dir, "*_O[0123]")
        binary_files = glob.glob(pattern)

        # 过滤掉.c文件
        binary_files = [f for f in binary_files if not f.endswith('.c')]

        return sorted(binary_files)

    def analyze_all_binaries(self):
        """分析所有二进制文件"""
        self.total_start_time = time.time()
        print(f"批量分析开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        binary_files = self.find_binary_files()

        if not binary_files:
            print(f"在 {self.benchmark_dir} 中未找到二进制文件")
            return

        print(f"发现 {len(binary_files)} 个二进制文件:")
        for binary in binary_files:
            print(f"  {binary}")

        # 为每个二进制文件运行符号执行
        for i, binary_path in enumerate(binary_files, 1):
            print(f"\n{'='*60}")
            print(f"正在分析 ({i}/{len(binary_files)}): {binary_path}")
            print(f"{'='*60}")

            # 提取优化等级作为前缀
            basename = os.path.basename(binary_path)
            output_prefix = basename

            # 记录单个分析开始时间
            single_start_time = time.time()

            try:
                # 重置全局变量
                global scanf_counter, scanf_variables
                scanf_counter = 0
                scanf_variables = {}

                analyzer = ImprovedPathAnalyzer(binary_path, output_prefix, self.timeout)
                results = analyzer.run_symbolic_execution()
                self.results[basename] = results

                # 记录时间统计
                single_end_time = time.time()
                single_total_time = single_end_time - single_start_time
                timing_info = analyzer.get_timing_info()
                timing_info['single_total_time'] = single_total_time
                self.timing_stats[basename] = timing_info

                print(f"✅ 完成分析 {basename}: 共 {len(results)} 条路径，耗时 {single_total_time:.3f} 秒")

            except Exception as e:
                print(f"❌ 分析 {basename} 时出错: {e}")
                self.results[basename] = []
                self.timing_stats[basename] = {
                    'error': str(e),
                    'single_total_time': time.time() - single_start_time
                }

        self.total_end_time = time.time()
        total_batch_time = self.total_end_time - self.total_start_time

        print(f"\n📊 批量分析完成!")
        print(f"总耗时: {total_batch_time:.3f} 秒")
        print(f"平均每个程序: {total_batch_time/len(binary_files):.3f} 秒")
        print(f"结束时间: {datetime.datetime.fromtimestamp(self.total_end_time).strftime('%Y-%m-%d %H:%M:%S')}")

        return self.results

    def generate_summary_report(self):
        """生成分析摘要报告"""
        report_file = os.path.join(self.benchmark_dir, "symbolic_execution_summary.txt")

        with open(report_file, "w", encoding='utf-8') as f:
            f.write("符号执行批量分析摘要报告\n")
            f.write("=" * 50 + "\n\n")

            f.write(f"分析目录: {self.benchmark_dir}\n")
            f.write(f"分析的二进制文件数量: {len(self.results)}\n")
            if self.total_start_time and self.total_end_time:
                total_time = self.total_end_time - self.total_start_time
                f.write(
                    "批量分析开始时间: "
                    f"{datetime.datetime.fromtimestamp(self.total_start_time).strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
                f.write(
                    "批量分析结束时间: "
                    f"{datetime.datetime.fromtimestamp(self.total_end_time).strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
                f.write(f"批量分析总耗时: {total_time:.3f} 秒\n")
                f.write(f"平均每个程序耗时: {total_time/max(1, len(self.results)):.3f} 秒\n")
            f.write("\n")

            # 详细的每个程序分析结果
            f.write("各程序分析详情:\n")
            f.write("-" * 50 + "\n")

            total_paths = 0
            total_exploration_time = 0
            successful_analyses = 0

            for binary_name, paths in self.results.items():
                f.write(f"\n程序: {binary_name}\n")
                f.write(f"  发现路径数: {len(paths)}\n")
                f.write(f"  生成的文件: {binary_name}_path_*.txt\n")

                # 时间统计
                if binary_name in self.timing_stats:
                    timing = self.timing_stats[binary_name]
                    if 'error' in timing:
                        f.write(f"  ❌ 分析失败: {timing['error']}\n")
                        f.write(f"  失败前耗时: {timing['single_total_time']:.3f} 秒\n")
                    else:
                        f.write("  ✅ 分析成功\n")
                        f.write(f"  总耗时: {timing['single_total_time']:.3f} 秒\n")
                        f.write(f"    - 项目设置: {timing['setup_time']:.3f} 秒\n")
                        f.write(f"    - 路径探索: {timing['exploration_time']:.3f} 秒\n")
                        f.write(f"    - 状态分析: {timing['analysis_time']:.3f} 秒\n")
                        f.write(f"  探索效率: {timing['exploration_efficiency']:.2f} 路径/秒\n")

                        total_paths += len(paths)
                        total_exploration_time += timing['exploration_time']
                        successful_analyses += 1

                f.write(f"  时间报告文件: {binary_name}_timing_report.txt\n")

            # 总体统计
            f.write("\n总体统计:\n")
            f.write("-" * 30 + "\n")
            f.write(f"成功分析的程序数: {successful_analyses}/{len(self.results)}\n")
            f.write(f"总共发现路径数: {total_paths}\n")
            if successful_analyses > 0:
                f.write(f"平均每个程序路径数: {total_paths/successful_analyses:.1f}\n")
            if total_exploration_time > 0:
                f.write(f"总路径探索时间: {total_exploration_time:.3f} 秒\n")
                f.write(f"总体探索效率: {total_paths/total_exploration_time:.2f} 路径/秒\n")

            f.write("\n下一步分析建议:\n")
            f.write("-" * 30 + "\n")
            f.write("使用 semantic_equivalence_analyzer.py 进行等价性分析\n")
            f.write("例如: python semantic_equivalence_analyzer.py program1_O1_path_ program1_O2_path_\n")

        print(f"📄 摘要报告已保存到: {report_file}")


def compare_path_collections_improved(analyzer1_results, analyzer2_results):
    """改进的路径集合比较"""
    print("\n开始改进的路径比较...")

    matches = {
        'exact_variable_matches': [],
        'exact_output_matches': [],
        'constraint_structure_matches': [],
        'no_matches': []
    }

    for path1 in analyzer1_results:
        best_match = None
        best_match_type = None
        best_score = float('inf')

        for path2 in analyzer2_results:
            # 1. 检查变量值完全匹配
            if path1['signature']['variables'] == path2['signature']['variables']:
                matches['exact_variable_matches'].append((path1['index'], path2['index']))
                best_match = path2['index']
                best_match_type = 'exact_variable'
                break

            # 2. 检查程序输出匹配
            if (path1['signature']['output'] == path2['signature']['output'] and
                    path1['signature']['output'] != ""):
                if best_match_type != 'exact_variable':
                    matches['exact_output_matches'].append((path1['index'], path2['index']))
                    best_match = path2['index']
                    best_match_type = 'exact_output'

            # 3. 检查约束结构相似性
            constraint_score = abs(
                path1['signature']['constraints']['count'] -
                path2['signature']['constraints']['count']
            )

            if constraint_score < best_score and best_match_type is None:
                best_score = constraint_score
                best_match = path2['index']
                best_match_type = 'constraint_structure'

        if best_match_type == 'constraint_structure':
            matches['constraint_structure_matches'].append((path1['index'], best_match, best_score))
        elif best_match_type is None:
            matches['no_matches'].append(path1['index'])

    # 打印比较结果
    print("\n路径匹配结果:")
    print(f"  精确变量匹配: {len(matches['exact_variable_matches'])} 对")
    print(f"  精确输出匹配: {len(matches['exact_output_matches'])} 对")
    print(f"  约束结构匹配: {len(matches['constraint_structure_matches'])} 对")
    print(f"  无匹配路径: {len(matches['no_matches'])} 个")

    return matches


def main():
    """主函数 - 支持单个文件分析和批量分析"""
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='符号执行分析工具')
    parser.add_argument('--benchmark', help='benchmark目录路径，用于批量分析')
    parser.add_argument('--binary', help='单个二进制文件路径')
    parser.add_argument('--timeout', type=int, default=120, help='符号执行超时时间(秒)')
    parser.add_argument('--output-prefix', help='输出文件前缀')

    args = parser.parse_args()

    if args.benchmark:
        # 批量分析模式
        print(f"开始批量分析benchmark: {args.benchmark}")
        analyzer = BenchmarkAnalyzer(args.benchmark, args.timeout)
        analyzer.analyze_all_binaries()
        analyzer.generate_summary_report()

    elif args.binary:
        # 单个文件分析模式
        print(f"开始分析单个文件: {args.binary}")
        analyzer = ImprovedPathAnalyzer(args.binary, args.output_prefix, args.timeout)
        results = analyzer.run_symbolic_execution()
        print(f"分析完成！共发现 {len(results)} 条路径")

    else:
        # 兼容旧的命令行格式
        if len(sys.argv) >= 2 and not sys.argv[1].startswith('--'):
            binary_path = sys.argv[1]
            analyzer = ImprovedPathAnalyzer(binary_path)
            results = analyzer.run_symbolic_execution()
            print(f"分析完成！共发现 {len(results)} 条路径")
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
