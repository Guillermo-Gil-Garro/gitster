"""Catalog step: ingest playlists from the Spotify API into raw JSON/JSONL files."""

from __future__ import annotations

import json
import logging

from gitster.config import RunConfig, extract_playlist_id
from gitster.paths import RunPaths
from gitster.spotify_client import get_spotify_client

logger = logging.getLogger(__name__)


def _extract_tracks_total(playlist: dict) -> int | None:
    playlist_tracks = playlist.get("tracks") or {}
    if isinstance(playlist_tracks, dict):
        tracks_total = playlist_tracks.get("total")
        if tracks_total is not None:
            return tracks_total

    playlist_items = playlist.get("items") or {}
    if isinstance(playlist_items, dict):
        return playlist_items.get("total")

    return None


def _iter_playlist_items(sp, playlist_id: str):
    limit = 100
    offset = 0

    while True:
        page = sp.playlist_items(
            playlist_id,
            limit=limit,
            offset=offset,
            additional_types=("track",),
        )
        page_items = page.get("items") or []
        if not isinstance(page_items, list):
            page_items = []

        for item in page_items:
            yield item

        fetched_count = len(page_items)
        if fetched_count == 0:
            break

        offset += fetched_count
        if fetched_count < limit:
            break

        total = page.get("total")
        if total is not None and offset >= total:
            break


def _get_item_track_payload(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None

    track = item.get("track")
    if isinstance(track, dict):
        return track

    track = item.get("item")
    if isinstance(track, dict):
        return track

    return None


def run_ingest(config: RunConfig, paths: RunPaths) -> None:
    logger.info("Catalog step: ingest")

    sp = get_spotify_client()

    raw_spotify_dir = paths.raw_dir / "spotify"
    raw_spotify_dir.mkdir(parents=True, exist_ok=True)

    playlist_meta_rows: list[dict] = []

    for owner in config.owners:
        playlist_id = extract_playlist_id(owner.playlist)
        playlist = sp.playlist(playlist_id)
        playlist_owner = playlist.get("owner") or {}
        playlist_urls = playlist.get("external_urls") or {}
        resolved_playlist_id = playlist.get("id") or playlist_id
        tracks_total = _extract_tracks_total(playlist)

        items_path = raw_spotify_dir / f"playlist_items_{owner.owner_id}.jsonl"
        items_fetched = 0
        items_with_track = 0
        items_without_track = 0

        with items_path.open("w", encoding="utf-8") as items_file:
            for item in _iter_playlist_items(sp, resolved_playlist_id):
                items_file.write(json.dumps(item, ensure_ascii=False))
                items_file.write("\n")

                items_fetched += 1
                if _get_item_track_payload(item) is not None:
                    items_with_track += 1
                else:
                    items_without_track += 1

        row = {
            "owner_id": owner.owner_id,
            "owner_name": owner.owner_name,
            "playlist_input": owner.playlist,
            "playlist_id": resolved_playlist_id,
            "playlist_name": playlist.get("name"),
            "playlist_owner_spotify_id": playlist_owner.get("id"),
            "playlist_owner_spotify_name": playlist_owner.get("display_name"),
            "tracks_total": tracks_total,
            "public": playlist.get("public"),
            "collaborative": playlist.get("collaborative"),
            "snapshot_id": playlist.get("snapshot_id"),
            "playlist_url": playlist_urls.get("spotify") or owner.playlist,
            "items_fetched": items_fetched,
            "items_with_track": items_with_track,
            "items_without_track": items_without_track,
        }
        playlist_meta_rows.append(row)

        out_path = raw_spotify_dir / f"playlist_meta_{owner.owner_id}.json"
        out_path.write_text(
            json.dumps(row, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.info(
            "OK | owner_id=%s | playlist_id=%s | name=%s | tracks_total=%s | "
            "items_fetched=%s | items_with_track=%s | items_without_track=%s",
            owner.owner_id,
            row["playlist_id"],
            row["playlist_name"],
            row["tracks_total"],
            row["items_fetched"],
            row["items_with_track"],
            row["items_without_track"],
        )

    summary_path = raw_spotify_dir / "playlist_meta_all.json"
    summary_path.write_text(
        json.dumps(playlist_meta_rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
