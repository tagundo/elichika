plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    // Chaquopy embeds CPython + the pip packages declared below into the APK so
    // the elichika dev-tools (adminui) and modding-tools (webtools) web UIs run
    // in-process. The web servers themselves are pure stdlib http.server; only
    // the modding tools need the native wheels.
    id("com.chaquo.python")
}

android {
    namespace = "com.tagundo.elichika"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.tagundo.elichika"
        minSdk = 29          // first API with a dependable exec-from-nativeLibraryDir guarantee
        targetSdk = 34
        // CalVer (date-based). On a tag build the CI derives these from the git tag
        // (vYYYY.MM.DD[.N]) and passes -PappVersionName / -PappVersionCode; local and
        // non-tag builds fall back to a dev version. versionCode must strictly
        // increase, so it is YYYYMMDD*100(+N) — monotonic and within a 32-bit int.
        versionCode = (project.findProperty("appVersionCode") as String?)?.toIntOrNull() ?: 1
        versionName = ((project.findProperty("appVersionName") as String?)?.takeIf { it.isNotBlank() })
            ?: "0.0.0-dev"

        // arm64 only: matches modern devices and the SIFAS client; keeps the APK small.
        ndk { abiFilters += listOf("arm64-v8a") }
    }

    // The elichika server binary ships as jniLibs/arm64-v8a/libelichika.so so the
    // installer unpacks it into nativeLibraryDir with the execute bit. Legacy
    // packaging keeps it extracted to disk (required to exec it as a subprocess).
    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }

    // A private release key, provided by CI from GitHub Secrets, signs the APKs
    // published to GitHub Releases — so only the maintainer can issue updates.
    // It is NEVER committed. When it isn't provided (local builds, PRs from
    // forks), we fall back to the committed debug key so builds still work.
    val releaseKeystore = System.getenv("RELEASE_KEYSTORE_FILE")
    val hasReleaseKey = !releaseKeystore.isNullOrBlank() && file(releaseKeystore).exists()

    signingConfigs {
        // A fixed, committed keystore so EVERY CI build shares one certificate.
        // The default debug signing uses an auto-generated ~/.android/debug.keystore
        // that differs on each fresh CI runner, so successive APKs had mismatched
        // signatures and Android refused to update over the installed app. This is
        // a debug key with well-known credentials (not a secret) — sideload only.
        create("stable") {
            storeFile = file("elichika-debug.keystore")
            storePassword = "android"
            keyAlias = "elichika"
            keyPassword = "android"
        }
        if (hasReleaseKey) {
            create("release") {
                storeFile = file(releaseKeystore!!)
                storePassword = System.getenv("RELEASE_STORE_PASSWORD")
                keyAlias = System.getenv("RELEASE_KEY_ALIAS")
                keyPassword = System.getenv("RELEASE_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        getByName("debug") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("stable")
        }
        getByName("release") {
            isMinifyEnabled = false   // Chaquopy/UnityPy rely on reflection; don't strip
            // The private release key when CI provides it, else the debug key.
            signingConfig = signingConfigs.getByName(if (hasReleaseKey) "release" else "stable")
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        viewBinding = true
    }
}

chaquopy {
    defaultConfig {
        // CPython version embedded in the APK. 3.8 has the widest Chaquopy
        // prebuilt-wheel coverage (matters for UnityPy's native deps); the tool
        // code is 3.8+ compatible with no 3.10-only syntax.
        version = "3.8"
        pip {
            // numpy + Pillow are Chaquopy-provided prebuilt wheels (safe).
            install("numpy")
            install("Pillow")
            // UnityPy itself is vendored as pure-Python source by CI (pip install
            // --no-deps into src/main/python; see .github/workflows/android.yml).
            // Here we provide only its IMPORT-TIME dependencies. `import UnityPy`
            // and editing bones/mesh/physics need just these; the native texture/
            // audio decoders (texture2ddecoder/etcpak/astc/fmod) are lazy-imported
            // and intentionally omitted, so texture/audio ops degrade but bundle
            // editing works. lz4/brotli are C — if Chaquopy has no arm64 wheel the
            // build will surface it and we adjust.
            install("lz4")
            install("brotli")
            install("attrs")
            install("fsspec")
        }
    }
    // CI syncs the Python sources (adminui/, webtools/, and the dev/mod scripts)
    // into src/main/python before the build. See android/README.md.
    sourceSets {
        getByName("main") {
            srcDir("src/main/python")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    // lets the WebView follow the app/system light-dark theme (algorithmic darkening)
    implementation("androidx.webkit:webkit:1.11.0")
}
