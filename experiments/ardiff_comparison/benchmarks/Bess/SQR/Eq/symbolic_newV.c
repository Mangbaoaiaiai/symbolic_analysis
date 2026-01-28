#include <stdio.h>
#include <stdlib.h>

int snippet(int a) {
        int result = 0;//change
        result = a*a;//change
        return result;//change
    }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int a;
    scanf("%d", &a);
    int result = snippet(a);
    printf("Result: %d\n", result);
    return 0;
}