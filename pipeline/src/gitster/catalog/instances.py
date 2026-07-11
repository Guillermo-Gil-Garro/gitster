"""Catalog step: normalize raw playlist items into per-owner track instances."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from gitster.config import OwnerPlaylist, RunConfig
from gitster.io_utils import write_csv, write_parquet_atomic
from gitster.paths import RunPaths

logger = logging.getLogger(__name__)


INSTANCE_COLUMNS = [
    "run_id",
    "owner_id",
    "owner_name",
    "playlist_id",
    "playlist_input",
    "track_id",
    "track_name",
    "artist_ids",
    "artist_names",
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
    "added_at",
]

QC_COLUMNS = [
    "owner_id",
    "rows_raw",
    "rows_valid_track",
    "rows_skipped_null",
    "rows_skipped_non_track",
    "rows_skipped_local",
    "rows_dedup_removed",
    "instances_final",
]


def _load_playlist_meta(raw_spotify_dir: Path, owner: OwnerPlaylist) -> dict:
    meta_path = raw_spotify_dir / f"playlist_meta_{owner.owner_id}.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"Missing {meta_path}; run ingest before instances")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.setdefault("owner_id", owner.owner_id)
    meta.setdefault("owner_name", owner.owner_name)
    meta.setdefault("playlist_input", owner.playlist)
    return meta


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


def _added_at_sort_key(value: str | None) -> tuple[bool, str]:
    return (value is None, value or "")


def _build_instance_row(paths: RunPaths, meta: dict, row: dict, track_payload: dict) -> dict | None:
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

    is_local = track_payload.get("is_local")
    if is_local is None and isinstance(row, dict):
        is_local = row.get("is_local")

    return {
        "run_id": paths.run_id,
        "owner_id": meta.get("owner_id"),
        "owner_name": meta.get("owner_name"),
        "playlist_id": meta.get("playlist_id"),
        "playlist_input": meta.get("playlist_input"),
        "track_id": track_id,
        "track_name": track_payload.get("name"),
        "artist_ids": artist_ids,
        "artist_names": artist_names,
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
        "added_at": row.get("added_at"),
    }


def run_instances(config: RunConfig, paths: RunPaths) -> None:
    logger.info("Catalog step: instances")

    raw_spotify_dir = paths.raw_dir / "spotify"
    instance_rows: list[dict] = []
    qc_rows: list[dict] = []

    for owner in config.owners:
        meta = _load_playlist_meta(raw_spotify_dir, owner)
        items_path = raw_spotify_dir / f"playlist_items_{owner.owner_id}.jsonl"
        if not items_path.exists():
            raise FileNotFoundError(f"Missing {items_path}; run ingest before instances")

        rows_raw = 0
        rows_valid_track = 0
        rows_skipped_null = 0
        rows_skipped_non_track = 0
        rows_skipped_local = 0

        instances_by_track_id: dict[str, dict] = {}

        for row in _iter_jsonl(items_path):
            rows_raw += 1

            track_payload = _extract_track_payload(row)
            if track_payload is None:
                rows_skipped_null += 1
                continue

            if track_payload.get("type") != "track" or track_payload.get("episode") is True:
                rows_skipped_non_track += 1
                continue

            is_local = track_payload.get("is_local")
            if is_local is None and isinstance(row, dict):
                is_local = row.get("is_local")
            if is_local is True:
                rows_skipped_local += 1
                continue

            instance_row = _build_instance_row(paths, meta, row, track_payload)
            if instance_row is None:
                rows_skipped_null += 1
                continue

            rows_valid_track += 1

            existing_row = instances_by_track_id.get(instance_row["track_id"])
            if existing_row is None or _added_at_sort_key(instance_row["added_at"]) < _added_at_sort_key(
                existing_row["added_at"]
            ):
                instances_by_track_id[instance_row["track_id"]] = instance_row

        owner_rows = sorted(
            instances_by_track_id.values(),
            key=lambda item: (item["owner_id"], _added_at_sort_key(item["added_at"]), item["track_id"]),
        )
        instance_rows.extend(owner_rows)

        rows_dedup_removed = rows_valid_track - len(owner_rows)
        qc_row = {
            "owner_id": owner.owner_id,
            "rows_raw": rows_raw,
            "rows_valid_track": rows_valid_track,
            "rows_skipped_null": rows_skipped_null,
            "rows_skipped_non_track": rows_skipped_non_track,
            "rows_skipped_local": rows_skipped_local,
            "rows_dedup_removed": rows_dedup_removed,
            "instances_final": len(owner_rows),
        }
        qc_rows.append(qc_row)

        logger.info(
            "OK | owner_id=%s | rows_raw=%s | rows_valid_track=%s | instances_final=%s",
            owner.owner_id,
            rows_raw,
            rows_valid_track,
            len(owner_rows),
        )

    instances_df = pd.DataFrame(instance_rows, columns=INSTANCE_COLUMNS)
    qc_df = pd.DataFrame(qc_rows, columns=QC_COLUMNS)

    write_parquet_atomic(paths.processed_dir / "instances.parquet", instances_df)
    write_csv(paths.reports_dir / "qc_instances.csv", qc_df)
