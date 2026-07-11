from __future__ import annotations

import os
from pathlib import Path

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth


SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative user-read-private"


def get_spotify_client(cache_path: str | Path | None = None) -> spotipy.Spotify:
    load_dotenv()

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

    if not client_id:
        raise RuntimeError("SPOTIFY_CLIENT_ID missing from .env")
    if not client_secret:
        raise RuntimeError("SPOTIFY_CLIENT_SECRET missing from .env")
    if not redirect_uri:
        raise RuntimeError("SPOTIFY_REDIRECT_URI missing from .env")

    cache_file = Path(cache_path) if cache_path else Path("data/cache/spotify_token_cache")
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SPOTIFY_SCOPES,
        cache_path=str(cache_file),
        open_browser=True,
    )

    return spotipy.Spotify(auth_manager=auth_manager)
