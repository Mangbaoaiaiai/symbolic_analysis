                      
"""
SMT constraint-equivalence checking tool.

Directly verifies whether two SMT-LIB formulas are logically equivalent,
without performing any simplification or pre-processing.
"""

import sys
import time
from z3 import *

class SMTEquivalenceChecker:
    """Checker for logical equivalence of SMT constraints."""
    
    def __init__(self, timeout=30000):
        self.timeout = timeout
        
    def parse_smt_file(self, file_path):
        """Parse an SMT-LIB file and return a combined formula."""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
                                 
            lines = []
            for line in content.split('\n'):
                line = line.strip()
                                
                if (line.startswith('(') and 
                    (line.startswith('(set-') or 
                     line.startswith('(declare-') or 
                     line.startswith('(assert') or 
                     line.startswith('(check-') or
                     line.startswith('(let ') or
                     line.startswith('(bv') or
                     line.startswith('(_ ') or
                     line.startswith(')'))):
                    lines.append(line)
                elif line == '':
                    continue
                else:
                                             
                    if lines and not lines[-1].endswith(')'):
                        lines.append(line)
            
                    
            filtered_content = '\n'.join(lines)
            
            ctx = Context()
            
            formulas = parse_smt2_string(filtered_content, ctx=ctx)
            
                       
            if len(formulas) == 0:
                return BoolVal(True, ctx=ctx)
            elif len(formulas) == 1:
                return formulas[0]
            else:
                return And(*formulas)
                
        except Exception as e:
            print(f"Failed to parse file {file_path}: {e}")
            return None
    
    def check_equivalence(self, file1, file2):
        """Check whether two SMT files encode logically equivalent constraints."""
        print(f"Checking SMT constraint equivalence:")
        print(f"  File 1: {file1}")
        print(f"  File 2: {file2}")
        print("-" * 50)
        
                
        start_time = time.time()
        
                  
        ctx = Context()
        
        print("Parsing file 1...")
        formula1 = self.parse_smt_file_with_context(file1, ctx)
        if formula1 is None:
            return False
            
        print("Parsing file 2...")
        formula2 = self.parse_smt_file_with_context(file2, ctx)
        if formula2 is None:
            return False
            
        parse_time = time.time() - start_time
        print(f"File parsing time: {parse_time:.3f} seconds")
        
        print("\nStarting equivalence check...")
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
        
        print(f"\nVerification result:")
        print(f"  Solver result: {result}")
        print(f"  Verification time: {verification_time:.3f} seconds")
        print(f"  Total time: {total_time:.3f} seconds")
        
        if result == unsat:
            print("  ✓ Constraints are logically equivalent")
            return True
        elif result == sat:
            print("  ✗ Constraints are NOT equivalent")
            model = solver.model()
            print(f"  Counterexample model:")
            for decl in model.decls():
                print(f"    {decl.name()} = {model[decl]}")
            return False
        else:
            print("  ? Equivalence unknown (timeout or unknown status)")
            return None
    
    def parse_smt_file_with_context(self, file_path, ctx):
        """Parse an SMT-LIB file using a provided Z3 context."""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
                                 
            lines = []
            for line in content.split('\n'):
                line = line.strip()
                                
                if (line.startswith('(') and 
                    (line.startswith('(set-') or 
                     line.startswith('(declare-') or 
                     line.startswith('(assert') or 
                     line.startswith('(check-') or
                     line.startswith('(let ') or
                     line.startswith('(bv') or
                     line.startswith('(_ ') or
                     line.startswith(')'))):
                    lines.append(line)
                elif line == '':
                    continue
                else:
                                             
                    if lines and not lines[-1].endswith(')'):
                        lines.append(line)
            
                    
            filtered_content = '\n'.join(lines)
            
            formulas = parse_smt2_string(filtered_content, ctx=ctx)
            
                       
            if len(formulas) == 0:
                return BoolVal(True, ctx=ctx)
            elif len(formulas) == 1:
                return formulas[0]
            else:
                return And(*formulas)
                
        except Exception as e:
            print(f"Failed to parse file {file_path}: {e}")
            return None
    
    def analyze_constraints(self, file_path):
        """Analyze the structure of constraints in a single SMT file."""
        print(f"\nAnalyzing file: {file_path}")
        print("-" * 30)
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            lines = content.split('\n')
            total_lines = len(lines)
            comment_lines = sum(1 for line in lines if line.strip().startswith(';'))
            declare_lines = sum(1 for line in lines if 'declare-fun' in line)
            assert_lines = sum(1 for line in lines if line.strip().startswith('(assert'))
            
            print(f"Total lines: {total_lines}")
            print(f"Comment lines: {comment_lines}")
            print(f"Variable declarations: {declare_lines}")
            print(f"Constraint assertions: {assert_lines}")
            
            variables = []
            for line in lines:
                if 'declare-fun' in line:
                    import re
                    match = re.search(r'declare-fun\s+(\w+)', line)
                    if match:
                        variables.append(match.group(1))
            
            print(f"Variables: {variables}")
            
            print(f"\nConstraint bodies:")
            for i, line in enumerate(lines):
                if line.strip().startswith('(assert'):
                    print(f"  Constraint {i+1}: {line.strip()}")
            
            print(f"\nComments:")
            for line in lines:
                if line.strip().startswith(';'):
                    print(f"  {line.strip()}")
                    
        except Exception as e:
            print(f"Analysis failed: {e}")

def main():
    """CLI entry point for the SMT equivalence checker."""
    if len(sys.argv) < 3:
        print("Usage: python smt_equivalence_checker.py <file1> <file2>")
        print("       python smt_equivalence_checker.py --analyze <file>")
        sys.exit(1)
    
    checker = SMTEquivalenceChecker()
    
    if sys.argv[1] == '--analyze':
        if len(sys.argv) != 3:
            print("Analysis mode usage: python smt_equivalence_checker.py --analyze <file>")
            sys.exit(1)
        checker.analyze_constraints(sys.argv[2])
    else:
        if len(sys.argv) != 3:
            print("Verification mode usage: python smt_equivalence_checker.py <file1> <file2>")
            sys.exit(1)
        
        file1 = sys.argv[1]
        file2 = sys.argv[2]
        
        checker.analyze_constraints(file1)
        checker.analyze_constraints(file2)
        
        result = checker.check_equivalence(file1, file2)
        
        print(f"\nFinal conclusion:")
        if result is True:
            print("  ✓ The two SMT constraint formulas are logically equivalent")
        elif result is False:
            print("  ✗ The two SMT constraint formulas are NOT logically equivalent")
        else:
            print("  ? Could not determine equivalence")

if __name__ == "__main__":
    main() 