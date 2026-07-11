package com.gitster.dj.spotify

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import java.io.IOException

private const val TAG = "SpotifyPlayback"
private const val DEVICE_WAKE_DELAY_MS = 1_200L

/**
 * Orchestrates Web API playback: device discovery (with a one-shot app wake),
 * transfer+play, pause/resume/replay/seek, and a single refresh+retry on 401.
 *
 * All operations report a [PlaybackUiState]; the UI maps states to strings.
 */
object SpotifyPlaybackController {

    @Volatile
    private var lastTrackUri: String? = null

    @Volatile
    private var lastKnownProgressMs: Long = 0L

    /** Remembers the current track so resume/replay can fall back to a fresh play. */
    fun rememberTrackUri(trackUri: String?) {
        if (!trackUri.isNullOrBlank()) {
            lastTrackUri = trackUri
        }
    }

    /**
     * Resolves the track, ensures auth (launching login if needed), wakes the
     * Spotify app when no device is visible, transfers playback and plays.
     *
     * Returns [PlaybackUiState.Playing] on success, [PlaybackUiState.AuthRequired]
     * when the interactive login was launched.
     */
    suspend fun startAutoplay(
        activity: Activity,
        rawUrl: String?,
        spotifyUri: String?
    ): PlaybackUiState {
        val resolvedUri = resolveFinalTrackUri(rawUrl = rawUrl, spotifyUri = spotifyUri)
        if (resolvedUri.isNullOrBlank()) {
            Log.w(TAG, "Autoplay aborted: unresolvable track (rawUrl=$rawUrl spotifyUri=$spotifyUri)")
            return PlaybackUiState.InvalidTrackUri
        }
        rememberTrackUri(resolvedUri)

        Log.d(TAG, "Autoplay start uri=$resolvedUri")
        val token = SpotifyAuthManager.ensureValidToken(activity) ?: return PlaybackUiState.AuthRequired

        return runWithSingle401Retry(token) { freshToken ->
            autoplayWithToken(activity = activity, token = freshToken, trackUri = resolvedUri)
        }
    }

    /** Pauses playback, capturing the current progress first so resume can restore it. */
    suspend fun pause(): PlaybackUiState {
        val token = tokenOrNull()
        if (token.isNullOrBlank()) {
            Log.w(TAG, "Pause failed: no token")
            return PlaybackUiState.AuthRequired
        }

        return try {
            updateLastKnownProgress(token)
            SpotifyWebApiClient.pausePlayback(token)
            PlaybackUiState.Paused
        } catch (error: Throwable) {
            if (error is CancellationException) throw error
            mapWebError("Pause", error, unauthorizedAsAuthRequired = true)
        }
    }

    /**
     * Resumes playback. If the device went inactive, falls back to a fresh
     * play of the remembered track at the last known position.
     */
    suspend fun resume(): PlaybackUiState {
        val token = tokenOrNull()
        if (token.isNullOrBlank()) {
            Log.w(TAG, "Resume failed: no token")
            return PlaybackUiState.AuthRequired
        }

        return try {
            SpotifyWebApiClient.resumePlayback(token)
            updateLastKnownProgress(token)
            Log.d(TAG, "Resume ok")
            PlaybackUiState.Playing
        } catch (error: Throwable) {
            if (error is CancellationException) throw error
            if (error is SpotifyWebApiClient.NoActiveDeviceException) {
                Log.w(TAG, "Resume: no active device, trying fallback play")
                resumeViaFallbackPlay(token)
            } else {
                mapWebError("Resume", error, unauthorizedAsAuthRequired = true)
            }
        }
    }

    /**
     * Restarts the current track from position 0 (seek+resume, with a fresh
     * play fallback when the device went inactive).
     */
    suspend fun replay(): PlaybackUiState {
        val token = tokenOrNull()
        if (token.isNullOrBlank()) {
            Log.w(TAG, "Replay failed: no token")
            return PlaybackUiState.AuthRequired
        }

        return try {
            SpotifyWebApiClient.seekTo(token = token, positionMs = 0L)
            lastKnownProgressMs = 0L
            try {
                SpotifyWebApiClient.resumePlayback(token)
                Log.d(TAG, "Replay ok")
                PlaybackUiState.Playing
            } catch (resumeError: Throwable) {
                if (resumeError is CancellationException) throw resumeError
                if (resumeError is SpotifyWebApiClient.NoActiveDeviceException) {
                    replayViaFallbackPlay(token)
                } else {
                    mapWebError("Replay", resumeError, unauthorizedAsAuthRequired = true)
                }
            }
        } catch (error: Throwable) {
            if (error is CancellationException) throw error
            mapWebError("Replay", error, unauthorizedAsAuthRequired = true)
        }
    }

