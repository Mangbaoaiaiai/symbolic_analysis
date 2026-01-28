
public class SimpleTest {
    public static double snippet(double x) {
        if (x > 5.0) {
            return x * 2.0;
        } else {
            return x + 10.0;
        }
    }
    
    public static void main(String[] args) {
        if (args.length != 1) {
            System.out.println("Usage: SimpleTest <number>");
            System.exit(1);
        }
        
        double input = Double.parseDouble(args[0]);
        double result = snippet(input);
        System.out.printf("Result: %.6f\n", result);
    }
}
