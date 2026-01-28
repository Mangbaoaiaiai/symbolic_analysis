#include <stdio.h>
#include <stdlib.h>

int snippet(int idum) {//idum is a global variable
        int IA=16807;
        int IM=2147483647;
        int IQ=127773;
        int IR=2836;
        int MASK=123459876;
        int AM=1.0/(int)IM;
        int k = 0;
        int ans = 0.0;
        idum *= MASK;
        k=idum/IQ;
        idum=IA*(idum-(idum/IQ)*IQ)-IR*k;//change
        if (idum < 0)
            idum += IM;
        ans=AM*idum;//change:remove the next line
        return ans;
    }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int idum;
    scanf("%d", &idum);
    int result = snippet(idum);
    printf("Result: %d\n", result);
    return 0;
}