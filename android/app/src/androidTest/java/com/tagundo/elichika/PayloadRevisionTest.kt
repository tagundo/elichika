package com.tagundo.elichika

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayInputStream
import java.io.File
import java.util.UUID

/** Real installer orchestration and Python journals, using only tiny cache fixtures. */
@RunWith(AndroidJUnit4::class)
class PayloadRevisionTest {
    @Test
    fun apkVersionOnlyChangeSkipsBulkWorkButAppliesSettings() = fixture { f ->
        f.prepare("synthetic-apk-1")
        val revision = f.revision()
        val marker = File(f.root, "installed_version")
        assertEquals(revision, marker.readText())
        f.editOwnerRow()
        File(f.root, "assets/owner-extra.txt").writeText("keep mod")
        val transactions = f.transactions()
        val receipt = File(f.root, ".payload-upgrade/current.json").readBytes()
        val baseline = File(f.root, ".payload-upgrade/baseline.sqlite").readBytes()
        val beforeSettings = f.settingsRuns
        f.locale = "ko"
        f.source.opened.clear()
        f.source.listCalls = 0
        f.source.forbidBulk = true
        f.prepare("synthetic-apk-2-code-and-ui-only")
        assertEquals(listOf("payload_revision.json"), f.source.opened)
        assertEquals(0, f.source.listCalls)
        assertEquals(transactions, f.transactions())
        assertTrue(receipt.contentEquals(File(f.root, ".payload-upgrade/current.json").readBytes()))
        assertTrue(baseline.contentEquals(File(f.root, ".payload-upgrade/baseline.sqlite").readBytes()))
        assertEquals(revision, marker.readText())
        assertEquals("owner override", f.ownerRow())
        assertEquals("keep mod", File(f.root, "assets/owner-extra.txt").readText())
        assertEquals(beforeSettings + 1, f.settingsRuns)
        assertEquals("ko", ServerConfig.read(f.root).getString("locales"))
        assertFalse(f.phases.contains(AssetInstaller.PreparationPhase.UPDATING_GAME_DATA))
        assertEquals(AssetInstaller.PreparationPhase.IDLE, f.phases.last())
        assertFalse(File(f.root, ".payload-incoming").exists())
        println("ANDROID_PAYLOAD_REVISION_NOOP_PASS nominal_apk_versions=2 manifest_opens=1 bulk_opens=0 new_transactions=0 settings_applied=true owner_mod_preserved=true")
    }

    @Test
    fun dataChangeLegacyMigrationRebaseEpochAndResetUseJournal() = fixture { f ->
        f.prepare("synthetic-apk-1")
        f.editOwnerRow()
        f.python("legacy", f.root.absolutePath)
        val legacyTransactions = f.transactions().size
        f.prepare("synthetic-apk-2")
        assertEquals(legacyTransactions + 1, f.transactions().size)
        assertEquals(f.revision(), File(f.root, "installed_version").readText())
        val noOpTransactions = f.transactions()
        f.prepare("synthetic-apk-3")
        assertEquals(noOpTransactions, f.transactions())
        val previousRevision = f.revision()
        f.source.files["payload/webui/index.html"] = "changed official fixture UI".toByteArray()
        f.refreshManifest()
        assertTrue(f.revision() != previousRevision)
        f.prepare("synthetic-apk-3")
        assertEquals(noOpTransactions.size + 1, f.transactions().size)
        assertEquals("owner override", f.ownerRow())
        val rebase = File(f.root, ".payload-upgrade/needs-rebase").apply { writeText("synthetic restore") }
        val beforeRebase = f.transactions().size
        f.prepare("synthetic-apk-3")
        assertEquals(beforeRebase + 1, f.transactions().size)
        assertFalse(rebase.exists())
        val beforeEpoch = f.transactions().size
        f.refreshManifest("instrumentation-compatible-epoch-2")
        f.prepare("synthetic-apk-3")
        assertEquals(beforeEpoch + 1, f.transactions().size)
        File(f.root, "assets/owner-extra.txt").writeText("remove only on reset")
        f.prepare("synthetic-apk-3", reset = true)
        assertFalse(File(f.root, "assets/owner-extra.txt").exists())
        assertEquals("synthetic master", f.ownerRow())
        assertEquals(f.revision(), File(f.root, "installed_version").readText())
        println("ANDROID_PAYLOAD_REVISION_FULL_PATH_PASS legacy_once=true changed_data=true epoch=true rebase=true reset=true")
    }

