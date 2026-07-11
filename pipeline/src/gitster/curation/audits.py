"""Audit exports: flat CSV/XLSX views of tracks and songs for manual inspection."""

from __future__ import annotations

import logging

import pandas as pd

from gitster.config import RunConfig
from gitster.identity import compute_base_title_norm, normalize_string_list
from gitster.io_utils import read_parquet, write_csv, write_xlsx
from gitster.paths import RunPaths


logger = logging.getLogger(__name__)

AUDIT_TRACKS_COLUMNS = [
    "run_id",
    "track_id",
    "track_name",
    "artist_names",
    "artist_count",
    "primary_artist_id",
    "primary_artist_name",
    "secondary_artist_ids",
    "secondary_artist_names",
    "secondary_artist_count",
    "album_id",
    "album_name",
    "album_release_date_spotify",
    "album_release_date_precision",
    "isrc",
    "explicit",
    "duration_ms",
    "track_uri",
    "track_url",
    "has_secondary_artists",
    "title_has_collapsible_tag",
    "year_precision_low",
    "missing_isrc",
]

AUDIT_SONGS_COLUMNS = [
    "run_id",
    "song_id",
    "winner_track_id",
    "title_display",
    "base_title_norm",
    "primary_artist_id",
    "primary_artist_name",
    "secondary_artist_ids",
    "secondary_artist_names",
    "feat_signature",
    "track_ids_merged",
    "merged_track_count",
    "owners_count",
    "album_release_date_spotify",
    "year_candidate",
    "year_final",
    "song_key_type",
    "isrc",
    "in_candidates",
    "selection_phase",
    "has_secondary_artists",
    "has_merge",
    "title_has_collapsible_tag",
    "year_precision_low",
    "missing_isrc",
]


def _serialize_list(value) -> str:
    items = normalize_string_list(value)
    return " | ".join(items)


def _list_count(value) -> int:
    return len(normalize_string_list(value))


def _missing_string(value) -> bool:
    if value is None or pd.isna(value):
        return True
    return str(value).strip() == ""


def _has_collapsible_tag(value) -> bool:
    _, had_collapsible_suffix, _ = compute_base_title_norm(value)
    return had_collapsible_suffix


def _build_audit_tracks_df(tracks_df: pd.DataFrame, *, run_id: str) -> pd.DataFrame:
    audit_df = tracks_df.copy()
    if "secondary_artist_names" not in audit_df.columns:
        audit_df["secondary_artist_names"] = [[] for _ in range(len(audit_df))]
    audit_df["run_id"] = audit_df["run_id"].fillna(run_id)
    audit_df["artist_names"] = audit_df["artist_names"].map(_serialize_list)
    audit_df["artist_count"] = tracks_df["artist_names"].map(_list_count).astype("Int64")
    audit_df["secondary_artist_ids"] = audit_df["secondary_artist_ids"].map(_serialize_list)
    audit_df["secondary_artist_names"] = audit_df["secondary_artist_names"].map(_serialize_list)
    audit_df["secondary_artist_count"] = tracks_df["secondary_artist_ids"].map(_list_count).astype("Int64")
    audit_df["has_secondary_artists"] = audit_df["secondary_artist_count"] > 0
    audit_df["title_has_collapsible_tag"] = audit_df["track_name"].map(_has_collapsible_tag)
    audit_df["year_precision_low"] = audit_df["album_release_date_precision"].isin(["year"]) | audit_df[
        "album_release_date_precision"
    ].isna()
    audit_df["missing_isrc"] = audit_df["isrc"].map(_missing_string)
    return audit_df.reindex(columns=AUDIT_TRACKS_COLUMNS)


