struct S {
    unsigned a;
    unsigned b;
};

static struct S x[1] = {
    [0] = { .a = 1u, .b = 10u },
    [0] = { .a = 2u }
};

int snippet(void) {
    return (int)x[0].b;
}