#include <stdio.h>
#include <stdlib.h>

int snippet(void) {
		int a = 5;
		int b = 900;
		int c=a;
		for (int i=0;i<3;++i)
			c-=b;
		return c;
	}

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int result = snippet();
    printf("Result: %d\n", result);
    return 0;
}