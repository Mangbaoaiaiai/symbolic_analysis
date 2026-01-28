                      
"""
angr符号执行内存需求分析
分析TSVC benchmark的内存要求并提供优化建议
"""

import os
import psutil
import subprocess

def analyze_current_system():
    """分析当前系统配置"""
    print("🖥️  当前系统配置分析")
    print("=" * 50)
    
          
    memory = psutil.virtual_memory()
    print(f"📊 内存信息:")
    print(f"   总内存: {memory.total / (1024**3):.1f} GB")
    print(f"   可用内存: {memory.available / (1024**3):.1f} GB")
    print(f"   已用内存: {memory.used / (1024**3):.1f} GB")
    print(f"   内存使用率: {memory.percent:.1f}%")
    
           
    print(f"\n🔧 CPU信息:")
    print(f"   CPU核心数: {psutil.cpu_count(logical=False)} 物理核心")
    print(f"   逻辑核心数: {psutil.cpu_count(logical=True)} 逻辑核心")
    
    return memory.total / (1024**3), memory.available / (1024**3)

def analyze_angr_memory_requirements():
    """分析angr符号执行的内存需求"""
    print(f"\n🧠 angr符号执行内存需求分析")
    print("=" * 50)
    
    requirements = {
        "简单程序": {
            "基础内存": "1-2 GB",
            "路径数": "< 100",
            "执行时间": "< 5分钟",
            "适用场景": "单循环，简单条件"
        },
        "中等程序": {
            "基础内存": "4-8 GB", 
            "路径数": "100-1000",
            "执行时间": "5-30分钟",
            "适用场景": "嵌套循环，数组操作"
        },
        "复杂程序": {
            "基础内存": "16-32 GB",
            "路径数": "1000-10000",
            "执行时间": "30分钟-数小时",
            "适用场景": "复杂算法，多重依赖"
        },
        "大型程序": {
            "基础内存": "64+ GB",
            "路径数": "10000+",
            "执行时间": "数小时-数天",
            "适用场景": "完整应用程序"
        }
    }
    
    print("📊 不同复杂度程序的内存需求:")
    for category, info in requirements.items():
        print(f"\n🔹 {category}:")
        for key, value in info.items():
            print(f"   {key}: {value}")
    
    return requirements

def analyze_tsvc_specific_requirements():
    """分析TSVC benchmark的具体需求"""
    print(f"\n🎯 TSVC Benchmark具体内存需求")
    print("=" * 50)
    
    tsvc_analysis = {
        "s000": {
            "描述": "a[i] = b[i] + 1 (简单向量加法)",
            "预估内存": "2-4 GB",
            "路径复杂度": "低",
            "优化建议": "适合作为测试起点"
        },
        "s121": {
            "描述": "a[i] = a[i+1] + b[i] (数据依赖)",
            "预估内存": "4-8 GB",
            "路径复杂度": "中",
            "优化建议": "需要限制循环次数"
        },
        "s2244": {
            "描述": "复杂赋值操作",
            "预估内存": "8-16 GB",
            "路径复杂度": "高",
            "优化建议": "需要大内存机器"
        },
        "所有benchmark": {
            "描述": "完整测试套件",
            "预估内存": "32+ GB",
            "路径复杂度": "极高",
            "优化建议": "需要高端服务器"
        }
    }
    
    for benchmark, info in tsvc_analysis.items():
        print(f"\n📋 {benchmark}:")
        for key, value in info.items():
            print(f"   {key}: {value}")
    
    return tsvc_analysis

def memory_optimization_strategies():
    """内存优化策略"""
    print(f"\n🚀 内存优化策略")
    print("=" * 50)
    
    strategies = {
        "程序简化": [
            "减小数组大小 (LEN=8 而不是 128)",
            "限制循环次数 (count=1)",
            "移除不必要的全局变量",
            "使用静态链接减少库依赖"
        ],
        "angr配置优化": [
            "限制最大路径数 (max_paths=5-10)",
            "设置超时时间 (timeout=60s)",
            "启用LAZY_SOLVES优化",
            "使用ZERO_FILL_UNCONSTRAINED_MEMORY",
            "限制符号执行深度"
        ],
        "系统级优化": [
            "增加交换空间",
            "关闭不必要的服务",
            "使用内存映射文件",
            "启用内存压缩"
        ],
        "分批处理": [
            "一次只分析一个benchmark",
            "每个优化级别单独处理",
            "实时清理中间结果",
            "增量保存状态"
        ]
    }
    
    for category, items in strategies.items():
        print(f"\n🔧 {category}:")
        for item in items:
            print(f"   • {item}")

