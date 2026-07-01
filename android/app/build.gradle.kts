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
        versionCode = 2
        versionName = "0.1.1"

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

    buildTypes {
        getByName("debug") {
            isMinifyEnabled = false
        }
        getByName("release") {
            isMinifyEnabled = false
            // CI ships a debug-signed build by default. To produce a release-signed
            // APK, add a signingConfig here that reads a keystore from CI secrets.
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