    /**
     * Seeks relative to the current position, clamped to [0, duration - 1s].
     * Returns [PlaybackUiState.Playing] on success.
     */
    suspend fun seekBy(deltaMs: Long): PlaybackUiState {
        val token = tokenOrNull()
        if (token.isNullOrBlank()) {
            Log.w(TAG, "Seek failed: no token")
            return PlaybackUiState.AuthRequired
        }

        return try {
            seekWithToken(token = token, deltaMs = deltaMs)
        } catch (unauthorized: SpotifyWebApiClient.UnauthorizedException) {
            val refreshed = SpotifyAuthManager.refreshIfNeeded()
            val refreshedToken = SpotifyAuthManager.getAccessTokenOrNull()
            if (!refreshed || refreshedToken.isNullOrBlank()) {
                Log.w(TAG, "Seek failed: refresh after 401 unsuccessful")
                PlaybackUiState.AuthRequired
            } else {
                try {
                    seekWithToken(token = refreshedToken, deltaMs = deltaMs)
                } catch (second: Throwable) {
                    if (second is CancellationException) throw second
                    mapWebError("Seek", second, unauthorizedAsAuthRequired = true)
                }
            }
        } catch (error: Throwable) {
            if (error is CancellationException) throw error
            mapWebError("Seek", error, unauthorizedAsAuthRequired = true)
        }
    }

    private suspend fun autoplayWithToken(
        activity: Activity,
        token: String,
        trackUri: String
    ): PlaybackUiState {
        var devices = SpotifyWebApiClient.getDevices(token)

        if (devices.isEmpty()) {
            wakeSpotifyApp(activity)
            delay(DEVICE_WAKE_DELAY_MS)
            devices = SpotifyWebApiClient.getDevices(token)
            if (devices.isEmpty()) {
                Log.w(TAG, "Autoplay: no device even after waking Spotify")
                return PlaybackUiState.NoActiveDevice
            }
        }

        val selectedDevice = devices.firstOrNull { it.isActive } ?: devices.first()
        Log.d(TAG, "Autoplay transfer -> deviceId=${selectedDevice.id}")
        SpotifyWebApiClient.transferPlayback(
            token = token,
            deviceId = selectedDevice.id,
            play = true
        )

        SpotifyWebApiClient.playTrack(
            token = token,
            deviceId = selectedDevice.id,
            spotifyTrackUri = trackUri
        )
        lastTrackUri = trackUri
        lastKnownProgressMs = 0L
        Log.d(TAG, "Autoplay play ok")
        return PlaybackUiState.Playing
    }

    private suspend fun runWithSingle401Retry(
        initialToken: String,
        block: suspend (token: String) -> PlaybackUiState
    ): PlaybackUiState {
        return try {
            block(initialToken)
        } catch (unauthorized: SpotifyWebApiClient.UnauthorizedException) {
            Log.w(TAG, "Autoplay caught 401, trying refresh+retry once")
            val refreshed = SpotifyAuthManager.refreshIfNeeded()
            val refreshedToken = SpotifyAuthManager.getAccessTokenOrNull()
            if (!refreshed || refreshedToken.isNullOrBlank()) {
                PlaybackUiState.Error(
                    kind = PlaybackUiState.ErrorKind.SPOTIFY_API,
                    detail = "auth expired: refresh after 401 failed"
                )
            } else {
                try {
                    block(refreshedToken)
                } catch (second: Throwable) {
                    if (second is CancellationException) throw second
                    mapWebError("Autoplay", second, unauthorizedAsAuthRequired = false)
                }
            }
        } catch (error: Throwable) {
            if (error is CancellationException) throw error
            mapWebError("Autoplay", error, unauthorizedAsAuthRequired = false)
        }
    }

    private suspend fun seekWithToken(token: String, deltaMs: Long): PlaybackUiState {
        val state = SpotifyWebApiClient.getPlayerState(token)
        val fromMs = state.progressMs.coerceAtLeast(0L)
        val unclampedTarget = fromMs + deltaMs
        val durationLimit = state.durationMs
            ?.minus(1_000L)
            ?.coerceAtLeast(0L)

        val targetMs = if (durationLimit == null) {
            unclampedTarget.coerceAtLeast(0L)
        } else {
            unclampedTarget.coerceIn(0L, durationLimit)
        }

        Log.d(TAG, "Seek deltaMs=$deltaMs from=$fromMs to=$targetMs")
        SpotifyWebApiClient.seekTo(token = token, positionMs = targetMs)
        lastKnownProgressMs = targetMs
        return PlaybackUiState.Playing
    }

    private suspend fun resumeViaFallbackPlay(token: String): PlaybackUiState {
        val trackUri = lastTrackUri
        if (trackUri.isNullOrBlank()) {
            return PlaybackUiState.NoActiveDevice
        }

        return try {
            Log.d(TAG, "Resume fallback: fresh play at ${lastKnownProgressMs}ms")
            SpotifyWebApiClient.playTrack(
                token = token,
                deviceId = null,
                spotifyTrackUri = trackUri,
                positionMs = lastKnownProgressMs.coerceAtLeast(0L)
            )
            PlaybackUiState.Playing
        } catch (fallbackError: Throwable) {
            if (fallbackError is CancellationException) throw fallbackError
            mapWebError("ResumeFallback", fallbackError, unauthorizedAsAuthRequired = true)
        }
    }

