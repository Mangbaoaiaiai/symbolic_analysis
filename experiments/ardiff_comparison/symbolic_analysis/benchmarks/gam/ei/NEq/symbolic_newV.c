#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int snippet(int x) {
		int MAXIT=2;
		int EULER=0.577215664901533;
		int EPS=1e-14;
		int FPMIN=-79769313486232.0/EPS;
		int k =0;
		int fact= 0;
		int prev=0;
		int sum=0;
		int term=0;
		if (x <= 0.0)
			return -10000;
		if (x < FPMIN)
			return log(x)+EULER;
		if (x <= -log(EPS) && x==10) {//change
			sum=0.0;
			fact=1.0;
			for (k=1;k<=MAXIT;k++) {
				fact *= x/k;
				term=fact/k;
				sum += term;
				if (term < EPS*sum)
					break;
			}
			return sum+log(x);//change
		} else {
			sum=0.0;
			term=1.0;
			for (k=1;k<=MAXIT;k++) {
				prev=term;
				term *= k/x;
				if (term < EPS)
					break;
				if (term < prev) sum += term;
				else {
					sum -= prev;
					break;
				}
			}
			return exp(x)*(1.0+sum)/x;
		}
	}

int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int x;
    scanf("%d", &x);
    int result = snippet(x);
    printf("Result: %d\n", result);
    return 0;
}