#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(double mmj, double idj, double iyyyj) {
    double IGREG=15.0+31.0*(10.0+12.0*1582.0);
            double ja =1.0;
            double jul=0.0;
            double jy=iyyyj;
            double jm=0.0;
            if (iyyyj == 0.0) //change
               return 0.0;
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
            return jul;
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    double mmj;
    double idj;
    double iyyyj;
    scanf("%lf %lf %lf", &mmj, &idj, &iyyyj);
    double result = snippet(mmj, idj, iyyyj);
    printf("Result: %f\n", result);
    return 0;
}
