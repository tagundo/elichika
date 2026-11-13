plugins {
    id("com.android.application") version "8.5.2"
    id("org.jetbrains.kotlin.android") version "1.9.24"
}
android {
    namespace = "com.tagundo.elichika.consoleqa"
    compileSdk = 34
    defaultConfig {
        applicationId = "com.tagundo.elichika.consoleqa"
        minSdk = 29
        targetSdk = 34
        versionCode = 1
        versionName = "c4-scroll-diagnostic-only"
    }
    signingConfigs {
        create("targetCertificate") {
            val provided = System.getenv("RELEASE_KEYSTORE_FILE")?.takeIf { it.isNotBlank() }
            storeFile = if (provided != null) file(provided) else file("../../android/app/elichika-debug.keystore")
            storePassword = if (provided != null) System.getenv("RELEASE_STORE_PASSWORD") else "android"
            keyAlias = if (provided != null) System.getenv("RELEASE_KEY_ALIAS") else "elichika"
            keyPassword = if (provided != null) System.getenv("RELEASE_KEY_PASSWORD") else "android"
        }
    }
    buildTypes { getByName("release") { isMinifyEnabled = false; signingConfig = signingConfigs.getByName("targetCertificate") } }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("androidx.test:runner:1.6.2")
    implementation("androidx.test:core:1.6.1")
    implementation("androidx.test.ext:junit:1.2.1")
    implementation("junit:junit:4.13.2")
}
