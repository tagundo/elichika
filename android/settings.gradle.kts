// Gradle settings for the standalone elichika Android server app.
//
// This module lives inside the elichika repo (see android/README.md) so the
// app is versioned together with the server: a server change and the app that
// ships it land in the same commit. The actual server binary (libelichika.so),
// the bundled data payload and the embedded Python sources are assembled by CI
// (.github/workflows/android.yml) before `gradle assembleDebug` runs.

pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.PREFER_SETTINGS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "elichika-android"
include(":app")
