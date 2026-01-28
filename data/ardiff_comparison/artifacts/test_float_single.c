#include <stdio.h>
#include <stdlib.h>

double snippet(double x) {
    if (x > 2.5) {
        return x * 2.0;
    } else {
        return x + 1.0;
    }
}

int main() {
    double x;
    scanf("%lf", &x);
    double result = snippet(x);
    printf("Result: %f\n", result);
    return 0;
} 