package com.tagundo.elichika

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID

/** Exact digests and backend routing through the installed Chaquopy bridge. */
@RunWith(AndroidJUnit4::class)
class PayloadFileHasherTest {
    @Test
    fun vectorsBoundaryRoutingAndConcurrentFilesMatchPython() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val directory = File(context.cacheDir, "payload-hash-test-${UUID.randomUUID()}")
        check(directory.mkdir())
        try {
            val empty = File(directory, "empty.bin").apply { writeBytes(byteArrayOf()) }
            val abc = File(directory, "한글-abc.bin").apply { writeText("abc", Charsets.UTF_8) }
            assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                PayloadFileHasher.sha256File(empty.absolutePath))
            assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                PayloadFileHasher.sha256File(abc.absolutePath))
            for (size in listOf(1048575, 1048576, 1048577, 2097169)) {
                val bytes = ByteArray(4096) { (it and 0xff).toByte() }
                File(directory, "pattern-$size.bin").outputStream().use { output ->
                    var remaining = size
                    while (remaining > 0) {
                        val count = minOf(remaining, bytes.size)
                        output.write(bytes, 0, count)
                        remaining -= count
                    }
                }
            }
            val python = EmbeddedPython.instance(context)
            val module = python.getModule("types").callAttr("ModuleType", "_payload_hash_test")
            val script = """
                import concurrent.futures
                import hashlib
                import json
                from pathlib import Path
                import payload_file_hash as hashes

                def verify(directory):
                    assert hashes.ANDROID_MIN_BYTES == 1048576
                    assert hashes.android_backend_available(), 'Android helper must resolve'
                    original = hashes._resolve_android_hasher()
                    root = Path(directory)
                    paths = sorted(root.iterdir())
                    expected = {}
                    for path in paths:
                        with path.open('rb') as stream:
                            expected[path] = hashlib.file_digest(stream, 'sha256').hexdigest()
                    large = [path for path in paths if path.stat().st_size >= hashes.ANDROID_MIN_BYTES]
                    calls = []
                    def counted(path):
                        calls.append(path)
                        return original(path)
                    hashes._android_hasher = counted
                    try:
                        for path in paths:
                            assert hashes.sha256(path) == expected[path]
                        assert len(calls) == len(large), 'Only large files use the Android backend'
                        threaded = large * 4
                        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as workers:
                            actual = list(workers.map(hashes.sha256, threaded))
                        assert actual == [expected[path] for path in threaded]
                        assert len(calls) == len(large) + len(threaded)
                        try:
                            original(str(root / 'missing.bin'))
                        except Exception:
                            missing_failed = True
                        else:
                            raise AssertionError('Android file errors must propagate')
                        assert original(str(large[0])) == expected[large[0]], 'Hash state must survive another call failing'
                        return json.dumps({'vectors': len(paths), 'large_backend_calls': len(calls),
                            'threaded_checks': len(threaded), 'android_backend_available': True,
                            'missing_file_failed': missing_failed, 'after_failure_digest_matches': True})
                    finally:
                        hashes._android_hasher = original
            """.trimIndent()
            python.getModule("builtins").callAttr("exec", script, module.get("__dict__"))
            val report = JSONObject(module.callAttr("verify", directory.absolutePath).toString())
            assertEquals(6, report.getInt("vectors"))
            assertEquals(15, report.getInt("large_backend_calls"))
            assertEquals(12, report.getInt("threaded_checks"))
            assertTrue(report.getBoolean("android_backend_available"))
            assertTrue(report.getBoolean("missing_file_failed"))
            assertTrue(report.getBoolean("after_failure_digest_matches"))
            println("ANDROID_PAYLOAD_FILE_HASH_REPORT=$report")
        } finally {
            directory.deleteRecursively()
        }
    }
}
