package com.tagundo.elichika

import android.content.Context
import java.io.File

/**
 * Unpacks the bundled server payload (the assets/payload tree, assembled by CI) into
 * the app's files dir, which is also the elichika server's working directory.
 *
 * Overwrite policy:
 *  - static server files (webui/, "server init jsons/", *.pem) are refreshed on
 *    every app upgrade so server changes ride along with a new APK;
 *  - user/state files (config.json, serverdata.db, userdata.db) are only created
 *    when missing, so progress and settings survive an upgrade.
 *
 * A version marker keyed to the APK's versionCode decides when to refresh the
 * static set.
 */
object AssetInstaller {

    private const val PAYLOAD = "payload"
    private const val MARKER = "installed_version"

    // Refresh-on-upgrade (server-owned master data / static assets, safe to overwrite
    // so a new APK ships updated game data). serverdata.db + the harasho assets/ tree +
    // the rekeyed static/ output are all regenerated from the build, not user state.
    private val ALWAYS = listOf(
        "webui", "server init jsons", "privatekey.pem", "publickey.pem",
        "assets", "static", "serverdata.db"
    )
    // Create-if-missing (user-owned, preserve across upgrades).
    private val PRESERVE = listOf("config.json", "userdata.db")

    /** Returns the server working dir (== app files dir). */
    fun install(ctx: Context, log: (String) -> Unit): File {
        val root = ctx.filesDir
        val am = ctx.assets
        val payloadExists = runCatching { am.list(PAYLOAD)?.isNotEmpty() == true }.getOrDefault(false)
        if (!payloadExists) {
            log("[setup] 번들 페이로드가 없습니다 (CI 빌드가 아님). 서버 파일 추출을 건너뜁니다.")
            return root
        }

        val installedVersion = File(root, MARKER).takeIf { it.exists() }?.readText()?.trim()
        val currentVersion = appVersion(ctx)
        val refreshStatic = installedVersion != currentVersion

        log("[setup] 서버 파일 준비 중… (버전 $currentVersion, 정적자산 갱신=$refreshStatic)")
        copyDir(ctx, PAYLOAD, root, refreshStatic, log)

        File(root, MARKER).writeText(currentVersion)
        log("[setup] 준비 완료.")
        return root
    }

    private fun appVersion(ctx: Context): String =
        runCatching {
            val pi = ctx.packageManager.getPackageInfo(ctx.packageName, 0)
            @Suppress("DEPRECATION")
            "${pi.versionName}-${pi.versionCode}"
        }.getOrDefault("unknown")

    private fun copyDir(ctx: Context, assetPath: String, destRoot: File, refreshStatic: Boolean, log: (String) -> Unit) {
        val am = ctx.assets
        val entries = am.list(assetPath) ?: return
        for (name in entries) {
            val childAsset = "$assetPath/$name"
            val children = am.list(childAsset)
            // Path relative to the payload root, used for the overwrite-policy check.
            val rel = childAsset.removePrefix("$PAYLOAD/")
            if (children != null && children.isNotEmpty()) {
                copyDir(ctx, childAsset, destRoot, refreshStatic, log)
            } else {
                val dest = File(destRoot, rel)
                if (shouldWrite(rel, dest, refreshStatic)) {
                    dest.parentFile?.mkdirs()
                    am.open(childAsset).use { input ->
                        dest.outputStream().use { input.copyTo(it) }
                    }
                }
            }
        }
    }

    private fun shouldWrite(rel: String, dest: File, refreshStatic: Boolean): Boolean {
        val top = rel.substringBefore('/')
        return when {
            PRESERVE.contains(top) || PRESERVE.contains(rel) -> !dest.exists()
            ALWAYS.contains(top) || ALWAYS.contains(rel) -> refreshStatic || !dest.exists()
            else -> !dest.exists()
        }
    }
}
