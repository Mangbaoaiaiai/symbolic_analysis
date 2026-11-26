#include <stdio.h>

extern int snippet(void);

int main(void) {
    printf("%d\n", snippet());
    return 0;
}