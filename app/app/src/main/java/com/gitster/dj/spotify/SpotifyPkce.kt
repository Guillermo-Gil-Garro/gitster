package com.gitster.dj.spotify

import android.util.Base64
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.security.SecureRandom

/** PKCE helpers for the Spotify authorization-code flow (RFC 7636). */
object SpotifyPkce {
    private val secureRandom = SecureRandom()

    /** 64 random bytes -> 86 base64url chars, within the RFC 7636 43..128 range. */
    fun generateCodeVerifier(): String {
        val bytes = ByteArray(64)
        secureRandom.nextBytes(bytes)
        return base64Url(bytes)
    }

    fun codeChallengeS256(verifier: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(verifier.toByteArray(StandardCharsets.US_ASCII))
        return base64Url(digest)
    }

    fun randomState(): String {
        val bytes = ByteArray(16)
        secureRandom.nextBytes(bytes)
        return base64Url(bytes)
    }

    private fun base64Url(bytes: ByteArray): String {
        return Base64.encodeToString(
            bytes,
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING
        )
    }
}
