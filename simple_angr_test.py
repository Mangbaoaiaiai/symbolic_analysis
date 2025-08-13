#!/usr/bin/env python3
"""
简单的angr测试：验证是否能从条件分支中提取真实约束
"""

import angr
import claripy

def test_simple_branch():
    print("🔍 测试简单条件分支的约束提取")
    
    # 创建angr项目
    project = angr.Project('./simple_branch_test', auto_load_libs=False)
    
    # 创建符号化状态
    state = project.factory.entry_state()
    
    # 符号化命令行参数
    x_sym = claripy.BVS('x', 32)
    # 不添加任何人工约束！
    
    # 创建simulation manager
    simgr = project.factory.simulation_manager(state)
    
    print("开始符号执行...")
    
    # 探索所有路径
    simgr.explore()
    
    print(f"探索完成:")
    print(f"  找到的路径: {len(simgr.found)}")
    print(f"  活跃的路径: {len(simgr.active)}")
    print(f"  死锁的路径: {len(simgr.deadended)}")
    print(f"  错误的路径: {len(simgr.errored)}")
    
    # 分析每条路径的约束
    all_states = simgr.found + simgr.deadended
    
    for i, state in enumerate(all_states[:5]):  # 最多分析5条路径
        print(f"\n路径 {i}:")
        constraints = state.solver.constraints
        print(f"  约束数量: {len(constraints)}")
        
        for j, constraint in enumerate(constraints):
            print(f"  约束 {j}: {constraint}")
        
        # 尝试求解一个具体值
        try:
            if hasattr(state.solver, 'eval'):
                example_val = state.solver.eval(x_sym, cast_to=int) 
                print(f"  示例x值: {example_val}")
        except Exception as e:
            print(f"  无法求解示例值: {e}")

if __name__ == "__main__":
    test_simple_branch() 