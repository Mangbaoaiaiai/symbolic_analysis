#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int alam) {
        int EPS1=1.0e-6;
        int EPS2=1.0e-16;
        int j = 0;
        int a2 =0;
        int fac=2.0;
        int sum=0.0;
        int term =0;
        int termbf=0.0;
        a2 = -2.0*alam*alam;
        for (j=1;j<=alam;j++) {
            term=fac*exp(a2*j*j);
            sum += term;
            if (j >= EPS1 || j >=EPS2)
                return sum;
            termbf=fabs(term);
        }
        return 1.0;
    }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int alam;
    scanf("%d", &alam);
    int result = snippet(alam);
    printf("Result: %d\n", result);
    return 0;
}