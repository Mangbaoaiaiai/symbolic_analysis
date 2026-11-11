extern int printf(const char *, ...);
extern int scanf(const char *, ...);
_Bool g = 0.5 && 0.3;
long snippet(void) { return g; }
int main(void) { printf("%ld\n", snippet()); return 0; }
