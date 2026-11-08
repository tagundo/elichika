package com.tagundo.elichika

import android.content.Context
import java.io.File

/** The same bounded preparation path serves the installer and disposable QA roots. */
internal object PayloadPreparation {
    fun prepare(context: Context, root: File, source: PayloadFiles.Source, apkVersion: String,
                reset: Boolean, onPhase: (AssetInstaller.PreparationPhase) -> Unit,
                log: (String) -> Unit, onProgress: (PayloadProgress.State?) -> Unit = {},
                settings: () -> Unit): File {
        fun report(phase: AssetInstaller.PreparationPhase) { runCatching { onPhase(phase) } }
        fun progress(value: PayloadProgress.State?) { runCatching { onProgress(value) } }
        var completed = false
        progress(null)
        report(AssetInstaller.PreparationPhase.PREPARING)
        try {
            val result = PayloadUpgrade.withMaintenance(context, root) {
                // A costume transaction may have partially changed game data.
                // Preserve its recovery inputs before any payload recovery or reset.
                PayloadUpgrade.checkCostumeStartup(context, root)
                // Pending journal inputs must survive until recovery completes,
                // even when this APK's mandatory manifest is missing or malformed.
                PayloadUpgrade.recover(context, root, log)
                PayloadFiles.clearStages(root)
                val manifest = PayloadFiles.revisionManifest(source)
                val decision = PayloadUpgrade.decide(context, root, manifest, reset)
                // APK identity is informational; only the admitted data revision
                // can trigger staging, backups, a merge or the completion marker.
                log(context.getString(R.string.log_setup_preparing, apkVersion, decision.requiresUpdate.toString()))
                val staged = if (decision.requiresUpdate) {
                    val files = PayloadFiles.managedFiles(source)
                    check(files.isNotEmpty()) { "Game-data update refused (PAYLOAD_FILES_MISSING)" }
                    PayloadFiles.stage(root, source, files)
                } else null
                var enteredUpdater = false
                var committed = false
                try {
                    settings()
                    if (staged != null) {
                        report(AssetInstaller.PreparationPhase.UPDATING_GAME_DATA)
                        if (decision.action == "upgrade") log(context.getString(R.string.log_setup_preserving_mods))
                        var loggedStage = ""
                        var loggedDatabase = ""
                        var loggedBucket = -1
                        enteredUpdater = true
                        try {
                            PayloadUpgrade.apply(context, root, staged, decision.fromVersion,
                                decision.revision, decision.action, manifest) { value ->
                                progress(value)
                                val bucket = value.percent / 10
                                if (value.stage != loggedStage || value.current != loggedDatabase || bucket != loggedBucket) {
                                    loggedStage = value.stage
                                    loggedDatabase = value.current
                                    loggedBucket = bucket
                                    val database = if (value.current.isEmpty()) "" else " · ${value.current}"
                                    // These are bounded work counters, never an estimated duration.
                                    runCatching { log(context.getString(R.string.log_setup_data_progress,
                                        value.percent, PayloadProgress.stageLabel(context, value.stage),
                                        value.completed, value.total, database)) }
                                }
                            }
                        } finally {
                            report(AssetInstaller.PreparationPhase.PREPARING)
                        }
                        committed = true
                    }
                    log(context.getString(R.string.log_setup_ready))
                    root
                } finally {
                    if (staged != null && (!enteredUpdater || committed)) PayloadFiles.removeStage(staged)
                }
            }
            completed = true
            return result
        } finally {
            progress(null)
            report(if (completed) AssetInstaller.PreparationPhase.IDLE else AssetInstaller.PreparationPhase.FAILED)
        }
    }
}
