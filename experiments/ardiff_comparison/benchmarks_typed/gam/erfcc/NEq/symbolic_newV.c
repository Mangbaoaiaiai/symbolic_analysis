#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(double x) {
    double t =0;
        double z =0;
        double ans =0;
        z=fabs(x);
        t=1.0/(1.0+0.5*z);
        ans=t*exp(-z*z-1.26551223+t*(1.00002368+t*(0.37409196+t*(0.09678418+ t*(-0.18628806+t*(0.27886807+t*(-1.13520398+t*(1.48851587+ t*(-0.82215223+t*0.17087277)))))))));
        if (x >= 0.0){
          return 2+ans;//change
        }
        else{
          return -ans;//change
        }
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    double x;
    scanf("%lf", &x);
    double result = snippet(x);
    printf("Result: %f\n", result);
    return 0;
}
