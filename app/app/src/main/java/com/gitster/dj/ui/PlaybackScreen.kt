package com.gitster.dj.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.gitster.dj.PlayableCard
import com.gitster.dj.R
import com.gitster.dj.findActivity
import com.gitster.dj.spotify.PlaybackUiState
import com.gitster.dj.spotify.RemoteState
import com.gitster.dj.spotify.SpotifyAppLauncher
import com.gitster.dj.spotify.SpotifyAuthManager
import com.gitster.dj.spotify.SpotifyPlaybackController
import com.gitster.dj.spotify.SpotifyRemoteManagerHolder
import com.gitster.dj.spotify.SpotifyUriResolver
import com.gitster.dj.ui.theme.GitsterAmber
import com.gitster.dj.ui.theme.GitsterBg0
import com.gitster.dj.ui.theme.GitsterCyan
import com.gitster.dj.ui.theme.GitsterInk
import com.gitster.dj.ui.theme.GitsterMagenta
import com.gitster.dj.ui.theme.GitsterMuted
import com.gitster.dj.ui.theme.GitsterPanel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val TAG = "PlaybackScreen"

private const val LISTENING_BUDGET_MS = 60_000L
private const val LISTENING_TICK_MS = 250L
private val TURN_TABLE_BOTTOM_BLOCK_BOTTOM_PADDING_DP = 4.dp
private val TURNTABLE_BAND_CENTER_COLOR = Color(0xFF20345A)
private const val TURNTABLE_BAND_CENTER_ALPHA = 0.34f
private const val TURNTABLE_BAND_EDGE_ALPHA = 0.10f
private const val TURNTABLE_BAND_RADIUS_MULTIPLIER = 0.9f

/**
 * UI-side playback status. The spotify layer reports [PlaybackUiState];
 * this enum is what we persist across recompositions/process death and
 * map to string resources at composition time.
 */
private enum class PlaybackStatus {
    CONNECTING,
    STARTING,
    RETRYING,
    PLAYING,
    PAUSED,
    AUTH_REQUIRED,
    NO_DEVICE,
    INVALID_TRACK,
    NO_ACTIVITY,
    TIME_UP,
    ERROR_NETWORK,
    ERROR_PREMIUM,
    ERROR_SPOTIFY,
    ERROR_UNKNOWN
}

