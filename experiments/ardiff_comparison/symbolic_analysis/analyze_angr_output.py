                      
"""
分析angr如何在没有具体输入的情况下生成输出
"""

import angr
import claripy

def analyze_angr_output():
    print("=== 分析angr输出生成机制 ===")
    
            
    project = angr.Project('./test_angr_output', auto_load_libs=False)
    
                  
    class ScanfHook(angr.SimProcedure):
        def run(self, fmt_ptr, *args):
                    
            sym_var = claripy.BVS('input_x', 32)
                  
            self.state.solver.add(sym_var >= 0)
            self.state.solver.add(sym_var <= 15)
                   
            self.state.memory.store(args[0], sym_var)
            return 1
    
                
    project.hook_symbol('scanf', ScanfHook())
    
            
    state = project.factory.entry_state()
    
             
    simgr = project.factory.simulation_manager(state)
    
            
    simgr.run()
    
    print(f"发现 {len(simgr.deadended)} 个终止状态")
    
              
    for i, state in enumerate(simgr.deadended):
        print(f"\n--- 路径 {i+1} ---")
        
              
        output = state.posix.dumps(1).decode(errors='ignore').strip()
        print(f"程序输出: {output}")
        
              
        constraints = state.solver.constraints
        print(f"约束数量: {len(constraints)}")
        
              
        for j, constraint in enumerate(constraints):
            print(f"  约束{j+1}: {constraint}")
        
                 
        if state.solver.satisfiable():
            try:
                          
                input_var = state.solver.BVS('input_x', 32)
                input_value = state.solver.eval(input_var, cast_to=int)
                print(f"输入值: {input_value}")
            except:
                print("无法求解输入值")
        else:
            print("约束不可满足")

if __name__ == "__main__":
    analyze_angr_output()
