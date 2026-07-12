"""Turns selected songs into physical card rows: ids, backgrounds, QR payloads.

Card numbering continues the registry's per-expansion sequence so delta print
runs never renumber existing cards. The QR payload is the song's public Spotify
track URL (see docs/qr-deck-contract.md).
"""

from __future__ import annotations

import pandas as pd

from gitster.deck.registry import make_card_id, next_card_number, split_owners
from gitster.identity import normalize_string_list, normalize_string_scalar

FRONT_BG_IDS = [f"g{index:02d}" for index in range(1, 13)]

CARD_COLUMNS = [
    "selection_rank",
    "card_id",
    "expansion_anchor",
    "is_new",
    "song_id",
    "winner_track_id",
    "track_url",
    "qr_payload",
    "front_bg_id",
    "title_display",
    "artists_display_resolved",
    "primary_artist_name",
    "secondary_artist_names",
    "year_final",
    "owners",
    "owners_display",
    "owner_color",
]

SPOTIFY_TRACK_URL_PREFIX = "https://open.spotify.com/track/"


def build_owner_name_map(instances_df: pd.DataFrame) -> dict[str, str]:
    owner_name_map: dict[str, str] = {}
    owner_rows = instances_df[["owner_id", "owner_name"]].dropna(subset=["owner_id"]).to_dict(orient="records")
    for row in owner_rows:
        owner_id = normalize_string_scalar(row.get("owner_id"))
        owner_name = normalize_string_scalar(row.get("owner_name"))
        if owner_id is None or owner_id in owner_name_map:
            continue
        owner_name_map[owner_id] = owner_name or owner_id
    return owner_name_map


def build_track_url_map(instances_df: pd.DataFrame) -> dict[str, str]:
    track_url_map: dict[str, str] = {}
    track_rows = instances_df[["track_id", "track_url"]].dropna(subset=["track_id"]).to_dict(orient="records")
    for row in track_rows:
        track_id = normalize_string_scalar(row.get("track_id"))
        track_url = normalize_string_scalar(row.get("track_url"))
        if track_id is None or track_id in track_url_map or track_url is None:
            continue
        track_url_map[track_id] = track_url
    return track_url_map


def format_owners_display(owner_ids: list[str], owner_name_map: dict[str, str]) -> str:
    owner_names: list[str] = []
    for owner_id in normalize_string_list(owner_ids):
        owner_name = normalize_string_scalar(owner_name_map.get(owner_id)) or owner_id
        if owner_name not in owner_names:
            owner_names.append(owner_name)
    if not owner_names:
        return ""
    return f"({', '.join(owner_names)})"


def _resolve_track_url(record: dict, track_url_map: dict[str, str]) -> str:
    winner_track_id = normalize_string_scalar(record.get("winner_track_id"))
    if winner_track_id is None:
        raise ValueError(f"Song {record.get('song_id')!r} has no winner_track_id; cannot build its QR")
    return track_url_map.get(winner_track_id) or f"{SPOTIFY_TRACK_URL_PREFIX}{winner_track_id}"


def build_new_card_rows(
    new_cards_df: pd.DataFrame,
    registry_df: pd.DataFrame,
    *,
    owner_name_map: dict[str, str],
    track_url_map: dict[str, str],
    owner_color_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Card rows for freshly selected songs, numbered after the registry's last card."""
    if new_cards_df.empty:
        return pd.DataFrame(columns=CARD_COLUMNS)

    next_numbers: dict[str, int] = {}
    rows: list[dict] = []
    for record in new_cards_df.to_dict(orient="records"):
        anchor = record["expansion_anchor"]
        number = next_numbers.get(anchor, next_card_number(registry_df, anchor))
        next_numbers[anchor] = number + 1

        track_url = _resolve_track_url(record, track_url_map)
        owner_ids = normalize_string_list(record.get("owner_ids"))
        title_display = normalize_string_scalar(record.get("title_display_resolved")) or normalize_string_scalar(
            record.get("title_display")
        )
        artists_display = normalize_string_scalar(record.get("artists_display_resolved")) or normalize_string_scalar(
            record.get("artists_display")
        )

        rows.append(
            {
                "selection_rank": number,
                "card_id": make_card_id(anchor, number),
                "expansion_anchor": anchor,
                "is_new": True,
                "song_id": record["song_id"],
                "winner_track_id": record["winner_track_id"],
                "track_url": track_url,
                "qr_payload": track_url,
                "front_bg_id": FRONT_BG_IDS[(number - 1) % len(FRONT_BG_IDS)],
                "title_display": title_display,
                "artists_display_resolved": artists_display,
                "primary_artist_name": normalize_string_scalar(record.get("primary_artist_name")),
                "secondary_artist_names": normalize_string_list(record.get("secondary_artist_names")),
                "year_final": int(record["year_final"]),
                "owners": "|".join(owner_ids),
                "owners_display": format_owners_display(owner_ids, owner_name_map),
                "owner_color": (owner_color_map or {}).get(anchor),
            }
        )

    cards_df = pd.DataFrame(rows, columns=CARD_COLUMNS)
    missing_title = cards_df["title_display"].isna()
    if missing_title.any():
        raise ValueError(f"{int(missing_title.sum())} cards are missing a display title")
    return cards_df


def card_rows_from_registry(
    registry_df: pd.DataFrame,
    owner_name_map: dict[str, str],
    owner_color_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Card rows reconstructed from the registry (for full reprints and deck.json)."""
    if registry_df.empty:
        return pd.DataFrame(columns=CARD_COLUMNS)

    rows: list[dict] = []
    for record in registry_df.to_dict(orient="records"):
        number = int(str(record["card_id"]).rsplit("_", 1)[1])
        owner_ids = split_owners(record.get("owners"))
        track_url = f"{SPOTIFY_TRACK_URL_PREFIX}{record['winner_track_id']}"
        rows.append(
            {
                "selection_rank": number,
                "card_id": record["card_id"],
                "expansion_anchor": record["expansion_anchor"],
                "is_new": False,
                "song_id": record["song_id"],
                "winner_track_id": record["winner_track_id"],
                "track_url": track_url,
                "qr_payload": track_url,
                "front_bg_id": FRONT_BG_IDS[(number - 1) % len(FRONT_BG_IDS)],
                "title_display": record.get("title"),
                "artists_display_resolved": record.get("artists"),
                "primary_artist_name": None,
                "secondary_artist_names": [],
                "year_final": int(record["year"]) if pd.notna(record.get("year")) else None,
                "owners": record.get("owners"),
                "owners_display": format_owners_display(owner_ids, owner_name_map),
                "owner_color": (owner_color_map or {}).get(record["expansion_anchor"]),
            }
        )
    return pd.DataFrame(rows, columns=CARD_COLUMNS)


def registry_rows_from_cards(cards_df: pd.DataFrame, *, identity_version: str) -> pd.DataFrame:
    """Registry-shaped frame for append_cards from packaged card rows."""
    registry_df = pd.DataFrame(
        {
            "song_id": cards_df["song_id"],
            "winner_track_id": cards_df["winner_track_id"],
            "card_id": cards_df["card_id"],
            "title": cards_df["title_display"],
            "artists": cards_df["artists_display_resolved"],
            "year": cards_df["year_final"],
            "owners": cards_df["owners"],
            "expansion_anchor": cards_df["expansion_anchor"],
            "identity_version": identity_version,
        }
    )
    return registry_df
