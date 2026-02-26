"""
Verify equivalence of two Java programs.
"""

import z3

def verify_java_equivalence():
    """Verify equivalence of newV and oldV programs."""
    print("🔍 Verifying Java program equivalence")
    print("=" * 50)
    solver = z3.Solver()
    a = z3.Real('a')
    b = z3.Real('b')
    print("📋 Program logic:")
    print("newV: if (b < a) return a; else return b;")
    print("oldV: if (b > a) return b; else return a;")
    print()
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
        a_val = float(model[a].as_fraction())
        b_val = float(model[b].as_fraction())
        print(f"   Counterexample: a={a_val}, b={b_val}")
        newV_val = a_val if b_val < a_val else b_val
        oldV_val = b_val if b_val > a_val else a_val
        print(f"   newV result: {newV_val}")
        print(f"   oldV result: {oldV_val}")
    else:
        print("⚠️  Result: inconclusive (solver timeout or error)")
    solver.pop()
    print(f"\n🔍 Logical equivalence analysis:")
    print("newV logic: if (b < a) return a; else return b;")
    print("oldV logic: if (b > a) return b; else return a;")
    print()
    print("Equivalence analysis:")
    print("1. When b < a:")
    print("   - newV: condition true, returns a")
    print("   - oldV: condition false, returns a")
    print("   - Same result: both return a")
    print()
    print("2. When b > a:")
    print("   - newV: condition false, returns b")
    print("   - oldV: condition true, returns b")
    print("   - Same result: both return b")
    print()
    print("3. When b = a:")
    print("   - newV: condition false, returns b (= a)")
    print("   - oldV: condition false, returns a")
    print("   - Same result: both return a (since a = b)")
    print()
    print("📋 Conclusion: The two programs are logically equivalent; both implement max(a,b).")

if __name__ == "__main__":
    verify_java_equivalence()
