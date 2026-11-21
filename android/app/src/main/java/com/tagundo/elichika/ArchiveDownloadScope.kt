package com.tagundo.elichika

internal enum class ArchiveDownloadScope(
    val region: String,
    val platform: String,
    val label: Int
) {
    GL_ANDROID("gl", "android", R.string.archive_scope_gl_android),
    GL_IOS("gl", "ios", R.string.archive_scope_gl_ios),
    GL_BOTH("gl", "both", R.string.archive_scope_gl_both),
    JP_ANDROID("jp", "android", R.string.archive_scope_jp_android),
    JP_IOS("jp", "ios", R.string.archive_scope_jp_ios),
    JP_BOTH("jp", "both", R.string.archive_scope_jp_both),
    ALL("both", "both", R.string.archive_scope_all);

    fun command(missingOnly: Boolean) = buildList {
        addAll(listOf("download_archive_profile", region, platform, "all"))
        if (missingOnly) add("--missing")
    }
}
