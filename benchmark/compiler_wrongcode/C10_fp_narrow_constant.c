extern int printf(const char *, ...);
extern int scanf(const char *, ...);
int g = (float)16777217.0;
long snippet(void) { return g; }
int main(void) { printf("%ld\n", snippet()); return 0; }
