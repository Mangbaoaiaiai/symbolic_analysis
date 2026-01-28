#include <stdio.h>
#include <stdlib.h>

int snippet(int x) {
		int c=900;
		for (int i=0;i<3;++i)
			c-=5;
		return c;
	}

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int x;
    scanf("%d", &x);
    int result = snippet(x);
    printf("Result: %d\n", result);
    return 0;
}