package com.gitster.dj.deck

import android.content.Context
import android.net.Uri
import android.util.Log
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val TAG = "DeckRepository"
private const val SPOTIFY_TRACK_URI_PREFIX = "spotify:track:"

/** Root of assets/deck.json, v2 contract (docs/qr-deck-contract.md). */
private data class DeckFile(
    @SerializedName("version") val version: String? = null,
    @SerializedName("generated_at") val generatedAt: String? = null,
    @SerializedName("cards") val cards: List<DeckCard>? = null
)

/**
 * Result of resolving a scanned QR payload.
 * [trackId] non-null means the scan is playable even when [card] is null
 * (physical card newer than the bundled deck).
 */
data class ScanResolution(
    val raw: String,
    val trackId: String?,
    val card: DeckCard?
)

/**
 * Loads the bundled deck and resolves scanned payloads to track ids / cards.
 * Accepted payloads: open.spotify.com track URLs (incl. intl-XX segments and
 * query params), spotify:track:<id> URIs and bare 22-char base62 track ids.
 */
class DeckRepository(
    private val context: Context,
    private val assetFileName: String = "deck.json"
) {
    private var loaded: Boolean = false
    private var byTrackId: Map<String, DeckCard> = emptyMap()

    suspend fun loadDeckIfNeeded() {
        if (loaded) return

        withContext(Dispatchers.IO) {
            val deck = runCatching {
                val json = context.assets.open(assetFileName).bufferedReader().use { it.readText() }
                Gson().fromJson(json, DeckFile::class.java)
            }.onFailure { error ->
                Log.w(TAG, "Failed to load $assetFileName: ${error.message}")
            }.getOrNull()

            val cards = deck?.cards.orEmpty()
            byTrackId = cards
                .mapNotNull { card ->
                    card.trackId?.trim()?.takeIf(::isLikelySpotifyTrackId)?.let { it to card }
                }
                .toMap()

            loaded = true
            Log.d(TAG, "Deck loaded version=${deck?.version} cards=${cards.size} indexed=${byTrackId.size}")
        }
    }

    fun resolveFromRaw(rawInput: String): ScanResolution {
        val raw = rawInput.trim()
        val trackId = extractTrackId(raw)
        val card = trackId?.let { byTrackId[it] }
        Log.d(TAG, "resolveFromRaw trackId=$trackId cardId=${card?.cardId}")
        return ScanResolution(raw = raw, trackId = trackId, card = card)
    }

    private fun extractTrackId(raw: String): String? {
        if (raw.isBlank()) return null

        if (raw.regionMatches(0, SPOTIFY_TRACK_URI_PREFIX, 0, SPOTIFY_TRACK_URI_PREFIX.length, ignoreCase = true)) {
            val id = raw.substring(SPOTIFY_TRACK_URI_PREFIX.length).substringBefore("?").trim()
            return id.takeIf(::isLikelySpotifyTrackId)
        }

        if (isLikelySpotifyTrackId(raw)) return raw

        val parsed = runCatching { Uri.parse(raw) }.getOrNull() ?: return null
        if (parsed.host?.contains("spotify.com", ignoreCase = true) != true) return null

        // pathSegments already excludes the query; intl-XX prefixes simply
        // shift the "track" segment, so locate it instead of assuming index 0.
        val segments = parsed.pathSegments.orEmpty()
        val trackIndex = segments.indexOfFirst { it.equals("track", ignoreCase = true) }
        if (trackIndex < 0 || trackIndex + 1 >= segments.size) return null
        return segments[trackIndex + 1].trim().takeIf(::isLikelySpotifyTrackId)
    }

    private fun isLikelySpotifyTrackId(value: String): Boolean {
        return value.length == 22 && value.all { it.isLetterOrDigit() && it.code < 128 }
    }
}
