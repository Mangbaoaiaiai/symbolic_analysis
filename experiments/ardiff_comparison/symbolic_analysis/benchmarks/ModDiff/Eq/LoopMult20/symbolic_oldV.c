#include <stdio.h>
#include <stdlib.h>

int snippet(int x) {
		if (x>=18 && x<22){
			int c=0;
			for (int i=1;i<=20;++i)
				c+=x;
			return c;
		}
		return 0;
	}

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int x;
    scanf("%d", &x);
    int result = snippet(x);
    printf("Result: %d\n", result);
    return 0;
}