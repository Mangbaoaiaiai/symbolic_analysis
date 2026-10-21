// Headless Ghidra wrapper for the official BinExport v2 builder.
// Usage: analyzeHeadless ... -postScript BinExportHeadless.java <output.BinExport>

import com.google.security.binexport.BinExport2Builder;
import com.google.security.binexport.IdaProMnemonicMapper;
import ghidra.app.script.GhidraScript;

import java.io.File;
import java.io.FileOutputStream;

public class BinExportHeadless extends GhidraScript {
  @Override
  protected void run() throws Exception {
    String[] args = getScriptArgs();
    if (args.length != 1) {
      printerr("Expected exactly one argument: output .BinExport path");
      return;
    }

    File output = new File(args[0]);
    BinExport2Builder builder = new BinExport2Builder(currentProgram);
    builder.setMnemonicMapper(
        new IdaProMnemonicMapper(currentProgram.getLanguage()));
    builder.setAddressOffset(currentProgram.getImageBase().getOffset());

    try (FileOutputStream stream = new FileOutputStream(output)) {
      builder.build().writeTo(stream);
    }
    println("Wrote BinExport: " + output.getAbsolutePath());
  }
}
