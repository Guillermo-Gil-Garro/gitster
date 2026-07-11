"""Builds the modular selection pool from the full curated song universe.

Unlike the legacy candidates flow (capped at ~400 songs ranked globally), the
modular deck selects per player, so the pool is the whole curated catalog of the
run: songs_curated + years_curated + owner mapping + editorial guardrail keys.
"""

from __future__ import annotations

import pandas as pd

from gitster.curation.candidates import build_song_owner_ids_by_song_id, prepare_selection_pool_df
from gitster.identity import (
    build_editorial_key,
    normalize_string_list,
    normalize_string_scalar,
    serialize_song_key,
)

_YEARS_COLUMNS = [
    "song_id",
    "winner_track_id",
    "album_release_date_spotify",
    "year_candidate",
    "year_final",
    "year_candidate_source",
    "year_candidate_precision",
    "year_candidate_confidence",
]


def _editorial_guardrail_key(row: pd.Series) -> str | None:
    primary_artist_id = normalize_string_scalar(row.get("primary_artist_id"))
    base_title_norm = normalize_string_scalar(row.get("base_title_norm"))
    feat_signature = normalize_string_list(row.get("feat_signature"))
    if primary_artist_id is None or base_title_norm is None:
        return None
    return serialize_song_key(build_editorial_key(primary_artist_id, base_title_norm, feat_signature))


def build_modular_pool(
    *,
    songs_curated_df: pd.DataFrame,
    years_curated_df: pd.DataFrame,
    instances_df: pd.DataFrame,
    song_variant_map_df: pd.DataFrame,
    run_id: str,
) -> pd.DataFrame:
    """Full curated pool with owner_ids, year_final and guardrail keys attached.

    Rows excluded by the max-year rule (current year not yet closed) are dropped;
    rows without year_final stay in the frame (the selector skips them) so QC can
    count them.
    """
    song_owner_ids_by_song_id = build_song_owner_ids_by_song_id(instances_df, song_variant_map_df)

    merged_df = songs_curated_df.merge(
        years_curated_df.reindex(columns=_YEARS_COLUMNS),
        on=["song_id", "winner_track_id"],
        how="left",
        suffixes=("", "_years"),
    )

    pool_df = prepare_selection_pool_df(
        merged_df,
        run_id=run_id,
        song_owner_ids_by_song_id=song_owner_ids_by_song_id,
        apply_max_year_exclusion=True,
    )
    pool_df["editorial_guardrail_key"] = pool_df.apply(_editorial_guardrail_key, axis=1)

    excluded_mask = pool_df["excluded_by_max_year_rule"].fillna(False).astype(bool)
    return pool_df[~excluded_mask].reset_index(drop=True)
