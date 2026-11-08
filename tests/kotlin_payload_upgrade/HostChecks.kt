package com.tagundo.elichika

import android.content.Context
import android.content.pm.PackageManager
import android.content.res.AssetManager
import com.chaquo.python.Hooks
import com.chaquo.python.Python
import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.util.Comparator
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

private fun removeTree(file: File) {
    if (file.exists() || Files.isSymbolicLink(file.toPath())) {
        Files.walk(file.toPath()).use { paths -> paths.sorted(Comparator.reverseOrder()).forEach { Files.deleteIfExists(it) } }
    }
}

private class Backend {
    var applyCount=0
    var recoverCount=0
    var decisionCount=0
    var startupReply="""{"status":"CLEAN"}"""
    var startupChecks=0
    var beforeDecision: (File)->Unit = {}
    val admittedManifests=mutableMapOf<File,String>()
    var launchCount=0
    var launchRoot: File?=null
    var refused=false
    var leaseBusy=false
    var recovered=false
    var failedStage: File?=null
    var heldRoot: File?=null
    var beforeApply: (File,File,String)->Unit = { _,_,_ -> }
    val modes=mutableListOf<String>()
    fun call(module: String, method: String, arguments: Array<out Any?>): String {
        if (module=="elichika_launch") { check(heldRoot==null); launchCount++; launchRoot=File(arguments[0].toString()); return "None" }
        val root=File(arguments[0].toString())
        if (module=="costume_management") {
            check(method=="startup_check_json" && arguments.size==1)
            startupChecks++
            return startupReply
        }
        if (module=="database_maintenance") {
            if (method=="begin_maintenance_json") {
                if (leaseBusy) return JSONObject().put("status","REFUSED").put("reason","DATABASE_MAINTENANCE_BUSY").toString()
                check(heldRoot==null)
                heldRoot=root
                return JSONObject().put("status","ACQUIRED").put("token","synthetic-lease").toString()
            }
            check(method=="end_maintenance_json" && heldRoot==root && arguments[1]=="synthetic-lease")
            heldRoot=null
            return JSONObject().put("status","RELEASED").toString()
        }
        check(heldRoot==root) { "Admission ran without the whole preparation lease" }
        if (module=="payload_revision" && method=="decide_json") {
            decisionCount++
            beforeDecision(root)
            val manifest=try { JSONObject(arguments[1].toString()) } catch (_: Exception) {
                return JSONObject().put("status","FAILED").put("reason","INVALID_PAYLOAD_MANIFEST").toString()
            }
            val revision=manifest.getString("revision")
            admittedManifests[root]=arguments[1].toString()
            val installed=File(root,"installed_version").takeIf { it.isFile }?.readText()?.trim().orEmpty()
            val reset=arguments[2] as Boolean
            if (!reset && installed.startsWith("payload-v1:") && !File(root,".payload-upgrade/current.json").isFile) {
                return JSONObject().put("status","FAILED").put("reason","MANAGED_PROVENANCE_MISSING").toString()
            }
            val required=manifest.getJSONObject("files").keys().asSequence().toList()
            val action=when {
                reset -> "reset"
                installed==revision && !File(root,".payload-upgrade/needs-rebase").exists() && required.all { File(root,it).isFile } -> "skip"
                installed.isNotEmpty() || File(root,"assets").exists() -> "upgrade"
                else -> "fresh"
            }
            return JSONObject().put("status","READY").put("action",action).put("revision",revision)
                .put("from_version",installed).put("reason","SYNTHETIC_ADMISSION").toString()
        }
        if (module=="payload_db_upgrade") {
            check(method=="recover_upgrade_json")
            recoverCount++
            failedStage?.let { check(it.exists()) { "Kotlin removed an input before journal recovery" } }
            return JSONObject().put("status",if (recovered) "ROLLED_BACK" else "CLEAN").toString()
        }
        check(module=="payload_revision" && method=="apply_json" && arguments.size==6)
        check(arguments[5]==admittedManifests[root]) { "Publisher lost the exact admitted manifest" }
        check(JSONObject(arguments[5].toString()).getString("revision")==arguments[3])
        applyCount++
        val payload=File(arguments[1].toString())
        val version=arguments[3].toString()
        val mode=arguments[4].toString()
        modes.add(mode)
        beforeApply(root,payload,mode)
        if (refused) {
            failedStage=payload
            return JSONObject().put("status","REFUSED").put("reason","DATABASE_MAINTENANCE_BUSY").toString()
        }
        // Backend double: this tests the caller's isolation and contract only.
        // The real transaction/SQLite merge is exercised by its Python tests.
        if (mode=="reset") {
            for (name in listOf("webui","assets","static","serverdata.db","server init jsons","privatekey.pem","publickey.pem")) removeTree(File(root,name))
        }
        payload.walkTopDown().filter { it.isFile }.forEach {
            val target=File(root,it.relativeTo(payload).path)
            target.parentFile.mkdirs()
            val incoming=it.readText()
            target.writeText(if (mode=="upgrade" && target.name=="masterdata.db" && target.exists()) target.readText()+"+"+incoming else incoming)
        }
        File(root,"installed_version").writeText(version)
        File(root,".payload-upgrade/current.json").apply { parentFile.mkdirs(); writeText("{}") }
        File(root,".payload-upgrade/needs-rebase").delete()
        failedStage=null
        recovered=false
        return JSONObject().put("status","COMMITTED").toString()
    }
}

