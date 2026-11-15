import com.android.tools.smali.dexlib2.*;
import com.android.tools.smali.dexlib2.iface.*;
import com.android.tools.smali.dexlib2.iface.instruction.*;
import com.android.tools.smali.dexlib2.iface.instruction.formats.*;
import com.android.tools.smali.dexlib2.iface.reference.MethodReference;
import com.android.tools.smali.dexlib2.immutable.*;
import com.android.tools.smali.dexlib2.immutable.instruction.*;
import com.android.tools.smali.dexlib2.immutable.reference.*;
import java.util.*;

/** Synthetic method fixtures only; never reads or builds a game DEX/APK. */
public final class UpdateFovDexTest {
    static int checks;
    static void check(boolean okay, String message) { checks++; if (!okay) throw new AssertionError(message); }
    static Method method(String owner, String name, List<ImmutableMethodParameter> parameters, int registers, List<Instruction> code) {
        return new ImmutableMethod(owner, name, parameters, "V", AccessFlags.PUBLIC.getValue(), Collections.emptySet(), Collections.emptySet(),
            new ImmutableMethodImplementation(registers, code, Collections.emptyList(), Collections.emptyList()));
    }
    static ClassDef cls(String type, String parent, Method... methods) {
        return new ImmutableClassDef(type, AccessFlags.PUBLIC.getValue(), parent, Collections.emptyList(), "Synthetic.java", Collections.emptySet(), Collections.emptyList(), Arrays.asList(methods));
    }
    static List<Instruction> instructions(Method method) {
        ArrayList<Instruction> list = new ArrayList<>();
        for (Instruction i : method.getImplementation().getInstructions()) list.add(i);
        return list;
    }
    static Method save() {
        MethodReference checked = new ImmutableMethodReference(UpdateFovDex.FOV, "saveConfigAndCheck", Arrays.asList("Landroid/content/Context;", "I", "I", "I", "I"), "Z");
        MethodReference restart = new ImmutableMethodReference("Ltest/Restart;", "restart", Collections.emptyList(), "V");
        return method(UpdateFovDex.SETTINGS, "saveAndLaunch", Collections.emptyList(), 5, Arrays.<Instruction>asList(
            new ImmutableInstruction35c(Opcode.INVOKE_STATIC, 5, 4, 0, 1, 2, 3, checked),
            new ImmutableInstruction11x(Opcode.MOVE_RESULT, 0),
            new ImmutableInstruction21t(Opcode.IF_EQZ, 0, 6),
            new ImmutableInstruction11n(Opcode.CONST_4, 0, 1),
            new ImmutableInstruction35c(Opcode.INVOKE_STATIC, 0, 0, 0, 0, 0, 0, restart),
            new ImmutableInstruction10x(Opcode.RETURN_VOID)));
    }
    static int[] simulateSave(Method method, boolean accepted, boolean inGame) {
        TreeMap<Integer,Instruction> code = new TreeMap<>(); int address = 0;
        for (Instruction i : instructions(method)) { code.put(address, i); address += i.getCodeUnits(); }
        int pc = 0, value = 0, pending = 0, close = 0, restart = 0;
        for (int step = 0; step < 30; step++) {
            Instruction i = code.get(pc); check(i != null, "Branch targets an instruction boundary");
            int next = pc+i.getCodeUnits();
            switch (i.getOpcode()) {
                case INVOKE_STATIC:
                    MethodReference call = (MethodReference)((Instruction35c)i).getReference();
                    if (call.getName().equals("saveConfigAndCheck")) pending = accepted ? 1 : 0;
                    else if (call.getName().equals("closeInGameSettings")) { close++; pending = inGame ? 1 : 0; }
                    else if (call.getName().equals("restart")) restart++;
                    else throw new AssertionError("Unknown fixture call");
                    break;
                case MOVE_RESULT: value = pending; break;
                case IF_EQZ: if (value == 0) next = pc+((OffsetInstruction)i).getCodeOffset(); break;
                case IF_NEZ: if (value != 0) next = pc+((OffsetInstruction)i).getCodeOffset(); break;
                case CONST_4: value = ((NarrowLiteralInstruction)i).getNarrowLiteral(); break;
                case RETURN_VOID: return new int[]{close, restart};
                default: throw new AssertionError("Unexpected fixture opcode " + i.getOpcode());
            }
            pc = next;
        }
        throw new AssertionError("Control flow failed to return");
    }
    static Method create() {
        MethodReference title = new ImmutableMethodReference(UpdateFovDex.SETTINGS, "title", Collections.singletonList("Ljava/lang/String;"), "Landroid/widget/TextView;");
        MethodReference add = new ImmutableMethodReference("Landroid/widget/LinearLayout;", "addView", Collections.singletonList("Landroid/view/View;"), "V");
        return method(UpdateFovDex.SETTINGS, "onCreate", Collections.singletonList(new ImmutableMethodParameter("Landroid/os/Bundle;", Collections.emptySet(), "state")), 15, Arrays.<Instruction>asList(
            new ImmutableInstruction21c(Opcode.CONST_STRING, 1, new ImmutableStringReference("SIFAS FoV  \u00b7  build 20")),
            new ImmutableInstruction35c(Opcode.INVOKE_DIRECT, 2, 13, 1, 0, 0, 0, title),
            new ImmutableInstruction11x(Opcode.MOVE_RESULT_OBJECT, 1),
            new ImmutableInstruction35c(Opcode.INVOKE_VIRTUAL, 2, 2, 1, 0, 0, 0, add),
            new ImmutableInstruction10x(Opcode.RETURN_VOID)));
    }
    public static void main(String[] args) {
        Method saved = UpdateFovDex.settingsSave(save());
        check(Arrays.equals(simulateSave(saved, false, true), new int[]{0,0}), "Failed save neither closes settings nor restarts the game");
        check(Arrays.equals(simulateSave(saved, true, true), new int[]{1,0}), "In-game save returns without running the restart path");
        check(Arrays.equals(simulateSave(saved, true, false), new int[]{1,1}), "Normal launcher save preserves the original game launch path");

        Method created = UpdateFovDex.settingsCreate(create());
        check(created.getImplementation().getRegisterCount() == 15, "Settings layout uses the original register allocation");
        int title = 0, hint = 0, note = 0, adds = 0;
        for (Instruction i : instructions(created)) {
            if (UpdateFovDex.call(i, UpdateFovDex.FOV, "getBuildTitle(Landroid/content/Context;)Ljava/lang/String;")) title++;
            if (UpdateFovDex.call(i, UpdateFovDex.FOV, "getMenuHint(Landroid/content/Context;)Ljava/lang/String;")) hint++;
            if (UpdateFovDex.call(i, UpdateFovDex.SETTINGS, "note(Ljava/lang/String;)Landroid/widget/TextView;")) note++;
            if (UpdateFovDex.call(i, "Landroid/widget/LinearLayout;", "addView(Landroid/view/View;)V")) adds++;
            check(i.getOpcode() != Opcode.CONST_STRING, "Obsolete hardcoded build title was removed");
        }
        check(title == 1 && hint == 1 && note == 1 && adds == 2, "One live build title and one visible gesture hint are inserted");

        String activity = "Ltest/Game;", firebase = "Ltest/Firebase;";
        Method orientation = method(activity, "setRequestedOrientation", Collections.singletonList(new ImmutableMethodParameter("I", Collections.emptySet(), "orientation")), 2,
            Collections.<Instruction>singletonList(new ImmutableInstruction10x(Opcode.RETURN_VOID)));
        ClassDef game = UpdateFovDex.gameActivity(cls(activity, firebase, orientation));
        Method dispatch = null;
        for (Method m : game.getMethods()) {
            if (m.getName().equals("dispatchTouchEvent")) dispatch = m;
            if (m.getName().equals("setRequestedOrientation")) check(m == orientation, "Existing orientation override is copied unchanged");
        }
        check(dispatch != null && dispatch.getReturnType().equals("Z"), "Game dispatch override returns the original boolean contract");
        List<Instruction> code = instructions(dispatch);
        check(UpdateFovDex.call(code.get(0), UpdateFovDex.FOV, "handleGameTouch(Landroid/app/Activity;Landroid/view/MotionEvent;)Z"), "Gesture helper observes input first");
        check(code.get(2).getOpcode() == Opcode.IF_EQZ && ((OffsetInstruction)code.get(2)).getCodeOffset() == 4, "Ordinary event branch skips the consuming return");
        check(code.get(5).getOpcode() == Opcode.INVOKE_SUPER && UpdateFovDex.call(code.get(5), firebase, "dispatchTouchEvent(Landroid/view/MotionEvent;)Z"), "Ordinary input forwards through the immediate Firebase superclass");
        boolean rejected = false;
        try { UpdateFovDex.gameActivity(game); } catch (IllegalStateException expected) { rejected = true; }
        check(rejected, "Already-patched touch routing is rejected instead of patched twice");
        System.out.println("PASS synthetic DEX control-flow assertions="+checks+"; no game DEX/APK build");
    }
}
