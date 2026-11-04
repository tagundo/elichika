package com.tagundo.elichika

import java.io.FileInputStream
import java.security.MessageDigest

/** One bridge call per file; works on every supported Android API level. */
object PayloadFileHasher {
    private const val HEX = "0123456789abcdef"

    @JvmStatic
    fun sha256File(path: String): String {
        // Each invocation owns its state, including when Python releases its
        // interpreter lock around concurrent Java calls.
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(path).use { input ->
            val buffer = ByteArray(256 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                if (count > 0) digest.update(buffer, 0, count)
            }
        }
        val bytes = digest.digest()
        val result = CharArray(bytes.size * 2)
        for (index in bytes.indices) {
            val value = bytes[index].toInt() and 0xff
            result[index * 2] = HEX[value ushr 4]
            result[index * 2 + 1] = HEX[value and 0x0f]
        }
        return String(result)
    }
}
