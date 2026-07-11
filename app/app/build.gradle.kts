import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.compose.compiler)
}

// Secrets fuera del repo: local.properties (gitignored) debe definir
// spotify.clientId y spotify.redirectUri.
val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) {
        file.inputStream().use { load(it) }
    }
}

fun requiredLocalProperty(key: String): String =
    localProperties.getProperty(key)?.takeIf { it.isNotBlank() }
        ?: error(
            "Missing '$key' in ${rootProject.file("local.properties")}. " +
                "Add: $key=<value> (this file is gitignored, never commit it)."
        )

val spotifyClientId = requiredLocalProperty("spotify.clientId")
val spotifyRedirectUri = requiredLocalProperty("spotify.redirectUri")

android {
    namespace = "com.gitster.dj"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.gitster.dj"
        minSdk = 24
        targetSdk = 35
        versionCode = 4
        versionName = "2.0"

        vectorDrawables {
            useSupportLibrary = true
        }

        buildConfigField("String", "SPOTIFY_CLIENT_ID", "\"$spotifyClientId\"")
        buildConfigField("String", "SPOTIFY_REDIRECT_URI", "\"$spotifyRedirectUri\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = "11"
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    val camerax = "1.3.4"

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation("androidx.camera:camera-core:$camerax")
    implementation("androidx.camera:camera-camera2:$camerax")
    implementation("androidx.camera:camera-lifecycle:$camerax")
    implementation("androidx.camera:camera-view:$camerax")

    implementation(libs.mlkit.barcode.scanning)
    implementation("com.google.code.gson:gson:2.10.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("androidx.browser:browser:1.8.0")
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    implementation(files("libs/spotify-app-remote-release-0.8.0.aar"))
}
