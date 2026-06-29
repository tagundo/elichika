// Top-level build file. Plugin versions are declared here and applied (without
// version) in the :app module. Keep these in sync with the Gradle wrapper
// version (gradle/wrapper/gradle-wrapper.properties) and Chaquopy's supported
// AGP range — see https://chaquo.com/chaquopy/doc/current/versions.html
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    id("com.chaquo.python") version "16.0.0" apply false
}
