                      
"""
Simple angr test: verify that real constraints can be extracted from conditional branches.
"""

import angr
import claripy

def test_simple_branch():
    print("🔍 Testing constraint extraction from simple conditional branch")
    
              
    project = angr.Project('./simple_branch_test', auto_load_libs=False)
    
             
    state = project.factory.entry_state()
    
              
    x_sym = claripy.BVS('x', 32)
                
    
                          
    simgr = project.factory.simulation_manager(state)
    
    print("Starting symbolic execution...")
    simgr.explore()
    print("Exploration done:")
    print(f"  Found: {len(simgr.found)}")
    print(f"  Active: {len(simgr.active)}")
    print(f"  Deadended: {len(simgr.deadended)}")
    print(f"  Errored: {len(simgr.errored)}")
    all_states = simgr.found + simgr.deadended
    for i, state in enumerate(all_states[:5]):
        print(f"\nPath {i}:")
        constraints = state.solver.constraints
        print(f"  Constraint count: {len(constraints)}")
        for j, constraint in enumerate(constraints):
            print(f"  Constraint {j}: {constraint}")
        try:
            if hasattr(state.solver, 'eval'):
                example_val = state.solver.eval(x_sym, cast_to=int)
                print(f"  Example x value: {example_val}")
        except Exception as e:
            print(f"  Could not get example value: {e}")

if __name__ == "__main__":
    test_simple_branch() 