private val revision="payload-v1:"+"a".repeat(64)
private fun source(): AssetManager {
    val assets=AssetManager(mutableMapOf(
    "payload/assets/db/gl/masterdata.db" to "NEW_DB",
    "payload/assets/db/gl/asset_a_ko.db" to "NEW_ASSET_DB",
    "payload/assets/new-file" to "NEW_ASSET",
    "payload/webui/page.html" to "NEW_HTML",
    "payload/serverdata.db" to "NEW_SERVER_DB",
    "payload/privatekey.pem" to "SYNTHETIC_KEY",
    "payload/config.json" to """{"preserved":"bundled default","cdn_cache":false}""",
    "payload/userdata.db" to "NEVER_STAGE_USER_DATA",
    "payload/serverstate.db" to "NEVER_STAGE_SERVER_STATE",
    "payload/backup/userdata.db" to "NEVER_STAGE_BACKUP"
))
    val files=JSONObject()
    for ((name,content) in assets.files) {
        val relative=name.removePrefix("payload/")
        if (relative.substringBefore('/') in setOf("assets","webui","serverdata.db","privatekey.pem")) {
            files.put(relative,JSONObject().put("bytes",content.length).put("sha256","0".repeat(64)))
        }
    }
    assets.files["payload_revision.json"]=JSONObject().put("revision",revision).put("files",files).toString()
    return assets
}

private fun context(parent: File,name: String, assets: AssetManager=source()): Context {
    val directory=File(parent,name).apply { mkdirs() }
    return Context(directory,assets,PackageManager())
}

private fun expectFailure(action: ()->Unit): String {
    try { action() } catch (error: IllegalStateException) { return error.message.orEmpty() }
    error("Expected preparation to fail")
}

