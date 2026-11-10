"""Final APK decoder presence and the production Kotlin Python-library bridge."""
import importlib.util
import io
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android/ci"))
from verify_hca_apk import verify


def elf(machine=183, alignment=16384):
    data = bytearray(128)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", data, 18, machine)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 1)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, 128, 128, alignment)
    return data


class ApkHcaTests(unittest.TestCase):
    def candidate(self, path, *, missing=(), alignment=16384, license=True):
        python = io.BytesIO()
        with zipfile.ZipFile(python, "w") as package:
            package.writestr("webtools/core/cri_audio_decode.pyc", b"original test module identity")
            if license:
                package.writestr("webtools/core/resources/cri_hca/LICENSE", b"Permission to use, copy, modify, and distribute this software")
        with zipfile.ZipFile(path, "w") as apk:
            for abi, machine in (("arm64-v8a", 183), ("x86_64", 62)):
                apk.writestr(f"lib/{abi}/libelichika.so", elf(machine))
                if abi not in missing:
                    apk.writestr(f"lib/{abi}/libelichika_hca.so", elf(machine, alignment))
            apk.writestr("assets/chaquopy/app.imy", python.getvalue())

    def test_every_shipped_abi_has_local_decoder_and_license(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "candidate.apk"; self.candidate(apk)
            result = verify(apk)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(set(result["libraries"]), {"arm64-v8a", "x86_64"})
            self.assertTrue(result["license_retained"])

    def test_missing_decoder_on_either_abi_blocks_apk(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "candidate.apk"
            for abi in ("arm64-v8a", "x86_64"):
                with self.subTest(abi=abi):
                    self.candidate(apk, missing=[abi])
                    with self.assertRaisesRegex(ValueError, "missing its local HCA decoder"):
                        verify(apk)

    def test_incompatible_pages_or_missing_license_block_apk(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "candidate.apk"
            self.candidate(apk, alignment=4096)
            with self.assertRaisesRegex(ValueError, "16KB-compatible"):
                verify(apk)
            self.candidate(apk, license=False)
            with self.assertRaisesRegex(ValueError, "ISC license"):
                verify(apk)


class KotlinHcaBridgeTests(unittest.TestCase):
    def test_native_path_is_available_before_servers_and_python_starts_once(self):
        tools = os.environ.get("KOTLIN_UPGRADE_QA_TOOLS")
        if not tools:
            self.skipTest("Configure the Kotlin compiler for the production bridge host check")
        jars = list(Path(tools).glob("*.jar"))
        compiler = os.pathsep.join(str(path) for path in jars)
        runtime = os.pathsep.join(str(path) for path in jars if path.name.startswith(("kotlin-stdlib-", "annotations-")))
        sources = {
            "Context.kt": '''package android.content
class ApplicationInfo(val nativeLibraryDir:String="/data/app/trusted/lib/arm64")
class Context {
    val applicationInfo=ApplicationInfo()
    val applicationContext:Context get()=this
}
''',
            "Platform.kt": '''package com.chaquo.python.android
class AndroidPlatform(val context:Any)
''',
            "Python.kt": '''package com.chaquo.python
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
object State { val starts=AtomicInteger(); val environment=ConcurrentHashMap<String,String>() }
class PyObject {
    fun get(name:String):PyObject? { check(name=="environ"); return this }
    fun callAttr(name:String,vararg values:Any?):PyObject {
        check(name=="__setitem__" && values.size==2)
        State.environment[values[0].toString()]=values[1].toString()
        return this
    }
}
class Python private constructor() {
    companion object {
        @Volatile private var started=false
        private val instance=Python()
        fun isStarted()=started
        fun start(platform:Any) { State.starts.incrementAndGet(); Thread.sleep(10); started=true }
        fun getInstance():Python { check(started); return instance }
    }
    fun getModule(name:String):PyObject { check(name=="os"); return PyObject() }
}
''',
            "HcaBridgeChecks.kt": '''package com.tagundo.elichika
import android.content.Context
import com.chaquo.python.State
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
fun main() {
    val context=Context(); val ready=CountDownLatch(1); val pool=Executors.newFixedThreadPool(12)
    val calls=(1..12).map { pool.submit { ready.await(); EmbeddedPython.instance(context) } }
    ready.countDown(); calls.forEach { it.get() }; pool.shutdown()
    check(State.starts.get()==1)
    check(State.environment["ELICHIKA_NATIVE_DIR"]==context.applicationInfo.nativeLibraryDir)
    check(State.environment["ELICHIKA_HCA_LIBRARY"]==File(context.applicationInfo.nativeLibraryDir,"libelichika_hca.so").absolutePath)
    check(State.environment["ELICHIKA_TEXTURE65_BIN"]==File(context.applicationInfo.nativeLibraryDir,"libelichika_texture65.so").absolutePath)
    println("ANDROID_HCA_PYTHON_BRIDGE_PASS")
}
'''}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = []
            for name, source in sources.items():
                file = root / name; file.write_text(source); files.append(str(file))
            files.append(str(ROOT / "android/app/src/main/java/com/tagundo/elichika/EmbeddedPython.kt"))
            output = root / "bridge.jar"
            result = subprocess.run(["java", "-cp", compiler, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", "-no-stdlib", "-no-reflect", "-jvm-target", "17", "-classpath", runtime, "-d", str(output), *files],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout)
            result = subprocess.run(["java", "-cp", str(output) + os.pathsep + runtime, "com.tagundo.elichika.HcaBridgeChecksKt"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("ANDROID_HCA_PYTHON_BRIDGE_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
