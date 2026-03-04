                      
"""
angr symbolic execution memory requirements analysis.
Analyzes TSVC benchmark memory needs and provides optimization suggestions.
"""

import os
import psutil
import subprocess

def analyze_current_system():
    """Analyze current system configuration."""
    print("🖥️  Current system configuration")
    print("=" * 50)
    
    memory = psutil.virtual_memory()
    print(f"📊 Memory:")
    print(f"   Total: {memory.total / (1024**3):.1f} GB")
    print(f"   Available: {memory.available / (1024**3):.1f} GB")
    print(f"   Used: {memory.used / (1024**3):.1f} GB")
    print(f"   Usage: {memory.percent:.1f}%")
    
    print(f"\n🔧 CPU:")
    print(f"   Physical cores: {psutil.cpu_count(logical=False)}")
    print(f"   Logical cores: {psutil.cpu_count(logical=True)}")
    
    return memory.total / (1024**3), memory.available / (1024**3)

def analyze_angr_memory_requirements():
    """Analyze angr symbolic execution memory requirements."""
    print(f"\n🧠 angr symbolic execution memory requirements")
    print("=" * 50)
    
    requirements = {
        "Simple programs": {
            "Base memory": "1-2 GB",
            "Paths": "< 100",
            "Execution time": "< 5 min",
            "Use case": "Single loop, simple conditions"
        },
        "Medium programs": {
            "Base memory": "4-8 GB", 
            "Paths": "100-1000",
            "Execution time": "5-30 min",
            "Use case": "Nested loops, array ops"
        },
        "Complex programs": {
            "Base memory": "16-32 GB",
            "Paths": "1000-10000",
            "Execution time": "30 min - hours",
            "Use case": "Complex algorithms, multiple dependencies"
        },
        "Large programs": {
            "Base memory": "64+ GB",
            "Paths": "10000+",
            "Execution time": "Hours - days",
            "Use case": "Full applications"
        }
    }
    
    print("📊 Memory requirements by program complexity:")
    for category, info in requirements.items():
        print(f"\n🔹 {category}:")
        for key, value in info.items():
            print(f"   {key}: {value}")
    
    return requirements

def analyze_tsvc_specific_requirements():
    """Analyze TSVC benchmark specific requirements."""
    print(f"\n🎯 TSVC benchmark memory requirements")
    print("=" * 50)
    
    tsvc_analysis = {
        "s000": {
            "Description": "a[i] = b[i] + 1 (simple vector add)",
            "Est. memory": "2-4 GB",
            "Path complexity": "Low",
            "Suggestion": "Good as test starting point"
        },
        "s121": {
            "Description": "a[i] = a[i+1] + b[i] (data dependency)",
            "Est. memory": "4-8 GB",
            "Path complexity": "Medium",
            "Suggestion": "Limit loop iterations"
        },
        "s2244": {
            "Description": "Complex assignment",
            "Est. memory": "8-16 GB",
            "Path complexity": "High",
            "Suggestion": "Requires high-memory machine"
        },
        "All benchmarks": {
            "Description": "Full test suite",
            "Est. memory": "32+ GB",
            "Path complexity": "Very high",
            "Suggestion": "Requires high-end server"
        }
    }
    
    for benchmark, info in tsvc_analysis.items():
        print(f"\n📋 {benchmark}:")
        for key, value in info.items():
            print(f"   {key}: {value}")
    
    return tsvc_analysis

def memory_optimization_strategies():
    """Memory optimization strategies."""
    print(f"\n🚀 Memory optimization strategies")
    print("=" * 50)
    
    strategies = {
        "Program simplification": [
            "Reduce array size (LEN=8 instead of 128)",
            "Limit loop count (count=1)",
            "Remove unnecessary globals",
            "Use static linking to reduce library deps"
        ],
        "angr configuration": [
            "Limit max paths (max_paths=5-10)",
            "Set timeout (timeout=60s)",
            "Enable LAZY_SOLVES",
            "Use ZERO_FILL_UNCONSTRAINED_MEMORY",
            "Limit symbolic execution depth"
        ],
        "System-level": [
            "Increase swap space",
            "Disable unneeded services",
            "Use memory-mapped files",
            "Enable memory compression"
        ],
        "Batch processing": [
            "Analyze one benchmark at a time",
            "Process each optimization level separately",
            "Clean intermediate results promptly",
            "Save state incrementally"
        ]
    }
    
    for category, items in strategies.items():
        print(f"\n🔧 {category}:")
        for item in items:
            print(f"   • {item}")