    @Test
    fun incompleteProvenanceRefusesPreparationWithoutChangingOwnerData() = fixture { f ->
        f.prepare("synthetic-apk-1")
        f.editOwnerRow()
        val marker = File(f.root, "installed_version").readText()
        val descriptor = File(f.root, ".payload-upgrade/current.json")
        val receipt = descriptor.readText()
        val transactions = f.transactions()
        val settings = f.settingsRuns
        for (malformed in listOf(false, true)) {
            if (malformed) descriptor.writeText("{private-row-sentinel") else descriptor.delete()
            f.source.opened.clear()
            val message = failure { f.prepare("synthetic-apk-2") }
            assertFalse(message.contains("private-row-sentinel"))
            assertEquals(marker, File(f.root, "installed_version").readText())
            assertEquals("owner override", f.ownerRow())
            assertEquals(transactions, f.transactions())
            assertEquals(settings, f.settingsRuns)
            assertEquals(listOf("payload_revision.json"), f.source.opened)
            assertEquals(AssetInstaller.PreparationPhase.FAILED, f.phases.last())
            descriptor.writeText(receipt)
        }
        descriptor.delete()
        f.prepare("synthetic-apk-2", reset = true)
        assertEquals("synthetic master", f.ownerRow())
        println("ANDROID_PAYLOAD_REVISION_PROVENANCE_PASS missing_and_malformed_refused=true settings_untouched=true explicit_reset=true")
    }

    @Test
    fun journalRecoveryPrecedesMissingAndMalformedManifestFailure() = fixture { f ->
        f.prepare("synthetic-apk-1")
        f.editOwnerRow()
        val revision = f.revision()
        val manifest = f.source.files.getValue("payload_revision.json")
        for (missing in listOf(true, false)) {
            PayloadUpgrade.withMaintenance(f.context, f.root) {
                val stage = PayloadFiles.stage(f.root, f.source, PayloadFiles.managedFiles(f.source))
                f.python("interrupt", f.root.absolutePath, stage.absolutePath, String(manifest))
            }
            assertTrue(File(f.root, ".payload-upgrade/journal.json").isFile)
            val journal = File(f.root, ".payload-upgrade/journal.json")
            val journalBytes = journal.readBytes()
            val pending = File(f.root, ".costume-management/receipts/unknown.json").apply {
                parentFile.mkdirs(); writeText("""{"state":"prepared"}""")
            }
            val pendingBytes = pending.readBytes()
            val beforeSettings = f.settingsRuns
            val beforeOpens = f.source.opened.toList()
            for (reset in listOf(false, true)) {
                assertTrue(failure { f.prepare("synthetic-apk-costume-pending", reset) }.contains("COSTUME_RECOVERY_REQUIRED"))
                assertTrue(journalBytes.contentEquals(journal.readBytes()))
                assertTrue(pendingBytes.contentEquals(pending.readBytes()))
                assertTrue(File(f.root, ".payload-incoming").exists())
                assertEquals(beforeSettings, f.settingsRuns)
                assertEquals(beforeOpens, f.source.opened)
            }
            val native = ServerProcess(f.context)
            try {
                assertFalse(native.startServer(f.root) {})
                assertFalse(native.runOnce(listOf("reset_accounts"), f.root) {})
                assertFalse(native.runOnce(listOf("rebuild_assets"), f.root) {})
            } finally { ServerProcess.awaitStopped(native.stop()) }
            assertTrue(journalBytes.contentEquals(journal.readBytes()))
            assertTrue(pendingBytes.contentEquals(pending.readBytes()))
            // Only this disposable malformed test input is removed. Production
            // startup never clears an uncertain costume or deletion receipt.
            assertTrue(pending.delete())
            if (missing) f.source.files.remove("payload_revision.json")
            else f.source.files["payload_revision.json"] = "{".toByteArray()
            val settings = f.settingsRuns
            failure { f.prepare("synthetic-apk-invalid") }
            assertFalse(File(f.root, ".payload-upgrade/journal.json").exists())
            assertFalse(File(f.root, ".payload-incoming").exists())
            assertEquals(revision, File(f.root, "installed_version").readText())
            assertEquals("owner override", f.ownerRow())
            assertEquals(settings, f.settingsRuns)
            f.source.files["payload_revision.json"] = manifest
        }
        f.prepare("synthetic-apk-recovered")
        assertEquals(revision, File(f.root, "installed_version").readText())
        println("ANDROID_PAYLOAD_REVISION_RECOVERY_PASS recovery_before_manifest=true missing_refused=true malformed_refused=true owner_mod_preserved=true pending_costume_blocks_prep_reset_and_native_cli=true")
    }

    private class Source(val files: MutableMap<String, ByteArray>) : PayloadFiles.Source {
        val opened = mutableListOf<String>()
        var listCalls = 0
        var forbidBulk = false
        override fun list(path: String): Array<String> {
            listCalls++
            check(!forbidBulk) { "A data-revision no-op enumerated the APK payload" }
            return files.keys.filter { it.startsWith("$path/") }
                .map { it.removePrefix("$path/").substringBefore('/') }.distinct().toTypedArray()
        }
        override fun open(path: String): ByteArrayInputStream {
            check(!forbidBulk || path == "payload_revision.json") { "A data-revision no-op opened bulk payload bytes" }
            opened.add(path)
            return ByteArrayInputStream(files[path] ?: throw java.io.FileNotFoundException())
        }
    }

