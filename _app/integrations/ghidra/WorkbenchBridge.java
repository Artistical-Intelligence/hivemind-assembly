// Additive script: complete native Ghidra remains unchanged.
// @category Workbench
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.SourceType;
import ghidra.framework.options.Options;
import com.google.gson.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

public class WorkbenchBridge extends GhidraScript {
    private final Gson gson = new GsonBuilder().setPrettyPrinting().create();
    @Override public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) throw new IllegalArgumentException("Expected request and result paths");
        JsonObject req = JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject();
        JsonObject result = new JsonObject();
        String action = req.get("action").getAsString();
        String operation = req.get("operation_id").getAsString();
        Options state = currentProgram.getOptions("SpecialistWorkbench");
        long revision = state.getLong("revision", 0);
        result.addProperty("program", currentProgram.getName());
        result.addProperty("executable_sha256", currentProgram.getExecutableSHA256());
        result.addProperty("language", currentProgram.getLanguageID().toString());
        result.addProperty("compiler", currentProgram.getCompilerSpec().getCompilerSpecID().toString());
        result.addProperty("operation_id", operation);
        result.addProperty("revision", revision);
        result.addProperty("status", "completed");
        if (action.equals("inventory")) {
            JsonArray functions = new JsonArray();
            FunctionIterator iter = currentProgram.getFunctionManager().getFunctions(true);
            int cap = req.has("limit") ? Math.min(req.get("limit").getAsInt(), 2000) : 200;
            while (iter.hasNext() && functions.size() < cap && !monitor.isCancelled()) {
                Function f = iter.next(); JsonObject item = new JsonObject();
                item.addProperty("name", f.getName()); item.addProperty("entry", f.getEntryPoint().toString());
                item.addProperty("signature", f.getSignature().toString()); item.addProperty("size", f.getBody().getNumAddresses()); functions.add(item);
            }
            result.add("functions", functions); result.addProperty("total_functions", currentProgram.getFunctionManager().getFunctionCount());
        } else if (action.equals("decompile")) {
            Function f = getFunctionAt(toAddr(req.get("address").getAsString()));
            if (f == null) throw new IllegalArgumentException("No function at exact address");
            DecompInterface decompiler = new DecompInterface();
            try {
                if (!decompiler.openProgram(currentProgram)) throw new IllegalStateException("Decompiler open: " + decompiler.getLastMessage());
                DecompileResults r = decompiler.decompileFunction(f, 60, monitor);
                if (!r.decompileCompleted()) throw new IllegalStateException("Decompiler incomplete: " + r.getErrorMessage() + " last=" + decompiler.getLastMessage() + " timedOut=" + r.isTimedOut() + " cancelled=" + r.isCancelled());
                result.addProperty("source", r.getDecompiledFunction().getC());
            } finally { decompiler.dispose(); }
        } else if (action.equals("pcode")) {
            Instruction instruction = getInstructionAt(toAddr(req.get("address").getAsString()));
            if (instruction == null) throw new IllegalArgumentException("No instruction at address");
            JsonArray pcode = new JsonArray();
            for (var op : instruction.getPcode()) pcode.add(op.toString());
            result.add("raw_pcode", pcode); result.addProperty("instruction", instruction.toString());
        } else if (action.equals("annotate")) {
            String payloadHash = req.get("payload_hash").getAsString();
            String recorded = state.getString("operation." + operation, "");
            if (!recorded.isEmpty()) {
                if (!recorded.equals(payloadHash)) throw new IllegalArgumentException("Operation identity conflict");
                result.addProperty("status", "saved"); result.addProperty("reconciled", true);
            } else {
                if (req.get("expected_revision").getAsLong() != revision) throw new IllegalArgumentException("Stale native program revision");
                Function f = getFunctionAt(toAddr(req.get("address").getAsString()));
                if (f == null) throw new IllegalArgumentException("No function at exact address");
                if (req.has("expected_name") && !f.getName().equals(req.get("expected_name").getAsString())) throw new IllegalArgumentException("Function changed since proposal");
                int tx = currentProgram.startTransaction("Workbench " + operation); boolean commit = false;
                try {
                    f.setName(req.get("name").getAsString(), SourceType.USER_DEFINED);
                    state.setLong("revision", revision + 1); state.setString("operation." + operation, payloadHash); commit = true;
                } finally { currentProgram.endTransaction(tx, commit); }
                // The enclosing GhidraScript transaction is committed and saved by headless.
                // The controller reopens the project to confirm this ledger entry.
                result.addProperty("revision", revision + 1); result.addProperty("status", "committed");
            }
        } else if (action.equals("reconcile")) {
            result.addProperty("recorded_payload_hash", state.getString("operation." + operation, ""));
        } else throw new IllegalArgumentException("Unsupported action");
        Path dest = Path.of(args[1]); Path temp = dest.resolveSibling(dest.getFileName() + ".tmp");
        Files.writeString(temp, gson.toJson(result), StandardCharsets.UTF_8);
        Files.move(temp, dest, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        println("WORKBENCH_RESULT " + dest);
    }
}
