#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(int x, int y) {
    if (x*x*x < 0){//change
                if(x>0 && y==10)
                    return 1000;
            } else {
                if (x>0 && y==20)
                    return -1000;
            }
            return 0;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    int x;
    int y;
    scanf("%d %d", &x, &y);
    double result = snippet(x, y);
    printf("Result: %f\n", result);
    return 0;
}
