plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    // Chaquopy embeds CPython + the pip packages declared below into the APK so
    // the elichika dev-tools (adminui) and modding-tools (webtools) web UIs run
    // in-process. The web servers themselves are pure stdlib http.server; only
    // the modding tools need the native wheels.
    id("com.chaquo.python")
}

// The phone build remains ARM64. A native x86_64 build lets an x86 emulator
// exercise the same server subprocess and Python tools without ARM translation.
val appAbi = providers.gradleProperty("appAbi").orElse("arm64-v8a").get()
require(appAbi in listOf("arm64-v8a", "x86_64")) { "Unsupported appAbi: $appAbi" }
val wheelAbi = appAbi.replace('-', '_')

android {
    namespace = "com.tagundo.elichika"
    compileSdk = 34
    ndkVersion = "28.2.13676358"

    defaultConfig {
        applicationId = "com.tagundo.elichika"
        minSdk = 29          // first API with a dependable exec-from-nativeLibraryDir guarantee
        targetSdk = 34
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // CalVer (date-based). On a tag build the CI derives these from the git tag
        // (vYYYY.MM.DD[.N]) and passes -PappVersionName / -PappVersionCode; local and
        // non-tag builds fall back to a dev version. versionCode must strictly
        // increase, so it is YYYYMMDD*100(+N) — monotonic and within a 32-bit int.
        versionCode = (project.findProperty("appVersionCode") as String?)?.toIntOrNull() ?: 1
        versionName = ((project.findProperty("appVersionName") as String?)?.takeIf { it.isNotBlank() })
            ?: "0.0.0-dev"

        // ARM64 by default; appAbi selects a native x86_64 emulator build for QA.
        ndk { abiFilters += listOf(appAbi) }
    }
    testBuildType = "release"

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
    // Test APK only: keep the synthetic DBs out of the production payload/APK.
    sourceSets.getByName("androidTest").assets.srcDir(
        layout.buildDirectory.dir("generated/serverConfigTestAssets")
    )
    // Always ship the CPU's local HCA decoder. Audio playback must work without
    // an external FFmpeg installation on the phone or emulator.
    sourceSets.getByName("main").jniLibs.srcDir(layout.buildDirectory.dir("generated/hca/jniLibs"))
    // Executable PIE: Android extracts this into nativeLibraryDir beside ASTC.
    sourceSets.getByName("main").jniLibs.srcDir(layout.buildDirectory.dir("generated/texture65/jniLibs"))
}

val hcaSdkDirectory = androidComponents.sdkComponents.sdkDirectory
val buildHcaDecoder by tasks.registering(Exec::class) {
    val builder = rootProject.file("ci/build_hca.py")
    val audit = rootProject.file("ci/audit_native.py")
    val source = rootProject.file("../modtools/webtools/core/resources/cri_hca")
    val output = layout.buildDirectory.file("generated/hca/jniLibs/$appAbi/libelichika_hca.so")
    val report = layout.buildDirectory.file("generated/hca/reports/$appAbi.json")
    inputs.file(builder)
    inputs.file(audit)
    inputs.dir(source)
    inputs.property("appAbi", appAbi)
    inputs.property("ndkVersion", android.ndkVersion)
    outputs.file(output)
    outputs.file(report)
    doFirst {
        // AGP's ndkDirectory provider is empty when no CMake/ndk-build model is
        // configured. This small direct C build uses the same pinned SDK NDK.
        val ndkRoot = providers.environmentVariable("ANDROID_NDK_ROOT").orNull
            ?: providers.environmentVariable("ANDROID_NDK_HOME").orNull
            ?: hcaSdkDirectory.get().asFile.resolve("ndk/${android.ndkVersion}").absolutePath
        commandLine(providers.gradleProperty("buildPython").orElse("python3").get(),
            builder.absolutePath, "--source", source.absolutePath, "--ndk", ndkRoot,
            "--abi", appAbi, "--output", output.get().asFile.absolutePath,
            "--report", report.get().asFile.absolutePath)
    }
}

