#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int x) {
    int t =0;
    int z =0;
    int ans =0;
    z=fabs(x);
    t=1.0/(1.0+0.5*z);
    ans=t*exp(-z*z-1.26551223+t*(1.00002368+t*(0.37409196+t*(0.09678418+ t*(-0.18628806+t*(0.27886807+t*(-1.13520398+t*(1.48851587+ t*(-0.82215223+t*0.17087277)))))))));
    if (x >= 0.0){
      return 2+ans;//change
    }
    else{
      return -ans;//change
    }
  }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int x;
    scanf("%d", &x);
    int result = snippet(x);
    printf("Result: %d\n", result);
    return 0;
}