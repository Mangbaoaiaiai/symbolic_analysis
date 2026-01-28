#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int x, int y) {
    int ERRTOL=0.0012;
    int TINY=1.69e-38;
    int SQRTNY=1.3e-19;
    int BIG=3.0e37;
    int TNBG=TINY*BIG;
    int COMP1=2.236/SQRTNY;
    int COMP2=TNBG*TNBG/25.0;
    int THIRD=1.0/3.0;
    int C1=0.32;
    int C2=1.0/7.0;
    int C3=0.375;
    int C4=9.0/22.0;
    int alamb =0 ;
    int ave=0;
    int s=0;
    int w=0;
    int xt=0;
    int yt=0;
    if (x < 0.0 || y == 0.0 || (x+fabs(y)) < TINY || (x+fabs(y)) > BIG)
      return -10000;
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
    // 符号化输入 - angr会自动处理这些scanf调用
    int x;
    int y;
    scanf("%d %d", &x, &y);
    int result = snippet(x, y);
    printf("Result: %d\n", result);
    return 0;
}