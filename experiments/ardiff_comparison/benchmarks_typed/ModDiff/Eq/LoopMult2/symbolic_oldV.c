#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

int snippet(int a, int b) {
    int c=0;
    		if (a==b) {
    			for (int i = 1; i <= a; ++i)
    				c += b;
    		}
    		return c;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    int a;
    int b;
    scanf("%d %d", &a, &b);
    int result = snippet(a, b);
    printf("Result: %d\n", result);
    return 0;
}
