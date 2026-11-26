union U {
    int a;
    char c[4];
};

int snippet(void) {
    union U u = { .a = 42, .c[2] = 1 };
    return (int)u.c[0];
}