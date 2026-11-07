"""Compile the actual Kotlin installer against tiny host API doubles.

This checks Kotlin staging/orchestration, not the separately tested SQLite merge
engine. Set KOTLIN_UPGRADE_QA_TOOLS to an existing Kotlin 1.9.24 compiler/deps
directory; no dependency download or Android/Go build is performed by the test.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
KOTLIN = ROOT / 'android/app/src/main/java/com/tagundo/elichika'
STUBS = {
    'Context.kt': r'''
package android.content
import android.content.res.AssetManager
import android.content.pm.PackageManager
import android.content.pm.ApplicationInfo
import java.io.File
open class Context(val filesDir: File, val assets: AssetManager, val packageManager: PackageManager) {
    companion object { const val MODE_PRIVATE=0 }
    val applicationContext: Context get() = this
    val packageName = "synthetic.test"
    val applicationInfo = ApplicationInfo()
    val cacheDir: File get() = File(filesDir, "cache")
    private val preferences = mutableMapOf<String, SharedPreferences>()
    var beforeServiceStart: (() -> Unit)?=null
    fun getSharedPreferences(name: String, mode: Int) = preferences.getOrPut(name) { SharedPreferences() }
    fun getExternalFilesDir(type: String?) = File(filesDir, "external")
    fun getString(id: Int, vararg args: Any?) = "$id:" + args.joinToString()
    fun startForegroundService(intent: Intent) {
        beforeServiceStart?.invoke()
        val service=com.tagundo.elichika.ServerService()
        service.holdRequest=intent.extras[com.tagundo.elichika.ServerService.EXTRA_HOLD_ID]
        com.tagundo.elichika.ServerService.current=service
    }
}
class Intent(context: Context,component: Class<*>) {
    val extras=mutableMapOf<String,String?>()
    fun setAction(action: String): Intent=this
    fun putExtra(key: String,value: String?): Intent { extras[key]=value; return this }
}
class SharedPreferences {
    private val values = mutableMapOf<String,String>()
    fun getString(key: String, fallback: String?) = values[key] ?: fallback
    fun edit() = Editor()
    inner class Editor {
        fun putString(key: String, value: String): Editor { values[key]=value; return this }
        fun remove(key: String): Editor { values.remove(key); return this }
        fun apply() {}
    }
}
''',
    'Assets.kt': r'''
package android.content.res
import java.io.ByteArrayInputStream
import java.io.InputStream
open class AssetManager(val files: MutableMap<String,String>) {
    var opens=0
    val openedPaths=mutableListOf<String>()
    var failPath: String?=null
    fun list(path: String): Array<String> = files.keys.filter { it.startsWith("$path/") }
        .map { it.removePrefix("$path/").substringBefore('/') }.distinct().toTypedArray()
    fun open(path: String): InputStream {
        if (path==failPath) throw java.io.IOException("synthetic extraction failure")
        opens++; openedPaths.add(path)
        return ByteArrayInputStream(files.getValue(path).toByteArray())
    }
}
''',
    'Package.kt': r'''
package android.content.pm
class PackageInfo(var versionName: String="new", var versionCode: Int=2)
class PackageManager(val info: PackageInfo=PackageInfo()) { fun getPackageInfo(name: String, flags: Int)=info }
class ApplicationInfo { var nativeLibraryDir="/nonexistent-synthetic-native" }
''',
    'Environment.kt': r'''
package android.os
import java.io.File
object Environment {
    const val DIRECTORY_DOWNLOADS="Download"
    fun getExternalStoragePublicDirectory(name: String)=File(System.getProperty("qa.shared"),name)
}
class Looper private constructor() {
    companion object {
        private val main=Looper()
        fun getMainLooper()=main
        fun myLooper(): Looper?=null
    }
}
class Handler(looper: Looper) { fun post(action: Runnable): Boolean { action.run(); return true } }
object Process { fun myTid()=Thread.currentThread().id.toInt() }
''',
    'Os.kt': r'''
package android.system
import java.nio.file.Files
import java.nio.file.Path
object Os { fun symlink(target: String, link: String) { Files.createSymbolicLink(Path.of(link),Path.of(target)) } }
''',
    'Platform.kt': r'''
package com.chaquo.python.android
import android.content.Context
class AndroidPlatform(val context: Context)
''',
    'Python.kt': r'''
package com.chaquo.python
import java.util.concurrent.atomic.AtomicInteger
object Hooks {
    var invoke: (String,String,Array<out Any?>)->String = { _,_,_ -> error("No synthetic Python backend") }
}
class PyObject(private val module: String, private val text: String="") {
    fun callAttr(method: String,vararg args: Any?)=PyObject("",Hooks.invoke(module,method,args))
    fun get(name: String): PyObject?=PyObject(module)
    override fun toString()=text
}
class Python private constructor() {
    companion object {
        val starts=AtomicInteger()
        @Volatile private var started=false
        private val instance=Python()
        fun isStarted()=started
        fun start(platform: Any) { starts.incrementAndGet(); Thread.sleep(20); started=true }
        fun getInstance()=instance
    }
    fun getModule(name: String)=PyObject(name)
}
''',
    'App.kt': r'''
package com.tagundo.elichika
import android.content.Context
import java.io.File
object R { object string {
    const val log_setup_no_payload=1; const val log_setup_preparing=2; const val log_setup_ready=3
    const val log_setup_downloads_link=4; const val log_setup_link_failed=5; const val log_setup_config_created=6
    const val log_setup_cdn_dir=7; const val log_setup_cdn_on=8; const val log_setup_preserving_mods=9
    const val log_setup_upgrade_recovered=10; const val log_pyservers_started=11; const val log_pyservers_failed=12
    const val log_error_missing_binary=13; const val log_error_exec_failed=14
} }
object Lang { var writes=0; fun effective(ctx: Context)="en"; fun writeWebuiLanguage(ctx: Context,root: File) { writes++ } }
object Bus {
    var serverRunning=false
    val logs=mutableListOf<String>()
    fun log(value: String) { logs.add(value) }; fun toolsStateChanged() {}
    fun setRunning(value: Boolean) { serverRunning=value }
    fun setStarting(value: Boolean) {}
    fun setPreparationPhase(value: AssetInstaller.PreparationPhase) {}
}
class ServerService {
    companion object {
        var current: ServerService?=null
        var cancellation=0L
        const val ACTION_PREPARE_INSTALL="prepare"
        const val EXTRA_HOLD_ID="hold"
    }
    var isReady=true
    var initializationFailure: Throwable?=null
    var holdRequest: String?=null
    var reserved=false
    var reserveCount=0; var pauseCount=0; var resumeCount=0; var finishCount=0
    var resumeHook: ()->Unit={}
    fun reserveForInstall() { check(current===this && !reserved); reserved=true; reserveCount++ }
    fun pauseReservedInstall(): java.lang.Process? { check(reserved); pauseCount++; Bus.serverRunning=false; return null }
    fun canResumeAfterInstall(expected: Long)=current===this && cancellation==expected && reserved
    fun resumeAfterInstall(expected: Long): Boolean {
        if (!canResumeAfterInstall(expected)) return false
        resumeHook(); resumeCount++; reserved=false; Bus.serverRunning=true; return true
    }
    fun finishInstall() { finishCount++; reserved=false; if (!Bus.serverRunning) current=null }
}
''',
    'TestRegistry.kt': r'''
package androidx.test.platform.app
import android.content.Context
class Instrumentation(val targetContext: Context, val context: Context)
object InstrumentationRegistry { fun getInstrumentation(): Instrumentation=error("Android instrumentation is not executed on host") }
''',
    'TestRunner.kt': r'''
package androidx.test.ext.junit.runners
import org.junit.runner.Runner
import org.junit.runner.Description
import org.junit.runner.notification.RunNotifier
class AndroidJUnit4: Runner() {
    override fun getDescription(): Description=Description.EMPTY
    override fun run(notifier: RunNotifier) {}
}
''',
}


class PackagingTests(unittest.TestCase):
    def test_mandatory_parent_sources_follow_optional_tool_modules(self):
        workflow = (ROOT / '.github/workflows/android.yml').read_text()
        optional = workflow.index('cp modtools/*.py')
        mandatory = workflow.index('cp payload_db_upgrade.py database_maintenance.py')
        self.assertLess(optional, mandatory)
        for module in ('payload_db_upgrade.py', 'database_maintenance.py', 'payload_file_hash.py', 'payload_revision.py',
                       'costume_scene_clones.py', 'costume_scene_sources.py'):
            self.assertTrue((ROOT / module).is_file(), f'Missing canonical parent runtime source: {module}')
            self.assertIn(f'cmp {module} "$PY/{module}"', workflow)

    def test_new_logs_exist_in_default_and_korean_resources(self):
        for folder in ('values', 'values-ko'):
            tree = ET.parse(ROOT / f'android/app/src/main/res/{folder}/strings.xml')
            names = {node.get('name') for node in tree.getroot()}
            self.assertTrue({'log_setup_preserving_mods', 'log_setup_upgrade_recovered'} <= names)

    def test_costume_admission_precedes_preparation_and_every_native_spawn(self):
        preparation = (KOTLIN / 'PayloadPreparation.kt').read_text()
        gate = preparation.index('PayloadUpgrade.checkCostumeStartup(context, root)')
        for operation in ('PayloadUpgrade.recover(', 'PayloadFiles.clearStages(',
                          'PayloadFiles.revisionManifest(', 'settings()'):
            self.assertLess(gate, preparation.index(operation), operation)
        process = (KOTLIN / 'ServerProcess.kt').read_text()
        self.assertEqual(process.count('ProcessBuilder('), 1)
        self.assertEqual(process.count('pb.start()'), 1)
        self.assertLess(process.index('PayloadUpgrade.checkCostumeStartup(ctx, workDir)'),
                        process.index('ProcessBuilder('))
        self.assertIn('start(emptyList(), workDir)', process)
        self.assertIn('start(args, workDir, onExit)', process)

    def test_cold_recovery_tools_are_limited_to_the_typed_refusal(self):
        bridge = (KOTLIN / 'PayloadUpgrade.kt').read_text()
        self.assertIn('result.optString("status") == "REFUSED" && result.optString("reason") == "COSTUME_RECOVERY_REQUIRED"', bridge)
        self.assertIn('requireStatus(result, setOf("CLEAN"))', bridge)
        tools = (KOTLIN / 'PyServers.kt').read_text()
        known = tools.split('catch (error: PayloadUpgrade.CostumeRecoveryRequired)', 1)[1]
        specific, generic = known.split('catch (error: Throwable)', 1)
        self.assertIn('ensureStarted(appContext, appContext.filesDir)', specific)
        self.assertNotIn('ensureStarted(', generic.split('fun ensureStarted', 1)[0])
        service = (KOTLIN / 'ServerService.kt').read_text()
        specific = service.split('catch (error: PayloadUpgrade.CostumeRecoveryRequired)', 1)[1].split('catch (error: Exception)', 1)[0]
        self.assertIn('pendingCommands.filter { it.action == ACTION_PREPARE_INSTALL }', specific)
        self.assertIn('Bus.setRunning(false)', specific)
        self.assertNotIn('startServer(', specific)
        self.assertNotIn('runAction(', specific)


class KotlinInstallerTests(unittest.TestCase):
    def test_staging_recovery_preservation_and_shared_interpreter_contract(self):
        configured = os.environ.get('KOTLIN_UPGRADE_QA_TOOLS')
        if not configured:
            self.skipTest('Kotlin host compiler not configured; Android build compiles these sources in CI')
        tools = Path(configured)
        java = os.environ.get('KOTLIN_UPGRADE_QA_JAVA', 'java')
        jars = list(tools.glob('*.jar'))
        self.assertTrue(any(p.name.startswith('kotlin-compiler-embeddable-') for p in jars))
        compiler = os.pathsep.join(map(str, jars))
        runtime = os.pathsep.join(str(p) for p in jars if p.name.startswith(('kotlin-stdlib-', 'annotations-', 'json-', 'junit-')))
        with tempfile.TemporaryDirectory(prefix='kotlin-upgrade-', dir=os.environ.get('KOTLIN_UPGRADE_QA_TMP')) as directory:
            temporary = Path(directory)
            sources = []
            for name, content in STUBS.items():
                path = temporary / name
                path.write_text(content)
                sources.append(str(path))
            sources += [str(KOTLIN / name) for name in ('AssetInstaller.kt', 'PayloadFiles.kt', 'PayloadUpgrade.kt', 'PayloadPreparation.kt', 'EmbeddedPython.kt', 'PyServers.kt', 'ServerConfig.kt', 'AndroidServerController.kt', 'ServerProcess.kt')]
            sources.append(str(ROOT / 'android/app/src/androidTest/java/com/tagundo/elichika/NativePythonTest.kt'))
            sources.append(str(ROOT / 'tests/kotlin_payload_upgrade/HostChecks.kt'))
            output = temporary / 'checks.jar'
            compiled = subprocess.run([java, '-cp', compiler, 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
                '-no-stdlib', '-no-reflect', '-jvm-target', '17', '-classpath', runtime, '-d', str(output), *sources],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            checked = subprocess.run([java, '-cp', str(output) + os.pathsep + runtime, 'com.tagundo.elichika.HostChecksKt', str(temporary)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            self.assertEqual(checked.returncode, 0, checked.stdout)
            self.assertIn('KOTLIN_UPGRADE_HOST_CHECKS_PASS', checked.stdout)
            print(checked.stdout.strip())

    def test_service_and_controller_compile_against_the_existing_android_sdk(self):
        configured = os.environ.get('KOTLIN_UPGRADE_QA_TOOLS')
        sdk = os.environ.get('KOTLIN_UPGRADE_QA_ANDROID_JAR')
        if not configured or not sdk:
            self.skipTest('Host Kotlin compiler and existing Android SDK jar not configured')
        tools = Path(configured)
        self.assertTrue(Path(sdk).is_file())
        java = os.environ.get('KOTLIN_UPGRADE_QA_JAVA', 'java')
        jars = list(tools.glob('*.jar'))
        compiler = os.pathsep.join(map(str, jars))
        runtime = os.pathsep.join([sdk, *(str(p) for p in jars if p.name.startswith(('kotlin-stdlib-', 'annotations-', 'json-', 'junit-')))])
        names = ('AssetInstaller.kt', 'PayloadFiles.kt', 'PayloadUpgrade.kt', 'PayloadPreparation.kt', 'EmbeddedPython.kt',
                 'PyServers.kt', 'ServerConfig.kt', 'AndroidServerController.kt', 'ServerService.kt',
                 'ServerProcess.kt', 'ServerSettings.kt', 'Bus.kt', 'PayloadFileHasher.kt')
        sources = [KOTLIN / name for name in names]
        sources.append(ROOT / 'android/app/src/androidTest/java/com/tagundo/elichika/PayloadRevisionTest.kt')
        resources = {}
        for source in sources:
            for group, key in re.findall(r'R\.(string|drawable)\.([A-Za-z0-9_]+)', source.read_text()):
                resources.setdefault(group, set()).add(key)
        resource_code = 'object R {\n' + '\n'.join('object ' + group + ' {\n' + '\n'.join(
            f'const val {key}={i}' for i, key in enumerate(sorted(keys), 1)) + '\n}' for group, keys in resources.items()) + '\n}'
        app = '''package com.tagundo.elichika
import android.content.Context
import java.io.File
object Lang { fun effective(context: Context)="en"; fun writeWebuiLanguage(context: Context,root: File) {} }
class MainActivity: android.app.Activity()
''' + resource_code
        with tempfile.TemporaryDirectory(prefix='kotlin-service-', dir=os.environ.get('KOTLIN_UPGRADE_QA_TMP')) as directory:
            temporary = Path(directory)
            for filename, text in (('Python.kt', STUBS['Python.kt']), ('Platform.kt', STUBS['Platform.kt']), ('AppSdk.kt', app),
                                   ('TestRegistry.kt', STUBS['TestRegistry.kt']), ('TestRunner.kt', STUBS['TestRunner.kt'])):
                file = temporary / filename
                file.write_text(text)
                sources.append(file)
            compiled = subprocess.run([java, '-cp', compiler, 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
                '-no-stdlib', '-no-reflect', '-jvm-target', '17', '-classpath', runtime,
                '-d', str(temporary / 'android-service-check.jar'), *map(str, sources)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)


if __name__ == '__main__':
    unittest.main()
