"""Compile the actual Bus/retained-log implementation with a deterministic looper.

These are host algorithm, event coalescing and real-file preservation checks,
not Android device frame measurements. No dependencies are downloaded.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUS = ROOT / 'android/app/src/main/java/com/tagundo/elichika/Bus.kt'
TOOLS = Path(os.environ.get('KOTLIN_UPGRADE_QA_TOOLS', '/workspace/android-build/kotlin-tools'))

STUB = r'''
package android.os
object Looper {
    private val main=Any()
    fun getMainLooper(): Any=main
    fun myLooper(): Any?=null
}
class Handler(looper: Any) {
    companion object {
        val tasks=java.util.ArrayDeque<Runnable>()
        var posted=0
        @Synchronized fun queued()=tasks.size
        fun drain() { while(true) {
            val next=synchronized(this) { if(tasks.isEmpty()) null else tasks.removeFirst() }
            if(next==null)return
            next.run()
        } }
    }
    fun post(task: Runnable): Boolean=synchronized(Companion) { tasks.addLast(task);posted++;true }
    fun postDelayed(task: Runnable,delay: Long)=post(task)
    fun removeCallbacks(task: Runnable) { synchronized(Companion) { tasks.remove(task) } }
}
'''

APP = r'''
package com.tagundo.elichika
object AssetInstaller { enum class PreparationPhase { IDLE,FAILED,UPDATING_GAME_DATA } }
object PayloadProgress { data class State(val percent: Int) }
'''

CHECKS = r'''
package com.tagundo.elichika
import android.os.Handler
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.TimeUnit
import kotlin.system.measureNanoTime

class BlockingLogWriter(file: File,val entered: CountDownLatch,val release: CountDownLatch):
    java.io.BufferedWriter(java.io.FileWriter(file,true)) {
    private var blocked=false
    override fun write(text: String,offset: Int,length: Int) {
        if(!blocked) { blocked=true;entered.countDown();check(release.await(15,TimeUnit.SECONDS)) }
        super.write(text,offset,length)
    }
}

fun main(args: Array<String>) {
    val model=ConsoleLogBuffer(8)
    model.append("abcd")
    val first=model.read(-1)
    check(first.reset && first.text=="abcd")
    model.append("efghij")
    val second=model.read(first.end)
    check(!second.reset && second.text=="efghij" && second.start==2L)
    check(model.read(-1).text=="cdefghij")
    check(model.read(0).reset && model.read(0).text=="cdefghij")
    model.clear()
    check(model.read(second.end).reset && model.read(second.end).text.isEmpty())
    model.append("0123456789abcdef")
    check(model.read(-1).text=="89abcdef")

    // Reproduce what the real Activity does with its independent cursor.
    val history=ConsoleLogBuffer(200_000)
    val display=StringBuilder()
    var offset=-1L;var start=-1L
    var fullSnapshotCharacters=0L;var deltaCharacters=0L
    val lines=(0 until 12_000).map { "synthetic-log-$it "+"x".repeat(70)+"\n" }
    val elapsed=measureNanoTime {
        for((i,line) in lines.withIndex()) {
            history.append(line)
            if(i%20==19) {
                val update=history.read(offset)
                if(update.reset) { display.setLength(0);display.append(update.text) }
                else {
                    val remove=(update.start-start).coerceAtLeast(0).coerceAtMost(display.length.toLong()).toInt()
                    display.delete(0,remove);display.append(update.text)
                }
                offset=update.end;start=update.start
                deltaCharacters+=update.text.length
                fullSnapshotCharacters+=history.read(-1).text.length
                check(display.toString()==history.read(-1).text)
            }
        }
    }
    check(deltaCharacters*20<fullSnapshotCharacters)
    // This is a bounded-tail equivalence proof, not a native TextView timing.

    val directory=File(args.single()).apply { mkdirs() }
    val target=File(directory,"persistent.log")
    Bus.attachLogFile(target)
    val owner1=Any();val owner2=Any()
    val received1=mutableListOf<String>();val received2=mutableListOf<String>()
    var cdn1=0;var cdn2=0
    Bus.addListener(owner1,{received1.add(it)},{},{},{cdn1++})
    Bus.addListener(owner2,{received2.add(it)},{},{},{cdn2++})
    val before=Handler.posted
    for(i in 0 until 10_000)Bus.log("burst-$i "+"z".repeat(80))
    Bus.log("cdn_cache: true")
    check(Handler.posted-before==1 && Handler.queued()==1)
    Handler.drain()
    check(received1.size==1 && received2==received1 && cdn1==1 && cdn2==1)
    val old=Bus.readLog(-1)
    check(old.text.length==200_000)
    Bus.removeListener(owner1)
    Bus.log("after-window-one-stopped")
    Handler.drain()
    check(received1.size==1 && received2.size==2)
    check(Bus.awaitLogFile(10_000))
    val onDisk=target.readText()
    val expected=(0 until 10_000).joinToString("") { "burst-$it "+"z".repeat(80)+"\n" }+
        "cdn_cache: true\nafter-window-one-stopped\n"
    check(onDisk.substringAfter("====\n")==expected)
    Bus.clear();Handler.drain()
    check(Bus.snapshot().isEmpty() && Bus.readLog(old.end).reset)
    check(Bus.awaitLogFile(10_000) && target.readText()==onDisk)
    Bus.clear();Bus.log("immediate-after-clear")
    Bus.addListener(owner1,{received1.add(it)},{})
    Handler.drain()
    check(Bus.snapshot()=="immediate-after-clear\n" && received1.last()=="immediate-after-clear\n")
    Bus.flushLogFile()
    check(Bus.awaitLogFile(10_000) && target.readText()==onDisk+"immediate-after-clear\n")
    Bus.removeListener(owner1)
    Bus.removeListener(owner2)
    // Fault injection only in this host test: the real sink blocks inside its
    // first active batch write, while the real producer continues flooding.
    val executor=Bus::class.java.getDeclaredField("disk").apply { isAccessible=true }.get(Bus) as ExecutorService
    val writer=Bus::class.java.getDeclaredField("logWriter").apply { isAccessible=true }
    val entered=CountDownLatch(1);val release=CountDownLatch(1)
    executor.submit { (writer.get(Bus) as? java.io.BufferedWriter)?.close()
        writer.set(Bus,BlockingLogWriter(target,entered,release)) }.get(10,TimeUnit.SECONDS)
    val beforeSlow=target.readText()
    Bus.log("slow-active-first")
    check(entered.await(5,TimeUnit.SECONDS))
    check(Bus.logFileStatus().pendingBytes>=64+3*"slow-active-first\n".length)
    val accepted=ArrayList<String>()
    var warnings=0;var maximumPending=0L
    val producerElapsed=measureNanoTime {
        repeat(100_000) { index ->
            val paused=Bus.logFilePaused
            val line="slow-$index "+"q".repeat(80)
            Bus.log(line)
            val status=Bus.logFileStatus()
            maximumPending=maxOf(maximumPending,status.pendingBytes)
            check(status.pendingBytes<=Bus.MAX_PENDING_FILE_BYTES)
            if(!status.paused) accepted.add(line)
            else if(!paused) {
                warnings+=Bus.snapshot().lines().count { it.startsWith("[log file paused]") }
                Handler.drain()
            }
        }
    }
    check(producerElapsed<TimeUnit.SECONDS.toNanos(5))
    val saturated=Bus.logFileStatus()
    check(saturated.paused && saturated.unmirroredLines==100_000L-accepted.size && warnings==1)
    check(saturated.unmirroredBytes>0 && maximumPending>Bus.MAX_PENDING_FILE_BYTES-1000)
    // Reopening an Activity cannot revive an overflowed sink under a blocked worker.
    val otherTarget=File(directory,"must-not-retry-overflow.log")
    Bus.attachLogFile(otherTarget)
    check(Bus.logFilePaused && !otherTarget.exists())
    release.countDown()
    check(Bus.awaitLogFile(10_000) && Bus.logFileStatus().pendingBytes==0L)
    check(target.readText()==beforeSlow+"slow-active-first\n"+accepted.joinToString("") { it+"\n" })
    check(Bus.logFilePaused && !otherTarget.exists())
    println("ANDROID_CONSOLE_HOST_PASS callbacks=1 burstLines=10001 retainedChars=200000 persistentLines=10003 deltaChars=$deltaCharacters equivalentFullSnapshotChars=$fullSnapshotCharacters algorithmNanos=$elapsed blockedWorkerFlood=100000 maximumPendingBytes=$maximumPending rejectedLines=${saturated.unmirroredLines} producerNanos=$producerElapsed")
}
'''

class AndroidConsolePerformanceTests(unittest.TestCase):
    def test_actual_kotlin_bus_preserves_tail_files_and_coalesces_burst(self):
        if not TOOLS.is_dir():
            self.skipTest('Existing Kotlin compiler/dependencies are required; no download attempted')
        jars = sorted(TOOLS.glob('*.jar'))
        compiler = os.pathsep.join(map(str, jars))
        runtime = os.pathsep.join(str(p) for p in jars if p.name.startswith(('kotlin-stdlib-', 'annotations-')))
        java = os.environ.get('KOTLIN_UPGRADE_QA_JAVA', 'java')
        with tempfile.TemporaryDirectory(prefix='android-console-host-', dir=os.environ.get('KOTLIN_UPGRADE_QA_TMP', '/tmp')) as directory:
            root = Path(directory)
            sources = [BUS]
            for name, text in (('Android.kt', STUB), ('App.kt', APP), ('Checks.kt', CHECKS)):
                path = root/name; path.write_text(text); sources.append(path)
            jar = root/'checks.jar'
            result = subprocess.run([java, '-Xmx384m', '-cp', compiler, 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
                '-no-stdlib', '-no-reflect', '-jvm-target', '17', '-classpath', runtime,
                '-d', str(jar), *map(str, sources)], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            checked = subprocess.run([java, '-Xmx256m', '-cp', str(jar)+os.pathsep+runtime,
                'com.tagundo.elichika.ChecksKt', str(root/'logs')], capture_output=True, text=True, timeout=30)
            self.assertEqual(checked.returncode, 0, checked.stdout+checked.stderr)
            self.assertIn('ANDROID_CONSOLE_HOST_PASS', checked.stdout)
            print(checked.stdout.strip())

if __name__ == '__main__':
    unittest.main()
