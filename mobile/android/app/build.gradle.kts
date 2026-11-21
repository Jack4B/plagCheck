// PlagCheck na Androida: Python (Chaquopy) uruchamia rdzeń aplikacji w telefonie,
// a WebView wyświetla ten sam interfejs co wersja serwerowa. Bez serwera zewnętrznego.
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// Wersja z app/__init__.py — jedno źródło prawdy dla serwera i APK.
val appVersion: String = Regex("__version__ = \"(.+?)\"")
    .find(rootDir.resolve("../../app/__init__.py").readText())!!.groupValues[1]
val versionParts = appVersion.split(".").map { it.toInt() }

android {
    namespace = "pl.plagcheck.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "pl.plagcheck.app"
        minSdk = 29
        targetSdk = 35
        versionName = appVersion
        versionCode = versionParts[0] * 10000 + versionParts[1] * 100 + versionParts[2]
        ndk { abiFilters += listOf("arm64-v8a") }
    }

    // Podpis: klucz z sekretów GitHuba (ANDROID_KEYSTORE_FILE + hasła w zmiennych środowiskowych,
    // ustawia workflow). Bez sekretów — zapasowo publiczny klucz z repozytorium (tylko do testów:
    // jest jawny, więc nie chroni przed podrobionymi aktualizacjami).
    signingConfigs {
        create("sideload") {
            val secretKeystore = System.getenv("ANDROID_KEYSTORE_FILE")?.let { file(it) }
            if (secretKeystore != null && secretKeystore.isFile) {
                storeFile = secretKeystore
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")?.takeIf { it.isNotBlank() } ?: "plagcheck"
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")?.takeIf { it.isNotBlank() }
                    ?: System.getenv("ANDROID_KEYSTORE_PASSWORD")
            } else {
                storeFile = file("plagcheck-sideload.keystore")
                storePassword = "plagcheck-sideload"
                keyAlias = "plagcheck"
                keyPassword = "plagcheck-sideload"
            }
        }
    }
    buildTypes {
        getByName("debug") { signingConfig = signingConfigs.getByName("sideload") }
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("sideload")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            // --no-deps: pełna, przypięta lista (jak requirements-lock.txt); pomija greenlet
            // (SQLAlchemy potrzebuje go tylko dla asyncio, a na Androidzie nie ma kół).
            options("--no-deps")
            install("a2wsgi==1.10.8")
            install("anyio==4.16.0")
            install("fastapi==0.115.6")
            install("idna==3.20")
            install("pydantic==1.10.27")
            install("PyMySQL==1.1.1")
            install("pypdf==5.1.0")
            install("python-multipart==0.0.20")
            install("SQLAlchemy==2.0.36")
            install("starlette==0.41.3")
            install("typing_extensions==4.16.0")
            install("numpy")
        }
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.core:core-ktx:1.15.0")
}
