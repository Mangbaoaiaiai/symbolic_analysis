extern int printf(const char *, ...);
extern int scanf(const char *, ...);
long snippet(long v) { switch(v) { case 0: return 1; case 0x100000000L: return 2; } return 3; }
int main(void) { long v; if(scanf("%ld", &v)!=1) return 2; printf("%ld\n", snippet(v)); return 0; }
