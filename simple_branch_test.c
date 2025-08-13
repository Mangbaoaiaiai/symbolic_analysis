#include <stdio.h>

int main(int argc, char* argv[]) {
    int x;
    int result = 0;
    
    if (argc > 1) {
        x = atoi(argv[1]);
    } else {
        x = 0;
    }
    
    // 简单的条件分支
    if (x > 10) {
        result = x * 2;
        printf("大于10: %d\n", result);
    } else if (x > 5) {
        result = x + 10;
        printf("大于5: %d\n", result);
    } else {
        result = x - 1;
        printf("小于等于5: %d\n", result);
    }
    
    return result;
} 