"""Curation sync: sync run catalogs to the global store and apply current curation to the run."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from gitster.artist_display import (
    build_artists_display_current,
    resolve_final_artists_display,
)
from gitster.config import RunConfig
from gitster.curation.candidates import (
    build_candidates_outputs,
    build_song_owner_ids_by_song_id,
)
from gitster.curation.store import (
    bootstrap_global_store,
    load_curation_current,
    resolve_global_store_dir,
    sync_song_catalog,
    sync_track_catalog,
)
from gitster.identity import IDENTITY_VERSION, normalize_string_list, normalize_string_scalar
from gitster.io_utils import read_parquet, write_csv, write_parquet_atomic, write_xlsx
from gitster.paths import RunPaths
from gitster.title_display import normalize_title_display


logger = logging.getLogger(__name__)

CURATION_APPLY_QC_COLUMNS = [
    "run_id",
    "songs_input",
    "songs_with_year_override",
    "songs_with_title_override",
    "songs_with_artists_override",
    "candidates_input",
    "candidates_output",
]

SONG_CURATION_COLUMNS = [
    "song_id",
    "year_override",
    "artists_display_override",
    "title_display_override",
    "curation_updated_at",
    "curation_run_id",
    "curation_note",
]

REVIEW_TEMPLATE_COLUMNS = [
    "song_id",
    "winner_track_id",
    "title_display_raw",
    "title_display_current",
    "title_display_override",
    "title_display_resolved",
    "title_display",
    "primary_artist_name",
    "secondary_artist_names",
    "has_secondary_artists",
    "artists_display_current",
    "artists_display",
    "album_release_date_spotify",
    "year_candidate",
    "year_final",
    "owners_count",
    "year_override",
    "artists_display_override",
    "note",
    "review_status",
    "review_keep",
]


def normalize_string_override(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    cleaned = str(value).strip()
    return cleaned or None


def coerce_year_override(value, *, strict: bool = False, song_id: str | None = None):
    if value is None or pd.isna(value):
        return pd.NA
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return pd.NA
    try:
        return int(value)
    except (TypeError, ValueError):
        if strict:
            song_suffix = f" for song_id={song_id}" if song_id else ""
            raise ValueError(f"Invalid year_override{song_suffix}: {value!r}") from None
        return pd.NA


def build_song_curation_frame(curation_df: pd.DataFrame) -> pd.DataFrame:
    if curation_df.empty:
        return pd.DataFrame(columns=SONG_CURATION_COLUMNS)

    filtered_df = curation_df[
        (curation_df["entity_type"] == "song") & (curation_df["identity_version"] == IDENTITY_VERSION)
    ].copy()
    if filtered_df.empty:
        return pd.DataFrame(columns=SONG_CURATION_COLUMNS)

    filtered_df["song_id"] = filtered_df["entity_id"]
    filtered_df["year_override"] = filtered_df["year_override"].apply(coerce_year_override)
    filtered_df["artists_display_override"] = filtered_df["artists_display_override"].apply(normalize_string_override)
    filtered_df["title_display_override"] = filtered_df["title_display_override"].apply(normalize_string_override)
    filtered_df["note"] = filtered_df["note"].apply(normalize_string_override)

    return filtered_df[
        [
            "song_id",
            "year_override",
            "artists_display_override",
            "title_display_override",
            "updated_at",
            "run_id",
            "note",
        ]
    ].rename(
        columns={
            "updated_at": "curation_updated_at",
            "run_id": "curation_run_id",
            "note": "curation_note",
        }
    )


def _load_apply_inputs(paths: RunPaths, *, require_tracks_snapshot: bool) -> dict[str, pd.DataFrame]:
    required_paths: list[tuple[Path, str]] = [
        (paths.processed_dir / "instances.parquet", "instances"),
        (paths.processed_dir / "songs.parquet", "identity"),
        (paths.processed_dir / "song_variant_map.parquet", "identity"),
        (paths.processed_dir / "years_baseline.parquet", "years"),
        (paths.processed_dir / "candidates.parquet", "candidates"),
    ]
    if require_tracks_snapshot:
        required_paths.insert(0, (paths.processed_dir / "tracks_snapshot.parquet", "tracks"))

    for required_path, step_name in required_paths:
        if not required_path.exists():
            raise FileNotFoundError(f"{required_path} not found; run the {step_name} step before this one")

    frames = {
        "instances": read_parquet(paths.processed_dir / "instances.parquet"),
        "songs": read_parquet(paths.processed_dir / "songs.parquet"),
        "song_variant_map": read_parquet(paths.processed_dir / "song_variant_map.parquet"),
        "years": read_parquet(paths.processed_dir / "years_baseline.parquet"),
        "candidates": read_parquet(paths.processed_dir / "candidates.parquet"),
    }
    if require_tracks_snapshot:
        frames["tracks"] = read_parquet(paths.processed_dir / "tracks_snapshot.parquet")

    return frames


def _build_songs_curated_df(songs_df: pd.DataFrame, song_curation_df: pd.DataFrame) -> pd.DataFrame:
    curated_df = songs_df.merge(song_curation_df, on="song_id", how="left")
    curated_df["title_display_raw"] = curated_df["title_display"]
    curated_df["title_display_original"] = curated_df["title_display_raw"]
    curated_df["title_display_current"] = curated_df["title_display_raw"].map(normalize_title_display)
    curated_df["title_display_current"] = curated_df["title_display_current"].combine_first(curated_df["title_display_raw"])
    curated_df["title_display_resolved"] = curated_df["title_display_override"].combine_first(
        curated_df["title_display_current"]
    )
    curated_df["title_display"] = curated_df["title_display_resolved"]
    curated_df["artists_display_current"] = curated_df.apply(
        lambda row: build_artists_display_current(
            row.get("primary_artist_name"),
            row.get("secondary_artist_names"),
        ),
        axis=1,
    )
    curated_df["artists_display_resolved"] = curated_df.apply(
        lambda row: resolve_final_artists_display(
            row,
            allow_legacy_display=False,
            allow_raw_fallback=True,
        ),
        axis=1,
    )
    curated_df["artists_display"] = curated_df["artists_display_resolved"]
    return curated_df


def _build_years_curated_df(years_df: pd.DataFrame, song_curation_df: pd.DataFrame) -> pd.DataFrame:
    curation_years_df = song_curation_df[
        ["song_id", "year_override", "curation_updated_at", "curation_run_id", "curation_note"]
    ].rename(columns={"year_override": "year_override_curation"})

    curated_df = years_df.merge(curation_years_df, on="song_id", how="left")
    curated_df["year_override"] = curated_df["year_override_curation"].combine_first(curated_df["year_override"])
    curated_df = curated_df.drop(columns=["year_override_curation"])
    curated_df["year_override"] = curated_df["year_override"].astype("Int64")
    curated_df["year_final"] = curated_df["year_override"].combine_first(curated_df["year_candidate"])
    curated_df["year_final"] = curated_df["year_final"].astype("Int64")
    return curated_df


def _attach_song_curation_columns(candidates_df: pd.DataFrame, songs_curated_df: pd.DataFrame) -> pd.DataFrame:
    song_columns = [
        "song_id",
        "winner_track_id",
        "title_display_raw",
        "title_display_current",
        "title_display_resolved",
        "artists_display_current",
        "artists_display_resolved",
        "artists_display",
        "secondary_artist_names",
        "year_override",
        "title_display_override",
        "artists_display_override",
        "curation_updated_at",
        "curation_run_id",
        "curation_note",
    ]
    return candidates_df.merge(
        songs_curated_df[song_columns],
        on=["song_id", "winner_track_id"],
        how="left",
    )


def _serialize_secondary_artist_names(value) -> str | None:
    names = normalize_string_list(value)
    if not names:
        return None
    return " | ".join(names)


def _build_artists_display_current(primary_artist_name, secondary_artist_names) -> str | None:
    return build_artists_display_current(primary_artist_name, secondary_artist_names)


def _build_review_template_df(candidates_curated_df: pd.DataFrame) -> pd.DataFrame:
    template_df = candidates_curated_df.copy()
    if "secondary_artist_names" not in template_df.columns:
        template_df["secondary_artist_names"] = [[] for _ in range(len(template_df))]
    if "title_display_raw" not in template_df.columns:
        template_df["title_display_raw"] = template_df.get("title_display")
    if "title_display_current" not in template_df.columns:
        template_df["title_display_current"] = template_df["title_display_raw"].map(normalize_title_display)
    template_df["title_display_current"] = template_df["title_display_current"].combine_first(template_df["title_display_raw"])
    if "title_display_resolved" not in template_df.columns:
        template_df["title_display_resolved"] = template_df["title_display_override"].combine_first(
            template_df["title_display_current"]
        )

    template_df["secondary_artist_names"] = template_df["secondary_artist_names"].map(_serialize_secondary_artist_names)
    template_df["has_secondary_artists"] = template_df["secondary_artist_names"].notna()
    if "artists_display_current" not in template_df.columns:
        template_df["artists_display_current"] = None
    template_df["artists_display_current"] = template_df["artists_display_current"].combine_first(
        template_df.apply(
            lambda row: _build_artists_display_current(
                row.get("primary_artist_name"),
                row.get("secondary_artist_names"),
            ),
            axis=1,
        )
    )
    template_df["artists_display"] = template_df.apply(resolve_final_artists_display, axis=1)
    template_df = template_df[
        [
            "song_id",
            "winner_track_id",
            "title_display_raw",
            "title_display_current",
            "title_display_override",
            "title_display_resolved",
            "title_display",
            "primary_artist_name",
            "secondary_artist_names",
            "has_secondary_artists",
            "artists_display_current",
            "artists_display",
            "album_release_date_spotify",
            "year_candidate",
            "year_final",
            "owners_count",
            "year_override",
            "artists_display_override",
            "curation_note",
        ]
    ].rename(columns={"curation_note": "note"})
    template_df["review_status"] = None
    template_df["review_keep"] = None

    if not template_df.empty:
        for column in ["owners_count", "year_candidate", "year_final", "year_override"]:
            if column in template_df.columns:
                template_df[column] = template_df[column].astype("Int64")

    return template_df.reindex(columns=REVIEW_TEMPLATE_COLUMNS)


def apply_current_curation_to_run(paths: RunPaths, *, store_dir: Path, sync_catalogs: bool) -> dict[str, int]:
    frames = _load_apply_inputs(paths, require_tracks_snapshot=sync_catalogs)
    songs_df = frames["songs"]
    years_df = frames["years"]
    candidates_df = frames["candidates"]

    track_catalog_rows = 0
    song_catalog_rows = 0
    if sync_catalogs:
        track_catalog_df = sync_track_catalog(store_dir, frames["tracks"])
        song_catalog_df = sync_song_catalog(store_dir, songs_df)
        track_catalog_rows = len(track_catalog_df)
        song_catalog_rows = len(song_catalog_df)

    curation_current_df = load_curation_current(store_dir)
    song_curation_df = build_song_curation_frame(curation_current_df)
    song_owner_ids_by_song_id = build_song_owner_ids_by_song_id(
        frames["instances"],
        frames["song_variant_map"],
    )

    songs_curated_df = _build_songs_curated_df(songs_df, song_curation_df)
    years_curated_df = _build_years_curated_df(years_df, song_curation_df)
    candidates_curated_df, _, _ = build_candidates_outputs(
        songs_curated_df,
        years_curated_df,
        run_id=paths.run_id,
        song_owner_ids_by_song_id=song_owner_ids_by_song_id,
    )
    candidates_curated_df = _attach_song_curation_columns(candidates_curated_df, songs_curated_df)
    review_template_df = _build_review_template_df(candidates_curated_df)

    write_parquet_atomic(paths.processed_dir / "songs_curated.parquet", songs_curated_df)
    write_parquet_atomic(paths.processed_dir / "years_curated.parquet", years_curated_df)
    write_parquet_atomic(paths.processed_dir / "candidates_curated.parquet", candidates_curated_df)
    write_csv(paths.reports_dir / "candidates_review_template.csv", review_template_df)
    write_xlsx(
        paths.reports_dir / "candidates_review_template.xlsx",
        review_template_df,
        sheet_name="review_template",
    )

    songs_with_year_override = int(songs_curated_df["year_override"].notna().sum()) if not songs_curated_df.empty else 0
    songs_with_title_override = (
        int(songs_curated_df["title_display_override"].notna().sum()) if not songs_curated_df.empty else 0
    )
    songs_with_artists_override = (
        int(songs_curated_df["artists_display_override"].notna().sum()) if not songs_curated_df.empty else 0
    )

    qc_row = {
        "run_id": paths.run_id,
        "songs_input": len(songs_df),
        "songs_with_year_override": songs_with_year_override,
        "songs_with_title_override": songs_with_title_override,
        "songs_with_artists_override": songs_with_artists_override,
        "candidates_input": len(candidates_df),
        "candidates_output": len(candidates_curated_df),
    }
    qc_df = pd.DataFrame([qc_row], columns=CURATION_APPLY_QC_COLUMNS)
    write_csv(paths.reports_dir / "curation_apply_qc.csv", qc_df)

    return {
        "track_catalog_rows": track_catalog_rows,
        "song_catalog_rows": song_catalog_rows,
        "songs_with_year_override": songs_with_year_override,
        "songs_with_title_override": songs_with_title_override,
        "songs_with_artists_override": songs_with_artists_override,
        "candidates_input": len(candidates_df),
        "candidates_output": len(candidates_curated_df),
    }


def run_curation_sync(config: RunConfig, paths: RunPaths) -> None:
    logger.info("Step: curation-sync")

    store_dir = resolve_global_store_dir()
    bootstrap_global_store(store_dir)
    stats = apply_current_curation_to_run(paths, store_dir=store_dir, sync_catalogs=True)

    logger.info(
        "OK | track_catalog_rows=%s | song_catalog_rows=%s | overrides_applied=%s | candidates_output=%s",
        stats["track_catalog_rows"],
        stats["song_catalog_rows"],
        stats["songs_with_year_override"] + stats["songs_with_title_override"] + stats["songs_with_artists_override"],
        stats["candidates_output"],
    )
