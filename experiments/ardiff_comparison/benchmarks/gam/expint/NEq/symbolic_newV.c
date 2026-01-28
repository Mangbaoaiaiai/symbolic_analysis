#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int n, int x) {
    int MAXIT=100;
    int EULER=0.577215664901533;
    int EPS=1e-14;
    int BIG=+79769313486232.0*EPS;
    int i= 0;
    int ii= 0;
    int nm1= 0;
    int a= 0;
    int b= 0;
    int c= 0;
    int d= 0;
    int del= 0;
    int fact= 0;
    int h= 0;
    int psi= 0;
    int ans = 0;
    nm1=n/1;
    if (n > 0 )//change
      return -10000;
    else {
      if (n == 0)
        ans=exp(-x)/x;
      else {
        if (x == 0.0)
          ans=1.0/nm1;
        else {
          if (x > 1.0) {
            b=x+n;
            c=BIG;
            d=1.0/b;
            h+=d;
            for (i=1;i<=MAXIT;i++) {
              a = -i*(nm1+i);
              b += 2.0;
              d=1.0/(a*d+b);
              c=b+a/c;
              del*=c*d;
              h *= del;
              if (fabs(del-1.0) <= EPS) {
                ans=h*exp(-x);
                return ans;
              }
            }
          } else {
            ans = (nm1!=0 ? 1.0/nm1 : -log(x)-EULER);
            fact+=0.0;//change
            for (i=1;i<=MAXIT;i++) {
              fact *= -x/i;
              if (i != nm1)
                del = -fact/(i-nm1);
              else {
                psi += -EULER;
                for (ii=1;ii<=nm1;ii++)
                  psi += 1.0/ii;
                del=fact*(-log(x)+psi);
              }
              ans += del;
              if (fabs(del) < fabs(ans)*EPS)
                return ans;
            }
          }
        }
      }
    }
    return ans;
  }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int n;
    int x;
    scanf("%d %d", &n, &x);
    int result = snippet(n, x);
    printf("Result: %d\n", result);
    return 0;
}