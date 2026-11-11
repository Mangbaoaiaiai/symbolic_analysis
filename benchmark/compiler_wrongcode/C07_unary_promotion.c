extern int printf(const char *, ...);
extern int scanf(const char *, ...);
long snippet(void) { char c=0; return (long)sizeof(+c); }
int main(void) { printf("%ld\n", snippet()); return 0; }
