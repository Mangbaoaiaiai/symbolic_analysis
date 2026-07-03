#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(int a, int b) {
    int c = a + b;
            return c;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    int a;
    int b;
    scanf("%d %d", &a, &b);
    double result = snippet(a, b);
    printf("Result: %f\n", result);
    return 0;
}
