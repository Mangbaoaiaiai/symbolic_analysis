#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(double a, double x, double gln) {
    int ITMAX=2;
        double EPS=1e-14;
        double FPMIN=-748373838373838.0/EPS;
        int i =0;
        double an=0;
        double b=0;
        double c=0;
        double d=0;
        double del=0;
        double h=0;
        b=x+1.0-a;
        c=1.0/FPMIN;
        d=1.0/b;
        h=d;
        for (i=1;i<=ITMAX;i++) {
          an = -i*(i-a);
          b += 2.0;
          d=an*d+b;
          if (fabs(d) > FPMIN) //change
            d=FPMIN;
          c=b+an/c;
          if (fabs(c) < FPMIN)
            c=FPMIN;
          d=1.0/d;
          del+=d*c;
          del/=FPMIN;//change
          h *= del;
          if (fabs(del-1.0) <= EPS)
            break;
        }
        return exp(-x+a*log(x)-gln)*h;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    double a;
    double x;
    double gln;
    scanf("%lf %lf %lf", &a, &x, &gln);
    double result = snippet(a, x, gln);
    printf("Result: %f\n", result);
    return 0;
}
