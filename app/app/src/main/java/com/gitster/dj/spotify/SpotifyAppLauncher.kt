package com.gitster.dj.spotify

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.util.Log

private const val TAG = "SpotifyAppLauncher"

/**
 * One-shot "warm up" launcher: opens the Spotify app so it registers as a
 * Connect device, at most once per process and throttled across calls.
 */
object SpotifyAppLauncher {
    private const val SPOTIFY_PACKAGE = "com.spotify.music"
    private const val OPEN_THROTTLE_MS = 15_000L

    @Volatile
    private var openedThisSession: Boolean = false

    @Volatile
    private var lastOpenMs: Long = 0L

    fun openSpotifyOnce(context: Context) {
        if (openedThisSession) return

        val now = SystemClock.elapsedRealtime()
        if (now - lastOpenMs < OPEN_THROTTLE_MS) return
        lastOpenMs = now

        val launchIntent = context.packageManager.getLaunchIntentForPackage(SPOTIFY_PACKAGE)
        if (launchIntent == null) {
            Log.w(TAG, "Spotify app not installed, cannot warm up")
            return
        }
        runCatching {
            context.startActivity(launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            openedThisSession = true
            Log.d(TAG, "Spotify app warm-up launched")
        }.onFailure { error ->
            Log.w(TAG, "Failed to launch Spotify app: ${error.message}", error)
        }
    }
}