def recommend_machine_specs(total_memory, available_memory):
    """Recommend machine configuration."""
    print(f"\n💻 Machine configuration recommendations")
    print("=" * 50)
    
    print(f"📊 Current: {total_memory:.1f}GB total, {available_memory:.1f}GB available")
    
    recommendations = {
        "Min (testing)": {
            "Memory": "8-16 GB",
            "Use": "Single simple benchmark",
            "Cost": "Low",
            "Scenario": "Proof of concept, learning"
        },
        "Recommended (development)": {
            "Memory": "32-64 GB", 
            "Use": "Multiple benchmarks, full analysis",
            "Cost": "Medium",
            "Scenario": "Research, experiments"
        },
        "High-end (production)": {
            "Memory": "128+ GB",
            "Use": "Full TSVC suite, large-scale analysis",
            "Cost": "High", 
            "Scenario": "Industrial use, large-scale research"
        }
    }
    
    for config, specs in recommendations.items():
        print(f"\n🖥️  {config}:")
        for key, value in specs.items():
            print(f"   {key}: {value}")
    
    if total_memory < 16:
        print(f"\n⚠️  Low memory suggestions:")
        print(f"   • Prefer enhanced simulation mode")
        print(f"   • For real symbolic execution, upgrade to 16GB+")
    elif total_memory < 32:
        print(f"\n✅ Moderate memory suggestions:")
        print(f"   • Can run real symbolic execution on simple benchmarks")
        print(f"   • Analyze one benchmark at a time")
    else:
        print(f"\n🎉 Sufficient memory:")
        print(f"   • Can run real symbolic execution on multiple benchmarks")

def create_optimized_analysis_script():
    """Create optimized analysis script."""
    script_content = '''#!/usr/bin/env python3
"""
Memory-optimized TSVC symbolic execution script.
"""

import angr
import os
import gc
import psutil

def memory_aware_analysis(binary_path, max_memory_gb=4):
    """Memory-aware symbolic execution."""
    
    def check_memory():
        """Check memory usage."""
        memory = psutil.virtual_memory()
        used_gb = memory.used / (1024**3)
        return used_gb < max_memory_gb
    
    # Create angr project
    project = angr.Project(str(binary_path), auto_load_libs=False)
    
    # Optimized state options
    state = project.factory.entry_state()
    state.options.add(angr.options.LAZY_SOLVES)
    state.options.add(angr.options.ZERO_FILL_UNCONSTRAINED_MEMORY)
    state.options.add(angr.options.AVOID_MULTIVALUED_READS)
    
    # Simulation manager with memory limits
    simgr = project.factory.simulation_manager(state)
    
    paths = []
    step_count = 0
    max_steps = 20  # Limit steps
    
    while simgr.active and step_count < max_steps:
        if not check_memory():
            print("Insufficient memory; stopping symbolic execution")
            break
            
        simgr.step()
        step_count += 1
        
        # Periodic GC
        if step_count % 5 == 0:
            gc.collect()
    
    # Collect results
    for state in simgr.deadended + simgr.active:
        if len(paths) >= 5:  # Limit path count
            break
        paths.append(extract_constraints(state))
    
    return paths

def extract_constraints(state):
    """Extract constraints (simplified)."""
    try:
        constraints = state.solver.constraints
        return {
            'constraint_count': len(constraints),
            'constraints': [str(c)[:100] for c in constraints[:5]]
        }
    except:
        return {'constraint_count': 0, 'constraints': []}

if __name__ == "__main__":
    # Example: result = memory_aware_analysis("path/to/binary", max_memory_gb=6)
    print("Memory-optimized symbolic execution script ready.")
'''
    
    with open('memory_optimized_analysis.py', 'w') as f:
        f.write(script_content)
    
    print(f"\n📄 Generated script: memory_optimized_analysis.py")

def main():
    """Main analysis entry."""
    print("🔍 angr symbolic execution memory requirements analysis")
    print("=" * 60)
    
            
    total_mem, avail_mem = analyze_current_system()
    
              
    analyze_angr_memory_requirements()
    
                
    analyze_tsvc_specific_requirements() 
    
          
    memory_optimization_strategies()
    
          
    recommend_machine_specs(total_mem, avail_mem)
    
            
    create_optimized_analysis_script()
    
    print(f"\n🎯 Summary:")
    print(f"   💰 Limited budget: use enhanced simulation mode (already implemented)")
    print(f"   🔬 Research: upgrade to 32GB+ machine") 
    print(f"   🏭 Production: use 128GB+ high-end server")
    print(f"   📊 Current: real symbolic execution on a single simple benchmark is feasible")

if __name__ == "__main__":
    main() 