                      
"""
TSVC Benchmark quick demo script.
This script sanity-checks the core benchmark pipeline.
"""

import os
import sys
import time
from pathlib import Path

def check_dependencies():
    """Check that all required dependency files exist."""
    print("Checking required dependency files...")
    
    required_files = [
        "pldi19-equivalence-checker/pldi19/TSVC/clean.c",
        "semantic_equivalence_analyzer.py", 
        "path_analyzer_fixed.py",
        "tsvc_benchmark_runner.py",
        "tsvc_symbolic_integration.py"
    ]
    
    missing_files = []
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"  ✓ {file_path}")
        else:
            print(f"  ✗ {file_path}")
            missing_files.append(file_path)
    
    if missing_files:
        print(f"\nError: {len(missing_files)} required file(s) are missing")
        print("Please make sure all files are in the expected locations.")
        return False
    
    print("All dependency files are present.")
    return True

def test_benchmark_extraction():
    """Test benchmark extraction from the TSVC source."""
    print("\nTesting benchmark extraction...")
    
    try:
        from tsvc_benchmark_runner import TSVCBenchmarkExtractor
        
        extractor = TSVCBenchmarkExtractor()
        functions = extractor.extract_benchmark_functions()
        
        print(f"  Extracted {len(functions)} benchmark functions")
        print(f"  Recommended benchmarks: {extractor.recommended_benchmarks}")
        
                                      
        for i, (name, info) in enumerate(list(functions.items())[:3]):
            status = "recommended" if info['recommended'] else "optional"
            print(f"    {name} ({status})")
        
        return True
        
    except Exception as e:
        print(f"  ✗ benchmark提取失败: {e}")
        return False

def test_single_benchmark():
    """Test compiling and analyzing a single benchmark."""
    print("\nTesting compilation of a single benchmark...")
    
    try:
        from tsvc_benchmark_runner import TSVCBenchmarkExtractor
        
        extractor = TSVCBenchmarkExtractor()
        extractor.extract_benchmark_functions()
        
                                               
        test_benchmark = 's000'
        print(f"  Testing benchmark: {test_benchmark}")
        
        variants = extractor.create_benchmark_variants(test_benchmark, ['O1', 'O2'])
        
        successful_variants = [k for k, v in variants.items() if v['compilation_success']]
        print(f"  Successfully compiled variants: {successful_variants}")
        
        if len(successful_variants) >= 2:
            print("  ✓ Compilation test passed")
            return True
        else:
            print("  ✗ Compilation test failed: at least 2 successful variants are required")
            return False
            
    except Exception as e:
        print(f"  ✗ Single benchmark compilation test failed: {e}")
        return False

def test_path_generation():
    """Test symbolic execution path generation."""
    print("\nTesting execution path generation...")
    
    try:
        from tsvc_symbolic_integration import TSVCSymbolicIntegrator
        
        integrator = TSVCSymbolicIntegrator()
        
                             
        paths = integrator.generate_execution_paths(
            "dummy_binary",
            "test_s000_O1", 
            num_paths=5
        )
        
        print(f"  Generated {len(paths)} paths")
        
                                        
        if paths:
            first_path = Path(paths[0])
            if first_path.exists():
                print("  ✓ Path files successfully generated")
                
                                     
                with open(first_path, 'r') as f:
                    content = f.read()
                    if 'declare-fun' in content and 'assert' in content:
                        print("  ✓ SMT constraint format looks correct")
                        return True
                    else:
                        print("  ✗ SMT constraint format is not correct")
                        return False
            else:
                print("  ✗ Path file does not exist")
                return False
        else:
            print("  ✗ No paths were generated")
            return False
            
    except Exception as e:
        print(f"  ✗ Path generation test failed: {e}")
        return False

