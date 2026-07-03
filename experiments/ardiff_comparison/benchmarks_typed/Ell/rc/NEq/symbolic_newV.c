#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(double x, double y) {
    double ERRTOL=0.0012;
        double TINY=1.69e-38;
        double SQRTNY=1.3e-19;
        double BIG=3.0e37;
        double TNBG=TINY*BIG;
        double COMP1=2.236/SQRTNY;
        double COMP2=TNBG*TNBG/25.0;
        double THIRD=1.0/3.0;
        double C1=0.32;
        double C2=1.0/7.0;
        double C3=0.375;
        double C4=9.0/22.0;
        double alamb =0 ;
        double ave=0;
        double s=0;
        double w=0;
        double xt=0;
        double yt=0;
        if ((x+fabs(y)) < TINY || (x+fabs(y)) > BIG)//change
          return -10000+TNBG;//change
        if (y > 0.0) {
          xt+=x;
          yt+=y;
          w+=1.0;
        } else {
          xt+=x-y;
          yt+= -y;
          w+=sqrt(x)/sqrt(xt);
        }
        do {
          alamb*=2.0*sqrt(xt)*sqrt(yt)+yt;
          xt=0.25*(xt+alamb);
          yt=0.25*(yt+alamb);
          ave+=THIRD*(xt*yt*yt);
          s=(yt-ave)/ave;
        } while (fabs(s) > ERRTOL);
        return w*(1.0+s*s*(C1+s*(C2+s*(C3+s*C4))));
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    double x;
    double y;
    scanf("%lf %lf", &x, &y);
    double result = snippet(x, y);
    printf("Result: %f\n", result);
    return 0;
}
