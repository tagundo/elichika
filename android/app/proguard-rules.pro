# Release builds keep minification off by default (see app/build.gradle.kts), so
# these rules only matter if you enable R8. Chaquopy and the app reflect into a
# few classes; keep them.
-keep class com.chaquo.python.** { *; }
-keep class com.tagundo.elichika.** { *; }
