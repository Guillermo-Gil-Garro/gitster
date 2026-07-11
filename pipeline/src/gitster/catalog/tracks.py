"""Catalog step: build one snapshot row per unique track from the raw playlist items."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from gitster.config import RunConfig
from gitster.io_utils import read_parquet, write_csv, write_parquet_atomic
from gitster.paths import RunPaths

logger = logging.getLogger(__name__)


TRACK_SNAPSHOT_COLUMNS = [
    "run_id",
    "track_id",
    "track_name",
    "artist_ids",
    "artist_names",
    "primary_artist_id",
    "primary_artist_name",
    "secondary_artist_ids",
    "secondary_artist_names",
    "album_id",
    "album_name",
    "album_release_date_spotify",
    "album_release_date_precision",
    "duration_ms",
    "explicit",
    "is_local",
    "is_playable",
    "preview_url",
    "track_uri",
    "track_url",
    "isrc",
    "popularity",
]

QC_COLUMNS = [
    "run_id",
    "track_ids_input",
    "tracks_snapshot_rows",
    "pct_missing_isrc",
    "pct_missing_album_release_date",
    "pct_missing_preview_url",
    "pct_missing_popularity",
]


def _unique_track_ids(values) -> list[str]:
    track_ids: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value is None:
            continue
        if not isinstance(value, str):
            if pd.isna(value):
                continue
            value = str(value)

        track_id = value.strip()
        if not track_id or track_id in seen:
            continue

        seen.add(track_id)
        track_ids.append(track_id)

    return track_ids


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            yield json.loads(payload)


def _extract_track_payload(row: object) -> dict | None:
    if not isinstance(row, dict):
        return None

    track = row.get("track")
    if isinstance(track, dict):
        return track

    item = row.get("item")
    if isinstance(item, dict):
        return item

    return None


def _extract_artist_lists(track_payload: dict) -> tuple[list, list]:
    artists = track_payload.get("artists") or []
    if not isinstance(artists, list):
        return [], []

    artist_ids: list[str | None] = []
    artist_names: list[str | None] = []
    for artist in artists:
        if not isinstance(artist, dict):
            continue
        artist_ids.append(artist.get("id"))
        artist_names.append(artist.get("name"))

    return artist_ids, artist_names


def _normalize_track_payload(run_id: str, row: dict, track_payload: dict) -> dict | None:
    track_id = track_payload.get("id")
    if not track_id:
        return None

    album = track_payload.get("album") or {}
    if not isinstance(album, dict):
        album = {}

    external_ids = track_payload.get("external_ids") or {}
    if not isinstance(external_ids, dict):
        external_ids = {}

    external_urls = track_payload.get("external_urls") or {}
    if not isinstance(external_urls, dict):
        external_urls = {}

    artist_ids, artist_names = _extract_artist_lists(track_payload)
    primary_artist_id = artist_ids[0] if artist_ids else None
    primary_artist_name = artist_names[0] if artist_names else None
    secondary_artist_ids = artist_ids[1:] if len(artist_ids) > 1 else []
    secondary_artist_names = artist_names[1:] if len(artist_names) > 1 else []

    is_local = track_payload.get("is_local")
    if is_local is None and isinstance(row, dict):
        is_local = row.get("is_local")

    return {
        "run_id": run_id,
        "track_id": track_id,
        "track_name": track_payload.get("name"),
        "artist_ids": artist_ids,
        "artist_names": artist_names,
        "primary_artist_id": primary_artist_id,
        "primary_artist_name": primary_artist_name,
        "secondary_artist_ids": secondary_artist_ids,
        "secondary_artist_names": secondary_artist_names,
        "album_id": album.get("id"),
        "album_name": album.get("name"),
        "album_release_date_spotify": album.get("release_date"),
        "album_release_date_precision": album.get("release_date_precision"),
        "duration_ms": track_payload.get("duration_ms"),
        "explicit": track_payload.get("explicit"),
        "is_local": is_local,
        "is_playable": track_payload.get("is_playable"),
        "preview_url": track_payload.get("preview_url"),
        "track_uri": track_payload.get("uri"),
        "track_url": external_urls.get("spotify"),
        "isrc": external_ids.get("isrc"),
        "popularity": track_payload.get("popularity"),
    }


def _is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return bool(pd.isna(value))


def _missing_pct(values: list) -> float:
    if not values:
        return 0.0
    missing_count = sum(1 for value in values if _is_missing(value))
    return round((missing_count / len(values)) * 100.0, 2)


def run_tracks_snapshot(config: RunConfig, paths: RunPaths) -> None:
    logger.info("Catalog step: tracks snapshot")

    instances_path = paths.processed_dir / "instances.parquet"
    if not instances_path.exists():
        raise FileNotFoundError(f"Missing {instances_path}; run instances before tracks")

    raw_spotify_dir = paths.raw_dir / "spotify"
    if not raw_spotify_dir.exists():
        raise FileNotFoundError(f"Missing {raw_spotify_dir}; run ingest before tracks")

    instances_df = read_parquet(instances_path)
    track_ids_order = _unique_track_ids(instances_df.get("track_id", pd.Series(dtype="object")).tolist())
    track_ids_set = set(track_ids_order)

    snapshot_by_track_id: dict[str, dict] = {}

    for owner in config.owners:
        items_path = raw_spotify_dir / f"playlist_items_{owner.owner_id}.jsonl"
        if not items_path.exists():
            raise FileNotFoundError(f"Missing {items_path}; run ingest before tracks")

        for row in _iter_jsonl(items_path):
            track_payload = _extract_track_payload(row)
            if track_payload is None:
                continue

            if track_payload.get("type") != "track" or track_payload.get("episode") is True:
                continue

            is_local = track_payload.get("is_local")
            if is_local is None and isinstance(row, dict):
                is_local = row.get("is_local")
            if is_local is True:
                continue

            normalized_row = _normalize_track_payload(paths.run_id, row, track_payload)
            if normalized_row is None:
                continue

            track_id = normalized_row["track_id"]
            if track_id not in track_ids_set or track_id in snapshot_by_track_id:
                continue

            snapshot_by_track_id[track_id] = normalized_row

        if len(snapshot_by_track_id) == len(track_ids_set):
            break

    snapshot_rows = [snapshot_by_track_id[track_id] for track_id in track_ids_order if track_id in snapshot_by_track_id]
    tracks_df = pd.DataFrame(snapshot_rows, columns=TRACK_SNAPSHOT_COLUMNS)
    qc_row = {
        "run_id": paths.run_id,
        "track_ids_input": len(track_ids_order),
        "tracks_snapshot_rows": len(snapshot_rows),
        "pct_missing_isrc": _missing_pct(tracks_df["isrc"].tolist() if not tracks_df.empty else []),
        "pct_missing_album_release_date": _missing_pct(
            tracks_df["album_release_date_spotify"].tolist() if not tracks_df.empty else []
        ),
        "pct_missing_preview_url": _missing_pct(tracks_df["preview_url"].tolist() if not tracks_df.empty else []),
        "pct_missing_popularity": _missing_pct(tracks_df["popularity"].tolist() if not tracks_df.empty else []),
    }
    qc_df = pd.DataFrame([qc_row], columns=QC_COLUMNS)

    write_parquet_atomic(paths.processed_dir / "tracks_snapshot.parquet", tracks_df)
    write_csv(paths.reports_dir / "qc_tracks.csv", qc_df)

    logger.info(
        "OK | track_ids_input=%s | tracks_snapshot_rows=%s",
        qc_row["track_ids_input"],
        qc_row["tracks_snapshot_rows"],
    )
