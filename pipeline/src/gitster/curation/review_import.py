"""Review import: turn a reviewed candidates file into curation events and re-apply curation."""

from __future__ import annotations

import logging
import numbers
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gitster.config import RunConfig
from gitster.curation.store import (
    CURATION_COLUMNS,
    append_curation_history,
    bootstrap_global_store,
    load_curation_current,
    recompute_curation_current,
    resolve_global_store_dir,
)
from gitster.curation.sync import (
    apply_current_curation_to_run,
    build_song_curation_frame,
    coerce_year_override,
    normalize_string_override,
)
from gitster.identity import IDENTITY_VERSION
from gitster.io_utils import read_xlsx
from gitster.paths import RunPaths


logger = logging.getLogger(__name__)

EDITABLE_REVIEW_COLUMNS = [
    "year_override",
    "artists_display_override",
    "title_display_override",
    "note",
]

REQUIRED_REVIEW_COLUMNS = ["song_id"] + EDITABLE_REVIEW_COLUMNS


def _normalize_nullable_scalar(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        return value
    return int(value) if isinstance(value, numbers.Integral) else value


def _load_review_csv(review_csv: str | Path) -> pd.DataFrame:
    review_path = Path(review_csv)
    if not review_path.exists():
        raise FileNotFoundError(f"review_csv={review_path} not found")

    review_df = pd.read_csv(review_path, dtype=str, keep_default_na=False)
    missing_columns = [column for column in REQUIRED_REVIEW_COLUMNS if column not in review_df.columns]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"Required columns missing from review_csv: {missing}")

    normalized_song_ids = review_df["song_id"].map(normalize_string_override)
    if normalized_song_ids.isna().any():
        raise ValueError("review_csv has rows without song_id")

    duplicated_song_ids = normalized_song_ids[normalized_song_ids.duplicated()].tolist()
    if duplicated_song_ids:
        duplicates = ", ".join(sorted(set(duplicated_song_ids)))
        raise ValueError(f"review_csv has duplicated song_id values: {duplicates}")

    review_df = review_df.copy()
    review_df["song_id"] = normalized_song_ids
    return review_df


def _load_review_xlsx(review_xlsx: str | Path) -> pd.DataFrame:
    review_path = Path(review_xlsx)
    if not review_path.exists():
        raise FileNotFoundError(f"review_xlsx={review_path} not found")

    review_df = read_xlsx(review_path, sheet_name=0)
    review_df = review_df.where(pd.notna(review_df), "")

    missing_columns = [column for column in REQUIRED_REVIEW_COLUMNS if column not in review_df.columns]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"Required columns missing from review_xlsx: {missing}")

    normalized_song_ids = review_df["song_id"].map(normalize_string_override)
    if normalized_song_ids.isna().any():
        raise ValueError("review_xlsx has rows without song_id")

    duplicated_song_ids = normalized_song_ids[normalized_song_ids.duplicated()].tolist()
    if duplicated_song_ids:
        duplicates = ", ".join(sorted(set(duplicated_song_ids)))
        raise ValueError(f"review_xlsx has duplicated song_id values: {duplicates}")

    review_df = review_df.copy()
    review_df["song_id"] = normalized_song_ids
    return review_df


def _build_review_state_df(review_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in review_df.to_dict(orient="records"):
        song_id = row["song_id"]
        rows.append(
            {
                "song_id": song_id,
                "year_override": coerce_year_override(
                    row.get("year_override"),
                    strict=True,
                    song_id=song_id,
                ),
                "artists_display_override": normalize_string_override(row.get("artists_display_override")),
                "title_display_override": normalize_string_override(row.get("title_display_override")),
                "note": normalize_string_override(row.get("note")),
            }
        )

    state_df = pd.DataFrame(rows, columns=REQUIRED_REVIEW_COLUMNS)
    if not state_df.empty:
        state_df["year_override"] = state_df["year_override"].astype("Int64")
    return state_df


def _build_current_state_df(curation_current_df: pd.DataFrame) -> pd.DataFrame:
    song_curation_df = build_song_curation_frame(curation_current_df)
    if song_curation_df.empty:
        return pd.DataFrame(columns=REQUIRED_REVIEW_COLUMNS)

    current_df = song_curation_df[
        ["song_id", "year_override", "artists_display_override", "title_display_override", "curation_note"]
    ].rename(columns={"curation_note": "note"})
    if not current_df.empty:
        current_df["year_override"] = current_df["year_override"].astype("Int64")
    return current_df


def _has_real_change(review_row: dict, current_row: dict) -> bool:
    for column in EDITABLE_REVIEW_COLUMNS:
        review_value = _normalize_nullable_scalar(review_row.get(column))
        current_value = _normalize_nullable_scalar(current_row.get(column))
        if review_value != current_value:
            return True
    return False


def _build_curation_events_df(review_state_df: pd.DataFrame, current_state_df: pd.DataFrame, *, run_id: str) -> pd.DataFrame:
    current_by_song_id = {
        row["song_id"]: row
        for row in current_state_df.to_dict(orient="records")
    }

    updated_at = datetime.now(timezone.utc).isoformat()
    event_rows = []
    for row in review_state_df.to_dict(orient="records"):
        current_row = current_by_song_id.get(row["song_id"], {})
        if not _has_real_change(row, current_row):
            continue

        event_rows.append(
            {
                "entity_type": "song",
                "entity_id": row["song_id"],
                "identity_version": IDENTITY_VERSION,
                "year_override": row["year_override"],
                "artists_display_override": row["artists_display_override"],
                "title_display_override": row["title_display_override"],
                "updated_at": updated_at,
                "run_id": run_id,
                "note": row["note"],
            }
        )

    events_df = pd.DataFrame(event_rows, columns=CURATION_COLUMNS)
    if not events_df.empty:
        events_df["year_override"] = events_df["year_override"].astype("Int64")
    return events_df


def run_review_import(
    config: RunConfig,
    paths: RunPaths,
    review_csv: str | None,
    review_xlsx: str | None,
) -> None:
    logger.info("Step: review-import")

    if review_xlsx:
        review_df = _load_review_xlsx(review_xlsx)
    elif review_csv:
        review_df = _load_review_csv(review_csv)
    else:
        raise ValueError(
            "review-import requires --review-csv path/to/reviewed.csv or --review-xlsx path/to/reviewed.xlsx"
        )

    store_dir = resolve_global_store_dir()
    bootstrap_global_store(store_dir)

    review_state_df = _build_review_state_df(review_df)
    current_state_df = _build_current_state_df(load_curation_current(store_dir))
    events_df = _build_curation_events_df(review_state_df, current_state_df, run_id=paths.run_id)

    history_path = append_curation_history(store_dir, paths.run_id, events_df)
    if not events_df.empty:
        recompute_curation_current(store_dir)

    stats = apply_current_curation_to_run(paths, store_dir=store_dir, sync_catalogs=False)

    history_status = history_path if history_path is not None else "no_changes"
    logger.info(
        "OK | imported_events=%s | history=%s | overrides_applied=%s | candidates_output=%s",
        len(events_df),
        history_status,
        stats["songs_with_year_override"] + stats["songs_with_title_override"] + stats["songs_with_artists_override"],
        stats["candidates_output"],
    )
