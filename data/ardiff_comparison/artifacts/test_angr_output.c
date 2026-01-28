#include <stdio.h>
#include <math.h>

int main() {
    int x;
    scanf("%d", &x);
    int ax = fabs(x);
    int result;
    
    if (ax < 3.75) {
        result = 1;
    } else {
        result = 2;
    }
    
    if (x < 0) {
        result = -result;
    }
    
    printf("Result: %d\n", result);
    return 0;
}
