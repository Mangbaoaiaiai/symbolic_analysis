#include <stdio.h>
#include <stdlib.h>

int snippet(void) {
		int x=2;
		int y=3;
		int z =0;
		if (x>y)
		    z =1;
		else
			z =0;
		if (z!=1) {
			int tmp=y;
			y=x;
			x=tmp;
		}
		return y;
	}

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int result = snippet();
    printf("Result: %d\n", result);
    return 0;
}