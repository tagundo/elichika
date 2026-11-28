import com.android.tools.smali.dexlib2.DexFileFactory;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.iface.*;
import com.android.tools.smali.dexlib2.iface.instruction.*;
import com.android.tools.smali.dexlib2.iface.reference.*;
import java.io.File;

/** Read-only exact-b25 DEX callback inventory; this class never enters a product. */
public final class ActivityResultAudit {
    public static void main(String[] args) throws Exception {
        for (String apk : args) {
            DexFile dex = DexFileFactory.loadDexEntry(new File(apk), "classes.dex", true,
                    Opcodes.forApi(21)).getDexFile();
            System.out.println("APK " + apk);
            for (ClassDef cls : dex.getClasses()) {
                if (cls.getType().contains("FirebaseMessagingActivity;")
                        || cls.getType().contains("FirebaseMessagingUnsafeActivity;")
                        || cls.getType().endsWith("/UnityPlayerActivity;")) {
                    System.out.println("RESULT_BASE " + cls.getType() + " SUPER " + cls.getSuperclass());
                    for (Method method : cls.getMethods()) if (method.getName().equals("onActivityResult"))
                        System.out.println("RESULT_BASE_METHOD " + UpdateFovDex.signature(method)
                                + " FLAGS " + method.getAccessFlags());
                }
                if (cls.getType().equals("Lcom/klab/lovelive/allstars/global/GlobalUnsafeMainActivity;")
                        || cls.getType().equals("Lcom/klab/lovelive/allstars/MainActivity;")) {
                    System.out.println("ACTIVITY " + cls.getType() + " SUPER " + cls.getSuperclass());
                    for (Method method : cls.getMethods())
                        System.out.println("METHOD " + UpdateFovDex.signature(method));
                }
                for (Method method : cls.getMethods()) {
                    if (method.getImplementation() == null) continue;
                    for (Instruction instruction : method.getImplementation().getInstructions()) {
                        if (instruction instanceof NarrowLiteralInstruction &&
                                ((NarrowLiteralInstruction)instruction).getNarrowLiteral()==0x534d)
                            System.out.println("REQUEST_CODE_COLLISION " + cls.getType() + " "
                                    + UpdateFovDex.signature(method));
                        if (!(instruction instanceof ReferenceInstruction)) continue;
                        Reference reference = ((ReferenceInstruction)instruction).getReference();
                        if (!(reference instanceof MethodReference)) continue;
                        MethodReference target = (MethodReference)reference;
                        if (target.getName().equals("onActivityResult") && (target.getDefiningClass()
                                .equals("Lcom/klab/lovelive/allstars/global/GlobalUnsafeMainActivity;")
                                || target.getDefiningClass().equals("Lcom/klab/lovelive/allstars/MainActivity;")))
                            System.out.println("EXPLICIT_RESULT_REFERENCE " + cls.getType() + " "
                                    + UpdateFovDex.signature(method) + " -> " + target);
                    }
                }
            }
        }
    }
}
