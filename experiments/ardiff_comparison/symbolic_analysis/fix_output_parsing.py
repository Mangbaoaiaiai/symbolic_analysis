                      
"""
修复程序输出解析问题
"""

def extract_program_output_fixed(content):
    """修复的程序输出提取函数"""
    lines = content.split('\n')
    program_output = ""
    
    for i, line in enumerate(lines):
        if line.strip().startswith('; 程序输出:'):
                          
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not next_line.startswith(';'):
                    program_output = next_line
                    break
    
    return program_output

          
with open('benchmarks/Airy/MAX/Eq/symbolic_newV_path_1.txt', 'r') as f:
    content = f.read()

output = extract_program_output_fixed(content)
print(f"提取的程序输出: '{output}'")
