import com.android.tools.smali.dexlib2.AccessFlags;
import com.android.tools.smali.dexlib2.DexFileFactory;
import com.android.tools.smali.dexlib2.Opcode;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.builder.BuilderInstruction;
import com.android.tools.smali.dexlib2.builder.Label;
import com.android.tools.smali.dexlib2.builder.MutableMethodImplementation;
import com.android.tools.smali.dexlib2.builder.instruction.*;
import com.android.tools.smali.dexlib2.iface.*;
import com.android.tools.smali.dexlib2.iface.instruction.*;
import com.android.tools.smali.dexlib2.iface.instruction.formats.Instruction35c;
import com.android.tools.smali.dexlib2.iface.reference.*;
import com.android.tools.smali.dexlib2.immutable.*;
import com.android.tools.smali.dexlib2.immutable.instruction.*;
import com.android.tools.smali.dexlib2.immutable.reference.ImmutableFieldReference;
import com.android.tools.smali.dexlib2.immutable.reference.ImmutableMethodReference;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;

/** Incremental updater for the released b25 DEX; never replays b21 edits. */
public final class UpdateFovDex {
    static final Opcodes OPS = Opcodes.forApi(21);
    static final String FOV = "Lcom/klab/lovelive/allstars/fovmod/FovMod;";
    static final String MV = "Lcom/klab/lovelive/allstars/fovmod/AndroidMVExport;";
    static final String ENCODER = "Lcom/klab/lovelive/allstars/fovmod/AndroidMVEncoder;";
    static final String CONTRACT = "Lcom/klab/lovelive/allstars/fovmod/MVExportContract;";
    static final String GAPLESS = "Lcom/klab/lovelive/allstars/fovmod/MP4Gapless;";
    static final String EXPORT_SERVICE = "Lcom/klab/lovelive/allstars/fovmod/MVExportService;";
    static final String SETTINGS = "Lcom/klab/lovelive/allstars/fovmod/FovSettingsActivity;";
    static final String MOTION = "Landroid/view/MotionEvent;";
    static final String INTENT = "Landroid/content/Intent;";
    static final String ACTIVITY = "Landroid/app/Activity;";
    static final String CONFIG = "Landroid/content/res/Configuration;";
    static final String ACTIVITY_RESULT = "onActivityResult(IILandroid/content/Intent;)V";
    static final String CONFIGURATION_CHANGED = "onConfigurationChanged("+CONFIG+")V";
    static final String UNITY_ACTIVITY = "Lcom/unity3d/player/UnityPlayerActivity;";
    static final String UNITY_PLAYER = "Lcom/unity3d/player/UnityPlayer;";
    static final String UNITY_RESUME_STATE = "Lcom/unity3d/player/n;";
    static boolean replacement(String type) {
        for (String root : Arrays.asList(FOV, MV, ENCODER, CONTRACT, GAPLESS, EXPORT_SERVICE))
            if (type.equals(root) || type.startsWith(root.substring(0, root.length()-1) + "$")) return true;
        return false;
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
    static ClassDef gameActivity(ClassDef original, boolean windowing) {
        ArrayList<Method> methods = new ArrayList<>();
        int orientation = 0;
        for (Method method : original.getMethods()) {
            require(!signature(method).equals("dispatchTouchEvent(" + MOTION + ")Z"), "Game already has touch override; review new baseline");
            // Exact released GL/JP b25 classes have no result override. Keep the
            // inherited Firebase/Unity result chain and reject a changed input.
            require(!signature(method).equals(ACTIVITY_RESULT), "Game already has result override; review new baseline");
            require(!windowing || !signature(method).equals(CONFIGURATION_CHANGED),
                "GL game already owns configuration callbacks; review new baseline");
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
        methods.add(activityResult(original));
        if (windowing) methods.add(activityConfiguration(original));
        return withMethods(original, methods);
    }
    static Method activityConfiguration(ClassDef original) {
        MethodReference parent = new ImmutableMethodReference(original.getSuperclass(), "onConfigurationChanged",
            Collections.singletonList(CONFIG), "V");
        MethodReference helper = new ImmutableMethodReference(FOV, "handleGameConfiguration",
            Collections.singletonList(ACTIVITY), "V");
        List<Instruction> code = Arrays.<Instruction>asList(
            new ImmutableInstruction35c(Opcode.INVOKE_SUPER, 2, 0, 1, 0, 0, 0, parent),
            new ImmutableInstruction35c(Opcode.INVOKE_STATIC, 1, 0, 0, 0, 0, 0, helper),
            new ImmutableInstruction10x(Opcode.RETURN_VOID));
        return new ImmutableMethod(original.getType(), "onConfigurationChanged",
            Collections.singletonList(new ImmutableMethodParameter(CONFIG, Collections.emptySet(), "configuration")),
            "V", AccessFlags.PUBLIC.getValue(), Collections.emptySet(), Collections.emptySet(),
            new ImmutableMethodImplementation(2, code, Collections.emptyList(), Collections.emptyList()));
    }
    static Method activityResult(ClassDef original) {
        MethodReference helper = new ImmutableMethodReference(MV, "handleActivityResult",
            Arrays.asList("Landroid/app/Activity;", "I", "I", INTENT), "Z");
        MethodReference parent = new ImmutableMethodReference(original.getSuperclass(), "onActivityResult",
            Arrays.asList("I", "I", INTENT), "V");
        // v1=this, v2=request, v3=result, v4=data. Every unrelated request takes
        // exactly the original inherited result path through the immediate base.
        List<Instruction> code = Arrays.<Instruction>asList(
            new ImmutableInstruction35c(Opcode.INVOKE_STATIC, 4, 1, 2, 3, 4, 0, helper),
            new ImmutableInstruction11x(Opcode.MOVE_RESULT, 0),
            new ImmutableInstruction21t(Opcode.IF_EQZ, 0, 3),
            new ImmutableInstruction10x(Opcode.RETURN_VOID),
            new ImmutableInstruction35c(Opcode.INVOKE_SUPER, 4, 1, 2, 3, 4, 0, parent),
            new ImmutableInstruction10x(Opcode.RETURN_VOID));
        return new ImmutableMethod(original.getType(), "onActivityResult",
            Arrays.asList(new ImmutableMethodParameter("I", Collections.emptySet(), "requestCode"),
                new ImmutableMethodParameter("I", Collections.emptySet(), "resultCode"),
                new ImmutableMethodParameter(INTENT, Collections.emptySet(), "data")),
            "V", AccessFlags.PROTECTED.getValue(), Collections.emptySet(), Collections.emptySet(),
            new ImmutableMethodImplementation(5, code, Collections.emptyList(), Collections.emptyList()));
    }
    static boolean callRegisters(Instruction instruction, Opcode opcode, String owner, String method, int register) {
        if (instruction.getOpcode() != opcode || !call(instruction, owner, method)) return false;
        Instruction35c call = (Instruction35c)instruction;
        return call.getRegisterCount() == 1 && call.getRegisterC() == register;
    }
    static boolean fieldRegisters(Instruction instruction, Opcode opcode, String owner, String name, String type) {
        if (instruction.getOpcode() != opcode || !(instruction instanceof ReferenceInstruction)
            || ((OneRegisterInstruction)instruction).getRegisterA() != 0) return false;
        if (instruction instanceof TwoRegisterInstruction && ((TwoRegisterInstruction)instruction).getRegisterB() != 1) return false;
        return new ImmutableFieldReference(owner, name, type).equals(((ReferenceInstruction)instruction).getReference());
    }
    static Method unityVisibilityMethod(Method original, String playerMethod, String hook, String additionalPlayerMethod) {
        MutableMethodImplementation body = new MutableMethodImplementation(original.getImplementation());
        List<? extends Instruction> code = body.getInstructions();
        require(body.getRegisterCount() == 2 && body.getTryBlocks().isEmpty() && code.size() == 4
            && callRegisters(code.get(0), Opcode.INVOKE_SUPER, ACTIVITY, signature(original), 1)
            && fieldRegisters(code.get(1), Opcode.IGET_OBJECT, UNITY_ACTIVITY, "mUnityPlayer", UNITY_PLAYER)
            && callRegisters(code.get(2), Opcode.INVOKE_VIRTUAL, UNITY_PLAYER, playerMethod+"()V", 0)
            && code.get(3).getOpcode() == Opcode.RETURN_VOID, "Pinned Unity Activity lifecycle differs: "+original.getName());
        Label finished = body.newLabelForIndex(3);
        int at = additionalPlayerMethod == null ? 1 : 3;
        MethodReference helper = new ImmutableMethodReference(FOV, hook, Collections.singletonList(ACTIVITY), "Z");
        body.addInstruction(at++, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 1, 1, 0, 0, 0, 0, helper));
        body.addInstruction(at++, new BuilderInstruction11x(Opcode.MOVE_RESULT, 0));
        body.addInstruction(at++, new BuilderInstruction21t(Opcode.IF_EQZ, 0, finished));
        if (additionalPlayerMethod != null) {
            FieldReference player = new ImmutableFieldReference(UNITY_ACTIVITY, "mUnityPlayer", UNITY_PLAYER);
            MethodReference callback = new ImmutableMethodReference(UNITY_PLAYER, additionalPlayerMethod, Collections.emptyList(), "V");
            body.addInstruction(at++, new BuilderInstruction22c(Opcode.IGET_OBJECT, 0, 1, player));
            body.addInstruction(at, new BuilderInstruction35c(Opcode.INVOKE_VIRTUAL, 1, 0, 0, 0, 0, 0, callback));
        }
        return changed(original, body);
    }
    static ClassDef unityActivity(ClassDef original) {
        require(ACTIVITY.equals(original.getSuperclass()), "Pinned Unity Activity superclass changed");
        ArrayList<Method> methods = new ArrayList<>();
        int changes = 0;
        for (Method method : original.getMethods()) {
            switch (signature(method)) {
                case "onPause()V": method = unityVisibilityMethod(method,"pause","pauseUnityOnActivityPause",null); changes++; break;
                case "onResume()V": method = unityVisibilityMethod(method,"resume","resumeUnityOnActivityResume",null); changes++; break;
                case "onStart()V": method = unityVisibilityMethod(method,"start","resumeUnityOnActivityStart","resume"); changes++; break;
                case "onStop()V": method = unityVisibilityMethod(method,"stop","pauseUnityOnActivityStop","pause"); changes++; break;
                default: break;
            }
            methods.add(method);
        }
        require(changes == 4, "Pinned Unity lifecycle methods absent");
        return withMethods(original, methods);
    }
    static Method unityResumeFocus(Method original) {
        MutableMethodImplementation body = new MutableMethodImplementation(original.getImplementation());
        List<BuilderInstruction> code = body.getInstructions();
        require(body.getRegisterCount() == 2 && body.getTryBlocks().isEmpty() && code.size() == 12
            && fieldRegisters(code.get(0), Opcode.SGET_BOOLEAN, UNITY_RESUME_STATE, "a", "Z")
            && fieldRegisters(code.get(2), Opcode.IGET_BOOLEAN, UNITY_RESUME_STATE, "b", "Z")
            && fieldRegisters(code.get(4), Opcode.IGET_BOOLEAN, UNITY_RESUME_STATE, "d", "Z")
            && fieldRegisters(code.get(6), Opcode.IGET_BOOLEAN, UNITY_RESUME_STATE, "c", "Z")
            && code.get(8).getOpcode() == Opcode.CONST_4 && ((NarrowLiteralInstruction)code.get(8)).getNarrowLiteral() == 1
            && code.get(9).getOpcode() == Opcode.RETURN && ((OneRegisterInstruction)code.get(9)).getRegisterA() == 0
            && code.get(10).getOpcode() == Opcode.CONST_4 && ((NarrowLiteralInstruction)code.get(10)).getNarrowLiteral() == 0
            && code.get(11).getOpcode() == Opcode.RETURN && ((OneRegisterInstruction)code.get(11)).getRegisterA() == 0,
            "Pinned Unity native-resume state differs");
        for (int index : new int[]{1,3,5,7}) {
            Opcode expected = index <= 3 ? Opcode.IF_EQZ : Opcode.IF_NEZ;
            require(code.get(index).getOpcode() == expected && ((OneRegisterInstruction)code.get(index)).getRegisterA() == 0
                && ((BuilderInstruction21t)code.get(index)).getTarget().getLocation().getIndex() == 10,
                "Pinned Unity native-resume rejection branch differs");
        }
        Label focused = body.newLabelForIndex(4);
        Label rejected = ((BuilderInstruction21t)code.get(3)).getTarget();
        FieldReference current = new ImmutableFieldReference(UNITY_PLAYER, "currentActivity", ACTIVITY);
        MethodReference helper = new ImmutableMethodReference(FOV, "canResumeVisibleUnityWithoutFocus", Collections.singletonList(ACTIVITY), "Z");
        body.replaceInstruction(3, new BuilderInstruction21t(Opcode.IF_NEZ, 0, focused));
        body.addInstruction(4, new BuilderInstruction21c(Opcode.SGET_OBJECT, 0, current));
        body.addInstruction(5, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 1, 0, 0, 0, 0, 0, helper));
        body.addInstruction(6, new BuilderInstruction11x(Opcode.MOVE_RESULT, 0));
        body.addInstruction(7, new BuilderInstruction21t(Opcode.IF_EQZ, 0, rejected));
        return changed(original, body);
    }
    static ClassDef unityResumeState(ClassDef original) {
        ArrayList<Method> methods = new ArrayList<>();
        int changes = 0;
        for (Method method : original.getMethods()) {
            if (signature(method).equals("f()Z")) { method = unityResumeFocus(method); changes++; }
            methods.add(method);
        }
        require(changes == 1, "Pinned Unity native-resume state absent");
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
        MethodReference exportButton = new ImmutableMethodReference(MV, "installSettingsButton",
            Arrays.asList("Landroid/app/Activity;", "Landroid/widget/LinearLayout;"), "V");
        body.replaceInstruction(at, new BuilderInstruction3rc(Opcode.INVOKE_STATIC_RANGE, self, 1, title));
        body.addInstruction(at+1, new BuilderInstruction11x(Opcode.MOVE_RESULT_OBJECT, dst));
        int start = at+5; // After the existing title TextView was added.
        body.addInstruction(start++, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 2, self, 2, 0, 0, 0, exportButton));
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
    static ClassDef omitAllowedMethods(ClassDef original, String activity, boolean windowing) {
        String type = original.getType();
        Set<String> allowed;
        if (type.equals(activity)) {
            allowed = new HashSet<>(Arrays.asList("dispatchTouchEvent("+MOTION+")Z", ACTIVITY_RESULT));
            if (windowing) allowed.add(CONFIGURATION_CHANGED);
        } else if (type.equals(SETTINGS)) {
            allowed = new HashSet<>(Arrays.asList("onCreate(Landroid/os/Bundle;)V", "saveAndLaunch()V"));
        } else if (windowing && type.equals(UNITY_ACTIVITY)) {
            allowed = new HashSet<>(Arrays.asList("onPause()V", "onResume()V", "onStart()V", "onStop()V"));
        } else if (windowing && type.equals(UNITY_RESUME_STATE)) {
            allowed = Collections.singleton("f()Z");
        } else allowed = Collections.emptySet();
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
    static byte[] preservedDigest(Map<String,ClassDef> classes, String activity, boolean windowing, File directory) throws Exception {
        ArrayList<ClassDef> preserved = new ArrayList<>();
        for (ClassDef cls : classes.values()) if (!replacement(cls.getType())) preserved.add(omitAllowedMethods(cls, activity, windowing));
        File temp = File.createTempFile("preserved-dex-", ".dex", directory);
        try {
            DexFileFactory.writeDexFile(temp.toString(), new ImmutableDexFile(OPS, preserved));
            return digest(temp);
        } finally { require(temp.delete(), "Owned preservation temporary file could not be removed"); }
    }
    static boolean hasInstanceField(ClassDef owner, String name, String type) {
        for (Field field : owner.getInstanceFields())
            if (name.equals(field.getName()) && type.equals(field.getType())) return true;
        return false;
    }
    static void verifyGlBackgroundDisplay(Map<String,ClassDef> classes, String activity) {
        Set<String> ancestors = new HashSet<>();
        String type = activity;
        while (!UNITY_ACTIVITY.equals(type)) {
            ClassDef current = classes.get(type);
            require(current != null && ancestors.add(type), "GL Activity must inherit the patched Unity Activity");
            type = current.getSuperclass();
        }
        ClassDef host = classes.get(UNITY_ACTIVITY), player = classes.get(UNITY_PLAYER);
        require(host != null && hasInstanceField(host, "mUnityPlayer", UNITY_PLAYER),
            "Active GL Unity Activity must own the Unity player field");
        require(player != null && hasInstanceField(player, "r", "Landroid/view/SurfaceView;"),
            "Unity player primary SurfaceView contract differs");
        Set<String> methods = new HashSet<>();
        for (Method method : player.getVirtualMethods())
            if (AccessFlags.PUBLIC.isSet(method.getAccessFlags())) methods.add(signature(method));
        require(methods.contains("displayChanged(ILandroid/view/Surface;)Z") && methods.contains("pause()V"),
            "Unity player surface handoff methods differ");

        ClassDef carrier = classes.get(FOV.substring(0, FOV.length()-1) + "$BackgroundDisplay;");
        require(carrier != null, "GL offscreen display carrier absent");
        Set<String> reflected = new HashSet<>();
        for (Method method : carrier.getDirectMethods()) {
            if (!"<init>".equals(method.getName()) || method.getImplementation() == null) continue;
            for (Instruction instruction : method.getImplementation().getInstructions()) {
                if (!(instruction instanceof ReferenceInstruction)) continue;
                Reference ref = ((ReferenceInstruction)instruction).getReference();
                if (ref instanceof StringReference) reflected.add(((StringReference)ref).getString());
            }
        }
        String hostName = UNITY_ACTIVITY.substring(1, UNITY_ACTIVITY.length()-1).replace('/', '.');
        require(reflected.contains(hostName) && reflected.contains("mUnityPlayer") && reflected.contains("r"),
            "GL background carrier must reflect the field on the installed Activity's actual Unity ancestor");
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 5, "Usage: UpdateFovDex B25.dex REPLACEMENT.dex OUTPUT.dex GL|JP VERIFY_TMP_DIR");
        require(!new File(args[2]).exists(), "Fresh output DEX required");
        boolean windowing = args[3].equals("GL");
        String activity = windowing ? "Lcom/klab/lovelive/allstars/global/GlobalUnsafeMainActivity;"
            : args[3].equals("JP") ? "Lcom/klab/lovelive/allstars/MainActivity;" : null;
        require(activity != null, "Region must be GL or JP");
        File temporary = new File(args[4]); require(temporary.isDirectory(), "Owned verification temporary directory required");
        DexFile input = DexFileFactory.loadDexFile(new File(args[0]), OPS), bridge = DexFileFactory.loadDexFile(new File(args[1]), OPS);
        TreeMap<String,ClassDef> original = new TreeMap<>(), classes = new TreeMap<>();
        int removed = 0, inserted = 0, activityChanges = 0, settingsChanges = 0, unityChanges = 0;
        for (ClassDef cls : input.getClasses()) {
            require(original.put(cls.getType(), cls) == null, "Duplicate original class");
            if (replacement(cls.getType())) { removed++; continue; }
            if (cls.getType().equals(activity)) { cls = gameActivity(cls, windowing); activityChanges++; }
            else if (cls.getType().equals(SETTINGS)) { cls = settings(cls); settingsChanges++; }
            else if (windowing && cls.getType().equals(UNITY_ACTIVITY)) { cls = unityActivity(cls); unityChanges++; }
            else if (windowing && cls.getType().equals(UNITY_RESUME_STATE)) { cls = unityResumeState(cls); unityChanges++; }
            classes.put(cls.getType(), cls);
        }
        require(activityChanges == 1 && settingsChanges == 1 && removed >= 1, "Exact original game/settings/bridge classes absent");
        require(!windowing || unityChanges == 2, "Exact GL Unity window lifecycle classes absent");
        for (ClassDef cls : bridge.getClasses()) {
            require(replacement(cls.getType()), "Unexpected replacement class: " + cls.getType());
            require(classes.put(cls.getType(), cls) == null, "Duplicate replacement class"); inserted++;
        }
        require(classes.keySet().containsAll(Arrays.asList(FOV, MV, ENCODER, CONTRACT, GAPLESS, EXPORT_SERVICE)),
            "Required FOV and MV export classes absent");
        Set<String> bridgeMethods = new HashSet<>();
        for (Method method : classes.get(FOV).getMethods()) bridgeMethods.add(signature(method));
        require(bridgeMethods.contains("nativeConfigure(FFILjava/lang/String;)I"), "Original JNI entry contract lost");
        require(bridgeMethods.contains("resolveOrientation(Landroid/app/Activity;I)I"), "Original orientation resolver lost");
        Set<String> exportMethods = new HashSet<>();
        for (Method method : classes.get(MV).getMethods()) exportMethods.add(signature(method));
        require(exportMethods.contains("installSettingsButton(Landroid/app/Activity;Landroid/widget/LinearLayout;)V"), "MV settings button contract absent");
        require(exportMethods.contains("onGameResumed(Landroid/app/Activity;)V"), "MV lifecycle contract absent");
        require(exportMethods.contains("handleActivityResult(Landroid/app/Activity;IILandroid/content/Intent;)Z"), "MV document result contract absent");
        require(exportMethods.contains("nativeQueueSelection(Ljava/lang/Object;)I")
            && exportMethods.contains("nativeQueueOpen(Ljava/lang/String;Ljava/lang/Object;)I"), "MV queue JNI contract absent");
        for (ClassDef cls : classes.values()) for (Method method : cls.getMethods()) {
            if (method.getImplementation() == null) continue;
            for (Instruction instruction : method.getImplementation().getInstructions()) if (instruction instanceof ReferenceInstruction) {
                Reference ref = ((ReferenceInstruction)instruction).getReference();
                if (ref instanceof MethodReference && ((MethodReference)ref).getDefiningClass().equals(FOV))
                    require(bridgeMethods.contains(signature((MethodReference)ref)), "Unresolved FovMod call: " + signature((MethodReference)ref));
                if (ref instanceof MethodReference && ((MethodReference)ref).getDefiningClass().equals(MV))
                    require(exportMethods.contains(signature((MethodReference)ref)), "Unresolved MV export call: " + signature((MethodReference)ref));
            }
        }
        DexFileFactory.writeDexFile(args[2], new ImmutableDexFile(OPS, classes.values()));
        DexFile output = DexFileFactory.loadDexFile(new File(args[2]), OPS);
        TreeMap<String,ClassDef> emitted = new TreeMap<>();
        for (ClassDef cls : output.getClasses()) emitted.put(cls.getType(), cls);
        require(emitted.size() == original.size()-removed+inserted, "DEX class count changed unexpectedly");
        if (windowing) verifyGlBackgroundDisplay(emitted, activity);
        require(Arrays.equals(preservedDigest(original, activity, windowing, temporary), preservedDigest(emitted, activity, windowing, temporary)),
            "Unrelated classes, orientation, fields, settings methods or original save branch changed");
        System.out.println("{\"status\":\"PASS_INCREMENTAL_B25_DEX_UPDATE\",\"region\":\""+args[3]+"\",\"original_classes\":"+original.size()+",\"output_classes\":"+emitted.size()+",\"removed_fov_classes\":"+removed+",\"inserted_fov_classes\":"+inserted+",\"added_touch_overrides\":1,\"added_document_result_overrides\":1,\"added_game_configuration_overrides\":"+(windowing?1:0)+",\"changed_unity_visibility_methods\":"+(windowing?5:0)+",\"mv_settings_buttons\":1,\"settings_title_and_help_methods\":1,\"in_game_save_return\":1,\"all_unrelated_class_bytes_preserved_canonically\":true}");
    }
}