@Composable
fun PlaybackScreen(
    playable: PlayableCard,
    onNextCard: () -> Unit,
    onBackHome: () -> Unit
) {
    val context = LocalContext.current
    val activity = context.findActivity()
    val lifecycleOwner = LocalLifecycleOwner.current
    val spotifyManager = remember { SpotifyRemoteManagerHolder.instance }
    val remoteState by spotifyManager.state.collectAsState()
    val authTokenVersion by SpotifyAuthManager.tokenVersion.collectAsState()

    val trackResetKey = playable.trackId ?: playable.rawUrl
    var isPlaying by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var listeningRemainingMs by rememberSaveable(trackResetKey) { mutableStateOf(LISTENING_BUDGET_MS) }
    var limitReached by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var status by rememberSaveable(trackResetKey) { mutableStateOf(PlaybackStatus.CONNECTING) }
    var errorDetail by rememberSaveable(trackResetKey) { mutableStateOf("") }
    var autoplayRunning by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var authInProgress by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var autoplayFailedFinal by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var autoplayNoActiveDevice by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var warmupTriggered by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var retryAutoplayOnResumePending by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var retryAutoplayOnResumeDone by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var manualPauseGuard by rememberSaveable(trackResetKey) { mutableStateOf(false) }
    var lastStateLog by rememberSaveable(trackResetKey) { mutableStateOf("") }
    val uiScope = rememberCoroutineScope()
    var playbackCardHeightPx by remember(trackResetKey) { mutableIntStateOf(0) }
    val density = LocalDensity.current

    val rawInputOrUrl = playable.rawUrl
    val resolvedSpotifyUri = remember(rawInputOrUrl, playable.spotifyUri) {
        SpotifyUriResolver.resolveSpotifyTrackUri(playable.spotifyUri)
            ?: SpotifyUriResolver.resolveSpotifyTrackUri(rawInputOrUrl)
    }
    val invalidSpotifyUri = resolvedSpotifyUri.isNullOrBlank()

    val showFallbackButton = !autoplayRunning &&
        !authInProgress &&
        (autoplayFailedFinal || invalidSpotifyUri)

    fun statusForError(state: PlaybackUiState.Error): PlaybackStatus {
        Log.d(TAG, "Playback error kind=${state.kind} detail=${state.detail}")
        errorDetail = shortSpotifyError(state.detail.orEmpty())
        return when (state.kind) {
            PlaybackUiState.ErrorKind.NETWORK -> PlaybackStatus.ERROR_NETWORK
            PlaybackUiState.ErrorKind.NO_PREMIUM -> PlaybackStatus.ERROR_PREMIUM
            PlaybackUiState.ErrorKind.SPOTIFY_API -> PlaybackStatus.ERROR_SPOTIFY
            PlaybackUiState.ErrorKind.UNKNOWN -> PlaybackStatus.ERROR_UNKNOWN
        }
    }

    /** Maps a control (pause/resume/replay/seek) result onto the UI flags. */
    fun applyControlResult(state: PlaybackUiState, playingOnSuccess: Boolean) {
        when (state) {
            PlaybackUiState.Playing -> {
                autoplayRunning = false
                authInProgress = false
                autoplayFailedFinal = false
                if (playingOnSuccess) isPlaying = true
                status = PlaybackStatus.PLAYING
            }

            PlaybackUiState.Paused -> {
                autoplayRunning = false
                authInProgress = false
                autoplayFailedFinal = false
                isPlaying = false
                status = PlaybackStatus.PAUSED
            }

            PlaybackUiState.AuthRequired -> {
                manualPauseGuard = false
                autoplayRunning = false
                authInProgress = true
                autoplayFailedFinal = false
                isPlaying = false
                status = PlaybackStatus.AUTH_REQUIRED
            }

            PlaybackUiState.NoActiveDevice -> {
                manualPauseGuard = false
                autoplayRunning = false
                authInProgress = false
                autoplayFailedFinal = true
                isPlaying = false
                status = PlaybackStatus.NO_DEVICE
            }

            PlaybackUiState.InvalidTrackUri -> {
                manualPauseGuard = false
                autoplayRunning = false
                authInProgress = false
                autoplayFailedFinal = true
                isPlaying = false
                status = PlaybackStatus.INVALID_TRACK
            }

            is PlaybackUiState.Error -> {
                manualPauseGuard = false
                autoplayRunning = false
                authInProgress = false
                autoplayFailedFinal = true
                isPlaying = false
                status = statusForError(state)
            }

            // The controller never returns these from control operations.
            PlaybackUiState.Idle, PlaybackUiState.Connecting -> Unit
        }
    }

    suspend fun runAutoplayAttempt(
        triggerWarmupOnNoActiveDevice: Boolean,
        reason: String
    ) {
        if (activity == null || resolvedSpotifyUri.isNullOrBlank()) {
            return
        }
        if (limitReached || manualPauseGuard) {
            autoplayRunning = false
            return
        }
        Log.d(TAG, "AUTOPLAY reason=$reason uri=$resolvedSpotifyUri")

        autoplayRunning = true
        authInProgress = false
        autoplayFailedFinal = false
        autoplayNoActiveDevice = false
        isPlaying = false
        status = if (reason == "resume_retry") PlaybackStatus.RETRYING else PlaybackStatus.STARTING

        val result = SpotifyPlaybackController.startAutoplay(
            activity = activity,
            rawUrl = rawInputOrUrl,
            spotifyUri = resolvedSpotifyUri
        )
        autoplayRunning = false

        when (result) {
            PlaybackUiState.Playing -> {
                authInProgress = false
                autoplayFailedFinal = false
                autoplayNoActiveDevice = false
                isPlaying = true
                status = PlaybackStatus.PLAYING
                retryAutoplayOnResumePending = false
            }

            PlaybackUiState.AuthRequired -> {
                authInProgress = true
                autoplayFailedFinal = false
                autoplayNoActiveDevice = false
                isPlaying = false
                status = PlaybackStatus.AUTH_REQUIRED
                retryAutoplayOnResumePending = false
            }

            PlaybackUiState.NoActiveDevice -> {
                authInProgress = false
                autoplayFailedFinal = true
                autoplayNoActiveDevice = true
                isPlaying = false
                status = PlaybackStatus.NO_DEVICE
                if (triggerWarmupOnNoActiveDevice && !warmupTriggered) {
                    warmupTriggered = true
                    retryAutoplayOnResumePending = true
                    SpotifyAppLauncher.openSpotifyOnce(context)
                }
            }

            PlaybackUiState.InvalidTrackUri -> {
                authInProgress = false
                autoplayFailedFinal = true
                autoplayNoActiveDevice = false
                isPlaying = false
                status = PlaybackStatus.INVALID_TRACK
                retryAutoplayOnResumePending = false
            }

            is PlaybackUiState.Error -> {
                authInProgress = false
                autoplayFailedFinal = true
                autoplayNoActiveDevice = false
                isPlaying = false
                status = statusForError(result)
                retryAutoplayOnResumePending = false
            }

            PlaybackUiState.Idle, PlaybackUiState.Connecting, PlaybackUiState.Paused -> Unit
        }
    }

    LaunchedEffect(trackResetKey) {
        SpotifyPlaybackController.rememberTrackUri(resolvedSpotifyUri)
        isPlaying = false
        listeningRemainingMs = LISTENING_BUDGET_MS
        limitReached = false
        status = PlaybackStatus.CONNECTING
        errorDetail = ""
        autoplayRunning = false
        authInProgress = false
        autoplayFailedFinal = false
        autoplayNoActiveDevice = false
        warmupTriggered = false
        retryAutoplayOnResumePending = false
        retryAutoplayOnResumeDone = false
        manualPauseGuard = false
        lastStateLog = ""
        if (invalidSpotifyUri) {
            status = PlaybackStatus.INVALID_TRACK
            autoplayFailedFinal = true
        }
        if (activity == null) {
            status = PlaybackStatus.NO_ACTIVITY
            autoplayFailedFinal = true
        }
    }

    LaunchedEffect(
        autoplayRunning,
        authInProgress,
        autoplayFailedFinal,
        autoplayNoActiveDevice,
        warmupTriggered,
        isPlaying,
        remoteState,
        status
    ) {
        val uiState = when {
            autoplayRunning -> "AutoplayRunning"
            authInProgress -> "AuthInProgress"
            autoplayFailedFinal && autoplayNoActiveDevice && warmupTriggered -> "NoActiveDeviceWarmupTriggered"
            autoplayFailedFinal && autoplayNoActiveDevice -> "NoActiveDevice"
            autoplayFailedFinal -> "Failure"
            remoteState == RemoteState.CONNECTING -> "RemoteConnecting"
            isPlaying -> "Playing"
            else -> "Idle"
        }
        if (uiState != lastStateLog) {
            Log.d(TAG, "STATE -> $uiState (status=$status)")
            lastStateLog = uiState
        }
    }

    LaunchedEffect(activity, resolvedSpotifyUri, authTokenVersion, trackResetKey) {
        runAutoplayAttempt(
            triggerWarmupOnNoActiveDevice = true,
            reason = "initial_or_token_refresh"
        )
    }

    // Best-effort App Remote fallback when Web API autoplay failed.
    LaunchedEffect(activity, resolvedSpotifyUri, autoplayFailedFinal) {
        if (!autoplayFailedFinal || activity == null || resolvedSpotifyUri.isNullOrBlank()) {
            return@LaunchedEffect
        }
        if (remoteState == RemoteState.CONNECTED || remoteState == RemoteState.CONNECTING) {
            return@LaunchedEffect
        }
        spotifyManager.connect(
            activity = activity,
            spotifyUri = resolvedSpotifyUri,
            onPlayerState = { state ->
                val shouldIgnorePlayState = (manualPauseGuard || limitReached) && !state.isPaused
                if (!shouldIgnorePlayState) {
                    isPlaying = !state.isPaused
                }
            }
        )
    }

    DisposableEffect(lifecycleOwner, trackResetKey, activity, resolvedSpotifyUri) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> {
                    val shouldRetryOnResume = autoplayNoActiveDevice &&
                        warmupTriggered &&
                        retryAutoplayOnResumePending &&
                        !retryAutoplayOnResumeDone &&
                        !autoplayRunning &&
                        activity != null &&
                        !resolvedSpotifyUri.isNullOrBlank()
                    if (shouldRetryOnResume) {
                        retryAutoplayOnResumePending = false
                        retryAutoplayOnResumeDone = true
                        uiScope.launch {
                            runAutoplayAttempt(
                                triggerWarmupOnNoActiveDevice = false,
                                reason = "resume_retry"
                            )
                        }
                    }
                }

                Lifecycle.Event.ON_STOP -> spotifyManager.disconnect("PlaybackScreen.ON_STOP")
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    // 60s listening budget: ticks on wall clock while playing, pauses at 0.
    LaunchedEffect(isPlaying, limitReached, trackResetKey) {
        if (!isPlaying || limitReached) return@LaunchedEffect
        var lastTickMs = SystemClock.elapsedRealtime()
        while (isPlaying && !limitReached) {
            delay(LISTENING_TICK_MS)
            val nowMs = SystemClock.elapsedRealtime()
            val elapsedMs = (nowMs - lastTickMs).coerceAtLeast(0L)
            lastTickMs = nowMs

            if (elapsedMs <= 0L) continue
            listeningRemainingMs = (listeningRemainingMs - elapsedMs).coerceAtLeast(0L)
            if (listeningRemainingMs <= 0L) {
                listeningRemainingMs = 0L
                limitReached = true
                isPlaying = false
                status = PlaybackStatus.TIME_UP
                uiScope.launch {
                    try {
                        val pauseResult = SpotifyPlaybackController.pause()
                        if (pauseResult == PlaybackUiState.Paused) {
                            isPlaying = false
                            status = PlaybackStatus.TIME_UP
                            Toast.makeText(
                                context,
                                context.getString(R.string.playback_time_up_toast),
                                Toast.LENGTH_SHORT
                            ).show()
                        } else {
                            applyControlResult(pauseResult, playingOnSuccess = false)
                        }
                    } catch (_: CancellationException) {
                        // Normal when leaving composition; don't show failure state.
                    }
                }
                break
            }
        }
    }

    val progress = (listeningRemainingMs.coerceIn(0L, LISTENING_BUDGET_MS)).toFloat() /
        LISTENING_BUDGET_MS.toFloat()

    fun pauseForGame() {
        if (limitReached) return
        manualPauseGuard = true
        isPlaying = false
        uiScope.launch {
            try {
                val pauseResult = SpotifyPlaybackController.pause()
                if (pauseResult == PlaybackUiState.Paused) {
                    // Keep auto-resume blocked: this pause was explicit.
                    autoplayRunning = false
                    authInProgress = false
                    autoplayFailedFinal = false
                    isPlaying = false
                    status = PlaybackStatus.PAUSED
                } else {
                    applyControlResult(pauseResult, playingOnSuccess = false)
                }
            } catch (_: CancellationException) {
                manualPauseGuard = false
                // Normal when leaving composition; don't show failure state.
            }
        }
    }

    fun resumeAfterGamePause() {
        if (limitReached) return
        manualPauseGuard = false
        uiScope.launch {
            try {
                applyControlResult(SpotifyPlaybackController.resume(), playingOnSuccess = true)
            } catch (_: CancellationException) {
                // Normal when leaving composition; don't show failure state.
            }
        }
    }

    fun replayFromStart() {
        manualPauseGuard = false
        listeningRemainingMs = LISTENING_BUDGET_MS
        limitReached = false
        uiScope.launch {
            try {
                applyControlResult(SpotifyPlaybackController.replay(), playingOnSuccess = true)
            } catch (_: CancellationException) {
                // Normal when leaving composition; don't show failure state.
            }
        }
    }

    fun seekBy(deltaMs: Long) {
        uiScope.launch {
            try {
                // Seek success does not change isPlaying (it does not resume a paused player).
                applyControlResult(SpotifyPlaybackController.seekBy(deltaMs), playingOnSuccess = false)
            } catch (_: CancellationException) {
                // Normal when leaving composition; don't show failure state.
            }
        }
    }

    val stickyStatusText = when (status) {
        PlaybackStatus.CONNECTING -> stringResource(R.string.playback_status_connecting)
        PlaybackStatus.STARTING -> stringResource(R.string.playback_status_starting)
        PlaybackStatus.RETRYING -> stringResource(R.string.playback_status_retrying)
        PlaybackStatus.PLAYING -> stringResource(R.string.playback_status_playing)
        PlaybackStatus.PAUSED -> stringResource(R.string.playback_status_paused)
        PlaybackStatus.AUTH_REQUIRED -> stringResource(R.string.playback_status_auth_required)
        PlaybackStatus.NO_DEVICE -> stringResource(R.string.playback_status_no_device)
        PlaybackStatus.INVALID_TRACK -> stringResource(R.string.playback_status_invalid_track)
        PlaybackStatus.NO_ACTIVITY -> stringResource(R.string.playback_status_no_activity)
        PlaybackStatus.TIME_UP -> stringResource(R.string.playback_status_time_up)
        PlaybackStatus.ERROR_NETWORK -> stringResource(R.string.playback_error_network)
        PlaybackStatus.ERROR_PREMIUM -> stringResource(R.string.playback_error_premium)
        PlaybackStatus.ERROR_SPOTIFY, PlaybackStatus.ERROR_UNKNOWN -> stringResource(
            R.string.playback_error_spotify,
            errorDetail.ifBlank { stringResource(R.string.playback_error_detail_unknown) }
        )
    }
    val statusText = when {
        autoplayRunning -> stickyStatusText
        authInProgress -> stringResource(R.string.playback_status_auth_required)
        autoplayFailedFinal -> stickyStatusText
        limitReached && !isPlaying -> stringResource(R.string.playback_status_paused_limit)
        remoteState == RemoteState.CONNECTING -> stringResource(R.string.playback_status_connecting)
        isPlaying -> stringResource(R.string.playback_status_playing)
        else -> stringResource(R.string.playback_status_paused)
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .background(
                Brush.verticalGradient(
                    listOf(
                        GitsterBg0,
                        Color(0xFF070B1C),
                        Color(0xFF060814)
                    )
                )
            )
            .padding(14.dp)
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Top
        ) {
            Text(
                text = stringResource(R.string.brand_name),
                modifier = Modifier.fillMaxWidth(),
                color = GitsterInk,
                fontWeight = FontWeight.Black
            )

            Spacer(Modifier.height(12.dp))

            Box(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .onSizeChanged { playbackCardHeightPx = it.height }
                        .background(GitsterPanel, RoundedCornerShape(22.dp))
                        .padding(16.dp)
                ) {
                    Text(
                        stringResource(R.string.playback_title),
                        color = GitsterInk,
                        fontWeight = FontWeight.Bold
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(statusText, color = GitsterMuted)

                    Spacer(Modifier.height(10.dp))

                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(10.dp)
                            .background(Color(0x22000000), RoundedCornerShape(99.dp))
                    ) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth(progress)
                                .height(10.dp)
                                .background(GitsterCyan, RoundedCornerShape(99.dp))
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    Text(
                        stringResource(
                            R.string.playback_time_remaining,
                            formatMmSsFromMs(listeningRemainingMs)
                        ),
                        color = GitsterInk,
                        fontWeight = FontWeight.SemiBold
                    )

                    Spacer(Modifier.height(14.dp))
                    val controlsEnabled = !authInProgress && !autoplayRunning && !invalidSpotifyUri
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(12.dp)
                        ) {
                            Button(
                                modifier = Modifier
                                    .weight(1f)
                                    .height(52.dp),
                                enabled = controlsEnabled && !limitReached,
                                onClick = {
                                    if (isPlaying) {
                                        pauseForGame()
                                    } else {
                                        resumeAfterGamePause()
                                    }
                                },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = GitsterCyan,
                                    contentColor = Color.Black
                                )
                            ) {
                                Text(
                                    if (isPlaying) {
                                        stringResource(R.string.playback_pause)
                                    } else {
                                        stringResource(R.string.playback_resume)
                                    }
                                )
                            }

                            Button(
                                modifier = Modifier
                                    .weight(1f)
                                    .height(52.dp),
                                enabled = controlsEnabled,
                                onClick = { replayFromStart() },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = Color(0xFF2ECC71),
                                    contentColor = Color.Black
                                )
                            ) {
                                Text(stringResource(R.string.playback_replay))
                            }
                        }

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(12.dp)
                        ) {
                            Button(
                                modifier = Modifier
                                    .weight(1f)
                                    .height(52.dp),
                                enabled = controlsEnabled,
                                onClick = { seekBy(10_000L) },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = GitsterAmber,
                                    contentColor = Color.Black
                                )
                            ) {
                                Text(stringResource(R.string.playback_seek_10))
                            }

                            Button(
                                modifier = Modifier
                                    .weight(1f)
                                    .height(52.dp),
                                enabled = controlsEnabled,
                                onClick = { seekBy(30_000L) },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = GitsterMagenta,
                                    contentColor = Color.Black
                                )
                            ) {
                                Text(stringResource(R.string.playback_seek_30))
                            }
                        }
                    }
                }

                if (playbackCardHeightPx > 0) {
                    AnimatedNeonBorder(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(with(density) { playbackCardHeightPx.toDp() }),
                        shape = RoundedCornerShape(22.dp),
                        strokeDp = 2.dp,
                        isAnimated = isPlaying
                    )
                }
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .drawWithCache {
                            val gradientCenter = Offset(size.width / 2f, size.height / 2f)
                            val brush = Brush.radialGradient(
                                colors = listOf(
                                    TURNTABLE_BAND_CENTER_COLOR.copy(alpha = TURNTABLE_BAND_CENTER_ALPHA),
                                    GitsterBg0.copy(alpha = TURNTABLE_BAND_EDGE_ALPHA),
                                    Color.Transparent
                                ),
                                center = gradientCenter,
                                radius = size.maxDimension * TURNTABLE_BAND_RADIUS_MULTIPLIER
                            )
                            onDrawBehind { drawRect(brush = brush) }
                        }
                )
                TurntableWidget(
                    isPlaying = isPlaying,
                    onTogglePlayPause = {
                        if (isPlaying) {
                            pauseForGame()
                        } else {
                            resumeAfterGamePause()
                        }
                    }
                )
            }

            Spacer(Modifier.height(12.dp))

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = TURN_TABLE_BOTTOM_BLOCK_BOTTOM_PADDING_DP)
            ) {
                SolidNextButton(
                    text = stringResource(R.string.playback_next),
                    enabled = true,
                    onClick = {
                        isPlaying = false
                        spotifyManager.spotifyAppRemote?.playerApi?.pause()
                        onNextCard()
                    }
                )
            }

            if (showFallbackButton) {
                Spacer(Modifier.height(12.dp))
                Button(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = {
                        openTrackInSpotify(context, playable.rawUrl, resolvedSpotifyUri)
                    },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color(0xFF11162E),
                        contentColor = GitsterInk
                    )
                ) {
                    Text(stringResource(R.string.playback_open_spotify))
                }
            }
        }
    }
}

