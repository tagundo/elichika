package com.tagundo.elichika

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/** Real HTTP on disposable loopback sockets, plus actual native loading status. */
@RunWith(AndroidJUnit4::class)
class ServerReadinessTest {
    private val tokenA = "a".repeat(32)
    private val tokenB = "b".repeat(32)

    private class Stub(private val body: () -> String) : AutoCloseable {
        private val socket = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        val port get() = socket.localPort
        val requests = AtomicInteger()
        init {
            Thread({
                while (!socket.isClosed) {
                    try {
                        socket.accept().use { client ->
                            client.soTimeout = 2000
                            val reader = client.getInputStream().bufferedReader()
                            val request = reader.readLine()
                            check(request == "GET /_elichika/ready HTTP/1.1")
                            while (!reader.readLine().isNullOrEmpty()) { }
                            requests.incrementAndGet()
                            val bytes = body().toByteArray()
                            client.getOutputStream().apply {
                                write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
                                write(bytes); flush()
                            }
                        }
                    } catch (_: SocketException) { }
                    catch (_: java.io.IOException) { }
                }
            }, "readiness-test-http").apply { isDaemon = true }.start()
        }
        override fun close() { socket.close() }
    }

    private fun response(token: String, ready: Boolean = true) = JSONObject().put("ready", ready).put("token", token).toString()

    @Test fun wildcardAndCustomPortsResolveToLocalReadinessEndpoint() {
        assertEquals("http://127.0.0.1:8765/_elichika/ready", ServerReadiness.endpoint("0.0.0.0:8765").toString())
        assertEquals("http://127.0.0.1:8081/_elichika/ready", ServerReadiness.endpoint("localhost:8081").toString())
        assertEquals(listOf("http://127.0.0.1:8081/_elichika/ready", "http://[::1]:8081/_elichika/ready"),
            ServerReadiness.endpoints("localhost:8081").map { it.toString() })
        assertEquals("http://[::1]:8082/_elichika/ready", ServerReadiness.endpoint("[::]:8082").toString())
        assertEquals("http://127.0.0.1:8083/_elichika/ready", ServerReadiness.endpoint(":8083").toString())
        for (bad in listOf("http://localhost:80", "127.0.0.1:0", "127.0.0.1:8080/private", "name@localhost:8080")) {
            assertNull(ServerReadiness.endpoint(bad))
        }
    }

    @Test fun delayedHttpAndWrongProcessTokenStayLoadingWithoutBlockingMain() {
        val current = AtomicReference(response(tokenB))
        Stub { current.get() }.use { stub ->
            val worker = Executors.newSingleThreadExecutor()
            try {
                val endpoint = ServerReadiness.endpoint("0.0.0.0:${stub.port}")!!
                val result = worker.submit<ServerReadiness.Result> { ServerReadiness.await(endpoint, tokenA, { true }, 4000) }
                await { stub.requests.get() >= 2 }
                assertFalse("Another process serving a valid readiness shape cannot satisfy this launch", result.isDone)
                val heartbeat = CountDownLatch(1)
                Handler(Looper.getMainLooper()).post { heartbeat.countDown() }
                assertTrue("HTTP loading leaves the main looper available", heartbeat.await(1, TimeUnit.SECONDS))
                current.set(response(tokenA))
                assertEquals(ServerReadiness.Result.READY, result.get(3, TimeUnit.SECONDS))
                current.set(response(tokenA, ready = false))
                assertFalse(ServerReadiness.responds(endpoint, tokenA))
                current.set("{\"ready\":true,\"token\":\"" + tokenA + "\",\"padding\":\"" + "x".repeat(2000) + "\"}")
                assertFalse("Only bounded response JSON is accepted", ServerReadiness.responds(endpoint, tokenA))
            } finally { worker.shutdownNow() }
        }
        println("ANDROID_SERVER_READINESS_HTTP_PASS delayed_ready=true wrong_process_token_refused=true main_responsive=true bounded_response=true")
    }

