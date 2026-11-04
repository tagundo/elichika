package com.tagundo.elichika

import android.content.Context
import org.json.JSONObject
import java.io.File

/** Mandatory, synchronous bridge; failures prevent preparation and server launch. */
internal object PayloadUpgrade {
    private val reasonCode = Regex("[a-zA-Z0-9_.:-]{1,100}")

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

    fun recover(context: Context, root: File, log: (String) -> Unit) {
        val result = invoke(context, "payload_db_upgrade", "recover_upgrade_json", root.absolutePath)
        requireStatus(result, setOf("CLEAN", "ROLLED_BACK", "COMMITTED"))
        if (result.getString("status") != "CLEAN") {
            log(context.getString(R.string.log_setup_upgrade_recovered))
        }
    }

    fun apply(context: Context, root: File, payload: File, from: String?, to: String, mode: String) {
        val result = invoke(context, "payload_db_upgrade", "apply_upgrade_json", root.absolutePath,
            payload.absolutePath, from.orEmpty(), to, mode)
        requireStatus(result, setOf("COMMITTED"))
        check(File(root, "installed_version").readText().trim() == to) {
            "Game-data update did not publish its completion marker"
        }
    }

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
