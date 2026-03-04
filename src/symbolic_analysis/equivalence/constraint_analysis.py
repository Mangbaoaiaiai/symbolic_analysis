                      
"""
In-depth analysis of path constraints.

Provides a detailed explanation of why the s121 and s000 constraints
are logically equivalent.
"""

from z3 import *

def analyze_constraint_semantics():
    """Explain the semantic meaning of the constraints."""
    print("=" * 80)
    print("Deep path-constraint analysis: s121_O1_path_1.txt vs s000_O1_path_1.txt")
    print("=" * 80)
    
          
    scanf_0_1_32 = BitVec('scanf_0_1_32', 32)
    
                  
    base_constraint1 = UGE(scanf_0_1_32, 0)
    base_constraint2 = ULE(scanf_0_1_32, 10)
    
    print("Base constraints (shared by both files):")
    print(f"  1. scanf_0_1_32 >= 0")
    print(f"  2. scanf_0_1_32 <= 10")
    print(f"  i.e., scanf_0_1_32 ∈ [0, 10]")
    
           
    x38 = ZeroExt(32, scanf_0_1_32)         
    x41 = x38 << 3                              
    x42 = Extract(31, 0, x41)               
    
    print(f"\nKey expression analysis:")
    print(f"  x38 = ZeroExt(32, scanf_0_1_32)  // extend to 64 bits")
    print(f"  x41 = x38 << 3                   // shift left by 3, i.e. multiply by 8")
    print(f"  x42 = Extract(31, 0, x41)        // take lower 32 bits")
    print(f"  Therefore: x42 = scanf_0_1_32 * 8 (within 32-bit range)")
    
          
    s121_constraint = 1 >= x42              
    s000_constraint = 0 >= x42              
    
    print(f"\nDiffering constraints:")
    print(f"  s121: 1 >= x42  i.e.  x42 <= 1")
    print(f"  s000: 0 >= x42  i.e.  x42 <= 0")
    
               
    print(f"\nPossible values of x42 for inputs in [0,10]:")
    possible_values = []
    for i in range(11):
        val = i * 8
        possible_values.append((i, val))
        print(f"  scanf_0_1_32 = {i:2d} → x42 = {val:2d}")
    
    print(f"\nSatisfaction analysis of the constraints:")
    
                         
    print(f"  s000 constraint (x42 <= 0):")
    s000_satisfying = []
    for input_val, x42_val in possible_values:
        if x42_val <= 0:
            s000_satisfying.append(input_val)
            print(f"    ✓ scanf_0_1_32 = {input_val} (x42 = {x42_val}) satisfies x42 <= 0")
        else:
            print(f"    ✗ scanf_0_1_32 = {input_val} (x42 = {x42_val}) does NOT satisfy x42 <= 0")
    
                         
    print(f"  s121 constraint (x42 <= 1):")
    s121_satisfying = []
    for input_val, x42_val in possible_values:
        if x42_val <= 1:
            s121_satisfying.append(input_val)
            print(f"    ✓ scanf_0_1_32 = {input_val} (x42 = {x42_val}) satisfies x42 <= 1")
        else:
            print(f"    ✗ scanf_0_1_32 = {input_val} (x42 = {x42_val}) does NOT satisfy x42 <= 1")
    
    print(f"\nConclusion:")
    print(f"  Solution set for s000 constraint: {s000_satisfying}")
    print(f"  Solution set for s121 constraint: {s121_satisfying}")
    
    if s000_satisfying == s121_satisfying:
        print(f"  ✅ The solution sets are identical; constraints are logically equivalent!")
    else:
        print(f"  ❌ Solution sets differ; constraints are not equivalent")
    
            
    print(f"\nUsing Z3 to validate the analysis:")
    
    solver = Solver()
    
                
    print(f"  Checking solution set for s000 constraint:")
    for val in range(11):
        solver.push()
        solver.add(base_constraint1, base_constraint2, s000_constraint)
        solver.add(scanf_0_1_32 == val)
        
        result = solver.check()
        if result == sat:
            print(f"    scanf_0_1_32 = {val}: SAT")
        else:
            print(f"    scanf_0_1_32 = {val}: UNSAT")
        solver.pop()
    
                
    print(f"  Checking solution set for s121 constraint:")
    for val in range(11):
        solver.push()
        solver.add(base_constraint1, base_constraint2, s121_constraint)
        solver.add(scanf_0_1_32 == val)
        
        result = solver.check()
        if result == sat:
            print(f"    scanf_0_1_32 = {val}: SAT")
        else:
            print(f"    scanf_0_1_32 = {val}: UNSAT")
        solver.pop()

def verify_equivalence_step_by_step():
    """Verify equivalence step by step using Z3."""
    print(f"\n" + "=" * 80)
    print("Step-by-step equivalence verification")
    print("=" * 80)
    
          
    scanf_0_1_32 = BitVec('scanf_0_1_32', 32)
    
            
    base_constraints = And(
        UGE(scanf_0_1_32, 0),
        ULE(scanf_0_1_32, 10)
    )
    
    x38 = ZeroExt(32, scanf_0_1_32)
    x41 = x38 << 3
    x42 = Extract(31, 0, x41)
    
    s000_full = And(base_constraints, 0 >= x42)
    s121_full = And(base_constraints, 1 >= x42)
    
    print("Step 1: Check satisfiability of s000 constraints")
    solver = Solver()
    solver.add(s000_full)
    result = solver.check()
    print(f"  Result: {result}")
    if result == sat:
        model = solver.model()
        print(f"  Model: {model}")
    
    print("Step 2: Check satisfiability of s121 constraints")
    solver = Solver()
    solver.add(s121_full)
    result = solver.check()
    print(f"  Result: {result}")
    if result == sat:
        model = solver.model()
        print(f"  Model: {model}")
    
    print("Step 3: Check s000 → s121 (s000 implies s121)")
    solver = Solver()
    solver.add(And(s000_full, Not(s121_full)))
    result = solver.check()
    print(f"  Satisfiability of s000 ∧ ¬s121: {result}")
    if result == unsat:
        print("  ✓ s000 → s121 holds")
    else:
        print("  ✗ s000 → s121 does NOT hold")
        
    print("Step 4: Check s121 → s000 (s121 implies s000)")
    solver = Solver()
    solver.add(And(s121_full, Not(s000_full)))
    result = solver.check()
    print(f"  Satisfiability of s121 ∧ ¬s000: {result}")
    if result == unsat:
        print("  ✓ s121 → s000 holds")
    else:
        print("  ✗ s121 → s000 does NOT hold")
        
    print("Step 5: Bi-directional implication check")
    solver = Solver()
    equivalence_check = Or(
        And(s000_full, Not(s121_full)),
        And(Not(s000_full), s121_full)
    )
    solver.add(equivalence_check)
    result = solver.check()
    print(f"  Satisfiability of equivalence-check formula: {result}")
    if result == unsat:
        print("  ✅ s000 ≡ s121 (fully equivalent)")
    else:
        print("  ❌ s000 ≢ s121 (not equivalent)")

if __name__ == "__main__":
    analyze_constraint_semantics()
    verify_equivalence_step_by_step() 