def _build_audit_songs_df(
    songs_df: pd.DataFrame,
    years_df: pd.DataFrame,
    candidates_df: pd.DataFrame,
    *,
    run_id: str,
) -> pd.DataFrame:
    songs_df = songs_df.copy()
    if "secondary_artist_names" not in songs_df.columns:
        songs_df["secondary_artist_names"] = [[] for _ in range(len(songs_df))]

    candidate_flags_df = candidates_df[["song_id", "selection_phase"]].copy()
    candidate_flags_df["in_candidates"] = True

    audit_df = songs_df.merge(
        years_df[
            [
                "song_id",
                "winner_track_id",
                "year_candidate",
                "year_final",
                "year_candidate_precision",
            ]
        ],
        on=["song_id", "winner_track_id"],
        how="left",
    ).merge(
        candidate_flags_df,
        on="song_id",
        how="left",
    )

    audit_df["run_id"] = audit_df["run_id"].fillna(run_id)
    audit_df["secondary_artist_ids"] = audit_df["secondary_artist_ids"].map(_serialize_list)
    audit_df["secondary_artist_names"] = audit_df["secondary_artist_names"].map(_serialize_list)
    audit_df["feat_signature"] = audit_df["feat_signature"].map(_serialize_list)
    audit_df["track_ids_merged"] = audit_df["track_ids_merged"].map(_serialize_list)
    audit_df["merged_track_count"] = songs_df["track_ids_merged"].map(_list_count).astype("Int64")
    audit_df["in_candidates"] = audit_df["in_candidates"].fillna(False).astype(bool)
    audit_df["has_secondary_artists"] = songs_df["secondary_artist_ids"].map(_list_count).gt(0)
    audit_df["has_merge"] = audit_df["merged_track_count"] > 1
    audit_df["title_has_collapsible_tag"] = audit_df["title_display"].map(_has_collapsible_tag)
    audit_df["year_precision_low"] = audit_df["year_candidate_precision"].isin(["year"]) | audit_df[
        "year_candidate_precision"
    ].isna()
    audit_df["missing_isrc"] = audit_df["isrc"].map(_missing_string)

    if not audit_df.empty:
        for column in ["owners_count", "year_candidate", "year_final", "merged_track_count"]:
            audit_df[column] = audit_df[column].astype("Int64")

    return audit_df.reindex(columns=AUDIT_SONGS_COLUMNS)


def run_audit_exports(config: RunConfig, paths: RunPaths) -> None:
    logger.info("Step: audit exports")

    tracks_path = paths.processed_dir / "tracks_snapshot.parquet"
    songs_path = paths.processed_dir / "songs.parquet"
    years_path = paths.processed_dir / "years_baseline.parquet"
    candidates_path = paths.processed_dir / "candidates.parquet"

    for required_path, step_name in [
        (tracks_path, "tracks"),
        (songs_path, "identity"),
        (years_path, "years"),
        (candidates_path, "candidates"),
    ]:
        if not required_path.exists():
            raise FileNotFoundError(f"{required_path} not found; run the {step_name} step before audit exports")

    tracks_df = read_parquet(tracks_path)
    songs_df = read_parquet(songs_path)
    years_df = read_parquet(years_path)
    candidates_df = read_parquet(candidates_path)

    audit_tracks_df = _build_audit_tracks_df(tracks_df, run_id=paths.run_id)
    audit_songs_df = _build_audit_songs_df(
        songs_df,
        years_df,
        candidates_df,
        run_id=paths.run_id,
    )

    write_csv(paths.reports_dir / "audit_tracks.csv", audit_tracks_df)
    write_csv(paths.reports_dir / "audit_songs.csv", audit_songs_df)
    write_xlsx(paths.reports_dir / "audit_tracks.xlsx", audit_tracks_df, sheet_name="audit_tracks")
    write_xlsx(paths.reports_dir / "audit_songs.xlsx", audit_songs_df, sheet_name="audit_songs")

    has_secondary_artists_count = int(audit_songs_df["has_secondary_artists"].sum()) if not audit_songs_df.empty else 0
    has_merge_count = int(audit_songs_df["has_merge"].sum()) if not audit_songs_df.empty else 0
    logger.info(
        "OK | audit_tracks_rows=%s | audit_songs_rows=%s | has_secondary_artists=%s | has_merge=%s",
        len(audit_tracks_df),
        len(audit_songs_df),
        has_secondary_artists_count,
        has_merge_count,
    )
