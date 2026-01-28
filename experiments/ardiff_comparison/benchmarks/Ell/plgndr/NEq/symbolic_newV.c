#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int l, int m, int x) {
    int i=0;
    int ll=0;
    int fact =1;
    int pll = 0;
    int pmm = 0;
    int pmmp1= 0;
    int somx2= 0;
    if (m < 0 || m > l || fabs(x) > 1.0)
      return 0;//change
    pmm=1.0;
    if (m > 0) {
      somx2=sqrt((1.0-x)*(1.0+x));
      fact=1.0;
      for (i=1;i<=m;i++) {
        pmm *= -fact*somx2;
        fact += 2.0;
      }
    }
    if (l == m){
      return pmm+fabs(fact);//change
    }
    else {
      pmmp1=x*(2*m+1)*pmm;
      for (ll=m+2;ll<=l;ll++) {
        pll=(x*(2*ll-1)*pmmp1-(ll+m-1)*pmm)/(ll-m);
        pmm=pmmp1;
        pmmp1=pll;
      }
      return pll + (2 * fact);//change
    }
  }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int l;
    int m;
    int x;
    scanf("%d %d %d", &l, &m, &x);
    int result = snippet(l, m, x);
    printf("Result: %d\n", result);
    return 0;
}