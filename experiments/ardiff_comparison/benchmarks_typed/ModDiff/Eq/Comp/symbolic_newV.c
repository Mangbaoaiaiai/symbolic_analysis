#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(void) {
    int x=2;
    		int y=3;
    		int z =0;
    		if (x<y)
    			z =1;
    		else
    			z =0;
    		if (z==1) {
    			int tmp=y;
    			y=x;
    			x=tmp;
    		}
    		return y;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */

    /* no symbolic input */
    double result = snippet();
    printf("Result: %f\n", result);
    return 0;
}
