package com.tagundo.elichika

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URI
import java.net.URL

/** Only this launch's private token can prove Go has bound after database initialization. */
internal object ServerReadiness {
    enum class Result { READY, CANCELLED, TIMED_OUT }
    private val tokenPattern = Regex("[0-9a-f]{32}")

    fun endpoint(address: String): URL? = runCatching {
        if (address.length !in 1..256) return null
        val normalized = if (address.startsWith(":")) "0.0.0.0$address" else address
        val uri = URI("http://$normalized")
        if (uri.rawUserInfo != null || uri.rawQuery != null || uri.rawFragment != null ||
            !uri.rawPath.isNullOrEmpty() || uri.port !in 1..65535) return null
        val host = uri.host?.removePrefix("[")?.removeSuffix("]") ?: return null
        val localHost = when (host.lowercase()) {
            "0.0.0.0", "localhost" -> "127.0.0.1"
            "::" -> "::1"
            else -> host
        }
        URI("http", null, localHost, uri.port, "/_elichika/ready", null, null).toURL()
    }.getOrNull()

    fun endpoints(address: String): List<URL> {
        val first = endpoint(address) ?: return emptyList()
        val host = runCatching { URI("http://$address").host }.getOrNull()
        return if (host.equals("localhost", ignoreCase = true)) {
            listOf(first, URI("http", null, "::1", first.port, "/_elichika/ready", null, null).toURL())
        } else listOf(first)
    }

    fun responds(endpoint: URL, expectedToken: String): Boolean {
        if (!tokenPattern.matches(expectedToken)) return false
        val connection = try {
            (endpoint.openConnection(Proxy.NO_PROXY) as HttpURLConnection).apply {
                requestMethod = "GET"
                instanceFollowRedirects = false
                connectTimeout = 500
                readTimeout = 500
                useCaches = false
            }
        } catch (_: Exception) { return false }
        return try {
            if (connection.responseCode != 200) false else {
                val bytes = connection.inputStream.use { input ->
                    val output = java.io.ByteArrayOutputStream()
                    val buffer = ByteArray(256)
                    val bodyDeadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(1)
                    while (output.size() <= 1024) {
                        if (System.nanoTime() >= bodyDeadline) return false
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                    }
                    output.toByteArray()
                }
                if (bytes.size > 1024) false else {
                    val data = JSONObject(bytes.toString(Charsets.UTF_8))
                    data.opt("ready") == true && data.opt("token") == expectedToken
                }
            }
        } catch (_: Exception) { false }
        finally { connection.disconnect() }
    }

    /** Worker only. Cancellation is checked again after each response and before publication. */
    fun await(endpoint: URL?, token: String, stillOwned: () -> Boolean,
              timeoutMillis: Long = 300_000L): Result {
        return await(listOfNotNull(endpoint), token, stillOwned, timeoutMillis)
    }

    fun await(endpoints: List<URL>, token: String, stillOwned: () -> Boolean,
              timeoutMillis: Long = 300_000L): Result {
        val until = System.nanoTime() + java.util.concurrent.TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
        while (stillOwned()) {
            for (endpoint in endpoints) {
                if (!stillOwned()) return Result.CANCELLED
                if (responds(endpoint, token) && stillOwned()) return Result.READY
            }
            if (System.nanoTime() >= until) return Result.TIMED_OUT
            try { Thread.sleep(250L) } catch (_: InterruptedException) { return Result.CANCELLED }
        }
        return Result.CANCELLED
    }
}
