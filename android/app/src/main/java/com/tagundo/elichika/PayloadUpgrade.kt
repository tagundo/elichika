package com.tagundo.elichika

import android.app.ActivityManager
import android.content.Context
import org.json.JSONObject
import java.io.File

/** Mandatory, synchronous bridge; failures prevent preparation and server launch. */
internal object PayloadUpgrade {
    private val reasonCode = Regex("[a-zA-Z0-9_.:-]{1,100}")
    private val revisionCode = Regex("payload-v1:[0-9a-f]{64}")

    data class Decision(val action: String, val revision: String, val fromVersion: String) {
        val requiresUpdate: Boolean get() = action != "skip"
    }

    class CostumeRecoveryRequired : IllegalStateException("Game-data update refused (COSTUME_RECOVERY_REQUIRED)")

    fun <T> withMaintenance(context: Context, root: File, action: () -> T): T {
        val lease = invoke(context, "database_maintenance", "begin_maintenance_json", root.absolutePath)
        requireStatus(lease, setOf("ACQUIRED"))
        val token = lease.getString("token")
        try {
            return action()
        } finally {
            // Keep the entire preparation on this worker. The engine's nested
            // guard uses the same native thread owner across Chaquopy calls.
            requireStatus(invoke(context, "database_maintenance", "end_maintenance_json",
                root.absolutePath, token), setOf("RELEASED"))
        }
    }

    fun checkCostumeStartup(context: Context, root: File) {
        val result = invoke(context, "costume_management", "startup_check_json", root.absolutePath)
        if (result.optString("status") == "REFUSED" && result.optString("reason") == "COSTUME_RECOVERY_REQUIRED") {
            throw CostumeRecoveryRequired()
        }
        requireStatus(result, setOf("CLEAN"))
    }

    fun recover(context: Context, root: File, log: (String) -> Unit) {
        val result = invoke(context, "payload_db_upgrade", "recover_upgrade_json", root.absolutePath)
        requireStatus(result, setOf("CLEAN", "ROLLED_BACK", "COMMITTED"))
        if (result.getString("status") != "CLEAN") {
            log(context.getString(R.string.log_setup_upgrade_recovered))
        }
    }

    fun decide(context: Context, root: File, manifest: String, reset: Boolean): Decision {
        val result = invoke(context, "payload_revision", "decide_json", root.absolutePath, manifest, reset)
        requireStatus(result, setOf("READY"))
        val action = result.optString("action")
        val revision = result.optString("revision")
        check(action in setOf("skip", "upgrade", "fresh", "reset") && revisionCode.matches(revision)) {
            "Game-data update refused (INVALID_REVISION_DECISION)"
        }
        return Decision(action, revision, result.getString("from_version"))
    }

    fun apply(context: Context, root: File, payload: File, from: String?, to: String,
              mode: String, manifest: String, progress: (PayloadProgress.State) -> Unit = {}) {
        val session = PayloadProgress.Session(progress)
        try {
            val result = invoke(context, "elichika_launch", "apply_payload_with_progress", root.absolutePath,
                payload.absolutePath, from.orEmpty(), to, mode, manifest, PayloadProgressObserver(session),
                availableMemory(context))
            requireStatus(result, setOf("COMMITTED"))
            check(File(root, "installed_version").readText().trim() == to) {
                "Game-data update did not publish its completion marker"
            }
            session.committed()
        } finally {
            session.close()
        }
    }

    /** Read on the preparation worker for this invocation, never cache a stale budget. */
    private fun availableMemory(context: Context): Long = runCatching {
        val manager = context.getSystemService(ActivityManager::class.java)
        val info = ActivityManager.MemoryInfo()
        manager.getMemoryInfo(info)
        info.availMem.takeIf { it > 0L } ?: 0L
    }.getOrDefault(0L)

    private fun invoke(context: Context, module: String, method: String, vararg arguments: Any): JSONObject = try {
        val result = EmbeddedPython.instance(context).getModule(module)
            .callAttr(method, *arguments).toString()
        JSONObject(result)
    } catch (_: Throwable) {
        // Python must return fixed reason codes. Do not surface SQLite rows,
        // configuration values, or exception arguments in the console.
        throw IllegalStateException("Game-data updater could not complete; recovery is required before startup")
    }

    private fun requireStatus(result: JSONObject, allowed: Set<String>) {
        val status = result.optString("status")
        if (status !in allowed) {
            val reason = result.optString("reason").takeIf { reasonCode.matches(it) } ?: "update_failed"
            throw IllegalStateException("Game-data update refused ($reason)")
        }
    }
}
