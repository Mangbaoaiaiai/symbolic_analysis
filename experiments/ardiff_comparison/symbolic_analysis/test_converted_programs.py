                      
"""
测试转换后的程序的符号执行
"""

import os
import subprocess
import sys
import time

def test_converted_programs():
    """测试6个转换后的程序"""
    programs = [
        "benchmarks/ModDiff/NEq/LoopSub/symbolic_newV",
        "benchmarks/ModDiff/NEq/LoopSub/symbolic_oldV", 
        "benchmarks/ModDiff/Eq/LoopSub/symbolic_newV",
        "benchmarks/ModDiff/Eq/LoopSub/symbolic_oldV",
        "benchmarks/ModDiff/Eq/Sub/symbolic_newV",
        "benchmarks/ModDiff/Eq/Sub/symbolic_oldV"
    ]
    
    print("🚀 测试转换后的6个程序...")
    
    successful_executions = 0
    meaningful_constraints = 0
    
    for i, program in enumerate(programs, 1):
        print(f"\n[{i}/6] 🔍 测试: {program}")
        
        try:
                    
            cmd = [sys.executable, "se_script.py", "--binary", program]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                successful_executions += 1
                
                            
                output = result.stdout
                if "共发现" in output and "条路径" in output:
                    import re
                    match = re.search(r'共发现 (\d+) 条路径', output)
                    if match:
                        path_count = int(match.group(1))
                        print(f"  ✅ 成功生成 {path_count} 条路径")
                        
                        if path_count > 0:
                                    
                            base_name = os.path.basename(program)
                            constraint_files = [f for f in os.listdir('.') if f.startswith(base_name + "_path_")]
                            for cf in constraint_files:
                                with open(cf, 'r') as f:
                                    content = f.read()
                                if '(assert' in content:
                                    meaningful_constraints += 1
                                    print(f"    🎯 {cf}: 有意义约束")
                                else:
                                    print(f"    ⚠️  {cf}: 空约束")
                        else:
                            print(f"    ⚠️  没有路径生成")
                else:
                    print(f"  ⚠️  符号执行完成但无法确定路径数")
            else:
                print(f"  ❌ 符号执行失败: {result.stderr[:100]}...")
                
        except subprocess.TimeoutExpired:
            print(f"  ⏱️  超时")
        except Exception as e:
            print(f"  💥 异常: {e}")
    
    print(f"\n📊 测试结果:")
    print(f"  • 成功执行: {successful_executions}/6")
    print(f"  • 有意义约束文件: {meaningful_constraints}")
    print(f"  • 成功率: {(successful_executions/6)*100:.1f}%")

if __name__ == "__main__":
    test_converted_programs() 