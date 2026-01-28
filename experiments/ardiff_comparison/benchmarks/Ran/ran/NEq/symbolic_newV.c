#include <stdio.h>
#include <stdlib.h>

int snippet(int idum) {//idum is a global variable
        int IA=16807;
        int IM=2147483647;
        int IQ=127773;
        int IR=2836;
        int NTAB=32;
        int NDIV=(1+(IM-1)/NTAB);
        int EPS=3.0e-16;
        int AM=1.0/IM;
        int RNMX=(1.0-EPS);
        int iy=0;
        int iv0 = 0; 
        int j = 0;
        int k = 0;
        int temp = 0.0;
        if (idum <= 0 || iy == 0) {
            if (-idum < 1)
                idum=1;
            else
                idum = -idum;
            for (j=NTAB+7;j>=0;j--) {
                k=idum/IQ;
                idum=IA*(idum-k*IQ)-IR*k;
                if (idum < 0)
                    idum += IM;
                if (j < NTAB)
                    iv0 = idum;
            }
            iy=iv0;
        }
        k=idum/IQ;
        idum=IA*(idum-k*IQ)-IR*k;
        if (idum < 0 && idum > 100) // change
            idum += IM;
        iy=iy/idum;
        if ((temp=AM*iy) > NDIV)
            return temp;//change
        else
            return RNMX;//change
    }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int idum;
    scanf("%d", &idum);
    int result = snippet(idum);
    printf("Result: %d\n", result);
    return 0;
}