fun main(args: Array<String>) {
    val temporary=File(args[0])
    System.setProperty("qa.shared",File(temporary,"shared").absolutePath)
    val backend=Backend()
    Hooks.invoke=backend::call

    // All production interpreter call sites share this Kotlin initialization lock.
    val raceContext=context(temporary,"interpreter")
    val ready=CountDownLatch(1)
    val pool=Executors.newFixedThreadPool(12)
    val racers=(1..12).map { pool.submit { ready.await(); EmbeddedPython.instance(raceContext) } }
    ready.countDown(); racers.forEach { it.get() }; pool.shutdown()
    check(Python.starts.get()==1)
    check(backend.launchCount==0)

    val first=context(temporary,"fresh")
    val phases=mutableListOf<AssetInstaller.PreparationPhase>()
    val observePhase: (AssetInstaller.PreparationPhase)->Unit = { phases.add(it) }
    AssetInstaller.install(first,observePhase) {}
    check(phases.first()==AssetInstaller.PreparationPhase.PREPARING && phases.last()==AssetInstaller.PreparationPhase.IDLE)
    check(AssetInstaller.PreparationPhase.UPDATING_GAME_DATA !in phases) { "Fresh install must not claim to preserve installed mods" }
    check(backend.modes.last()=="fresh")
    check(File(first.filesDir,"installed_version").readText()==revision)
    check(!File(first.filesDir,"userdata.db").exists())
    check(!File(first.filesDir,"serverstate.db").exists())
    val config=JSONObject(File(first.filesDir,"config.json").readText())
    check(config.getString("preserved")=="bundled default")
    check(config.getBoolean("cdn_cache"))
    val count=backend.applyCount
    val opens=first.assets.opens
    val languageWrites=Lang.writes
    first.packageManager.info.versionName="apk-code-only"
    first.packageManager.info.versionCode=99
    File(first.filesDir,"assets/db/gl/masterdata.db").appendText("+OWNER_MOD")
    first.getSharedPreferences("elichika",Context.MODE_PRIVATE).edit().putString("gamedata_locales","ko").apply()
    phases.clear()
    AssetInstaller.install(first,observePhase) {}
    check(backend.applyCount==count && first.assets.opens==opens+1) { "Same data revision needlessly copied the payload" }
    check(first.assets.openedPaths.last()=="payload_revision.json")
    check(File(first.filesDir,"assets/db/gl/masterdata.db").readText().endsWith("+OWNER_MOD"))
    check(Lang.writes==languageWrites+1 && JSONObject(File(first.filesDir,"config.json").readText()).getString("locales")=="ko")
    check(!File(first.filesDir,".payload-incoming").exists())
    check(AssetInstaller.PreparationPhase.UPDATING_GAME_DATA !in phases && phases.last()==AssetInstaller.PreparationPhase.IDLE)
    File(first.filesDir,"assets/db/gl/asset_a_ko.db").delete()
    AssetInstaller.install(first) {}
    check(backend.applyCount==count+1 && backend.modes.last()=="upgrade")
    check(File(first.filesDir,"assets/db/gl/asset_a_ko.db").isFile)
    val rebase=File(first.filesDir,".payload-upgrade/needs-rebase").apply { parentFile.mkdirs(); writeText("restore") }
    AssetInstaller.install(first) {}
    check(backend.applyCount==count+2 && backend.modes.last()=="upgrade" && !rebase.exists())
    first.assets.files["payload_revision.json"]=first.assets.files.getValue("payload_revision.json").replace(revision,"payload-v1:"+"b".repeat(64))
    AssetInstaller.install(first) {}
    check(backend.applyCount==count+3 && File(first.filesDir,"installed_version").readText()=="payload-v1:"+"b".repeat(64))
    File(first.filesDir,".payload-upgrade/current.json").delete()
    val beforeRefused=backend.applyCount
    check("MANAGED_PROVENANCE_MISSING" in expectFailure { AssetInstaller.install(first) {} })
    check(backend.applyCount==beforeRefused)
    AssetInstaller.resetServerData(first) {}
    check(backend.modes.last()=="reset")

    val upgrade=context(temporary,"upgrade")
    File(upgrade.filesDir,"assets/db/gl").mkdirs()
    File(upgrade.filesDir,"assets/db/gl/masterdata.db").writeText("MOD_DB")
    File(upgrade.filesDir,"assets/mod-extra").writeText("KEEP_EXTRA")
    File(upgrade.filesDir,"userdata.db").writeText("KEEP_USER")
    File(upgrade.filesDir,"serverstate.db").writeText("KEEP_STATE")
    File(upgrade.filesDir,"config.json").writeText("""{"custom":"KEEP_CONFIG","cdn_cache_dir":"/chosen/cache"}""")
    File(upgrade.filesDir,"installed_version").writeText("old-1")
    backend.beforeApply={ root,payload,mode ->
        if (root==upgrade.filesDir) {
            check(mode=="upgrade")
            check(phases.last()==AssetInstaller.PreparationPhase.UPDATING_GAME_DATA) { "Long merge must expose its active phase" }
            check(File(root,"assets/db/gl/masterdata.db").readText()=="MOD_DB")
            check(File(root,"installed_version").readText()=="old-1")
            check(File(root,"userdata.db").readText()=="KEEP_USER")
            check(File(root,"serverstate.db").readText()=="KEEP_STATE")
            check(!File(payload,"userdata.db").exists() && !File(payload,"config.json").exists() && !File(payload,"serverstate.db").exists())
        }
    }
    phases.clear()
    AssetInstaller.install(upgrade,observePhase) {}
    check(phases.last()==AssetInstaller.PreparationPhase.IDLE)
    check(File(upgrade.filesDir,"assets/db/gl/masterdata.db").readText()=="MOD_DB+NEW_DB")
    check(File(upgrade.filesDir,"assets/mod-extra").readText()=="KEEP_EXTRA")
    check(JSONObject(File(upgrade.filesDir,"config.json").readText()).getString("custom")=="KEEP_CONFIG")
    check(JSONObject(File(upgrade.filesDir,"config.json").readText()).getString("cdn_cache_dir")=="/chosen/cache")
    backend.beforeApply={ root,_,mode -> if (root==upgrade.filesDir) { check(mode=="reset"); check(File(root,"assets/mod-extra").exists()) } }
    AssetInstaller.resetServerData(upgrade) {}
    check(backend.modes.last()=="reset" && !File(upgrade.filesDir,"assets/mod-extra").exists())
    check(File(upgrade.filesDir,"userdata.db").readText()=="KEEP_USER")
    check(File(upgrade.filesDir,"serverstate.db").readText()=="KEEP_STATE")
    check(JSONObject(File(upgrade.filesDir,"config.json").readText()).getString("custom")=="KEEP_CONFIG")

    val retry=context(temporary,"retry")
    File(retry.filesDir,"installed_version").writeText("old-1")
    backend.beforeApply={ _,_,_-> }
    backend.refused=true
    phases.clear()
    check("DATABASE_MAINTENANCE_BUSY" in expectFailure { AssetInstaller.install(retry,observePhase) {} })
    check(AssetInstaller.PreparationPhase.UPDATING_GAME_DATA in phases && phases.last()==AssetInstaller.PreparationPhase.FAILED)
    check(File(retry.filesDir,"installed_version").readText()=="old-1")
    val retained=backend.failedStage!!
    check(retained.exists())
    backend.refused=false; backend.recovered=true
    backend.beforeApply={ root,_,_-> if (root==retry.filesDir) check(!retained.exists()) { "Recovered inputs were not cleaned before retry" } }
    phases.clear()
    AssetInstaller.install(retry,observePhase) {}
    check(phases.first()==AssetInstaller.PreparationPhase.PREPARING && phases.last()==AssetInstaller.PreparationPhase.IDLE)
    check(File(retry.filesDir,"installed_version").readText()==revision)

    val busy=context(temporary,"busy-before-preparation")
    File(busy.filesDir,"installed_version").writeText("old-1")
    File(busy.filesDir,"config.json").writeText("""{ "custom" : "KEEP_EXACT_CONFIG" }""")
    val activeInput=File(busy.filesDir,".payload-incoming/another-process/payload/input").apply { parentFile.mkdirs(); writeText("ACTIVE_INPUT") }
    val originalConfig=File(busy.filesDir,"config.json").readText()
    val beforeBusyApply=backend.applyCount
    backend.leaseBusy=true
    check("DATABASE_MAINTENANCE_BUSY" in expectFailure { AssetInstaller.install(busy) {} })
    check(activeInput.readText()=="ACTIVE_INPUT")
    check(File(busy.filesDir,"config.json").readText()==originalConfig)
    check(File(busy.filesDir,"installed_version").readText()=="old-1")
    check(busy.assets.opens==0 && backend.applyCount==beforeBusyApply)
    backend.leaseBusy=false

    val extraction=context(temporary,"extraction")
    File(extraction.filesDir,"installed_version").writeText("old-1")
    extraction.assets.failPath="payload/assets/db/gl/masterdata.db"
    val before=backend.applyCount
    phases.clear()
    try { AssetInstaller.install(extraction,observePhase) {}; error("Expected source failure") } catch (_: java.io.IOException) {}
    check(backend.applyCount==before && File(extraction.filesDir,"installed_version").readText()=="old-1")
    check(AssetInstaller.PreparationPhase.UPDATING_GAME_DATA !in phases && phases.last()==AssetInstaller.PreparationPhase.FAILED)

    for ((name,manifest) in listOf("missing-manifest" to null, "malformed-manifest" to "{", "oversized-manifest" to "x".repeat(4*1024*1024+1))) {
        val invalid=context(temporary,name)
        if (manifest==null) invalid.assets.files.remove("payload_revision.json") else invalid.assets.files["payload_revision.json"]=manifest
        File(invalid.filesDir,"installed_version").writeText("old-1")
        File(invalid.filesDir,"config.json").writeText("""{"keep":"exact"}""")
        val retainedInput=File(invalid.filesDir,".payload-incoming/recovered/payload/keep").apply { parentFile.mkdirs(); writeText("journal input") }
        backend.failedStage=retainedInput.parentFile
        val beforeRecover=backend.recoverCount
        val beforeApply=backend.applyCount
        expectFailure { AssetInstaller.install(invalid) {} }
        check(backend.recoverCount==beforeRecover+1 && !retainedInput.exists())
        check(backend.applyCount==beforeApply && File(invalid.filesDir,"config.json").readText()=="""{"keep":"exact"}""")
        check(File(invalid.filesDir,"installed_version").readText()=="old-1")
        backend.failedStage=null
    }

    val missingModule=context(temporary,"missing-module")
    File(missingModule.filesDir,"installed_version").writeText("old-1")
    Hooks.invoke={ _,_,_-> throw IllegalStateException("private-row-sentinel") }
    val message=expectFailure { AssetInstaller.install(missingModule) {} }
    check("private-row-sentinel" !in message)
    check(File(missingModule.filesDir,"installed_version").readText()=="old-1")
    Hooks.invoke=backend::call

    val links=context(temporary,"links")
    val external=File(temporary,"outside").apply { mkdirs() }
    File(external,"keep").writeText("KEEP")
    val incoming=File(links.filesDir,".payload-incoming").apply { mkdirs() }
    Files.createSymbolicLink(File(incoming,"link").toPath(),external.toPath())
    PayloadFiles.clearStages(links.filesDir)
    check(File(external,"keep").readText()=="KEEP")
    Files.createSymbolicLink(incoming.toPath(),external.toPath())
    expectFailure { PayloadFiles.clearStages(links.filesDir) }
    check(File(external,"keep").exists())
    Files.delete(incoming.toPath())

    check(backend.launchCount==0 && backend.heldRoot==null) { "Preparation started tools or leaked its lease" }
    checkCostumeStartup(temporary,backend)
    check(PyServers.ensureStarted(first,first.filesDir))
    check(backend.launchCount==1 && Python.starts.get()==1)
    checkController(temporary)
    println("KOTLIN_UPGRADE_HOST_CHECKS_PASS: fresh/reset, mod-state isolation, missing-file repair, APK-only no-op, data revision change, rebase, missing provenance, manifest admission and recovery ordering, settings on skip, whole preparation lease, busy leaves inputs/config untouched, refusal/recovery, source/module failure, no-follow cleanup, shared Python init, costume startup refusal before recovery/reset/native CLI, known-only cold recovery HTTP tools")
}

