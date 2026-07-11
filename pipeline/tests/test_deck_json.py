from __future__ import annotations

import json

import pandas as pd

from gitster.export.deck_json import build_deck_json, export_deck_json


def _registry() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "song_id": "s1",
                "winner_track_id": "4uLU6hMCjMI75M1A2tKUQC",
                "card_id": "GITSTER_ANA_001",
                "title": "Song One",
                "artists": "Artist A feat. Artist B",
                "year": 1999,
                "owners": "ana|bob",
                "expansion_anchor": "ana",
                "printed_status": "printed",
                "version": "baseline",
            }
        ]
    )


def test_build_deck_json_schema():
    payload = build_deck_json(_registry(), version="baseline")

    assert payload["version"] == "baseline"
    assert "generated_at" in payload
    card = payload["cards"][0]
    assert card == {
        "card_id": "GITSTER_ANA_001",
        "title": "Song One",
        "artists": "Artist A feat. Artist B",
        "year": 1999,
        "owners": ["ana", "bob"],
        "expansion": "ana",
        "spotify_url": "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
        "track_id": "4uLU6hMCjMI75M1A2tKUQC",
    }
    assert isinstance(card["year"], int)


def test_export_writes_file_and_mirrors_to_app(tmp_path, monkeypatch):
    app_path = tmp_path / "app" / "deck.json"
    monkeypatch.setenv("GITSTER_APP_DECK_JSON_PATH", str(app_path))

    out_path = export_deck_json(_registry(), version="baseline", out_path=tmp_path / "deck.json")

    for path in (out_path, app_path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert len(payload["cards"]) == 1
