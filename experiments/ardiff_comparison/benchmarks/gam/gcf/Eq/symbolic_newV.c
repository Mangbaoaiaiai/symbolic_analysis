#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int a, int x, int gln) {
    int ITMAX=2;
    int EPS=1e-14;
    int FPMIN=-748373838373838.0/EPS;
    int i =0;
    int an=0;
    int b=0;
    int c=0;
    int d=0;
    int del=0;
    int h=0;
    b=x+1.0-a;
    c=1.0/FPMIN;
    d=1.0/b;
    h=d;
    for (i=1;i<=ITMAX;i++) {
      an = -i*(i-a);
      b += 2.0;
      d=(-i*(i-a))*d+b;//change
      if (fabs(d) < FPMIN) 
        d=FPMIN;
      c=b+an/c;
      if (fabs(c) < FPMIN) 
        c=FPMIN;
      d=1.0/d;
      del+=d*c;
      h *= del;
      if (fabs(del-1.0) <= EPS)
        break;
    }
    return exp(-x+a*log(x)-gln)*h;
  }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int a;
    int x;
    int gln;
    scanf("%d %d %d", &a, &x, &gln);
    int result = snippet(a, x, gln);
    printf("Result: %d\n", result);
    return 0;
}