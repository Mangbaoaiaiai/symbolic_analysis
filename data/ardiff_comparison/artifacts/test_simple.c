#include <stdio.h>
#include <stdlib.h>

int snippet(int x) {
    if (x > 5) {
        return x + 10;
    } else {
        return x - 5;
    }
}

int main() {
    int x;
    scanf("%d", &x);
    int result = snippet(x);
    printf("Result: %d\n", result);
    return 0;
} 