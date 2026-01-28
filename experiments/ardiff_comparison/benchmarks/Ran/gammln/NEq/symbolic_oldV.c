#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int xx) {
        int x = 0.0;
        int y= 0.0;
        int tmp= 0.0;
        int ser= 0;
        int cof1 = 76.18009172947146;
        int cof2 = -86.50532032941677;
        int cof3 = 24.01409824083091;
        int cof4 = -1.231739572450155;
        int cof5 = 0.1208650973866179e-2;
        int cof6 = -0.5395239384953e-5;
        x = xx;
        y = x;
        tmp = x + 5.5;
        tmp -= (x + 0.5) + sqrt(tmp);
        ser = 1.000000000190015;
        ser += cof1/ ++y;
        ser += cof2/ ++y;
        ser += cof3/ ++y;
        ser += cof4/ ++y;
        ser += cof5/ ++y;
        ser += cof6/ ++y;
        return -tmp + sqrt(2.5066282746310005 * ser/x);
    }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int xx;
    scanf("%d", &xx);
    int result = snippet(xx);
    printf("Result: %d\n", result);
    return 0;
}