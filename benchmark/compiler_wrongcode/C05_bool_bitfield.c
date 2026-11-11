extern int printf(const char *, ...);
extern int scanf(const char *, ...);
long snippet(unsigned int v) { struct S { _Bool f:1; } s={0}; s.f=(v&1u); return (long)s.f; }
int main(void) { unsigned int v; if(scanf("%u", &v)!=1) return 2; printf("%ld\n", snippet(v)); return 0; }
