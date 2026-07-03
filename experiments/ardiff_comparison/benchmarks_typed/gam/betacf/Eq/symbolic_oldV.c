#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(double a, double b, double x) {
    int MAXIT=100;
        double EPS=1e-14;
        double FPMIN=-7837383829242323.0/EPS;
        int m=0;
        int m2=0;
        double aa=0;
        double c=0;
        double d=0;
        double del=0;
        double h=0;
        double qab=0;
        double qam=0;
        double qap=0;
        qab=a+b;
        qap=a+1.0;
        qam=a-1.0;
        c=1.0;
        d=1.0-qab*x/qap;
        if (fabs(d) < FPMIN)
          d=FPMIN;
        d=1.0/d;
        h=d;
        for (m=1;m<=MAXIT;m++) {
          m2=2*m;
          aa=m*(b-m)*x/((qam+m2)*(a+m2));
          d=1.0+aa*d;
          if (fabs(d) < FPMIN)
            d=FPMIN;
          c=1.0+aa/c;
          if (fabs(c) < FPMIN)
            c=FPMIN;
          d=1.0/d;
          h *= d*c;
          aa = -(a+m)*(qab+m)*x/((a+m2)*(qap+m2));
          d=1.0+aa*d;
          if (fabs(d) < FPMIN)
            d=FPMIN;
          c=1.0+aa/c;
          if (fabs(c) < FPMIN)
            c=FPMIN;
          d=1.0/d;
          del=d*c;
          h *= del;
          if (fabs(del-1.0) <= EPS)
            break;
        }
        return h;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    double a;
    double b;
    double x;
    scanf("%lf %lf %lf", &a, &b, &x);
    double result = snippet(a, b, x);
    printf("Result: %f\n", result);
    return 0;
}
