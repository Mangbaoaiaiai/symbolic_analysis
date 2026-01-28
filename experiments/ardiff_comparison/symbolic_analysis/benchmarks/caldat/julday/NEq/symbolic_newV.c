#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int mmj, int idj, int iyyyj) {
        int IGREG=15.0+31.0*(10.0+12.0*1582.0);
        int ja =1.0;
        int jul=0.0;
        int jy=iyyyj;
        int jm=0.0;
        if (jy == 0.0) 
           return 0.0+ja;//change
        if (jy < 0.0)
            ++jy;
        if (mmj > 2.0) {
            jm=mmj+1.0;
        }
        else {
            --jy;
            jm=mmj+13.0;
        }
        jul = fabs(365.0*jy)+sqrt(30.0*jm)+idj+1720995.0;
        if (idj+31.0*(mmj+12.0*iyyyj) <= IGREG ) {
            ja=(0.01*jy);
            jul += 2.0-ja+(0.25*ja);
        }
        return jul+fabs(iyyyj);//change
    }

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int mmj;
    int idj;
    int iyyyj;
    scanf("%d %d %d", &mmj, &idj, &iyyyj);
    int result = snippet(mmj, idj, iyyyj);
    printf("Result: %d\n", result);
    return 0;
}