#include <stdio.h>
union U { int a; char c[4]; };
union U u = { .a = 42, .c[2] = 1 };
int main(void) {
    printf("%d %d %d %d\n", u.c[0], u.c[1], u.c[2], u.c[3]);
    return 0;
}