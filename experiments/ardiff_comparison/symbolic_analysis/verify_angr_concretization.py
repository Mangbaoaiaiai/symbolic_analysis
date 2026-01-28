                      
"""
验证angr的具体化过程
"""

import angr
import claripy

def verify_concretization():
    print("=== 验证angr具体化过程 ===")
    
            
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
    
                                  
    if len(simgr.deadended) >= 3:
        state = simgr.deadended[2]                           
        
        print(f"\n--- 分析路径3 (对应Bess路径2) ---")
        
              
        output = state.posix.dumps(1).decode(errors='ignore').strip()
        print(f"程序输出: {output}")
        
              
        constraints = state.solver.constraints
        print(f"约束数量: {len(constraints)}")
        
                
        for i, constraint in enumerate(constraints):
            if i >= 10:            
                print(f"  约束{i+1}: {constraint}")
        
                 
        if state.solver.satisfiable():
            print(f"\n--- 求解多个解 ---")
            input_var = state.solver.BVS('input_x', 32)
            
                    
            try:
                sol1 = state.solver.eval(input_var, cast_to=int)
                print(f"解1: {sol1}")
                
                            
                state.solver.add(input_var != sol1)
                
                        
                if state.solver.satisfiable():
                    sol2 = state.solver.eval(input_var, cast_to=int)
                    print(f"解2: {sol2}")
                else:
                    print("没有第二个解")
                    
            except Exception as e:
                print(f"求解失败: {e}")
        else:
            print("约束不可满足")

if __name__ == "__main__":
    verify_concretization()
