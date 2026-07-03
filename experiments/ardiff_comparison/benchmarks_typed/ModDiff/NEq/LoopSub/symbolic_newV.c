#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

int snippet(int x) {
    int c=900;
    		for (int i=0;i<3;++i)
    			c-=5;
    		return c;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    int x;
    scanf("%d", &x);
    int result = snippet(x);
    printf("Result: %d\n", result);
    return 0;
}