private fun checkCostumeStartup(parent: File, backend: Backend) {
    val ctx=context(parent,"costume-recovery")
    val input=File(ctx.filesDir,".payload-incoming/pending/payload/keep").apply { parentFile.mkdirs(); writeText("PRESERVE") }
    val config=File(ctx.filesDir,"config.json").apply { writeText("""{"keep":"EXACT"}""") }
    val userdata=File(ctx.filesDir,"userdata.db").apply { writeText("SYNTHETIC_USER") }
    val native=File(parent,"synthetic-native").apply { mkdirs() }
    val executable=File(native,"libelichika.so").apply {
        writeText("#!/bin/sh\nprintf '%s\\n' \"${'$'}*\" >> native-invocations\n")
        check(setExecutable(true))
    }
    check(executable.isFile)
    ctx.applicationInfo.nativeLibraryDir=native.absolutePath
    val marker=File(ctx.filesDir,"native-invocations")
    val beforeRecover=backend.recoverCount
    val beforeApply=backend.applyCount
    val beforeDecision=backend.decisionCount
    val beforeLanguage=Lang.writes
    val refused="""{"status":"REFUSED","reason":"COSTUME_RECOVERY_REQUIRED"}"""
    val invalidReplies=listOf(refused,"""{"status":"FAILED","reason":"COSTUME_RECOVERY_REQUIRED"}""",
        """{"status":"READY"}""", "private-row-sentinel")
    for (reply in invalidReplies) {
        backend.startupReply=reply
        val checked=backend.startupChecks
        expectFailure { AssetInstaller.install(ctx) {} }
        expectFailure { AssetInstaller.resetServerData(ctx) {} }
        val process=ServerProcess(ctx)
        check(!process.startServer(ctx.filesDir) { error("A refused server must not invoke onExit") })
        for (verb in listOf("reset_accounts","rebuild_assets")) {
            check(!process.runOnce(listOf(verb),ctx.filesDir) { error("A refused CLI must not invoke onExit") })
        }
        check(backend.startupChecks==checked+5 && backend.heldRoot==null)
        check(backend.recoverCount==beforeRecover && backend.applyCount==beforeApply && backend.decisionCount==beforeDecision)
        check(ctx.assets.opens==0 && Lang.writes==beforeLanguage && !marker.exists())
        check(input.readText()=="PRESERVE" && config.readText()=="""{"keep":"EXACT"}""" && userdata.readText()=="SYNTHETIC_USER")
    }
    backend.startupReply="""{"status":"CLEAN"}"""
    for (arguments in listOf(emptyList(),listOf("reset_accounts"))) {
        val exited=CountDownLatch(1)
        val process=ServerProcess(ctx)
        check(process.runOnce(arguments,ctx.filesDir) { code -> check(code==0); exited.countDown() })
        check(exited.await(5,TimeUnit.SECONDS))
    }
    check(marker.readLines()==listOf("","reset_accounts"))
    fun awaitTools() {
        val deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5)
        while (PyServers.isPreparing() && System.nanoTime()<deadline) Thread.sleep(5)
        check(!PyServers.isPreparing())
    }
    for (reply in invalidReplies.drop(1)) {
        backend.startupReply=reply
        PyServers.prepareAsync(ctx); awaitTools()
        check(!PyServers.isStarted() && PyServers.hasPreparationError() && backend.launchCount==0)
    }
    Hooks.invoke={ module,method,arguments ->
        if (module=="costume_management") throw IllegalStateException("private-row-sentinel")
        backend.call(module,method,arguments)
    }
    PyServers.prepareAsync(ctx); awaitTools()
    check(!PyServers.isStarted() && backend.launchCount==0)
    Hooks.invoke=backend::call
    backend.startupReply=refused
    PyServers.prepareAsync(ctx); awaitTools()
    check(PyServers.isStarted() && !PyServers.hasPreparationError() && backend.launchCount==1 && backend.launchRoot==ctx.filesDir)
    check(backend.recoverCount==beforeRecover && input.readText()=="PRESERVE" && backend.heldRoot==null)
    check(Bus.logs.none { "private-row-sentinel" in it })
    backend.startupReply="""{"status":"CLEAN"}"""
}

