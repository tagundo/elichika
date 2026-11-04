package com.tagundo.elichika

import java.io.File
import java.io.InputStream
import java.nio.file.Files
import java.nio.file.LinkOption
import java.util.Comparator
import java.util.UUID

/** APK reads and private staging only: publishing belongs to the upgrade journal. */
internal object PayloadFiles {
    private const val INCOMING = ".payload-incoming"
    private val MANAGED = setOf(
        "webui", "server init jsons", "privatekey.pem", "publickey.pem",
        "assets", "static", "serverdata.db"
    )

    interface Source {
        fun list(path: String): Array<String>
        fun open(path: String): InputStream
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

    fun needsUpdate(root: File, installed: String?, current: String, files: List<String>): Boolean =
        installed != current || File(root, ".payload-upgrade/needs-rebase").exists() ||
            files.any { !File(root, it).isFile }

    fun hasInstalledData(root: File, installed: String?): Boolean =
        installed != null || MANAGED.any {
            Files.exists(File(root, it).toPath(), LinkOption.NOFOLLOW_LINKS)
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
