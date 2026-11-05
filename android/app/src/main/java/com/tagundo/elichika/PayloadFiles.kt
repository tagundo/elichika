package com.tagundo.elichika

import java.io.File
import java.io.InputStream
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.file.Files
import java.nio.file.LinkOption
import java.util.Comparator
import java.util.UUID

/** APK reads and private staging only: publishing belongs to the upgrade journal. */
internal object PayloadFiles {
    private const val INCOMING = ".payload-incoming"
    private const val REVISION_MANIFEST = "payload_revision.json"
    private const val MAX_MANIFEST_BYTES = 4 * 1024 * 1024
    private val MANAGED = setOf(
        "webui", "server init jsons", "privatekey.pem", "publickey.pem",
        "assets", "static", "serverdata.db"
    )

    interface Source {
        fun list(path: String): Array<String>
        fun open(path: String): InputStream
    }

    /** The signed manifest is outside payload/ and never copied into live data. */
    fun revisionManifest(source: Source): String = try {
        val bytes = source.open(REVISION_MANIFEST).use { input ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (output.size() <= MAX_MANIFEST_BYTES) {
                val count = input.read(buffer, 0, minOf(buffer.size, MAX_MANIFEST_BYTES + 1 - output.size()))
                if (count < 0) break
                output.write(buffer, 0, count)
            }
            check(output.size() <= MAX_MANIFEST_BYTES)
            output.toByteArray()
        }
        Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
    } catch (_: Exception) {
        throw IllegalStateException("Game-data update refused (PAYLOAD_MANIFEST_MISSING_OR_INVALID)")
    }

    fun managedFiles(source: Source): List<String> {
        val files = mutableListOf<String>()
        fun visit(path: String) {
            val entries = source.list("payload/$path")
            if (entries.isNotEmpty()) {
                for (name in entries) {
                    require(name.isNotEmpty() && name != "." && name != ".." && '/' !in name && '\\' !in name) {
                        "Invalid bundled payload path"
                    }
                    if (name != ".git") visit(if (path.isEmpty()) name else "$path/$name")
                }
            } else if (path.substringBefore('/') in MANAGED) {
                files.add(path)
            }
        }
        for (name in source.list("payload")) {
            if (name in MANAGED) visit(name)
        }
        return files.sorted()
    }

    fun stage(root: File, source: Source, files: List<String>): File {
        val incoming = incoming(root)
        Files.createDirectories(incoming.toPath())
        val directory = File(incoming, UUID.randomUUID().toString())
        Files.createDirectory(directory.toPath())
        val payload = File(directory, "payload")
        Files.createDirectory(payload.toPath())
        try {
            for (relative in files) {
                val destination = File(payload, relative)
                destination.parentFile?.mkdirs()
                source.open("payload/$relative").use { input ->
                    destination.outputStream().use { output -> input.copyTo(output) }
                }
            }
        } catch (error: Throwable) {
            removeTree(directory)
            throw error
        }
        return payload
    }

    /** Call only after the Python journal has completed recovery. */
    fun clearStages(root: File) {
        val directory = incoming(root)
        if (Files.exists(directory.toPath(), LinkOption.NOFOLLOW_LINKS)) removeTree(directory)
    }

    fun removeStage(payload: File) = removeTree(payload.parentFile!!)

    private fun incoming(root: File): File {
        val directory = File(root, INCOMING)
        check(!Files.isSymbolicLink(directory.toPath())) { "Upgrade staging must be a private directory" }
        return directory
    }

    private fun removeTree(directory: File) {
        // Do not follow a stray link into shared packs or an external mod folder.
        Files.walk(directory.toPath()).use { paths ->
            paths.sorted(Comparator.reverseOrder()).forEach { Files.deleteIfExists(it) }
        }
    }
}