private fun openTrackInSpotify(context: Context, rawUrl: String?, spotifyUri: String?) {
    val spotifyPkg = "com.spotify.music"

    val url = rawUrl
        ?: spotifyUri?.let { "https://open.spotify.com/track/" + it.substringAfterLast(":") }
        ?: return

    val viaSpotifyUrl = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
        setPackage(spotifyPkg)
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    val viaSpotifyUri = spotifyUri?.let {
        Intent(Intent.ACTION_VIEW, Uri.parse(it)).apply {
            setPackage(spotifyPkg)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
    }

    try {
        context.startActivity(viaSpotifyUrl)
    } catch (_: Throwable) {
        try {
            if (viaSpotifyUri != null) {
                context.startActivity(viaSpotifyUri)
            } else {
                context.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
            }
        } catch (_: Throwable) {
            Toast.makeText(
                context,
                context.getString(R.string.playback_cant_open_spotify),
                Toast.LENGTH_SHORT
            ).show()
        }
    }
}

private fun formatMmSsFromMs(ms: Long): String {
    val s = (ms.coerceAtLeast(0L) / 1_000L).toInt()
    val mm = s / 60
    val ss = s % 60
    return "%d:%02d".format(mm, ss)
}

private fun shortSpotifyError(message: String, max: Int = 80): String {
    val singleLine = message
        .lineSequence()
        .firstOrNull()
        .orEmpty()
        .replace(Regex("\\s+"), " ")
        .trim()
    if (singleLine.isBlank()) return ""
    if (singleLine.length <= max) return singleLine
    return singleLine.take(max - 3) + "..."
}

@Composable
private fun SolidNextButton(
    text: String,
    enabled: Boolean,
    onClick: () -> Unit
) {
    val backgroundColor = if (enabled) Color(0xFFFF2D55) else Color(0xFF5A1D2D)

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(54.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(backgroundColor)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = text,
            color = Color.White.copy(alpha = if (enabled) 0.95f else 0.6f),
            fontWeight = FontWeight.Bold
        )
    }
}
