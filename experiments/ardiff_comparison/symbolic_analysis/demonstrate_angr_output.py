                      
"""
演示angr如何获取程序输出
"""

import angr
import claripy

def demonstrate_angr_output():
    """演示angr获取程序输出的过程"""
    print("🔍 演示angr如何获取程序输出")
    print("=" * 50)
    
                   
    c_code = '''
#include <stdio.h>
int main() {
    int a, b;
    scanf("%d %d", &a, &b);
    if (a > b) {
        printf("Result: %d\\n", a);
    } else {
        printf("Result: %d\\n", b);
    }
    return 0;
}
'''
    
    print("📋 示例C程序:")
    print(c_code)
    
                            
    binary_path = "/root/ardiff/symbolic_analysis/benchmarks/Airy/MAX/Eq/symbolic_newV"
    
    try:
        print(f"\n🔧 加载二进制文件: {binary_path}")
        project = angr.Project(binary_path, auto_load_libs=False)
        
                          
        class SimpleScanfHook(angr.SimProcedure):
            def run(self, fmt_ptr, *args):
                          
                a = claripy.BVS('a', 32)
                b = claripy.BVS('b', 32)
                
                        
                self.state.solver.add(a >= 0)
                self.state.solver.add(a <= 10)
                self.state.solver.add(b >= 0)
                self.state.solver.add(b <= 10)
                
                           
                self.state.memory.store(args[0], a)
                self.state.memory.store(args[1], b)
                
                print(f"  📝 创建符号变量: a={a}, b={b}")
                return 2             
        
                      
        project.hook_symbol('scanf', SimpleScanfHook())
        
                
        initial_state = project.factory.entry_state()
        
        print("\n🚀 开始符号执行...")
        simgr = project.factory.simulation_manager(initial_state)
        simgr.run()
        
        print(f"\n📊 符号执行结果:")
        print(f"  终止路径数: {len(simgr.deadended)}")
        print(f"  活跃路径数: {len(simgr.active)}")
        
                  
        for i, state in enumerate(simgr.deadended):
            print(f"\n🔍 分析路径 {i+1}:")
            
                        
            try:
                a_val = state.solver.eval(state.solver.BVS('a', 32), cast_to=int)
                b_val = state.solver.eval(state.solver.BVS('b', 32), cast_to=int)
                print(f"  输入值: a={a_val}, b={b_val}")
            except:
                print(f"  输入值: 无法获取具体值")
            
                    
            try:
                output = state.posix.dumps(1).decode(errors='ignore').strip()
                print(f"  程序输出: '{output}'")
                
                            
                print(f"  📝 输出分析:")
                print(f"    - stdout内容: {repr(state.posix.dumps(1))}")
                print(f"    - 解码后: {repr(output)}")
                
            except Exception as e:
                print(f"  ❌ 获取输出失败: {e}")
            
                  
            print(f"  约束数量: {len(state.solver.constraints)}")
            for j, constraint in enumerate(state.solver.constraints[:3]):          
                print(f"    约束{j+1}: {constraint}")
    
    except Exception as e:
        print(f"❌ 演示失败: {e}")
        print("这可能是因为二进制文件不存在或格式不兼容")

def explain_angr_output_mechanism():
    """解释angr输出机制"""
    print(f"\n📚 Angr获取程序输出的机制:")
    print("=" * 50)
    
    print("1. 状态维护:")
    print("   - Angr维护一个符号状态，包含所有程序状态")
    print("   - 包括内存、寄存器、文件描述符等")
    print("   - 文件描述符1对应stdout")
    
    print("\n2. 系统调用模拟:")
    print("   - 当程序调用printf时，angr模拟这个系统调用")
    print("   - 将输出内容写入到状态的文件描述符中")
    print("   - 保持符号形式，不立即具体化")
    
    print("\n3. 输出获取:")
    print("   - state.posix.dumps(1) 获取stdout的内容")
    print("   - 返回的是字节数据")
    print("   - 需要decode()转换为字符串")
    
    print("\n4. 具体化过程:")
    print("   - 当需要具体输出时，使用SMT求解器")
    print("   - 找到满足当前约束的具体值")
    print("   - 将符号表达式替换为具体值")
    print("   - 得到具体的输出字符串")
    
    print("\n5. 多路径处理:")
    print("   - 每个路径可能有不同的输出")
    print("   - 每个路径的约束不同，导致不同的具体值")
    print("   - 因此每个路径产生不同的输出")

if __name__ == "__main__":
    demonstrate_angr_output()
    explain_angr_output_mechanism()