    @Test fun stoppedGenerationRejectsLateReadyAndNextLaunchRequiresNewToken() {
        val owned = AtomicBoolean(true)
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val current = AtomicReference(tokenA)
        Stub {
            entered.countDown()
            release.await(3, TimeUnit.SECONDS)
            response(current.get())
        }.use { stub ->
            val worker = Executors.newSingleThreadExecutor()
            try {
                val endpoint = ServerReadiness.endpoint("127.0.0.1:${stub.port}")!!
                val first = worker.submit<ServerReadiness.Result> { ServerReadiness.await(endpoint, tokenA, { owned.get() }, 2000) }
                assertTrue(entered.await(2, TimeUnit.SECONDS))
                owned.set(false) // Stop, process exit or replacement invalidates the exact launch.
                release.countDown()
                assertEquals(ServerReadiness.Result.CANCELLED, first.get(2, TimeUnit.SECONDS))
                assertEquals(ServerReadiness.Result.TIMED_OUT, ServerReadiness.await(endpoint, tokenB, { true }, 300))
                current.set(tokenB)
                assertEquals(ServerReadiness.Result.READY, ServerReadiness.await(endpoint, tokenB, { true }, 2000))
            } finally { release.countDown(); worker.shutdownNow() }
        }
        println("ANDROID_SERVER_READINESS_GENERATION_PASS late_response_cancelled=true old_token_timeout=true new_launch_ready=true")
    }

    @Test fun nativeHeaderSeparatesLiveProcessLoadingFromHttpReadyAcrossWindows() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        assertFalse("UI-only readiness test requires a stopped server", Bus.serverRunning)
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val previousGuide = preferences.all["seen_guide"]
        val previousPhase = Bus.preparationPhase
        var first: android.app.Activity? = null
        var second: android.app.Activity? = null
        try {
            preferences.edit().putBoolean("seen_guide", true).commit()
            instrumentation.runOnMainSync {
                Bus.setPreparationPhase(AssetInstaller.PreparationPhase.IDLE)
                Bus.setRunning(true)
            }
            first = instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                assertEquals(first!!.getString(R.string.status_server_loading), first!!.findViewById<TextView>(R.id.txt_status).text.toString())
                assertEquals(first!!.getString(R.string.stop_server), first!!.findViewById<Button>(R.id.btn_toggle).text.toString())
                assertEquals(View.VISIBLE, first!!.findViewById<View>(R.id.progress_preparing).visibility)
                first!!.finish()
            }
            second = instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            instrumentation.waitForIdleSync()
            val screenshot = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
            try {
                java.io.File(context.cacheDir, "server-loading-header.png").outputStream().use {
                    assertTrue(screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it))
                }
            } finally { screenshot.recycle() }
            instrumentation.runOnMainSync {
                assertEquals(second!!.getString(R.string.status_server_loading), second!!.findViewById<TextView>(R.id.txt_status).text.toString())
                Bus.setServerReady()
            }
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                assertEquals(second!!.getString(R.string.status_running), second!!.findViewById<TextView>(R.id.txt_status).text.toString())
                assertEquals(View.GONE, second!!.findViewById<View>(R.id.progress_preparing).visibility)
                Bus.setRunning(false)
                Bus.setServerReady() // Late publication is rejected after Stop.
                assertFalse(Bus.serverReady)
            }
            println("ANDROID_SERVER_READINESS_HEADER_PASS native_loading_spinner=true stop_available=true window_replay=true http_ready_removes_spinner=true late_ready_after_stop_refused=true")
        } finally {
            instrumentation.runOnMainSync {
                first?.finish(); second?.finish()
                Bus.setRunning(false)
                Bus.setStarting(false)
                Bus.setPreparationPhase(previousPhase)
            }
            preferences.edit().apply {
                if (previousGuide is Boolean) putBoolean("seen_guide", previousGuide) else remove("seen_guide")
            }.commit()
        }
    }

    private fun await(condition: () -> Boolean) {
        val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(3)
        while (!condition() && System.nanoTime() < until) Thread.sleep(20)
        assertTrue(condition())
    }
}
