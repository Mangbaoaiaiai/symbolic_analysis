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
    if (x>=18 && x<22){
    			int c=0;
    			for (int i=1;i<=x;++i)
    				c+=20;
    			return c;
    		}
    		return 0;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    int x;
    scanf("%d", &x);
    int result = snippet(x);
    printf("Result: %d\n", result);
    return 0;
}
