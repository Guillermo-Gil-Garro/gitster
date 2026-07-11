package com.gitster.dj.spotify

import com.gitster.dj.BuildConfig

/** Single source of Spotify credentials, injected via local.properties -> BuildConfig. */
object SpotifyConfig {
    val clientId: String = BuildConfig.SPOTIFY_CLIENT_ID
    val redirectUri: String = BuildConfig.SPOTIFY_REDIRECT_URI

    fun isConfigured(): Boolean = clientId.isNotBlank() && redirectUri.isNotBlank()
}
