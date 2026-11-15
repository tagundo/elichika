import com.android.tools.smali.dexlib2.AccessFlags;
import com.android.tools.smali.dexlib2.DexFileFactory;
import com.android.tools.smali.dexlib2.Opcode;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.builder.Label;
import com.android.tools.smali.dexlib2.builder.MutableMethodImplementation;
import com.android.tools.smali.dexlib2.builder.instruction.*;
import com.android.tools.smali.dexlib2.iface.*;
import com.android.tools.smali.dexlib2.iface.instruction.*;
import com.android.tools.smali.dexlib2.iface.instruction.formats.Instruction35c;
import com.android.tools.smali.dexlib2.iface.reference.*;
import com.android.tools.smali.dexlib2.immutable.*;
import com.android.tools.smali.dexlib2.immutable.instruction.*;
import com.android.tools.smali.dexlib2.immutable.reference.ImmutableMethodReference;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;

/** Incremental updater for the released b25 DEX; never replays b21 edits. */
public final class UpdateFovDex {
    static final Opcodes OPS = Opcodes.forApi(21);
    static final String FOV = "Lcom/klab/lovelive/allstars/fovmod/FovMod;";
    static final String SETTINGS = "Lcom/klab/lovelive/allstars/fovmod/FovSettingsActivity;";
    static final String MOTION = "Landroid/view/MotionEvent;";
    static boolean replacement(String type) {
        return type.equals(FOV) || type.startsWith(FOV.substring(0, FOV.length()-1) + "$");
    }
    static void require(boolean okay, String message) {
        if (!okay) throw new IllegalStateException(message);
    }
    static String signature(MethodReference method) {
        StringBuilder out = new StringBuilder(method.getName()).append('(');
        for (CharSequence p : method.getParameterTypes()) out.append(p);
        return out.append(')').append(method.getReturnType()).toString();
    }
    static boolean call(Instruction instruction, String owner, String sig) {
        if (!(instruction instanceof ReferenceInstruction)) return false;
        Reference ref = ((ReferenceInstruction)instruction).getReference();
        return ref instanceof MethodReference && ((MethodReference)ref).getDefiningClass().equals(owner)
            && signature((MethodReference)ref).equals(sig);
    }
    static Method changed(Method original, MutableMethodImplementation body) {
        return new ImmutableMethod(original.getDefiningClass(), original.getName(), original.getParameters(),
            original.getReturnType(), original.getAccessFlags(), original.getAnnotations(),
            original.getHiddenApiRestrictions(), body);
    }
    static ClassDef withMethods(ClassDef original, Collection<? extends Method> methods) {
        return new ImmutableClassDef(original.getType(), original.getAccessFlags(), original.getSuperclass(),
            original.getInterfaces(), original.getSourceFile(), original.getAnnotations(), original.getFields(), methods);
    }
    static ClassDef gameActivity(ClassDef original) {
        ArrayList<Method> methods = new ArrayList<>();
        int orientation = 0;
        for (Method method : original.getMethods()) {
            require(!signature(method).equals("dispatchTouchEvent(" + MOTION + ")Z"), "Game already has touch override; review new baseline");
            if (signature(method).equals("setRequestedOrientation(I)V")) orientation++;
            methods.add(method);
        }
        require(orientation == 1, "Released b25 orientation override must be retained");
        MethodReference helper = new ImmutableMethodReference(FOV, "handleGameTouch",
            Arrays.asList("Landroid/app/Activity;", MOTION), "Z");
        MethodReference parent = new ImmutableMethodReference(original.getSuperclass(), "dispatchTouchEvent",
            Collections.singletonList(MOTION), "Z");
        // Four registers: v2=this, v3=event; ordinary events use the immediate
        // Firebase superclass, preserving the original game dispatch chain.
        List<Instruction> code = Arrays.<Instruction>asList(
            new ImmutableInstruction35c(Opcode.INVOKE_STATIC, 2, 2, 3, 0, 0, 0, helper),
            new ImmutableInstruction11x(Opcode.MOVE_RESULT, 0),
            new ImmutableInstruction21t(Opcode.IF_EQZ, 0, 4),
            new ImmutableInstruction11n(Opcode.CONST_4, 0, 1),
            new ImmutableInstruction11x(Opcode.RETURN, 0),
            new ImmutableInstruction35c(Opcode.INVOKE_SUPER, 2, 2, 3, 0, 0, 0, parent),
            new ImmutableInstruction11x(Opcode.MOVE_RESULT, 0),
            new ImmutableInstruction11x(Opcode.RETURN, 0));
        methods.add(new ImmutableMethod(original.getType(), "dispatchTouchEvent",
            Collections.singletonList(new ImmutableMethodParameter(MOTION, Collections.emptySet(), "event")),
            "Z", AccessFlags.PUBLIC.getValue(), Collections.emptySet(), Collections.emptySet(),
            new ImmutableMethodImplementation(4, code, Collections.emptyList(), Collections.emptyList())));
        return withMethods(original, methods);
    }
    static Method settingsCreate(Method original) {
        MutableMethodImplementation body = new MutableMethodImplementation(original.getImplementation());
        int at = -1;
        for (int i = 0; i < body.getInstructions().size(); i++) {
            Instruction instruction = body.getInstructions().get(i);
            if (!(instruction instanceof ReferenceInstruction)) continue;
            Reference ref = ((ReferenceInstruction)instruction).getReference();
            if (ref instanceof StringReference && ((StringReference)ref).getString().equals("SIFAS FoV  \u00b7  build 20")) {
                require(at == -1, "Multiple legacy settings titles"); at = i;
            }
        }
        require(at >= 0 && body.getRegisterCount() == 15, "Expected exact released settings title and registers");
        require(body.getInstructions().get(at) instanceof OneRegisterInstruction, "Title destination register absent");
        int dst = ((OneRegisterInstruction)body.getInstructions().get(at)).getRegisterA();
        int self = body.getRegisterCount() - 2;
        require(dst == 1 && self == 13, "Released settings title registers changed");
        require(call(body.getInstructions().get(at+1), SETTINGS, "title(Ljava/lang/String;)Landroid/widget/TextView;"), "Title call changed");
        require(body.getInstructions().get(at+2).getOpcode() == Opcode.MOVE_RESULT_OBJECT
            && ((OneRegisterInstruction)body.getInstructions().get(at+2)).getRegisterA() == dst, "Title result changed");
        Instruction add = body.getInstructions().get(at+3);
        require(add instanceof Instruction35c && call(add, "Landroid/widget/LinearLayout;", "addView(Landroid/view/View;)V"), "Title parent layout changed");
        Instruction35c addView = (Instruction35c)add;
        require(addView.getRegisterCount() == 2 && addView.getRegisterC() == 2 && addView.getRegisterD() == dst, "Title parent layout registers changed");
        MethodReference title = new ImmutableMethodReference(FOV, "getBuildTitle", Collections.singletonList("Landroid/content/Context;"), "Ljava/lang/String;");
        MethodReference hint = new ImmutableMethodReference(FOV, "getMenuHint", Collections.singletonList("Landroid/content/Context;"), "Ljava/lang/String;");
        MethodReference note = new ImmutableMethodReference(SETTINGS, "note", Collections.singletonList("Ljava/lang/String;"), "Landroid/widget/TextView;");
        body.replaceInstruction(at, new BuilderInstruction3rc(Opcode.INVOKE_STATIC_RANGE, self, 1, title));
        body.addInstruction(at+1, new BuilderInstruction11x(Opcode.MOVE_RESULT_OBJECT, dst));
        int start = at+5; // After the existing title TextView was added.
        body.addInstruction(start++, new BuilderInstruction3rc(Opcode.INVOKE_STATIC_RANGE, self, 1, hint));
        body.addInstruction(start++, new BuilderInstruction11x(Opcode.MOVE_RESULT_OBJECT, dst));
        body.addInstruction(start++, new BuilderInstruction35c(Opcode.INVOKE_DIRECT, 2, self, dst, 0, 0, 0, note));
        body.addInstruction(start++, new BuilderInstruction11x(Opcode.MOVE_RESULT_OBJECT, dst));
        body.addInstruction(start, new BuilderInstruction35c(Opcode.INVOKE_VIRTUAL, 2, 2, dst, 0, 0, 0, addView.getReference()));
        return changed(original, body);
    }
    static Method settingsSave(Method original) {
        MutableMethodImplementation body = new MutableMethodImplementation(original.getImplementation());
        require(body.getRegisterCount() == 5, "Released settings save registers changed");
        int at = -1;
        for (int i = 0; i < body.getInstructions().size(); i++) {
            if (!call(body.getInstructions().get(i), FOV, "saveConfigAndCheck(Landroid/content/Context;IIII)Z")) continue;
            require(at < 0, "Multiple checked-save calls"); at = i;
        }
        require(at >= 0 && body.getInstructions().get(at+1).getOpcode() == Opcode.MOVE_RESULT
            && ((OneRegisterInstruction)body.getInstructions().get(at+1)).getRegisterA() == 0
            && body.getInstructions().get(at+2).getOpcode() == Opcode.IF_EQZ
            && ((OneRegisterInstruction)body.getInstructions().get(at+2)).getRegisterA() == 0,
            "Released failed-save guard must remain before in-game return");
        int last = body.getInstructions().size()-1;
        require(body.getInstructions().get(last).getOpcode() == Opcode.RETURN_VOID, "Settings save return absent");
        Label finished = body.newLabelForIndex(last);
        MethodReference close = new ImmutableMethodReference(FOV, "closeInGameSettings", Collections.singletonList("Landroid/app/Activity;"), "Z");
        body.addInstruction(at+3, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 1, 4, 0, 0, 0, 0, close));
        body.addInstruction(at+4, new BuilderInstruction11x(Opcode.MOVE_RESULT, 0));
        body.addInstruction(at+5, new BuilderInstruction21t(Opcode.IF_NEZ, 0, finished));
        return changed(original, body);
    }
    static ClassDef settings(ClassDef original) {
        ArrayList<Method> methods = new ArrayList<>();
        int create = 0, save = 0, note = 0;
        for (Method method : original.getMethods()) {
            String sig = signature(method);
            if (sig.equals("onCreate(Landroid/os/Bundle;)V")) { methods.add(settingsCreate(method)); create++; }
            else if (sig.equals("saveAndLaunch()V")) { methods.add(settingsSave(method)); save++; }
            else { methods.add(method); if (sig.equals("note(Ljava/lang/String;)Landroid/widget/TextView;")) note++; }
        }
        require(create == 1 && save == 1 && note == 1, "Expected original settings methods absent");
        return withMethods(original, methods);
    }
    static ClassDef omitAllowedMethods(ClassDef original, String activity) {
        Set<String> allowed = original.getType().equals(activity) ? Collections.singleton("dispatchTouchEvent("+MOTION+")Z")
            : original.getType().equals(SETTINGS) ? new HashSet<>(Arrays.asList("onCreate(Landroid/os/Bundle;)V", "saveAndLaunch()V")) : Collections.emptySet();
        ArrayList<Method> methods = new ArrayList<>();
        for (Method method : original.getMethods()) if (!allowed.contains(signature(method))) methods.add(method);
        return withMethods(original, methods);
    }
    static byte[] digest(File file) throws Exception {
        MessageDigest hash = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = input.read(buffer)) != -1) hash.update(buffer, 0, count);
        }
        return hash.digest();
    }
    static byte[] preservedDigest(Map<String,ClassDef> classes, String activity, File directory) throws Exception {
        ArrayList<ClassDef> preserved = new ArrayList<>();
        for (ClassDef cls : classes.values()) if (!replacement(cls.getType())) preserved.add(omitAllowedMethods(cls, activity));
        File temp = File.createTempFile("preserved-dex-", ".dex", directory);
        try {
            DexFileFactory.writeDexFile(temp.toString(), new ImmutableDexFile(OPS, preserved));
            return digest(temp);
        } finally { require(temp.delete(), "Owned preservation temporary file could not be removed"); }
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 5, "Usage: UpdateFovDex B25.dex REPLACEMENT.dex OUTPUT.dex GL|JP VERIFY_TMP_DIR");
        require(!new File(args[2]).exists(), "Fresh output DEX required");
        String activity = args[3].equals("GL") ? "Lcom/klab/lovelive/allstars/global/GlobalUnsafeMainActivity;"
            : args[3].equals("JP") ? "Lcom/klab/lovelive/allstars/MainActivity;" : null;
        require(activity != null, "Region must be GL or JP");
        File temporary = new File(args[4]); require(temporary.isDirectory(), "Owned verification temporary directory required");
        DexFile input = DexFileFactory.loadDexFile(new File(args[0]), OPS), bridge = DexFileFactory.loadDexFile(new File(args[1]), OPS);
        TreeMap<String,ClassDef> original = new TreeMap<>(), classes = new TreeMap<>();
        int removed = 0, inserted = 0, activityChanges = 0, settingsChanges = 0;
        for (ClassDef cls : input.getClasses()) {
            require(original.put(cls.getType(), cls) == null, "Duplicate original class");
            if (replacement(cls.getType())) { removed++; continue; }
            if (cls.getType().equals(activity)) { cls = gameActivity(cls); activityChanges++; }
            else if (cls.getType().equals(SETTINGS)) { cls = settings(cls); settingsChanges++; }
            classes.put(cls.getType(), cls);
        }
        require(activityChanges == 1 && settingsChanges == 1 && removed >= 1, "Exact original game/settings/bridge classes absent");
        for (ClassDef cls : bridge.getClasses()) {
            require(replacement(cls.getType()), "Unexpected replacement class: " + cls.getType());
            require(classes.put(cls.getType(), cls) == null, "Duplicate replacement class"); inserted++;
        }
        require(classes.containsKey(FOV), "Replacement FovMod absent");
        Set<String> bridgeMethods = new HashSet<>();
        for (Method method : classes.get(FOV).getMethods()) bridgeMethods.add(signature(method));
        require(bridgeMethods.contains("nativeConfigure(FFILjava/lang/String;)I"), "Original JNI entry contract lost");
        require(bridgeMethods.contains("resolveOrientation(Landroid/app/Activity;I)I"), "Original orientation resolver lost");
        for (ClassDef cls : classes.values()) for (Method method : cls.getMethods()) {
            if (method.getImplementation() == null) continue;
            for (Instruction instruction : method.getImplementation().getInstructions()) if (instruction instanceof ReferenceInstruction) {
                Reference ref = ((ReferenceInstruction)instruction).getReference();
                if (ref instanceof MethodReference && ((MethodReference)ref).getDefiningClass().equals(FOV))
                    require(bridgeMethods.contains(signature((MethodReference)ref)), "Unresolved FovMod call: " + signature((MethodReference)ref));
            }
        }
        DexFileFactory.writeDexFile(args[2], new ImmutableDexFile(OPS, classes.values()));
        DexFile output = DexFileFactory.loadDexFile(new File(args[2]), OPS);
        TreeMap<String,ClassDef> emitted = new TreeMap<>();
        for (ClassDef cls : output.getClasses()) emitted.put(cls.getType(), cls);
        require(emitted.size() == original.size()-removed+inserted, "DEX class count changed unexpectedly");
        require(Arrays.equals(preservedDigest(original, activity, temporary), preservedDigest(emitted, activity, temporary)),
            "Unrelated classes, orientation, fields, settings methods or original save branch changed");
        System.out.println("{\"status\":\"PASS_INCREMENTAL_B25_DEX_UPDATE\",\"region\":\""+args[3]+"\",\"original_classes\":"+original.size()+",\"output_classes\":"+emitted.size()+",\"removed_fov_classes\":"+removed+",\"inserted_fov_classes\":"+inserted+",\"added_touch_overrides\":1,\"settings_title_and_help_methods\":1,\"in_game_save_return\":1,\"all_unrelated_class_bytes_preserved_canonically\":true}");
    }
}