private fun checkController(parent: File) {
    val context=context(parent,"controller")
    val controller=AndroidServerController(context)
    var databaseGuardHeld=false
    fun service(): ServerService {
        val value=ServerService()
        ServerService.current=value
        Bus.serverRunning=true
        value.resumeHook={ check(!databaseGuardHeld) { "Go restarted before releasing the DB guard" } }
        return value
    }

    val nested=service()
    check(controller.begin_job())
    check(nested.reserveCount==1 && nested.pauseCount==0 && Bus.serverRunning)
    databaseGuardHeld=true
    check(controller.stop() && controller.was_running_before_stop())
    check(controller.stop() && nested.pauseCount==1)
    check(controller.start() && controller.restart_is_pending())
    controller.finish(); controller.finish()
    check(nested.reserved && nested.finishCount==0 && nested.resumeCount==0)
    val other=Executors.newSingleThreadExecutor()
    try {
        check(!other.submit<Boolean> { controller.finish_job(true) }.get())
        check(other.submit<Boolean> { try { controller.stop(); false } catch (_: Exception) { true } }.get())
    } finally { other.shutdownNow() }
    check(nested.reserved)
    databaseGuardHeld=false
    check(controller.finish_job(true))
    check(nested.resumeCount==1 && nested.finishCount==1 && !nested.reserved)

    val cancelled=service()
    check(controller.begin_job() && controller.stop() && controller.start())
    controller.finish()
    ServerService.cancellation++
    check(controller.restart_is_pending())
    check(!controller.finish_job(true) && cancelled.resumeCount==0 && !cancelled.reserved)

    val failed=service()
    check(controller.begin_job() && controller.stop() && controller.start())
    controller.finish()
    check(controller.finish_job(false) && failed.resumeCount==0 && !failed.reserved)

    val nonStopping=service()
    check(controller.begin_job())
    check(controller.finish_job(true))
    check(nonStopping.pauseCount==0 && nonStopping.resumeCount==0 && Bus.serverRunning)

    val legacy=service()
    check(controller.stop() && controller.start())
    controller.finish()
    check(legacy.pauseCount==1 && legacy.resumeCount==1 && legacy.finishCount==1)

    ServerService.current=null
    Bus.serverRunning=false
    val cold=context(parent,"cold-controller")
    cold.beforeServiceStart={ check(!databaseGuardHeld); AssetInstaller.install(cold) {} }
    val coldController=AndroidServerController(cold)
    check(coldController.begin_job())
    databaseGuardHeld=true
    check(ServerService.current!!.reserved)
    databaseGuardHeld=false
    check(coldController.finish_job(true))
    println("KOTLIN_JOB_HOLD_CHECKS_PASS: reserve before DB guard, nested stop/finish, deferred restart, cancellation/failure, other-owner refusal, legacy path")
}
