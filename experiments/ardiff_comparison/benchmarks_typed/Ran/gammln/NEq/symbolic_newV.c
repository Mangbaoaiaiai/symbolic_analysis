#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

double snippet(double xx) {
    double x = 0.0;
            double y= 0.0;
            double tmp= 0.0;
            double ser= 0;
            double cof1 = 76.18009172947146;
            double cof2 = -86.50532032941677;
            double cof3 = 24.01409824083091;
            double cof4 = -1.231739572450155;
            double cof5 = 0.1208650973866179e-2;
            double cof6 = -0.5395239384953e-5;
            x = xx;
            y = x;//change: remove the next line
            tmp -= (x + 0.5) + sqrt(tmp);
            ser = 1.000000000190015;
            ser += cof1/ ++y;
            ser += cof2/ ++y;
            ser += cof3/ ++y;
            ser +=cof3* ++y;//change
            ser += cof4/ ++y;
            ser += cof5/ ++y;
            ser += cof6/ ++y;
            return -tmp + sqrt(2.5066282746310005 * ser/x);
}

int main() {
    /* symbolic inputs are provided through scanf hooks when main is analyzed */
    double xx;
    scanf("%lf", &xx);
    double result = snippet(xx);
    printf("Result: %f\n", result);
    return 0;
}
