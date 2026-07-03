#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(int idum) {
    //idum is a global variable
            int IA=16807;
            int IM=2147483647;
            int IQ=127773;
            int IR=2836;
            int MASK=123459876;
            double AM=1.0/(double)IM;
            int k = 0;
            double ans = 0.0;
            idum *= MASK;
            k=idum/IQ;
            idum=IA*(idum-k*IQ)-IR*k;
            if (idum < 0)
                idum += IM;
            ans=AM*idum;
            idum *= MASK;
            return ans;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    int idum;
    scanf("%d", &idum);
    double result = snippet(idum);
    printf("Result: %f\n", result);
    return 0;
}
