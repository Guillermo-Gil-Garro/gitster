package com.gitster.dj.spotify

import android.app.Activity
import android.os.SystemClock
import android.util.Log
import com.spotify.android.appremote.api.ConnectionParams
import com.spotify.android.appremote.api.Connector
import com.spotify.android.appremote.api.SpotifyAppRemote
import com.spotify.protocol.client.Subscription
import com.spotify.protocol.types.PlayerState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private const val TAG = "SpotifyRemote"
private const val MAX_CONNECT_ATTEMPTS = 2
private const val CONNECT_WATCHDOG_MS = 2_500L
private const val ON_STOP_CONNECT_GRACE_MS = 5_000L
private const val RETRY_CONNECT_DELAY_MS = 800L

enum class RemoteState { IDLE, CONNECTING, CONNECTED, FAILED, HUNG }

/**
 * Best-effort Spotify App Remote connection used as a fallback when Web API
 * autoplay fails. A watchdog detects hung connects (SDK never calls back);
 * after [MAX_CONNECT_ATTEMPTS] hangs, [permanentFallback] disables further
 * attempts for the current track.
 */
class SpotifyRemoteManager {
    private val _state = MutableStateFlow(RemoteState.IDLE)
    val state: StateFlow<RemoteState> = _state.asStateFlow()

    var spotifyAppRemote: SpotifyAppRemote? = null
        private set

    var permanentFallback: Boolean = false
        private set

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var watchdogJob: Job? = null
    private var pendingUri: String? = null
    private var playerStateSubscription: Subscription<PlayerState>? = null
    private var connectStartedAtMs: Long = 0L
    private var attemptCount: Int = 0

    fun connect(
        activity: Activity,
        spotifyUri: String,
        onPlayerState: (PlayerState) -> Unit = {}
    ) {
        if (pendingUri != spotifyUri) {
            attemptCount = 0
            permanentFallback = false
            pendingUri = spotifyUri
            Log.d(TAG, "New track uri, reset attempts/permanentFallback")
        }

        if (permanentFallback) {
            Log.d(TAG, "Connect skipped: permanentFallback=true")
            return
        }

        if (_state.value == RemoteState.CONNECTING) {
            Log.d(TAG, "Connect skipped: already connecting")
            return
        }

        if (attemptCount >= MAX_CONNECT_ATTEMPTS) {
            permanentFallback = true
            _state.value = RemoteState.FAILED
            Log.w(TAG, "Connect blocked: attempts exhausted -> permanentFallback=true")
            return
        }

        attemptCount += 1
        connectStartedAtMs = SystemClock.uptimeMillis()
        Log.d(TAG, "Connect attempt=$attemptCount uri=$spotifyUri")
        pendingUri = spotifyUri
        _state.value = RemoteState.CONNECTING

        watchdogJob?.cancel()
        watchdogJob = scope.launch {
            delay(CONNECT_WATCHDOG_MS)
            if (_state.value == RemoteState.CONNECTING) {
                Log.w(TAG, "Connect hang detected attempt=$attemptCount (no callbacks)")
                _state.value = RemoteState.HUNG
                if (attemptCount >= MAX_CONNECT_ATTEMPTS) {
                    permanentFallback = true
                    Log.w(TAG, "permanentFallback=true after repeated hangs")
                }
            }
        }

        val params = ConnectionParams.Builder(SpotifyConfig.clientId)
            .setRedirectUri(SpotifyConfig.redirectUri)
            .showAuthView(true)
            .build()

        activity.runOnUiThread {
            SpotifyAppRemote.connect(
                activity,
                params,
                object : Connector.ConnectionListener {
                    override fun onConnected(appRemote: SpotifyAppRemote) {
                        watchdogJob?.cancel()
                        spotifyAppRemote = appRemote
                        _state.value = RemoteState.CONNECTED
                        permanentFallback = false
                        Log.d(TAG, "Remote connected")

                        playerStateSubscription?.cancel()
                        val subscription = appRemote.playerApi.subscribeToPlayerState()
                        subscription.setEventCallback { ps ->
                            Log.d(TAG, "Player state trackUri=${ps.track?.uri} isPaused=${ps.isPaused}")
                            onPlayerState(ps)
                        }
                        subscription.setErrorCallback { t ->
                            Log.w(TAG, "subscribeToPlayerState error: ${t.message}", t)
                        }
                        playerStateSubscription = subscription

                        val uri = pendingUri
                        if (!uri.isNullOrBlank()) {
                            Log.d(TAG, "Remote play uri=$uri")
                            appRemote.playerApi.play(uri)
                                .setErrorCallback { t ->
                                    Log.w(TAG, "Remote play error: ${t.message}", t)
                                }
                        }
                    }

                    override fun onFailure(t: Throwable) {
                        watchdogJob?.cancel()
                        spotifyAppRemote = null
                        _state.value = RemoteState.FAILED
                        Log.w(TAG, "Remote connect failed ${t.javaClass.name}: ${t.message}", t)
                    }
                }
            )
        }
    }

    fun disconnect(reason: String = "unknown") {
        val now = SystemClock.uptimeMillis()
        Log.d(TAG, "Disconnect reason=$reason state=${_state.value} dt=${now - connectStartedAtMs}ms")

        // ON_STOP right after starting a connect is usually the Spotify auth
        // overlay taking the foreground; killing the connect would loop forever.
        if (_state.value == RemoteState.CONNECTING &&
            reason.contains("ON_STOP") &&
            (now - connectStartedAtMs) < ON_STOP_CONNECT_GRACE_MS
        ) {
            Log.d(TAG, "Ignoring disconnect during connect (likely auth/overlay)")
            return
        }

        watchdogJob?.cancel()
        watchdogJob = null
        playerStateSubscription?.cancel()
        playerStateSubscription = null
        spotifyAppRemote?.let { SpotifyAppRemote.disconnect(it) }
        spotifyAppRemote = null

        // Keep FAILED/HUNG visible across ON_STOP so the UI can offer a retry.
        if (reason.contains("ON_STOP") &&
            (_state.value == RemoteState.HUNG || _state.value == RemoteState.FAILED)
        ) {
            Log.d(TAG, "Keeping state=${_state.value} across ON_STOP")
            return
        }

        _state.value = RemoteState.IDLE
    }
}

object SpotifyRemoteManagerHolder {
    val instance: SpotifyRemoteManager = SpotifyRemoteManager()
}