    private class Fixture(val context: Context, val directory: File, val source: Source) {
        val root = File(directory, "runtime").apply { mkdir() }
        private val stock = File(directory, "source").apply { mkdir() }
        val phases = mutableListOf<AssetInstaller.PreparationPhase>()
        var settingsRuns = 0
        var locale = "en"
        private val python = EmbeddedPython.instance(context)
        private val helpers = python.getModule("types").callAttr("ModuleType", "_payload_revision_fixture_${UUID.randomUUID().toString().replace('-', '_')}")
        init {
            python.getModule("builtins").callAttr("exec", """
                import json
                import sqlite3
                from pathlib import Path
                import payload_db_upgrade as upgrade

                def legacy(path):
                    root = Path(path)
                    version = '2026.11.04.2'
                    (root / 'installed_version').write_text(version)
                    descriptor = root / '.payload-upgrade/current.json'
                    data = json.loads(descriptor.read_text())
                    data['payload_version'] = version
                    descriptor.write_text(json.dumps(data))
                    with sqlite3.connect(root / '.payload-upgrade/baseline.sqlite') as db:
                        db.execute("UPDATE meta SET value=? WHERE key='payload_version'", (version,))

                def interrupt(path, stage, manifest_json):
                    # Android may expose /data/user/0 while the engine resolves
                    # the same private directory through /data/data.
                    root = Path(path).resolve(strict=True)
                    before = (root / 'installed_version').read_text()
                    prepared = upgrade.prepare_upgrade(path, stage, before, 'payload-v1:' + 'f' * 64,
                        expected_files=json.loads(manifest_json)['files'])
                    assert prepared['status'] == 'PREPARED'
                    replace = upgrade._replace
                    injected = False
                    class PowerLoss(BaseException):
                        pass
                    def lose_power(source, destination):
                        nonlocal injected
                        if Path(destination) == root / 'installed_version' and Path(source).parent.name == 'next':
                            injected = True
                            raise PowerLoss()
                        return replace(source, destination)
                    upgrade._replace = lose_power
                    try:
                        try:
                            upgrade.commit_upgrade(path, prepared['transaction_id'])
                        except PowerLoss:
                            pass
                        else:
                            raise AssertionError('Expected a pending real journal')
                    finally:
                        upgrade._replace = replace
                    assert injected, 'The marker power-loss hook did not run'
                    assert (root / '.payload-upgrade/journal.json').is_file()
            """.trimIndent(), helpers.get("__dict__"))
            refreshManifest()
        }
        fun python(method: String, vararg args: Any) { helpers.callAttr(method, *args) }
        fun refreshManifest(epoch: String? = null) {
            for ((name, bytes) in source.files) if (name.startsWith("payload/")) {
                File(stock, name.removePrefix("payload/")).apply { parentFile?.mkdirs(); writeBytes(bytes) }
            }
            val module = python.getModule("payload_revision")
            val json = if (epoch == null) module.callAttr("build_manifest_json", stock.absolutePath).toString()
                else module.callAttr("build_manifest_json", stock.absolutePath, epoch).toString()
            source.files["payload_revision.json"] = json.toByteArray()
        }
        fun revision() = JSONObject(String(source.files.getValue("payload_revision.json"))).getString("revision")
        fun transactions(): Set<String> = File(root, ".payload-upgrade/transactions").list()?.toSet().orEmpty()
        fun prepare(apkVersion: String, reset: Boolean = false) {
            phases.clear()
            PayloadPreparation.prepare(context, root, source, apkVersion, reset, { phases.add(it) }, {}) {
                settingsRuns++
                ServerConfig.update(root) { it.put("locales", locale).put("settings_runs", settingsRuns) }
            }
        }
        fun editOwnerRow() {
            SQLiteDatabase.openDatabase(File(root, "assets/db/gl/masterdata.db").absolutePath, null,
                SQLiteDatabase.OPEN_READWRITE).use { db -> db.execSQL("UPDATE fixture_catalog SET value='owner override' WHERE id=1") }
        }
        fun ownerRow(): String = SQLiteDatabase.openDatabase(File(root, "assets/db/gl/masterdata.db").absolutePath, null,
            SQLiteDatabase.OPEN_READONLY).use { db -> db.rawQuery("SELECT value FROM fixture_catalog WHERE id=1", null).use {
                check(it.moveToFirst()); it.getString(0)
            } }
    }

    private fun fixture(action: (Fixture) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val directory = File(context.cacheDir, "payload-revision-test-${UUID.randomUUID()}").apply { check(mkdir()) }
        try {
            val files = mutableMapOf<String, ByteArray>()
            val assets = instrumentation.context.assets
            fun read(path: String) {
                val children = assets.list(path).orEmpty()
                if (children.isEmpty()) files[path] = assets.open(path).use { it.readBytes() }
                else children.forEach { read("$path/$it") }
            }
            read("payload")
            action(Fixture(context, directory, Source(files)))
        } finally {
            directory.deleteRecursively()
        }
    }

    private fun failure(action: () -> Unit): String {
        try { action() } catch (error: IllegalStateException) { return error.message.orEmpty() }
        throw AssertionError("Expected preparation to refuse invalid metadata")
    }
}
