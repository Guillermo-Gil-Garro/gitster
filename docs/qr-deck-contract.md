# QR & deck.json contract

Contract between the **pipeline** (card generator) and the **app** (scanner/player). Any change here must be applied on both sides.

## QR payload

Each card's QR encodes the song's public Spotify track URL, nothing else:

```
https://open.spotify.com/track/<track_id>
```

- `<track_id>` is the 22-character base62 Spotify track id.
- Query parameters (e.g. `?si=...`) may be present and must be ignored by consumers.
- Rationale: cards remain scannable by any phone camera (opens Spotify directly) even without the app. The app extracts `<track_id>` and uses it both for playback and to look the card up in `deck.json`.

QR rendering (pipeline): 30 mm, error correction level H, black on white.

## deck.json

Exported by the pipeline from the printed-cards registry (the full physical collection, all expansions). Bundled into the app at `app/src/main/assets/deck.json`.

```json
{
  "version": "baseline-2026-07",
  "generated_at": "2026-07-11T00:00:00Z",
  "cards": [
    {
      "card_id": "GITSTER_GUILLE_017",
      "title": "Song Title",
      "artists": "Artist A, Artist B",
      "year": 1999,
      "owners": ["guille", "blo"],
      "expansion": "guille",
      "spotify_url": "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
      "track_id": "4uLU6hMCjMI75M1A2tKUQC"
    }
  ]
}
```

Field notes:

- `card_id`: `GITSTER_<OWNER>_<NNN>`, unique across the whole collection; `NNN` is per-expansion, append-only numbering.
- `year`: integer — the reveal year used for Timeline placement.
- `owners`: players whose playlists contain the song (lowercase ids as in the pipeline config).
- `expansion`: the single physical expansion the card lives in (its anchor player). Invariant: `expansion ∈ owners`.
- `track_id` is derived from `spotify_url`; both are always present.

## App resolution flow

1. Scan QR → raw string.
2. Extract `track_id` from the Spotify URL (also accept a bare 22-char id or `spotify:track:<id>` URI for robustness).
3. Look up the card in `deck.json` by `track_id` → title / artists / year / owners for the reveal screen.
4. Play `spotify:track:<track_id>` via the Spotify Web API.
5. If the id is not present in `deck.json` (e.g. newer physical cards than the bundled deck), the app may still play the track but shows no card metadata.

## Invariants guaranteed by the pipeline

- A canonical song appears on exactly one physical card (one `card_id`, one `expansion`), ever.
- Printed cards are never renumbered, re-anchored or removed; new print runs only append.
- Every card of expansion `E` has `E` among its `owners`.
