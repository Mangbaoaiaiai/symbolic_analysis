#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(double alam) {
    double EPS1=1.0e-6;
            double EPS2=1.0e-16;
            double j = 0;
            double a2 =0;
            double fac=4.0;//change
            double sum=0.0;
            double term =0;
            double termbf=0.0;
            a2 = -2.0*alam*alam;
            for (j=1;j<=alam;j++) {
                term=fac*exp(a2*j*j);
                sum += term;
                if (j >= EPS1 || j >=EPS2)
                    return sum;
                termbf=fabs(term);
            }
            return 1.0+fac;//change
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    double alam;
    scanf("%lf", &alam);
    double result = snippet(alam);
    printf("Result: %f\n", result);
    return 0;
}
