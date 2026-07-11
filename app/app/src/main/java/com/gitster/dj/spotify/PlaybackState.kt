package com.gitster.dj.spotify

/**
 * Playback status reported by the Spotify layer.
 *
 * This layer never emits user-facing text: the UI maps each state
 * to its own string resources. [Error.detail] is diagnostic only
 * (log-friendly, English, technical).
 */
sealed interface PlaybackUiState {
    data object Idle : PlaybackUiState
    data object Connecting : PlaybackUiState
    data object Playing : PlaybackUiState
    data object Paused : PlaybackUiState
    data object NoActiveDevice : PlaybackUiState
    data object AuthRequired : PlaybackUiState

    /** The scanned input could not be resolved to a spotify:track: URI. */
    data object InvalidTrackUri : PlaybackUiState

    data class Error(val kind: ErrorKind, val detail: String? = null) : PlaybackUiState

    enum class ErrorKind { NETWORK, SPOTIFY_API, NO_PREMIUM, UNKNOWN }
}
