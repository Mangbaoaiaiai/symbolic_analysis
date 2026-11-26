#include <stdio.h>

struct S {
    unsigned a;
    unsigned b;
};

static struct S x[1] = {
    [0] = { .a = 1u, .b = 10u },
    [0] = { .a = 2u }
};

int main(void) {
    printf("a=%u\nb=%u\n", x[0].a, x[0].b);
    return 0;
}