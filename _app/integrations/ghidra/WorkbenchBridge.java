// Additive script: complete native Ghidra remains unchanged.
// @category Workbench
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.data.*;
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
            int cap = req.has("limit") ? req.get("limit").getAsInt() : 200;
            int offset = req.has("offset") ? req.get("offset").getAsInt() : 0;
            if (cap < 1 || cap > 2000 || offset < 0) throw new IllegalArgumentException("Invalid inventory page bounds");
            int skipped = 0;
            while (iter.hasNext() && skipped < offset) { monitor.checkCancelled(); iter.next(); skipped++; }
            while (iter.hasNext() && functions.size() < cap && !monitor.isCancelled()) {
                Function f = iter.next(); JsonObject item = new JsonObject();
                item.addProperty("name", f.getName()); item.addProperty("entry", f.getEntryPoint().toString());
                item.addProperty("signature", f.getSignature().toString()); item.addProperty("size", f.getBody().getNumAddresses()); item.addProperty("external", f.isExternal()); item.addProperty("thunk", f.isThunk()); functions.add(item);
            }
            monitor.checkCancelled();
            result.add("functions", functions); result.addProperty("total_functions", currentProgram.getFunctionManager().getFunctionCount());
            result.addProperty("offset", offset); result.addProperty("next_offset", offset + functions.size()); result.addProperty("has_more", iter.hasNext());
        } else if (action.equals("decompile") || action.equals("decompile_batch")) {
            JsonArray addresses = action.equals("decompile_batch") ? req.getAsJsonArray("addresses") : new JsonArray();
            if (action.equals("decompile")) addresses.add(req.get("address"));
            if (addresses.size() < 1 || addresses.size() > 8) throw new IllegalArgumentException("Use 1–8 exact function addresses");
            JsonArray units = new JsonArray();
            DecompInterface decompiler = new DecompInterface();
            try {
                if (!decompiler.openProgram(currentProgram)) throw new IllegalStateException("Decompiler open: " + decompiler.getLastMessage());
                for (JsonElement address : addresses) {
                    Function f = getFunctionAt(toAddr(address.getAsString()));
                    if (f == null) throw new IllegalArgumentException("No function at exact address");
                    DecompileResults r = decompiler.decompileFunction(f, 60, monitor);
                    if (!r.decompileCompleted()) throw new IllegalStateException("Decompiler incomplete: " + r.getErrorMessage());
                    JsonObject unit = new JsonObject();
                    unit.addProperty("address", f.getEntryPoint().toString());
                    unit.addProperty("name", f.getName());
                    unit.addProperty("source", r.getDecompiledFunction().getC());
                    units.add(unit);
                }
            } finally { decompiler.dispose(); }
            if (action.equals("decompile")) result.add("source", units.get(0).getAsJsonObject().get("source"));
            else result.add("units", units);
        } else if (action.startsWith("context_")) {
            int cap = req.has("limit") ? req.get("limit").getAsInt() : 200;
            int offset = req.has("offset") ? req.get("offset").getAsInt() : 0;
            if (cap < 1 || cap > 2000 || offset < 0) throw new IllegalArgumentException("Invalid page bounds");
            JsonArray rows = new JsonArray(); int skipped = 0; boolean more = false;
            if (action.equals("context_layout")) {
                for (var block : currentProgram.getMemory().getBlocks()) {
                    JsonObject v = new JsonObject();v.addProperty("name",block.getName());
                    v.addProperty("start",block.getStart().toString());v.addProperty("size",block.getSize());
                    v.addProperty("read",block.isRead());v.addProperty("write",block.isWrite());v.addProperty("execute",block.isExecute());
                    v.addProperty("initialized",block.isInitialized());rows.add(v);
                }
                JsonArray exports = new JsonArray();var entries=currentProgram.getSymbolTable().getExternalEntryPointIterator();
                while(entries.hasNext() && exports.size()<2000) exports.add(entries.next().toString());
                result.add("entry_points", exports);
                JsonArray imports = new JsonArray();var symbols=currentProgram.getSymbolTable().getExternalSymbols();
                while(symbols.hasNext() && imports.size()<2000){var symbol=symbols.next();JsonObject v=new JsonObject();v.addProperty("name",symbol.getName(true));v.addProperty("address",symbol.getAddress().toString());imports.add(v);}
                result.add("imports",imports);
            } else if (action.equals("context_callgraph")) {
                var functions=currentProgram.getFunctionManager().getFunctions(true);
                while(functions.hasNext()) {
                    monitor.checkCancelled(); Function f=functions.next(); if(skipped++<offset)continue;
                    if(rows.size()>=cap){more=true;break;}
                    JsonObject node=new JsonObject();node.addProperty("id",f.getEntryPoint().toString());node.addProperty("name",f.getName());
                    JsonArray calls=new JsonArray();var called=new java.util.ArrayList<Function>(f.getCalledFunctions(monitor));
                    called.sort(java.util.Comparator.comparing(Function::getEntryPoint));
                    for(Function target:called) { if(calls.size()>=2000)break;calls.add(target.getEntryPoint().toString()); }
                    node.add("callees",calls);node.addProperty("calls_truncated",called.size()>2000);
                    node.addProperty("external",f.isExternal());node.addProperty("thunk",f.isThunk());rows.add(node);
                }
                result.addProperty("total_functions",currentProgram.getFunctionManager().getFunctionCount());
            } else if (action.equals("context_function")) {
                Function f=getFunctionAt(toAddr(req.get("address").getAsString()));
                if(f==null)throw new IllegalArgumentException("No exact function");
                result.addProperty("signature",f.getSignature().toString());
                result.addProperty("calling_convention",f.getCallingConventionName());
                JsonArray callers=new JsonArray(), callees=new JsonArray(), variables=new JsonArray();
                for(Function other:f.getCallingFunctions(monitor))if(callers.size()<2000)callers.add(other.getEntryPoint().toString());
                for(Function other:f.getCalledFunctions(monitor))if(callees.size()<2000)callees.add(other.getEntryPoint().toString());
                for(Variable variable:f.getAllVariables()){JsonObject v=new JsonObject();v.addProperty("name",variable.getName());v.addProperty("type",variable.getDataType().getPathName());v.addProperty("storage",variable.getVariableStorage().toString());variables.add(v);}
                result.add("callers",callers);result.add("callees",callees);result.add("variables",variables);
            } else if (action.equals("context_references")) {
                var address=toAddr(req.get("address").getAsString());
                var refs=currentProgram.getReferenceManager().getReferencesTo(address);
                while(refs.hasNext()){Reference ref=refs.next();if(skipped++<offset)continue;if(rows.size()>=cap){more=true;break;}JsonObject v=new JsonObject();v.addProperty("from",ref.getFromAddress().toString());v.addProperty("to",ref.getToAddress().toString());v.addProperty("type",ref.getReferenceType().toString());rows.add(v);}
                JsonArray outgoing=new JsonArray();for(Reference ref:currentProgram.getReferenceManager().getReferencesFrom(address)){JsonObject v=new JsonObject();v.addProperty("to",ref.getToAddress().toString());v.addProperty("type",ref.getReferenceType().toString());outgoing.add(v);}result.add("outgoing",outgoing);
            } else if (action.equals("context_strings")) {
                var data=currentProgram.getListing().getDefinedData(true);
                while(data.hasNext() && !monitor.isCancelled()){Data d=data.next();Object value=d.getValue();if(!(value instanceof String))continue;if(skipped++<offset)continue;if(rows.size()>=cap){more=true;break;}JsonObject v=new JsonObject();v.addProperty("address",d.getAddress().toString());v.addProperty("value",value.toString());v.addProperty("length",d.getLength());rows.add(v);}
            } else if (action.equals("context_types")) {
                var types=currentProgram.getDataTypeManager().getAllDataTypes();
                while(types.hasNext() && !monitor.isCancelled()){DataType dt=types.next();if(skipped++<offset)continue;if(rows.size()>=cap){more=true;break;}JsonObject v=new JsonObject();v.addProperty("path",dt.getPathName());v.addProperty("length",dt.getLength());
                    if(dt instanceof Composite){JsonArray components=new JsonArray();for(DataTypeComponent component:((Composite)dt).getComponents()){JsonObject field=new JsonObject();field.addProperty("name",component.getFieldName());field.addProperty("offset",component.getOffset());field.addProperty("length",component.getLength());field.addProperty("type",component.getDataType().getPathName());components.add(field);}v.add("fields",components);}rows.add(v);}
            } else if (action.equals("context_bytes")) {
                int count=req.has("length")?req.get("length").getAsInt():256;if(count<1||count>16384)throw new IllegalArgumentException("Read 1–16384 bytes");
                byte[] bytes=new byte[count];int read=currentProgram.getMemory().getBytes(toAddr(req.get("address").getAsString()),bytes);
                StringBuilder hex=new StringBuilder();for(int i=0;i<read;i++)hex.append(String.format("%02x",bytes[i]&255));result.addProperty("hex",hex.toString());result.addProperty("length",read);
            } else throw new IllegalArgumentException("Unknown context view");
            monitor.checkCancelled();
            result.add("items",rows);result.addProperty("offset",offset);result.addProperty("has_more",more);result.addProperty("next_offset",offset+rows.size());
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
