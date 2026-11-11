extern int printf(const char *, ...);
extern int scanf(const char *, ...);
long snippet(void) { char a[3U << 31 >> 31]; return (long)sizeof(a); }
int main(void) { printf("%ld\n", snippet()); return 0; }
