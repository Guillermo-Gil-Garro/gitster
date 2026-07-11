package com.gitster.dj.deck

import com.google.gson.annotations.SerializedName

/**
 * One card from assets/deck.json, v2 contract (docs/qr-deck-contract.md).
 * Plain field names only; the pipeline guarantees the schema.
 */
data class DeckCard(
    @SerializedName("card_id") val cardId: String? = null,
    @SerializedName("title") val title: String? = null,
    @SerializedName("artists") val artists: String? = null,
    @SerializedName("year") val year: Int? = null,
    @SerializedName("owners") val owners: List<String>? = null,
    @SerializedName("expansion") val expansion: String? = null,
    @SerializedName("spotify_url") val spotifyUrl: String? = null,
    @SerializedName("track_id") val trackId: String? = null
)