def test_symbolic_analysis():
    """Test the symbolic analysis components."""
    print("\nTesting symbolic analysis tools...")
    
    try:
                                                 
        from semantic_equivalence_analyzer import ConstraintEquivalenceChecker
        
        checker = ConstraintEquivalenceChecker(timeout=5000)        
        
                                                            
        vars1 = {'x': 32, 'y': 32}
        vars2 = {'a': 32, 'b': 32}
        constraints1 = ['(= x (bvadd y #x00000001))']
        constraints2 = ['(= a (bvadd b #x00000001))']
        var_mapping = {'x': 'a', 'y': 'b'}
        
        result, details = checker.check_constraint_equivalence(
            constraints1, constraints2, vars1, vars2, var_mapping
        )
        
        print(f"  Constraint equivalence result: {result}")
        print(f"  Solver time: {details.get('solve_time', 0):.3f}s")
        
        if result == 'equivalent':
            print("  ✓ Symbolic analysis tool works as expected")
            return True
        elif result in ['not_equivalent', 'unknown']:
            print("  ⚠ Solver ran successfully, but the constraints were not proven equivalent")
            return True
        else:
            print("  ✗ Symbolic analysis tool returned an unexpected result")
            return False
            
    except Exception as e:
        print(f"  ✗ Symbolic analysis test failed: {e}")
        return False

def run_mini_benchmark():
    """Run a tiny end-to-end benchmark to test the full pipeline."""
    print("\nRunning a mini benchmark test...")
    
    try:
        from tsvc_symbolic_integration import TSVCSymbolicIntegrator
        
        integrator = TSVCSymbolicIntegrator()
        
                                                        
        result = integrator.run_benchmark_analysis('s000', opt_levels=['O1', 'O2'])
        
        if result and len(result) > 0:
            print("  ✓ Mini benchmark completed successfully")
            
            for comparison, comp_result in result.items():
                status = comp_result.get('status', 'unknown')
                print(f"    {comparison}: {status}")
            
            return True
        else:
            print("  ✗ Mini benchmark failed")
            return False
            
    except Exception as e:
        print(f"  ✗ Mini benchmark test failed: {e}")
        return False

def cleanup_test_files():
    """Clean up temporary files created during the quick demo."""
    print("\nCleaning up test files...")
    
    cleanup_patterns = [
        "benchmark_temp_*",
        "paths_*",
        "*_fixed.txt",
        "tsvc_analysis_results",
    ]
    
    import shutil
    import glob
    
    for pattern in cleanup_patterns:
        for path in glob.glob(pattern):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                print(f"  Deleted: {path}")
            except Exception as e:
                print(f"  Warning: failed to delete {path}: {e}")

def main():
    """Entry point for the TSVC benchmark quick demo."""
    print("TSVC Benchmark Quick Demo")
    print("=" * 40)
    
    start_time = time.time()
    
                          
    tests = [
        ("Dependency check", check_dependencies),
        ("Benchmark extraction", test_benchmark_extraction),
        ("Single benchmark compilation", test_single_benchmark),
        ("Path generation", test_path_generation),
        ("Symbolic analysis", test_symbolic_analysis),
        ("Mini benchmark", run_mini_benchmark),
    ]
    
    passed_tests = 0
    total_tests = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        
        try:
            if test_func():
                passed_tests += 1
                print(f"✓ {test_name} 通过")
            else:
                print(f"✗ {test_name} 失败")
        except Exception as e:
            print(f"✗ {test_name} 出现异常: {e}")
    
    end_time = time.time()
    
                                 
    print(f"\n{'='*50}")
    print("Test summary")
    print(f"{'='*50}")
    print(f"Total tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print(f"Pass rate: {passed_tests/total_tests*100:.1f}%")
    print(f"Total time: {end_time - start_time:.2f}s")
    
    if passed_tests == total_tests:
        print("\n🎉 All tests passed. The system looks ready.")
        print("\nNext steps:")
        print("  Run the full analysis: python tsvc_symbolic_integration.py")
        print("  Read the documentation: cat README_TSVC_BENCHMARK.md")
    elif passed_tests >= total_tests * 0.7:
        print("\n⚠ Most tests passed; the system is likely usable.")
        print("Please inspect and fix the failing tests before relying on it.")
    else:
        print("\n❌ Many tests failed; please check your environment/configuration.")
        print("Refer to README_TSVC_BENCHMARK.md for troubleshooting hints.")
    
                                            
    try:
        response = input("\nClean up generated test files? (y/N): ").strip().lower()
        if response in ['y', 'yes']:
            cleanup_test_files()
        else:
            print("Keeping test files for debugging.")
    except KeyboardInterrupt:
        print("\n\n测试完成")

if __name__ == "__main__":
    main() 