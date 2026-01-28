#include <stdio.h>
#include <stdlib.h>

int snippet(int x, int y) {
        int result = 0; 
        int path = 0;
        if (x > 0) {
            if (y == x * x) {
                path = 1;
            }
            else {
                path = 2;
            }
            if (-y < -8) {//change
                if (path == 1)
                    result = 3;
                if (path == 2)
                    result = 13;
            }
            else {
                if (path == 1)
                    result = 4;
                if (path == 2)
                    result = 14;
            }
        }
        return result;
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