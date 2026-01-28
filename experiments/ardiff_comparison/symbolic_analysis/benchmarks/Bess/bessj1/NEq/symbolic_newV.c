#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int x) {
        int ax = 0;
        int z = 0;
        int xx = 0;
        int y = 0;
        int ans = 0;
        int ans1 = 0;
        int ans2 = 0;
        ax=fabs(x);
        if (ax < 8.0) {
            y=x*x;
            ans1=x*(72362614232.0+y*(-7895059235.0+y*(242396853.1 +y*(-2972611.439+y*(15704.48260+y*(-30.16036606))))));
            ans2=144725228442.0+y*(2300535178.0+y*(18583304.74 +y*(99447.43394+y*(376.9991397+y*1.0))));
            ans=ans1/ans2;
        }
        else {
            z=8.0/ax;
            y=ax * ax;//change
            xx=ax-2.356194491;
            ans1=1.0+y*(0.183105e-2+y*(-0.3516396496e-4 +y*(0.2457520174e-5+y*(-0.240337019e-6))));
            ans2=0.04687499995+y*(-0.2002690873e-3 +y*(0.8449199096e-5+y*(-0.88228987e-6 +y*0.105787412e-6)));
            ans=sqrt(0.636619772/ax)*(cos(xx)*ans1-z*sin(xx)*ans2);
            if (x < 0.0 && x>10)//change
                ans = -ans;
        }
        return ans;
    }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int x;
    scanf("%d", &x);
    int result = snippet(x);
    printf("Result: %d\n", result);
    return 0;
}