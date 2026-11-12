package com.tagundo.elichika

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

private fun eventually(check: () -> Boolean) {
    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(7)
    while (!check() && System.nanoTime() < deadline) Thread.sleep(10)
    check(check()) { "Management lifecycle condition did not complete" }
}

fun main(args: Array<String>) {
    val root = File(args[0])
    val ctx = Context(root, File(root, "native"))
    fun launches() = File(root, "launches.jsonl").takeIf { it.isFile }?.readLines().orEmpty()
    fun latest() = JSONObject(launches().last())
    fun childDead(pid: Long) = !java.lang.ProcessHandle.of(pid).map { it.isAlive }.orElse(false)

    ManagementServer.prepare(ctx, root)
    Thread.sleep(50)
    check(ManagementServer.url() == null && ManagementServer.currentPid() == null && launches().isEmpty()) {
        "Preparing standalone tools must not start a Go process before the management panel is requested"
    }
    val unrequested = ManagementServer.suspendForService()
    check(ManagementServer.awaitSuspended(unrequested))
    ManagementServer.releaseService(unrequested)
    Thread.sleep(50)
    check(ManagementServer.currentPid() == null && launches().isEmpty())
    ManagementServer.prepareAsync(ctx)
    eventually { ManagementServer.url() != null }
    val first = latest()
    val firstUrl = ManagementServer.url()!!
    check(first.getJSONArray("args").toString() == "[\"management\"]")
    check(first.getString("token").matches(Regex("[0-9a-f]{32}")))
    check(first.getString("parent") == android.os.Process.myPid().toString())
    check(ManagementServer.currentPid() == first.getLong("pid").toInt())
    check(!Bus.serverRunning && !ManagementServer.isPreparing() && !ManagementServer.hasError())
    check(ServerReadiness.responds(URL("$firstUrl/_elichika/ready"), first.getString("token")))
    check(!ServerReadiness.responds(URL("$firstUrl/_elichika/ready"), "0".repeat(32)))
    check(Bus.logs.none { it.contains("ELICHIKA_MANAGEMENT_READY") || it.contains(first.getString("token")) || it.contains("PRIVATE-PASSWORD-SENTINEL") })

    val lease = ManagementServer.suspendForService()
    check(ManagementServer.url() == null && !ManagementServer.isPreparing())
    check(ManagementServer.awaitSuspended(lease))
    eventually { childDead(first.getLong("pid")) }
    check(ManagementServer.currentPid() == null)
    val secondLease = ManagementServer.suspendForService()
    check(ManagementServer.awaitSuspended(secondLease))
    ManagementServer.prepare(ctx, root)
    ManagementServer.releaseService(lease)
    Thread.sleep(50)
    check(ManagementServer.url() == null && launches().size == 1)
    ManagementServer.releaseService(secondLease)
    eventually { ManagementServer.url() != null && launches().size == 2 }
    val second = latest()
    check(second.getLong("pid") != first.getLong("pid"))
    check(second.getString("token") != first.getString("token"))

    // An expensive Python startup admission must not block service reservation
    // on Android's main thread, and a cancelled pending launch must not spawn.
    val beforePending = ManagementServer.suspendForService()
    check(ManagementServer.awaitSuspended(beforePending))
    PayloadUpgrade.entered = CountDownLatch(1)
    PayloadUpgrade.gate = CountDownLatch(1)
    ManagementServer.releaseService(beforePending)
    check(PayloadUpgrade.entered!!.await(3, TimeUnit.SECONDS))
    val started = System.nanoTime()
    val cancelledPending = ManagementServer.suspendForService()
    check(System.nanoTime() - started < TimeUnit.MILLISECONDS.toNanos(500))
    check(ManagementServer.awaitSuspended(cancelledPending))
    PayloadUpgrade.gate!!.countDown()
    PayloadUpgrade.gate = null
    PayloadUpgrade.entered = null
    Thread.sleep(100)
    check(ManagementServer.url() == null && launches().size == 2)

    // Known data-recovery refusal remains visible without launching any Go child.
    PayloadUpgrade.failure = "COSTUME_RECOVERY_REQUIRED"
    ManagementServer.releaseService(cancelledPending)
    eventually { ManagementServer.hasError() }
    check(ManagementServer.errorMessage() == "COSTUME_RECOVERY_REQUIRED")
    check(ManagementServer.url() == null && launches().size == 2)
    PayloadUpgrade.failure = null
    ManagementServer.prepareAsync(ctx)
    eventually { ManagementServer.url() != null && launches().size == 3 }
    check(!Bus.serverRunning)
    val final = latest()
    val windowA = Any()
    val windowB = Any()
    ManagementServer.requestUi(ctx, windowA)
    ManagementServer.requestUi(ctx, windowB)
    ManagementServer.releaseUi(windowA)
    Thread.sleep(50)
    check(ManagementServer.currentPid() == final.getInt("pid") && launches().size == 3) {
        "Releasing one app window must not stop another window's process"
    }
    File(root, "management-drain-requested").delete()
    File(root, "release-management-drain").delete()
    File(root, "hold-management-drain").writeText("An authenticated write is completing")
    ManagementServer.releaseUi(windowB)
    eventually { File(root, "management-drain-requested").exists() && ManagementServer.isDraining() }
    val editing = ManagementServer.suspendForService()
    val takeoverFinished = CountDownLatch(1)
    val takeover = Thread {
        check(ManagementServer.awaitSuspended(editing))
        takeoverFinished.countDown()
    }.apply { start() }
    // The previous generic cleanup would SIGKILL after ten seconds. A slow
    // authenticated write must retain its process and block database takeover.
    Thread.sleep(11_000)
    check(ManagementServer.currentPid() == final.getInt("pid") && !childDead(final.getLong("pid")))
    check(ManagementServer.isDraining() && takeoverFinished.count == 1L && launches().size == 3)
    File(root, "release-management-drain").writeText("The fixture write committed")
    check(takeoverFinished.await(3, TimeUnit.SECONDS))
    takeover.join(1000)
    File(root, "hold-management-drain").delete()
    File(root, "release-management-drain").delete()
    eventually { ManagementServer.currentPid() == null && childDead(final.getLong("pid")) }
    check(ManagementServer.url() == null)
    ManagementServer.prepare(ctx, root)
    ManagementServer.releaseService(editing)
    Thread.sleep(100)
    check(launches().size == 3 && ManagementServer.currentPid() == null) {
        "A data job must not restart management after its last app window releases demand"
    }

    // A rotation hands demand to the new Activity without retaining a dead owner.
    val rotated = android.app.Activity()
    val replacement = android.app.Activity()
    ManagementServer.requestUi(ctx, rotated)
    eventually { ManagementServer.url() != null && launches().size == 4 }
    val rotatedPid = latest().getLong("pid")
    rotated.isDestroyed = true
    ManagementServer.requestUi(ctx, replacement)
    ManagementServer.releaseUi(replacement)
    eventually { childDead(rotatedPid) && ManagementServer.currentPid() == null }

    // Automatic UI refreshes must preserve an error until an explicit Retry.
    PayloadUpgrade.failure = "COSTUME_RECOVERY_REQUIRED"
    ManagementServer.requestUi(ctx, windowA)
    eventually { ManagementServer.hasError() }
    PayloadUpgrade.failure = null
    ManagementServer.requestUi(ctx, windowA)
    ManagementServer.prepare(ctx, root)
    Thread.sleep(100)
    check(ManagementServer.hasError() && launches().size == 4)
    ManagementServer.requestUi(ctx, windowA, retry = true)
    eventually { ManagementServer.url() != null && launches().size == 5 }
    val retried = latest()
    ManagementServer.releaseUi(windowA)
    eventually { childDead(retried.getLong("pid")) && ManagementServer.currentPid() == null }
    val stopped = ManagementServer.suspendForService()
    check(ManagementServer.awaitSuspended(stopped))
    check(Bus.logs.none { it.contains("ELICHIKA_MANAGEMENT_READY") || it.contains(final.getString("token")) || it.contains("PRIVATE-PASSWORD-SENTINEL") })
    println("ANDROID_MANAGEMENT_HOST_CHECKS_PASS: lazy explicit demand, owned PID, private readiness, fresh nonce, parent PID, game OFF, lease exclusion, graceful authenticated-write drain without SIGKILL, blocked takeover until explicit release, stop/reap, restart, cancelled pending launch, recovery refusal, explicit retry, two UI owners, owner release without job restart, rotation handoff, no secret logs")
}
