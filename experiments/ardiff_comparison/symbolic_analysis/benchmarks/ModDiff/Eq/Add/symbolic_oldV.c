#include <stdio.h>
#include <stdlib.h>

int snippet(int a, int b) {
        int c = a + b;
        return c;
    }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int a;
    int b;
    scanf("%d %d", &a, &b);
    int result = snippet(a, b);
    printf("Result: %d\n", result);
    return 0;
}