    private suspend fun replayViaFallbackPlay(token: String): PlaybackUiState {
        val trackUri = lastTrackUri
        if (trackUri.isNullOrBlank()) {
            Log.w(TAG, "Replay fallback failed: no remembered track")
            return PlaybackUiState.NoActiveDevice
        }

        return try {
            SpotifyWebApiClient.playTrack(
                token = token,
                deviceId = null,
                spotifyTrackUri = trackUri,
                positionMs = 0L
            )
            lastKnownProgressMs = 0L
            Log.d(TAG, "Replay fallback ok")
            PlaybackUiState.Playing
        } catch (fallbackError: Throwable) {
            if (fallbackError is CancellationException) throw fallbackError
            mapWebError("ReplayFallback", fallbackError, unauthorizedAsAuthRequired = true)
        }
    }

    /**
     * Maps Web API failures to states. Autoplay historically surfaced 401 as a
     * terminal error (login was already attempted), while pause/resume/replay/seek
     * surfaced it as "log in again" -> [unauthorizedAsAuthRequired].
     */
    private fun mapWebError(
        operation: String,
        error: Throwable,
        unauthorizedAsAuthRequired: Boolean
    ): PlaybackUiState {
        if (error is CancellationException) throw error
        return when (error) {
            is SpotifyWebApiClient.NoActiveDeviceException -> {
                Log.w(TAG, "$operation failed: no active device (code=${error.statusCode})")
                PlaybackUiState.NoActiveDevice
            }

            is SpotifyWebApiClient.UnauthorizedException -> {
                Log.w(TAG, "$operation failed: unauthorized (code=${error.statusCode})")
                if (unauthorizedAsAuthRequired) {
                    PlaybackUiState.AuthRequired
                } else {
                    PlaybackUiState.Error(
                        kind = PlaybackUiState.ErrorKind.SPOTIFY_API,
                        detail = "unauthorized (${error.statusCode})"
                    )
                }
            }

            is SpotifyWebApiClient.WebApiException -> {
                Log.w(TAG, "$operation failed: code=${error.statusCode} body=${error.bodyPreview}")
                val kind = if (error.bodyPreview.contains("PREMIUM_REQUIRED", ignoreCase = true)) {
                    PlaybackUiState.ErrorKind.NO_PREMIUM
                } else {
                    PlaybackUiState.ErrorKind.SPOTIFY_API
                }
                PlaybackUiState.Error(kind = kind, detail = "${error.message} (${error.statusCode})")
            }

            is IOException -> {
                Log.w(TAG, "$operation failed: network error", error)
                PlaybackUiState.Error(
                    kind = PlaybackUiState.ErrorKind.NETWORK,
                    detail = error.message ?: error.javaClass.simpleName
                )
            }

            else -> {
                Log.e(TAG, "$operation failed: unexpected error", error)
                PlaybackUiState.Error(
                    kind = PlaybackUiState.ErrorKind.UNKNOWN,
                    detail = error.message?.takeIf { it.isNotBlank() } ?: error.javaClass.simpleName
                )
            }
        }
    }

    /** Cached token, refreshing once if it is missing/expired; null means re-login needed. */
    private suspend fun tokenOrNull(): String? {
        val cached = SpotifyAuthManager.getAccessTokenOrNull()
        if (!cached.isNullOrBlank()) return cached
        if (!SpotifyAuthManager.refreshIfNeeded()) return null
        return SpotifyAuthManager.getAccessTokenOrNull()
    }

    private suspend fun updateLastKnownProgress(token: String) {
        runCatching {
            val state = SpotifyWebApiClient.getPlayerState(token)
            lastKnownProgressMs = state.progressMs.coerceAtLeast(0L)
        }.onFailure { error ->
            if (error is CancellationException) throw error
            // Best-effort: keep the previous position if the player state is unavailable.
            Log.d(TAG, "Could not refresh last known progress: ${error.message}")
        }
    }

    private fun resolveFinalTrackUri(rawUrl: String?, spotifyUri: String?): String? {
        val candidates = listOfNotNull(spotifyUri, rawUrl)
        for (candidate in candidates) {
            val resolved = SpotifyUriResolver.resolveSpotifyTrackUri(candidate)
            if (!resolved.isNullOrBlank()) {
                return resolved
            }
        }
        return null
    }

    private fun wakeSpotifyApp(activity: Activity) {
        val packageManager = activity.packageManager
        val launchIntent = packageManager.getLaunchIntentForPackage("com.spotify.music")
            ?: packageManager.getLaunchIntentForPackage("com.spotify.lite")
            ?: Intent(Intent.ACTION_VIEW, Uri.parse("spotify:"))

        runCatching {
            launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(launchIntent)
            Log.d(TAG, "Wake Spotify app intent sent")
        }.onFailure { error ->
            Log.w(TAG, "Wake Spotify app failed: ${error.message}", error)
        }
    }
}
