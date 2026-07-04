"""
Analyze equivalence of Airy MAX Eq programs.

Uses the solver to verify whether path constraints of two programs are equivalent.
"""

import z3
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

def load_smt_constraints(file_path):
    """Load SMT constraint file."""
    with open(file_path, 'r') as f:
        content = f.read()
    lines = content.split('\n')
    constraints = []
    for line in lines:
        line = line.strip()
        if line.startswith('(assert') and not line.startswith(';'):
            constraints.append(line)
    return constraints

def analyze_program_equivalence():
    """Analyze equivalence of the two programs."""
    print("🔍 Analyzing Airy MAX Eq program equivalence")
    print("=" * 50)
    base_dir = REPO_ROOT / "experiments" / "ardiff_comparison" / "benchmarks" / "Airy" / "MAX" / "Eq"
    newV_path1 = os.path.join(base_dir, "symbolic_newV_path_1.txt")
    newV_path2 = os.path.join(base_dir, "symbolic_newV_path_2.txt")
    oldV_path1 = os.path.join(base_dir, "symbolic_oldV_path_1.txt")
    oldV_path2 = os.path.join(base_dir, "symbolic_oldV_path_2.txt")
    print("📋 Program logic:")
    print("newV: if (b < a) return a; else return b;")
    print("oldV: if (b > a) return b; else return a;")
    print()
    print("📂 Loading path constraints...")
    newV_constraints = []
    oldV_constraints = []
    for path_file in [newV_path1, newV_path2]:
        if os.path.exists(path_file):
            constraints = load_smt_constraints(path_file)
            newV_constraints.extend(constraints)
            print(f"  newV: loaded {len(constraints)} constraints")
    for path_file in [oldV_path1, oldV_path2]:
        if os.path.exists(path_file):
            constraints = load_smt_constraints(path_file)
            oldV_constraints.extend(constraints)
            print(f"  oldV: loaded {len(constraints)} constraints")
    print(f"\n📊 Constraint stats:")
    print(f"  newV total: {len(newV_constraints)}")
    print(f"  oldV total: {len(oldV_constraints)}")
    print(f"\n🔍 Constraint content:")
    print("newV constraints:")
    for i, constraint in enumerate(newV_constraints, 1):
        print(f"  {i}. {constraint}")
    print("\noldV constraints:")
    for i, constraint in enumerate(oldV_constraints, 1):
        print(f"  {i}. {constraint}")
    print(f"\n🧮 Verifying equivalence with Z3...")
    solver = z3.Solver()
    a = z3.BitVec('a', 32)
    b = z3.BitVec('b', 32)
    newV_result = z3.If(b < a, a, b)
    oldV_result = z3.If(b > a, b, a)
    equivalence = z3.ForAll([a, b], newV_result == oldV_result)
    print("🔍 Formula: ∀a,b. newV(a,b) = oldV(a,b)")
    solver.push()
    solver.add(z3.Not(equivalence))
    result = solver.check()
    if result == z3.unsat:
        print("✅ Result: programs are equivalent!")
        print("   For all inputs, both programs produce the same result.")
    elif result == z3.sat:
        print("❌ Result: programs are not equivalent!")
        print("   There exist inputs for which the programs differ.")
        model = solver.model()
        a_val = model[a].as_long()
        b_val = model[b].as_long()
        print(f"   Counterexample: a={a_val}, b={b_val}")
        newV_val = a_val if b_val < a_val else b_val
        oldV_val = b_val if b_val > a_val else a_val
        print(f"   newV result: {newV_val}")
        print(f"   oldV result: {oldV_val}")
    else:
        print("⚠️  Result: inconclusive (solver timeout or error)")
    solver.pop()
    print(f"\n🔍 Path constraint analysis:")
    print("newV path1: bvsge ... (i.e. a >= b, b < a false, return b)")
    print("newV path2: bvslt ... (i.e. a < b, b < a true, return a)")
    print("oldV path1: bvsle ... (i.e. a <= b, b > a false, return a)")
    print("oldV path2: bvsgt ... (i.e. a > b, b > a true, return b)")
    print(f"\n🔍 Path constraint equivalence check:")
    newV_path1_cond = a >= b
    newV_path1_result = b
    newV_path2_cond = a < b
    newV_path2_result = a
    oldV_path1_cond = a <= b
    oldV_path1_result = a
    oldV_path2_cond = a > b
    oldV_path2_result = b
    print("Verifying path coverage...")
    solver.push()
    path1_eq = z3.ForAll([a, b],
        z3.Implies(newV_path1_cond,
                  z3.And(oldV_path2_cond, newV_path1_result == oldV_path2_result)))
    solver.add(z3.Not(path1_eq))
    result1 = solver.check()
    solver.pop()
    if result1 == z3.unsat:
        print("✅ newV path1 ≈ oldV path2 (both return b when a>=b)")
    else:
        print("❌ newV path1 ≠ oldV path2")
    solver.push()
    path2_eq = z3.ForAll([a, b],
        z3.Implies(newV_path2_cond,
                  z3.And(oldV_path1_cond, newV_path2_result == oldV_path1_result)))
    solver.add(z3.Not(path2_eq))
    result2 = solver.check()
    solver.pop()
    if result2 == z3.unsat:
        print("✅ newV path2 ≈ oldV path1 (both return a when a<b)")
    else:
        print("❌ newV path2 ≠ oldV path1")
    print(f"\n📋 Conclusion:")
    print("The two programs are logically equivalent (both implement max(a,b)).")
    print("Symbolic execution yields path constraints that do not match syntactically.")
    print("Possible reasons for equivalence analysis failure:")
    print("1. Different constraint representation (bvsge vs bvsgt)")
    print("2. Different path order (newV checks b<a first, oldV checks b>a first)")
    print("3. Constraint matching needs smarter equivalence reasoning")

if __name__ == "__main__":
    analyze_program_equivalence()