def recommend_machine_specs(total_memory, available_memory):
    """推荐机器配置"""
    print(f"\n💻 机器配置推荐")
    print("=" * 50)
    
    print(f"📊 当前配置: {total_memory:.1f}GB 总内存, {available_memory:.1f}GB 可用")
    
    recommendations = {
        "最小配置(测试)": {
            "内存": "8-16 GB",
            "用途": "单个简单benchmark",
            "成本": "较低",
            "适用场景": "概念验证、学习"
        },
        "推荐配置(开发)": {
            "内存": "32-64 GB", 
            "用途": "多个benchmark，完整分析",
            "成本": "中等",
            "适用场景": "研究开发、论文实验"
        },
        "高端配置(生产)": {
            "内存": "128+ GB",
            "用途": "完整TSVC套件，大规模分析",
            "成本": "较高", 
            "适用场景": "工业应用、大规模研究"
        }
    }
    
    for config, specs in recommendations.items():
        print(f"\n🖥️  {config}:")
        for key, value in specs.items():
            print(f"   {key}: {value}")
    
                
    if total_memory < 16:
        print(f"\n⚠️  当前内存不足建议:")
        print(f"   • 优先使用增强模拟模式")
        print(f"   • 如需真实符号执行，建议升级到16GB+")
    elif total_memory < 32:
        print(f"\n✅ 当前内存适中建议:")
        print(f"   • 可以运行简单benchmark的真实符号执行")
        print(f"   • 建议一次只分析一个benchmark")
    else:
        print(f"\n🎉 当前内存充足:")
        print(f"   • 可以运行多个benchmark的真实符号执行")

def create_optimized_analysis_script():
    """创建优化的分析脚本"""
    script_content = '''#!/usr/bin/env python3
"""
内存优化的TSVC符号执行脚本
"""

import angr
import os
import gc
import psutil

def memory_aware_analysis(binary_path, max_memory_gb=4):
    """内存感知的符号执行"""
    
    def check_memory():
        """检查内存使用"""
        memory = psutil.virtual_memory()
        used_gb = memory.used / (1024**3)
        return used_gb < max_memory_gb
    
    # 创建angr项目
    project = angr.Project(str(binary_path), auto_load_libs=False)
    
    # 优化的状态配置
    state = project.factory.entry_state()
    state.options.add(angr.options.LAZY_SOLVES)
    state.options.add(angr.options.ZERO_FILL_UNCONSTRAINED_MEMORY)
    state.options.add(angr.options.AVOID_MULTIVALUED_READS)
    
    # 创建内存限制的simulation manager
    simgr = project.factory.simulation_manager(state)
    
    paths = []
    step_count = 0
    max_steps = 20  # 限制步数
    
    while simgr.active and step_count < max_steps:
        if not check_memory():
            print(f"内存不足，停止符号执行")
            break
            
        simgr.step()
        step_count += 1
        
        # 定期清理内存
        if step_count % 5 == 0:
            gc.collect()
    
    # 收集结果
    for state in simgr.deadended + simgr.active:
        if len(paths) >= 5:  # 限制路径数
            break
        paths.append(extract_constraints(state))
    
    return paths

def extract_constraints(state):
    """提取约束（简化版）"""
    try:
        constraints = state.solver.constraints
        return {
            'constraint_count': len(constraints),
            'constraints': [str(c)[:100] for c in constraints[:5]]  # 只取前5个，截断长度
        }
    except:
        return {'constraint_count': 0, 'constraints': []}

if __name__ == "__main__":
    # 使用示例
    # result = memory_aware_analysis("path/to/binary", max_memory_gb=6)
    print("内存优化的符号执行脚本已准备就绪")
'''
    
    with open('memory_optimized_analysis.py', 'w') as f:
        f.write(script_content)
    
    print(f"\n📄 已生成优化脚本: memory_optimized_analysis.py")

def main():
    """主分析函数"""
    print("🔍 angr符号执行内存需求完整分析")
    print("=" * 60)
    
            
    total_mem, avail_mem = analyze_current_system()
    
              
    analyze_angr_memory_requirements()
    
                
    analyze_tsvc_specific_requirements() 
    
          
    memory_optimization_strategies()
    
          
    recommend_machine_specs(total_mem, avail_mem)
    
            
    create_optimized_analysis_script()
    
    print(f"\n🎯 总结建议:")
    print(f"   💰 预算有限: 使用增强模拟模式(已实现)")
    print(f"   🔬 研究需要: 升级到32GB+内存机器") 
    print(f"   🏭 生产环境: 使用128GB+高端服务器")
    print(f"   📊 当前可行: 单个简单benchmark的真实符号执行")

if __name__ == "__main__":
    main() 