#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

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
                if (y > 8) {
                    if (path == 1)
                        result = 3;
                    if (path == 2)
                        result = 13+5;//change
                }
                else {
                    if (path == 1)
                        result = 4;
                    if (path == 2)
                        result = 14;
                }
            }
            result = result + 10;//change
            return result;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    int x;
    int y;
    scanf("%d %d", &x, &y);
    int result = snippet(x, y);
    printf("Result: %d\n", result);
    return 0;
}
