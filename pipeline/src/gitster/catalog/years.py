"""Catalog step: derive baseline release years from Spotify album release dates."""

from __future__ import annotations

import logging

import pandas as pd

from gitster.config import RunConfig
from gitster.io_utils import read_parquet, write_parquet_atomic
from gitster.paths import RunPaths
from gitster.release_dates import infer_release_year_precision

logger = logging.getLogger(__name__)


YEARS_BASELINE_COLUMNS = [
    "run_id",
    "song_id",
    "winner_track_id",
    "album_release_date_spotify",
    "album_release_date_spotify_source",
    "album_release_date_spotify_track_id",
    "year_candidate",
    "year_candidate_source",
    "year_candidate_precision",
    "year_candidate_confidence",
    "year_final",
    "year_override",
]

_CONFIDENCE_BY_PRECISION = {
    "day": 0.8,
    "month": 0.7,
    "year": 0.6,
}


def build_years_baseline_df(songs_df: pd.DataFrame, *, run_id: str) -> pd.DataFrame:
    rows: list[dict] = []
    for row in songs_df.to_dict(orient="records"):
        year_candidate, year_precision = infer_release_year_precision(row.get("album_release_date_spotify"))
        year_confidence = _CONFIDENCE_BY_PRECISION.get(year_precision)

        rows.append(
            {
                "run_id": row.get("run_id") or run_id,
                "song_id": row.get("song_id"),
                "winner_track_id": row.get("winner_track_id"),
                "album_release_date_spotify": row.get("album_release_date_spotify"),
                "album_release_date_spotify_source": row.get("album_release_date_spotify_source"),
                "album_release_date_spotify_track_id": row.get("album_release_date_spotify_track_id"),
                "year_candidate": year_candidate,
                "year_candidate_source": "spotify_album_release_date",
                "year_candidate_precision": year_precision,
                "year_candidate_confidence": year_confidence,
                "year_final": year_candidate,
                "year_override": None,
            }
        )

    years_df = pd.DataFrame(rows, columns=YEARS_BASELINE_COLUMNS)
    if not years_df.empty:
        years_df["year_candidate"] = years_df["year_candidate"].astype("Int64")
        years_df["year_final"] = years_df["year_final"].astype("Int64")
    return years_df


def run_years_baseline(_config: RunConfig, paths: RunPaths) -> None:
    logger.info("Catalog step: years baseline")

    songs_path = paths.processed_dir / "songs.parquet"
    if not songs_path.exists():
        raise FileNotFoundError(f"Missing {songs_path}; run identity before years")

    songs_df = read_parquet(songs_path)
    years_df = build_years_baseline_df(songs_df, run_id=paths.run_id)

    write_parquet_atomic(paths.processed_dir / "years_baseline.parquet", years_df)

    songs_with_year = int(years_df["year_final"].notna().sum()) if not years_df.empty else 0
    logger.info("OK | songs_input=%s | songs_with_year=%s", len(years_df), songs_with_year)
