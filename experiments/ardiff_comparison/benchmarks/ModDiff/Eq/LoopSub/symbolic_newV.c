#include <stdio.h>
#include <stdlib.h>

int snippet(void) {
		int a = 900;
		int b = 5;
		int c=b;
		for (int i=0;i<3;++i)
			c-=a;
		return c;
	}

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int result = snippet();
    printf("Result: %d\n", result);
    return 0;
}