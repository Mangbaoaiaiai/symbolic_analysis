                      
"""
最终约束总结脚本 - 总结所有有效的约束生成结果
"""

import os
import glob
import re
from pathlib import Path

def analyze_all_constraints():
    """分析所有约束文件"""
    print("🔍 正在扫描所有约束文件...")
    
                
    pattern = "/root/ardiff/symbolic_analysis/**/*_path_*.txt"
    constraint_files = glob.glob(pattern, recursive=True)
    
    print(f"📋 找到 {len(constraint_files)} 个约束文件")
    
    meaningful_files = []
    empty_files = []
    
    for file_path in constraint_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
                     
            has_constraints = '(assert' in content
            has_variables = 'scanf_' in content or 'mem_' in content
            has_output = 'Result:' in content and len(content.split('Result:')[1].strip()) > 0
            
            file_info = {
                'path': file_path,
                'has_constraints': has_constraints,
                'has_variables': has_variables,
                'has_output': has_output,
                'size': len(content)
            }
            
            if has_constraints and has_variables:
                meaningful_files.append(file_info)
            else:
                empty_files.append(file_info)
                
        except Exception as e:
            print(f"❌ 读取文件失败: {file_path}, 错误: {e}")
    
    print(f"\n📊 分析结果:")
    print(f"  • 有意义约束文件: {len(meaningful_files)}")
    print(f"  • 空约束文件: {len(empty_files)}")
    
    if meaningful_files:
        print(f"\n🏆 有意义的约束文件:")
        for i, file_info in enumerate(meaningful_files, 1):
            relative_path = os.path.relpath(file_info['path'], '/root/ardiff/symbolic_analysis')
            print(f"  {i}. {relative_path}")
            print(f"     约束: {'✅' if file_info['has_constraints'] else '❌'}")
            print(f"     变量: {'✅' if file_info['has_variables'] else '❌'}")
            print(f"     输出: {'✅' if file_info['has_output'] else '❌'}")
    
             
    print(f"\n📁 按测试用例分组:")
    test_groups = {}
    for file_info in meaningful_files:
        path_parts = Path(file_info['path']).parts
        if 'benchmarks' in path_parts:
            idx = path_parts.index('benchmarks')
            if len(path_parts) > idx + 3:
                test_name = '/'.join(path_parts[idx+1:idx+4])
                if test_name not in test_groups:
                    test_groups[test_name] = []
                test_groups[test_name].append(file_info)
    
    for test_name, files in test_groups.items():
        print(f"  🔸 {test_name}: {len(files)}个约束文件")
    
    return meaningful_files, empty_files

def generate_usage_guide(meaningful_files):
    """生成使用指南"""
    print(f"\n📋 使用指南:")
    print(f"{'='*50}")
    
    if meaningful_files:
        print(f"✅ 您现在拥有 {len(meaningful_files)} 个有效的SMT约束文件！")
        print(f"\n🔍 查看约束文件:")
        print(f"   find . -name '*_path_*.txt' -exec grep -l '(assert' {{}} \\;")
        
        print(f"\n📄 查看特定约束内容:")
        sample_file = os.path.relpath(meaningful_files[0]['path'], '/root/ardiff/symbolic_analysis')
        print(f"   cat {sample_file}")
        
        print(f"\n🧮 使用Z3求解器求解约束:")
        print(f"   # 安装Z3")
        print(f"   pip install z3-solver")
        print(f"   # 求解约束文件")
        print(f"   z3 {sample_file}")
        
        print(f"\n📊 统计约束类型:")
        print(f"   grep -h '(assert' */*/symbolic_*_path_*.txt | sort | uniq -c")
        
    else:
        print(f"❌ 当前没有生成有效约束。")
        print(f"\n🔧 建议:")
        print(f"   1. 检查程序是否有分支逻辑")
        print(f"   2. 确认scanf输入被正确符号化")
        print(f"   3. 验证程序能正常编译和运行")

if __name__ == "__main__":
    print("🚀 启动最终约束总结分析...")
    meaningful_files, empty_files = analyze_all_constraints()
    generate_usage_guide(meaningful_files)
    print(f"\n🎉 分析完成！") 