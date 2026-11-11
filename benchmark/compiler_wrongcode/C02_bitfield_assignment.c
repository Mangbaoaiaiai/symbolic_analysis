extern int printf(const char *, ...);
extern int scanf(const char *, ...);
long snippet(unsigned int v) { struct S { unsigned a:3; } s={0}; return (long)(s.a=v); }
int main(void) { unsigned int v; if(scanf("%u", &v)!=1) return 2; printf("%ld\n", snippet(v)); return 0; }
