#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int a, int b, int x) {
    int MAXIT=100;
    int EPS=1e-14;
    int FPMIN=-7837383829242323.0/EPS;
    int m=0;
    int m2=0;
    int aa=0;
    int c=0;
    int d=0;
    int del=0;
    int h=0;
    int qab=0;
    int qam=0;
    int qap=0;
    int one =1.0;//change
    qab=a+b;
    qap=a+one;//change
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
      d=1.0+(-(a+m)*(qab+m)*x/((a+m2)*(qap+m2)))*d;//change
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
    // 符号化输入 - angr会自动处理这些scanf调用
    int a;
    int b;
    int x;
    scanf("%d %d %d", &a, &b, &x);
    int result = snippet(a, b, x);
    printf("Result: %d\n", result);
    return 0;
}