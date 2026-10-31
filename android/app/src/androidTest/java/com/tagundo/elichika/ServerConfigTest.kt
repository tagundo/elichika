package com.tagundo.elichika

import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.content.res.AssetManager
import android.os.Handler
import android.os.Looper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.nio.file.Files
import java.util.Comparator
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class ServerConfigTest {
    @Test
    fun choiceBeforeConfigExistsSurvivesPreparationWithoutWaitingForPayloadLock() = withConfig { context ->
        val locked = CountDownLatch(1)
        val release = CountDownLatch(1)
        val saved = CountDownLatch(1)
        val executor = Executors.newSingleThreadExecutor()
        try {
            executor.submit {
                synchronized(AssetInstaller) {
                    locked.countDown()
                    release.await(10, TimeUnit.SECONDS)
                }
            }
            assertTrue(locked.await(5, TimeUnit.SECONDS))
            Handler(Looper.getMainLooper()).post {
                ServerConfig.setGameDataLocales(context, "ko")
                Lang.setPref(context, "ja")
                Lang.writeWebuiLanguage(context, context.filesDir)
                saved.countDown()
            }
            assertTrue("Saving settings must not wait for payload extraction", saved.await(2, TimeUnit.SECONDS))
            assertFalse(File(context.filesDir, "config.json").exists())
        } finally {
            release.countDown()
            executor.shutdownNow()
        }
        // The test APK provides a tiny real payload, so this exercises the same
        // preparation/default/locale paths without extracting the game database.
        AssetInstaller.install(context) {}
        val config = JSONObject(File(context.filesDir, "config.json").readText())
        assertEquals("ko", config.getString("locales"))
        assertEquals("ko", ServerConfig.gameDataLocales(context))
        assertEquals("ja", config.getString("webui_language"))
        assertEquals("bundled default", config.getString("preserved"))
        assertTrue(config.getBoolean("cdn_cache"))
        assertTrue(config.getString("cdn_cache_dir").endsWith("/sukusta/packs"))
    }

    @Test
    fun laterServerWebUiLocaleChangeSurvivesPreparation() = withConfig { context ->
        AssetInstaller.install(context) {}
        ServerConfig.setGameDataLocales(context, "ko")
        assertEquals("ko", ServerConfig.gameDataLocales(context))

        // The server WebUI writes config.json independently of native settings.
        val file = File(context.filesDir, "config.json")
        val external = JSONObject(file.readText()).put("locales", "en")
        file.writeText(external.toString())
        assertEquals("en", ServerConfig.gameDataLocales(context))

        AssetInstaller.install(context) {}
        assertEquals("en", ServerConfig.gameDataLocales(context))
        assertEquals("en", JSONObject(file.readText()).getString("locales"))
        assertEquals("bundled default", JSONObject(file.readText()).getString("preserved"))
    }

    @Test
    fun concurrentSetupAndSettingsPreserveFieldsAndPublishCompleteJson() = withConfig { context ->
        AssetInstaller.install(context) {}
        val start = CountDownLatch(1)
        val executor = Executors.newFixedThreadPool(3)
        try {
            val locale = executor.submit {
                start.await()
                repeat(20) { ServerConfig.setGameDataLocales(context, if (it % 2 == 0) "ja" else "ko") }
            }
            val language = executor.submit {
                start.await()
                repeat(20) {
                    Lang.setPref(context, if (it % 2 == 0) "ko" else "en")
                    Lang.writeWebuiLanguage(context, context.filesDir)
                }
            }
            val setup = executor.submit {
                start.await()
                repeat(20) { AssetInstaller.install(context) {} }
            }
            val futures = listOf(locale, language, setup)
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120)
            start.countDown()
            // Read directly, like the Go server, rather than taking the helper's
            // lock. A reader must only ever see a complete JSON document.
            do {
                val current = JSONObject(File(context.filesDir, "config.json").readText())
                assertEquals("bundled default", current.getString("preserved"))
                assertTrue(current.getBoolean("cdn_cache"))
                assertTrue(System.nanoTime() < deadline)
                Thread.sleep(1)
            } while (futures.any { !it.isDone })
            futures.forEach { it.get(5, TimeUnit.SECONDS) }
            val final = ServerConfig.read(context.filesDir)
            assertEquals("ko", final.getString("locales"))
            assertEquals("en", final.getString("webui_language"))
            assertEquals("bundled default", final.getString("preserved"))
            assertTrue(final.getString("cdn_cache_dir").endsWith("/sukusta/packs"))
        } finally {
            executor.shutdownNow()
        }
    }

    private fun withConfig(check: (Context) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val target = instrumentation.targetContext
        val directory = File(target.cacheDir, "config-test-${UUID.randomUUID()}").apply { mkdirs() }
        val prefix = directory.name
        val context = object : ContextWrapper(target) {
            override fun getFilesDir(): File = directory
            override fun getAssets(): AssetManager = instrumentation.context.assets
            override fun getSharedPreferences(name: String, mode: Int): SharedPreferences =
                target.getSharedPreferences("$prefix-$name", mode)
        }
        try { check(context) }
        finally {
            context.getSharedPreferences("elichika", Context.MODE_PRIVATE).edit().clear().commit()
            // Preparation creates storage/downloads as a symlink to the real
            // shared folder. Walk without FOLLOW_LINKS when removing fixtures.
            Files.walk(directory.toPath()).use { paths ->
                paths.sorted(Comparator.reverseOrder()).forEach { Files.deleteIfExists(it) }
            }
        }
    }
}
