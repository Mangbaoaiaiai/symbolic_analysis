#include <stdio.h>
#include <stdlib.h>

int snippet(int x, int y) {
        if (x*x*x > 0){
            if(y==10)//change
                return 1000;
        } else {
            if (0)//change
                return -1000;
        }
        return 0;
    }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int x;
    int y;
    scanf("%d %d", &x, &y);
    int result = snippet(x, y);
    printf("Result: %d\n", result);
    return 0;
}