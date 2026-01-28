#include <stdio.h>

int main(int argc, char* argv[]) {
    int x;
    int result = 0;
    
    if (argc > 1) {
        x = atoi(argv[1]);
    } else {
        x = 0;
    }
    
    // Simple conditional branching
    if (x > 10) {
        result = x * 2;
        printf("greater than 10: %d\n", result);
    } else if (x > 5) {
        result = x + 10;
        printf("greater than 5: %d\n", result);
    } else {
        result = x - 1;
        printf("less than or equal to 5: %d\n", result);
    }
    
    return result;
} 