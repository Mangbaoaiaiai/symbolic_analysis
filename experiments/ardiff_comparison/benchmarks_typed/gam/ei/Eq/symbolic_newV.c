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
    int MAXIT=2;
            double EULER=0.577215664901533;
            double EPS=1e-14;
            double FPMIN=-79769313486232.0/1e-14;//change
            int k =0;
            double fact= 1.0;//change
            double prev=0;
            double sum=0;
            double term=0;
            if (x <= 0.0)
                return -10000;
            if (x < FPMIN)
                return log(x)+EULER;
            if (x <= -log(EPS)) {
                sum=0.0;//change:remove the next line
                for (k=1;k<=MAXIT;k++) {
                    fact *= x/k;
                    term=fact/k;
                    sum += term;
                    if (term < EPS*sum)
                        break;
                }
                return sum+log(x)+EULER;
            } else {
                sum=0.0;
                term=1.0;
                for (k=1;k<=MAXIT;k++) {
                    prev=term;
                    term *= k/x;
                    if (term < EPS)
                        break;
                    if (term < prev) sum += term;
                    else {
                        sum -= prev;
                        break;
                    }
                }
                return exp(x)*(1.0+sum)/x;
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
