"""deck.json export for the Android app (see docs/qr-deck-contract.md)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gitster.deck.registry import split_owners

logger = logging.getLogger(__name__)

APP_DECK_JSON_ENV_VAR = "GITSTER_APP_DECK_JSON_PATH"
SPOTIFY_TRACK_URL_PREFIX = "https://open.spotify.com/track/"


def build_deck_json(registry_df: pd.DataFrame, *, version: str) -> dict:
    cards = []
    for record in registry_df.to_dict(orient="records"):
        track_id = record["winner_track_id"]
        cards.append(
            {
                "card_id": record["card_id"],
                "title": record["title"],
                "artists": record["artists"],
                "year": int(record["year"]) if pd.notna(record.get("year")) else None,
                "owners": split_owners(record.get("owners")),
                "expansion": record["expansion_anchor"],
                "spotify_url": f"{SPOTIFY_TRACK_URL_PREFIX}{track_id}",
                "track_id": track_id,
            }
        )
    return {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cards": cards,
    }


def export_deck_json(registry_df: pd.DataFrame, *, version: str, out_path: Path) -> Path:
    """Write deck.json for the whole physical collection; mirror to the app if configured.

    If the GITSTER_APP_DECK_JSON_PATH environment variable points at the app's
    assets file, a copy is written there too.
    """
    payload = build_deck_json(registry_df, version=version)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote deck.json with %d cards to %s", len(payload["cards"]), out_path)

    app_path_value = os.getenv(APP_DECK_JSON_ENV_VAR)
    if app_path_value:
        app_path = Path(app_path_value)
        app_path.parent.mkdir(parents=True, exist_ok=True)
        app_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Mirrored deck.json to the app assets at %s", app_path)

    return out_path
