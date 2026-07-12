# Gitster

Gitster is a custom, self-hosted take on the [Hitster](https://hitstergame.com/) music board game: the deck is built from **your own group's Spotify playlists**, printed as physical cards with QR codes, and played with a companion Android app that scans a card and plays the song through Spotify.

Rules of the game (with tokens, bets and steals on top of vanilla Hitster): [Español](https://guillermo-gil-garro.github.io/gitster/rules/es/) · [English](https://guillermo-gil-garro.github.io/gitster/rules/en/)

Operator's guide (Spanish): [COMO_GENERAR_UN_MAZO.md](COMO_GENERAR_UN_MAZO.md) — the full playlist-to-printed-deck walkthrough.

## Repository layout

```
pipeline/   Python pipeline: Spotify ingest → song identity & curation → modular
            deck building → print-ready PDF renders, deck.json and HTML report
app/        Android app (Kotlin + Compose): scans a card's QR and plays the
            track on Spotify (OAuth PKCE + Web API)
docs/       Game rules (es/en) and the QR / deck.json contract between
            pipeline and app
```

## How it fits together

1. Each player maintains a Spotify playlist. The **pipeline** ingests all of them, deduplicates songs into canonical identities, and applies human curation (release-year fixes, display names).
2. The deck is **modular**: every player gets their own expansion (default 60 cards), anchored to songs from their playlist. A song is printed exactly once, even if several players share it. Adding a new player later only prints their expansion plus small delta packs for existing expansions — never reprints.
3. Cards carry a QR with the song's Spotify URL. The pipeline exports print-ready PDFs per expansion and a `deck.json` consumed by the app.
4. The **app** scans the QR, resolves card metadata from `deck.json`, and controls playback on the player's Spotify app.

See [docs/qr-deck-contract.md](docs/qr-deck-contract.md) for the exact contract.

## Quickstart

### Pipeline

Requires Python ≥ 3.11 and Spotify API credentials.

```bash
cd pipeline
cp .env.example .env                      # fill in Spotify credentials
cp config/config.example.json config/config.json   # define players & playlists
pip install -e .
gitster --help
```

### App

Open `app/` in Android Studio (AGP 8.7 / Kotlin 2.0), put your Spotify Client ID
in `local.properties`, and run on a device with the Spotify app installed.

## Status

Active rewrite of two earlier projects (a v1/v2 pipeline and a standalone app) into this single repository. History starts fresh here; the legacy repos remain archived locally and at `GITSTER-legacy` on GitHub.
