                      
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
    
              
    project = angr.Project(str(binary_path), auto_load_libs=False)
    
             
    state = project.factory.entry_state()
    state.options.add(angr.options.LAZY_SOLVES)
    state.options.add(angr.options.ZERO_FILL_UNCONSTRAINED_MEMORY)
    state.options.add(angr.options.AVOID_MULTIVALUED_READS)
    
                               
    simgr = project.factory.simulation_manager(state)
    
    paths = []
    step_count = 0
    max_steps = 20        
    
    while simgr.active and step_count < max_steps:
        if not check_memory():
            print(f"内存不足，停止符号执行")
            break
            
        simgr.step()
        step_count += 1
        
                
        if step_count % 5 == 0:
            gc.collect()
    
          
    for state in simgr.deadended + simgr.active:
        if len(paths) >= 5:         
            break
        paths.append(extract_constraints(state))
    
    return paths

def extract_constraints(state):
    """提取约束（简化版）"""
    try:
        constraints = state.solver.constraints
        return {
            'constraint_count': len(constraints),
            'constraints': [str(c)[:100] for c in constraints[:5]]              
        }
    except:
        return {'constraint_count': 0, 'constraints': []}

if __name__ == "__main__":
          
                                                                       
    print("内存优化的符号执行脚本已准备就绪")
