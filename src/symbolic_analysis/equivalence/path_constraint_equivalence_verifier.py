                      
"""
Path-constraint equivalence verifier.

Uses the Z3 solver to directly check whether two SMT-LIB path constraints
are logically equivalent, including both positive and negative test cases.
"""

import sys
import time
from z3 import *

class PathConstraintEquivalenceVerifier:
    """Verifier for logical equivalence of path constraints."""
    
    def __init__(self, timeout=30000):
        """
        Initialize the verifier.

        :param timeout: Z3 solver timeout in milliseconds.
        """
        self.timeout = timeout
        
    def create_test_constraints(self):
        """Create example SMT files used as test constraints."""
        print("Creating test constraint files...")
        
                             
        constraint1_a = """
; Equivalence test constraint 1A
(set-info :status unknown)
(declare-fun x () (_ BitVec 32))
(assert (bvuge x (_ bv5 32)))
(assert (bvule x (_ bv10 32)))
(check-sat)
"""
        
        constraint1_b = """
; Equivalence test constraint 1B
(set-info :status unknown)
(declare-fun x () (_ BitVec 32))
(assert (and (bvuge x (_ bv5 32)) (bvule x (_ bv10 32))))
(check-sat)
"""
        
                               
        constraint2_a = """
; Equivalence test constraint 2A
(set-info :status unknown)
(declare-fun y () (_ BitVec 32))
(assert (or (bvult y (_ bv3 32)) (bvugt y (_ bv7 32))))
(check-sat)
"""
        
        constraint2_b = """
; Equivalence test constraint 2B
(set-info :status unknown)
(declare-fun y () (_ BitVec 32))
(assert (not (and (bvuge y (_ bv3 32)) (bvule y (_ bv7 32)))))
(check-sat)
"""
        
                              
        constraint3_a = """
; Non-equivalence test constraint 3A
(set-info :status unknown)
(declare-fun z () (_ BitVec 32))
(assert (bvuge z (_ bv5 32)))
(assert (bvule z (_ bv10 32)))
(check-sat)
"""
        
        constraint3_b = """
; Non-equivalence test constraint 3B
(set-info :status unknown)
(declare-fun z () (_ BitVec 32))
(assert (bvuge z (_ bv6 32)))
(assert (bvule z (_ bv10 32)))
(check-sat)
"""
        
                              
        constraint4_a = """
; Non-equivalence test constraint 4A
(set-info :status unknown)
(declare-fun w () (_ BitVec 32))
(assert (= w (_ bv0 32)))
(check-sat)
"""
        
        constraint4_b = """
; Non-equivalence test constraint 4B
(set-info :status unknown)
(declare-fun w () (_ BitVec 32))
(assert (= w (_ bv1 32)))
(check-sat)
"""
        
                
        test_files = [
            ("test_constraint_1a.smt", constraint1_a),
            ("test_constraint_1b.smt", constraint1_b),
            ("test_constraint_2a.smt", constraint2_a),
            ("test_constraint_2b.smt", constraint2_b),
            ("test_constraint_3a.smt", constraint3_a),
            ("test_constraint_3b.smt", constraint3_b),
            ("test_constraint_4a.smt", constraint4_a),
            ("test_constraint_4b.smt", constraint4_b),
        ]
        
        for filename, content in test_files:
            with open(filename, 'w') as f:
                f.write(content)
                
        print(f"Successfully created {len(test_files)} test constraint files")
        return test_files
    
    def parse_smt_constraint(self, file_path):
        """
        Parse an SMT constraint file.

        :param file_path: Path to the SMT-LIB file.
        :return: Z3 formula and its context.
        """
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
                     
            ctx = Context()
            
                        
            lines = []
            for line in content.split('\n'):
                line = line.strip()
                                
                if (line.startswith('(') and not line.startswith(';')) or line == ')':
                    lines.append(line)
            
            smt_content = '\n'.join(lines)
            
            formulas = parse_smt2_string(smt_content, ctx=ctx)
            
            if len(formulas) == 0:
                return BoolVal(True, ctx=ctx), ctx
            elif len(formulas) == 1:
                return formulas[0], ctx
            else:
                return And(*formulas), ctx
                
        except Exception as e:
            print(f"Failed to parse constraint file {file_path}: {e}")
            return None, None
    
    def verify_equivalence(self, file1, file2, description=""):
        """
        Verify logical equivalence of two SMT constraint files.

        :param file1: First SMT file.
        :param file2: Second SMT file.
        :param description: Description of the test.
        :return: True / False / None for equivalent / not equivalent / unknown.
        """
        print(f"\n{'='*60}")
        print(f"Verifying path-constraint equivalence: {description}")
        print(f"Constraint file 1: {file1}")
        print(f"Constraint file 2: {file2}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
                  
        print("Step 1: parsing constraint files...")
        constraint1, ctx1 = self.parse_smt_constraint(file1)
        constraint2, ctx2 = self.parse_smt_constraint(file2)
        
        if constraint1 is None or constraint2 is None:
            print("Error: constraint parsing failed")
            return None
        
                   
        ctx = Context()
        
                        
        with open(file1, 'r') as f:
            content1 = f.read()
        with open(file2, 'r') as f:
            content2 = f.read()
        
                    
        def clean_smt_content(content):
            lines = []
            for line in content.split('\n'):
                line = line.strip()
                if (line.startswith('(') and not line.startswith(';')) or line == ')':
                    if not line.startswith('(check-sat)'):
                        lines.append(line)
            return '\n'.join(lines)
        
        clean_content1 = clean_smt_content(content1)
        clean_content2 = clean_smt_content(content2)
        
        try:
            formulas1 = parse_smt2_string(clean_content1, ctx=ctx)
            formulas2 = parse_smt2_string(clean_content2, ctx=ctx)
            
                  
            if len(formulas1) == 0:
                formula1 = BoolVal(True, ctx=ctx)
            elif len(formulas1) == 1:
                formula1 = formulas1[0]
            else:
                formula1 = And(*formulas1)
                
            if len(formulas2) == 0:
                formula2 = BoolVal(True, ctx=ctx)
            elif len(formulas2) == 1:
                formula2 = formulas2[0]
            else:
                formula2 = And(*formulas2)
                
        except Exception as e:
            print(f"Error: failed to parse cleaned constraints - {e}")
            return None
        
        parse_time = time.time() - start_time
        print(f"Constraint parsing finished in {parse_time:.3f} seconds")
        
                
        print(f"\nStep 2: constraint inspection")
        print(f"Constraint 1: {formula1}")
        print(f"Constraint 2: {formula2}")
        
               
        print(f"\nStep 3: equivalence checking")
        print("Using logical equivalence check: (C1 ∧ ¬C2) ∨ (¬C1 ∧ C2)")
        print("If this formula is UNSAT, then C1 ≡ C2")
        
        verification_start = time.time()
        
               
        solver = Solver(ctx=ctx)
        solver.set("timeout", self.timeout)
        
                   
        equivalence_check = Or(
            And(formula1, Not(formula2)),
            And(Not(formula1), formula2)
        )
        
        solver.add(equivalence_check)
        
        print("Solving...")
        result = solver.check()
        
        verification_time = time.time() - verification_start
        total_time = time.time() - start_time
        
        print(f"\nStep 4: verification result")
        print(f"Solve status: {result}")
        print(f"Verification time: {verification_time:.3f} seconds")
        print(f"Total time: {total_time:.3f} seconds")
        
        if result == unsat:
            print("🟢 Conclusion: the two path constraints are logically equivalent")
            print("   Explanation: the equivalence-check formula is UNSAT,")
            print("   meaning no assignment makes the truth values differ.")
            return True
        elif result == sat:
            print("🔴 Conclusion: the two path constraints are NOT logically equivalent")
            print("   Explanation: a counterexample was found where their truth values differ.")
            
            model = solver.model()
            print(f"   Counterexample model:")
            for decl in model.decls():
                print(f"     {decl.name()} = {model[decl]}")
            
            print(f"   Counterexample evaluation:")
            eval1 = simplify(substitute(formula1, [(decl(), model[decl]) for decl in model.decls()]))
            eval2 = simplify(substitute(formula2, [(decl(), model[decl]) for decl in model.decls()]))
            print(f"     Constraint 1 value under counterexample: {eval1}")
            print(f"     Constraint 2 value under counterexample: {eval2}")
            
            return False
        else:
            print("🟡 Conclusion: equivalence unknown (timeout or unknown solver status)")
            return None
    
    def run_comprehensive_test(self):
        """Run the full built-in test suite."""
        print("Path-constraint equivalence verifier - full test suite")
        print("=" * 80)
        
                
        test_files = self.create_test_constraints()
        
        test_cases = [
            {
                "file1": "test_constraint_1a.smt",
                "file2": "test_constraint_1b.smt",
                "description": "Positive 1 - separate vs combined constraints",
                "expected": True
            },
            {
                "file1": "test_constraint_2a.smt", 
                "file2": "test_constraint_2b.smt",
                "description": "Positive 2 - De Morgan equivalence",
                "expected": True
            },
            {
                "file1": "test_constraint_3a.smt",
                "file2": "test_constraint_3b.smt", 
                "description": "Negative 1 - different numeric ranges",
                "expected": False
            },
            {
                "file1": "test_constraint_4a.smt",
                "file2": "test_constraint_4b.smt",
                "description": "Negative 2 - completely different equality constraints", 
                "expected": False
            }
        ]
        
              
        results = []
        passed_tests = 0
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\nTest case {i}/{len(test_cases)}")
            
            result = self.verify_equivalence(
                test_case["file1"],
                test_case["file2"], 
                test_case["description"]
            )
            
                    
            if result == test_case["expected"]:
                test_status = "✅ PASSED"
                passed_tests += 1
            elif result is None:
                test_status = "⚠️  UNKNOWN"
            else:
                test_status = "❌ FAILED"
                
            results.append({
                "test": test_case["description"],
                "expected": test_case["expected"],
                "actual": result,
                "status": test_status
            })
            
            print(f"Test status: {test_status}")
        
        print(f"\n{'='*80}")
        print(f"Test summary")
        print(f"{'='*80}")
        print(f"Total tests: {len(test_cases)}")
        print(f"Passed: {passed_tests}")
        print(f"Pass rate: {passed_tests/len(test_cases)*100:.1f}%")
        
        print(f"\nDetailed results:")
        for i, result in enumerate(results, 1):
            print(f"{i}. {result['test']}")
            print(f"   Expected: {'equivalent' if result['expected'] else 'not equivalent'}")
            if result['actual'] is True:
                actual_str = 'equivalent'
            elif result['actual'] is False:
                actual_str = 'not equivalent'
            else:
                actual_str = 'unknown'
            print(f"   Actual: {actual_str}")
            print(f"   Status: {result['status']}")
        
        return results

def main():
    """CLI entry point for the path-constraint equivalence verifier."""
    print("Path-constraint equivalence verifier")
    print("Use Z3 to check whether two path constraints are logically equivalent.")
    print("-" * 50)
    
    if len(sys.argv) == 1:
        print("No arguments provided; running full internal test suite...")
        verifier = PathConstraintEquivalenceVerifier()
        verifier.run_comprehensive_test()
        
    elif len(sys.argv) == 3:
        file1, file2 = sys.argv[1], sys.argv[2]
        print(f"Verifying user-specified files: {file1} vs {file2}")
        
        verifier = PathConstraintEquivalenceVerifier()
        result = verifier.verify_equivalence(file1, file2, "user-specified files")
        
        print(f"\nFinal conclusion:")
        if result is True:
            print("✅ The two path constraints are logically equivalent")
        elif result is False:
            print("❌ The two path constraints are NOT logically equivalent")
        else:
            print("⚠️  Equivalence could not be determined")
            
    else:
        print("Usage:")
        print("  python path_constraint_equivalence_verifier.py")
        print("      # Run the full internal test suite")
        print("  python path_constraint_equivalence_verifier.py <file1> <file2>")
        print("      # Verify equivalence of two SMT-LIB files")
        sys.exit(1)

if __name__ == "__main__":
    main() 