val buildTexture65Decoder by tasks.registering(Exec::class) {
    val builder = rootProject.file("ci/build_texture65.py")
    val audit = rootProject.file("ci/audit_native.py")
    val source = rootProject.file("../modtools/webtools/core/resources/texture65_decoder")
    val output = layout.buildDirectory.file("generated/texture65/jniLibs/$appAbi/libelichika_texture65.so")
    val report = layout.buildDirectory.file("generated/texture65/reports/$appAbi.json")
    inputs.file(builder)
    inputs.file(audit)
    inputs.dir(source)
    inputs.property("appAbi", appAbi)
    inputs.property("ndkVersion", android.ndkVersion)
    outputs.file(output)
    outputs.file(report)
    doFirst {
        val ndkRoot = providers.environmentVariable("ANDROID_NDK_ROOT").orNull
            ?: providers.environmentVariable("ANDROID_NDK_HOME").orNull
            ?: hcaSdkDirectory.get().asFile.resolve("ndk/${android.ndkVersion}").absolutePath
        commandLine(providers.gradleProperty("buildPython").orElse("python3").get(),
            builder.absolutePath, "--source", source.absolutePath, "--ndk", ndkRoot,
            "--abi", appAbi, "--output", output.get().asFile.absolutePath,
            "--report", report.get().asFile.absolutePath)
    }
}

tasks.named("preBuild") { dependsOn(buildHcaDecoder, buildTexture65Decoder) }

val generateServerConfigTestPayload by tasks.registering(Exec::class) {
    val generator = rootProject.file("ci/generate_server_config_payload.py")
    val revisionHelper = rootProject.file("../payload_revision.py")
    val assets = layout.buildDirectory.dir("generated/serverConfigTestAssets")
    inputs.file(generator)
    inputs.file(revisionHelper)
    outputs.dir(assets)
    commandLine(providers.gradleProperty("buildPython").orElse("python3").get(),
        generator.absolutePath, "--output", assets.get().dir("payload").asFile.absolutePath,
        "--manifest-output", assets.get().file("payload_revision.json").asFile.absolutePath)
}

// Applies to both debug and release instrumentation variants when available.
tasks.configureEach {
    if (name.startsWith("merge") && name.endsWith("AndroidTestAssets")) {
        dependsOn(generateServerConfigTestPayload)
    }
}

chaquopy {
    defaultConfig {
        // Chaquopy 17 supports 16 KB pages. Its Python 3.13 Android wheels have
        // the corresponding native layout; older wheels may still be 4 KB-only.
        // APK CI inspects every ELF, including those inside Chaquopy asset ZIPs.
        version = "3.13"
        providers.gradleProperty("buildPython").orNull?.let { buildPython(it) }
        pip {
            // An explicit local wheelhouse keeps offline builds away from all
            // package indexes, including Chaquopy's default extra index.
            providers.gradleProperty("chaquopyWheelhouse").orNull?.let {
                options("--no-index", "--find-links", file(it).absolutePath)
            }
            // Pin the Android wheels exercised by APK layout and runtime checks.
            install("numpy==1.26.2")
        // C LAPACK avoids the old libgfortran RELRO layout which crashes on 16KB.
        install("native-wheels/chaquopy_openblas-0.3.33-1-py3-none-android_24_${wheelAbi}.whl")
            install("Pillow==11.0.0")
            // Pillow's upstream Chaquopy wheel still contains a 4 KB FreeType.
            // CI rebuilds the same 2.9.1 ABI and supplies this local wheel.
            install("native-wheels/chaquopy_freetype-2.9.1-3-py3-none-android_24_${wheelAbi}.whl")
            // UnityPy itself is vendored as pure-Python source by CI (pip install
            // --no-deps into src/main/python; see .github/workflows/android.yml).
            // Here we provide only its IMPORT-TIME dependencies. `import UnityPy`
            // and editing bones/mesh/physics need just these; the native texture/
            // audio decoders (texture2ddecoder/etcpak/astc/fmod) are lazy-imported
            // and intentionally omitted, so texture/audio ops degrade but bundle
            // editing works. lz4/brotli are C — if Chaquopy has no arm64 wheel the
            // build will surface it and we adjust.
            install("lz4==4.3.3")
            install("brotli==1.1.0")
            install("attrs==26.1.0")
            install("fsspec==2026.9.0")
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
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    // lets the WebView follow the app/system light-dark theme (algorithmic darkening)
    implementation("androidx.webkit:webkit:1.11.0")
}
