"""Global curation store: cross-run catalogs and curation state persisted outside runs."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from gitster.io_utils import write_parquet_atomic


TRACK_CATALOG_COLUMNS = [
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

SONG_CATALOG_COLUMNS = [
    "run_id",
    "identity_version",
    "song_id",
    "winner_track_id",
    "song_key_type",
    "track_ids_merged",
    "title_display",
    "base_title_norm",
    "primary_artist_id",
    "primary_artist_name",
    "secondary_artist_ids",
    "secondary_artist_names",
    "feat_signature",
    "isrc",
    "album_id",
    "album_release_date_spotify",
    "album_release_date_spotify_source",
    "album_release_date_spotify_track_id",
    "explicit",
    "popularity_winner",
    "owners_count",
]

CURATION_COLUMNS = [
    "entity_type",
    "entity_id",
    "identity_version",
    "year_override",
    "artists_display_override",
    "title_display_override",
    "updated_at",
    "run_id",
    "note",
]


def _empty_df(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _read_or_empty(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return _empty_df(columns)

    df = pd.read_parquet(path)
    for column in columns:
        if column not in df.columns:
            df[column] = None
    return df[columns]


def _union_columns(existing_df: pd.DataFrame, incoming_df: pd.DataFrame, preferred_columns: list[str]) -> list[str]:
    columns = list(preferred_columns)
    for frame in [existing_df, incoming_df]:
        for column in frame.columns.tolist():
            if column not in columns:
                columns.append(column)
    return columns


def _upsert_table(path: Path, incoming_df: pd.DataFrame, key_columns: list[str], preferred_columns: list[str]) -> pd.DataFrame:
    existing_df = pd.read_parquet(path) if path.exists() else _empty_df(preferred_columns)
    columns = _union_columns(existing_df, incoming_df, preferred_columns)

    existing_aligned = existing_df.reindex(columns=columns)
    incoming_aligned = incoming_df.reindex(columns=columns)

    combined_df = pd.concat([existing_aligned, incoming_aligned], ignore_index=True)
    if combined_df.empty:
        combined_df = _empty_df(columns)
    else:
        combined_df = combined_df.drop_duplicates(subset=key_columns, keep="last")

    write_parquet_atomic(path, combined_df)
    return combined_df


def resolve_global_store_dir() -> Path:
    load_dotenv(dotenv_path=".env")

    store_dir_value = os.getenv("GITSTER_GLOBAL_STORE_DIR")
    if not store_dir_value:
        raise RuntimeError("GITSTER_GLOBAL_STORE_DIR missing from .env")

    store_dir = Path(store_dir_value)
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


def bootstrap_global_store(store_dir: Path) -> dict[str, Path]:
    store_dir.mkdir(parents=True, exist_ok=True)
    history_dir = store_dir / "curation_history"
    history_dir.mkdir(parents=True, exist_ok=True)

    track_catalog_path = store_dir / "track_catalog.parquet"
    song_catalog_path = store_dir / "song_catalog.parquet"
    curation_current_path = store_dir / "curation_current.parquet"

    if not track_catalog_path.exists():
        write_parquet_atomic(track_catalog_path, _empty_df(TRACK_CATALOG_COLUMNS))
    if not song_catalog_path.exists():
        write_parquet_atomic(song_catalog_path, _empty_df(SONG_CATALOG_COLUMNS))
    if not curation_current_path.exists():
        write_parquet_atomic(curation_current_path, _empty_df(CURATION_COLUMNS))

    return {
        "store_dir": store_dir,
        "history_dir": history_dir,
        "track_catalog_path": track_catalog_path,
        "song_catalog_path": song_catalog_path,
        "curation_current_path": curation_current_path,
    }


def append_curation_history(store_dir: Path, run_id: str, events_df: pd.DataFrame) -> Path | None:
    if events_df.empty:
        return None

    history_path = store_dir / "curation_history" / f"{run_id}.parquet"
    existing_df = _read_or_empty(history_path, CURATION_COLUMNS)
    incoming_df = events_df.reindex(columns=CURATION_COLUMNS)
    combined_df = pd.concat([existing_df, incoming_df], ignore_index=True)
    write_parquet_atomic(history_path, combined_df)
    return history_path


def load_curation_history_events(store_dir: Path) -> pd.DataFrame:
    history_dir = store_dir / "curation_history"
    history_dir.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    file_order = 0
    for history_path in sorted(history_dir.glob("*.parquet")):
        history_df = _read_or_empty(history_path, CURATION_COLUMNS)
        if history_df.empty:
            file_order += 1
            continue

        history_df = history_df.copy()
        history_df["_history_file_order"] = file_order
        history_df["_history_row_order"] = range(len(history_df))
        frames.append(history_df)
        file_order += 1

    if not frames:
        return pd.DataFrame(columns=CURATION_COLUMNS + ["_history_file_order", "_history_row_order"])

    return pd.concat(frames, ignore_index=True)


def sync_track_catalog(store_dir: Path, tracks_df: pd.DataFrame) -> pd.DataFrame:
    return _upsert_table(
        store_dir / "track_catalog.parquet",
        tracks_df.reindex(columns=TRACK_CATALOG_COLUMNS),
        key_columns=["track_id"],
        preferred_columns=TRACK_CATALOG_COLUMNS,
    )


def sync_song_catalog(store_dir: Path, songs_df: pd.DataFrame) -> pd.DataFrame:
    return _upsert_table(
        store_dir / "song_catalog.parquet",
        songs_df.reindex(columns=SONG_CATALOG_COLUMNS),
        key_columns=["song_id", "identity_version"],
        preferred_columns=SONG_CATALOG_COLUMNS,
    )


def load_curation_current(store_dir: Path) -> pd.DataFrame:
    curation_path = store_dir / "curation_current.parquet"
    curation_df = _read_or_empty(curation_path, CURATION_COLUMNS)
    if curation_df.empty:
        return curation_df

    return curation_df.drop_duplicates(
        subset=["entity_type", "entity_id", "identity_version"],
        keep="last",
    )


def recompute_curation_current(store_dir: Path) -> pd.DataFrame:
    current_path = store_dir / "curation_current.parquet"
    current_df = _read_or_empty(current_path, CURATION_COLUMNS)
    history_df = load_curation_history_events(store_dir)

    frames: list[pd.DataFrame] = []
    if not current_df.empty:
        current_df = current_df.copy()
        current_df["_history_file_order"] = -1
        current_df["_history_row_order"] = range(len(current_df))
        frames.append(current_df)
    if not history_df.empty:
        frames.append(history_df)

    if not frames:
        empty_df = _empty_df(CURATION_COLUMNS)
        write_parquet_atomic(current_path, empty_df)
        return empty_df

    combined_df = pd.concat(frames, ignore_index=True)
    combined_df["_updated_at_sort"] = pd.to_datetime(combined_df["updated_at"], errors="coerce")
    combined_df["_run_id_sort"] = combined_df["run_id"].fillna("")
    combined_df = combined_df.sort_values(
        by=["_updated_at_sort", "_run_id_sort", "_history_file_order", "_history_row_order"],
        kind="stable",
    )
    current_df = combined_df.drop_duplicates(
        subset=["entity_type", "entity_id", "identity_version"],
        keep="last",
    )[CURATION_COLUMNS]

    write_parquet_atomic(current_path, current_df)
    return current_df
