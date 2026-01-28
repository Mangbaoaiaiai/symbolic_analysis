#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int x) {
        int ax = 0;
        int ans = 0;
        int y = 0;
        ax = fabs(x);
        if (ax < 3.75) {
            y=x/3.75;
            y*=y;
            ans=ax*(0.5+y*(0.87890594+y*(0.51498869+y*(0.15084934 +y*(0.2658733e-1+y*(0.301532e-2+y*0.32411e-3))))));
        } else {
            y=3.75/ax;
            ans=0.2282967e-1+(3.75/ax)*(-0.2895312e-1+(3.75/ax)*(0.1787654e-1 -(3.75/ax)*0.420059e-2));//change
            ans=0.39894228+y*(-0.3988024e-1+y*(-0.362018e-2 +y*(0.163801e-2+y*(-0.1031555e-1+y*ans))));
            ans *= (exp(ax)/sqrt(ax));
        }
        if (x < 0.0)
            return -ans;
        else
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