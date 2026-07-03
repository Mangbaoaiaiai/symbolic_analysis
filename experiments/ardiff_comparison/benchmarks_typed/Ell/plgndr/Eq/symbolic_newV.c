#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(int l, int m, double x) {
    int i=0;
        int ll=0;
        double fact =1;
        double pll = 0;
        double pmm = 0;
        double pmmp1= 0;
        double somx2= 0;
        double result =0;//change
        if (m < 0 || m > l || fabs(x) > 1.0)
          return -1000;
        pmm=1.0;
        if (m > 0) {
          somx2=sqrt((1.0-x)*(1.0+x));
          fact=pll+1.0;//change
          for (i=1;i<=m;i++) {
            pmm *= -fact*somx2;
            fact += 2.0;
          }
        }
        if (l == m){
          result =pmm;//change
          return result;//change
        }
        else {
          pmmp1=x*(2*m+1)*pmm;
          for (ll=m+2;ll<=l;ll++) {
            pll=(x*(2*ll-1)*pmmp1-(ll+m-1)*pmm)/(ll-m);
            pmm=pmmp1;
            pmmp1=pll;
          }
            return pll;
        }
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    int l;
    int m;
    double x;
    scanf("%d %d %lf", &l, &m, &x);
    double result = snippet(l, m, x);
    printf("Result: %f\n", result);
    return 0;
}
