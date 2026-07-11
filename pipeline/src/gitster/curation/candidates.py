"""Candidate selection: rank songs into a balanced candidate pool for the deck."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime

import pandas as pd

from gitster.config import RunConfig
from gitster.identity import normalize_string_list, normalize_string_scalar
from gitster.io_utils import read_parquet, write_csv, write_parquet_atomic
from gitster.paths import RunPaths


logger = logging.getLogger(__name__)

TARGET_CANDIDATES = 400

YEAR_PENALTY_WEIGHT = 0.35
OWNER_AVG_PENALTY_WEIGHT = 0.20
OWNER_MAX_PENALTY_WEIGHT = 0.05
NEW_OWNER_BONUS_WEIGHT = 0.20
ARTIST_PENALTY_WEIGHT = 0.10

CANDIDATES_COLUMNS = [
    "run_id",
    "song_id",
    "winner_track_id",
    "title_display",
    "primary_artist_name",
    "owners_count",
    "album_release_date_spotify",
    "year_candidate",
    "year_final",
    "year_candidate_source",
    "year_candidate_precision",
    "year_candidate_confidence",
    "excluded_by_max_year_rule",
    "selection_phase",
]

CANDIDATES_QC_COLUMNS = [
    "run_id",
    "songs_input",
    "songs_with_year",
    "songs_missing_year",
    "max_year",
    "current_year",
    "excluded_by_max_year_rule",
    "distinct_years_in_candidates",
    "top_year_counts",
    "top_owner_counts",
    "top_artist_counts",
    "candidates_final",
]

REVIEW_COLUMNS = ["selection_rank"] + CANDIDATES_COLUMNS


def _normalize_artist_key(value) -> str:
    artist_name = normalize_string_scalar(value)
    return artist_name or "__missing_artist__"


def _normalize_year_value(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _json_top_counts(counter: Counter, *, limit: int = 5) -> str:
    ordered_items = sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
    top_counts = [{str(key): int(value)} for key, value in ordered_items[:limit]]
    return json.dumps(top_counts, ensure_ascii=False)


def _normalize_dedupe_key(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "tolist") and not isinstance(value, str):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        normalized_items = [
            normalize_string_scalar(item)
            for item in value
        ]
        normalized_items = [item for item in normalized_items if item is not None]
        if not normalized_items:
            return None
        return json.dumps(normalized_items, ensure_ascii=False, separators=(",", ":"))

    normalized_value = normalize_string_scalar(value)
    return normalized_value


def build_song_owner_ids_by_song_id(
    instances_df: pd.DataFrame,
    song_variant_map_df: pd.DataFrame,
) -> dict[str, list[str]]:
    if instances_df.empty or song_variant_map_df.empty:
        return {}

    owner_pairs = instances_df[["track_id", "owner_id"]].dropna(subset=["track_id", "owner_id"]).copy()
    variant_pairs = song_variant_map_df[["track_id", "song_id"]].dropna(subset=["track_id", "song_id"]).copy()
    merged_pairs = owner_pairs.merge(variant_pairs, on="track_id", how="inner").drop_duplicates()

    owners_by_song_id: dict[str, set[str]] = {}
    for row in merged_pairs.to_dict(orient="records"):
        song_id = normalize_string_scalar(row.get("song_id"))
        owner_id = normalize_string_scalar(row.get("owner_id"))
        if song_id is None or owner_id is None:
            continue
        owners_by_song_id.setdefault(song_id, set()).add(owner_id)

    return {
        song_id: sorted(owner_ids)
        for song_id, owner_ids in owners_by_song_id.items()
    }


def prepare_selection_pool_df(
    pool_df: pd.DataFrame,
    *,
    run_id: str,
    song_owner_ids_by_song_id: dict[str, list[str]],
    apply_max_year_exclusion: bool,
) -> pd.DataFrame:
    merged_df = pool_df.copy()
    current_year = datetime.now().year
    non_null_years = merged_df["year_final"].dropna()
    max_year = int(non_null_years.max()) if not non_null_years.empty else None
    exclude_max_year = apply_max_year_exclusion and max_year == current_year if max_year is not None else False

    if "run_id" in merged_df.columns:
        merged_df["run_id"] = merged_df["run_id"].fillna(run_id)
    else:
        merged_df["run_id"] = run_id
    merged_df["excluded_by_max_year_rule"] = False
    if exclude_max_year:
        merged_df["excluded_by_max_year_rule"] = merged_df["year_final"] == max_year

    merged_df["selection_phase"] = None
    merged_df["owner_ids"] = merged_df["song_id"].map(lambda song_id: song_owner_ids_by_song_id.get(song_id, []))
    merged_df["owner_ids"] = merged_df["owner_ids"].map(normalize_string_list)
    merged_df["owner_ids_count"] = merged_df["owner_ids"].map(len)
    merged_df["owners_count"] = merged_df["owners_count"].fillna(merged_df["owner_ids_count"]).astype("Int64")
    merged_df["year_final"] = merged_df["year_final"].astype("Int64")
    merged_df["year_candidate"] = merged_df["year_candidate"].astype("Int64")

    return merged_df


def _build_candidate_pool(
    songs_df: pd.DataFrame,
    years_df: pd.DataFrame,
    *,
    run_id: str,
    song_owner_ids_by_song_id: dict[str, list[str]],
) -> pd.DataFrame:
    merged_df = songs_df.merge(
        years_df[
            [
                "song_id",
                "winner_track_id",
                "album_release_date_spotify",
                "year_candidate",
                "year_final",
                "year_candidate_source",
                "year_candidate_precision",
                "year_candidate_confidence",
            ]
        ],
        on=["song_id", "winner_track_id"],
        how="left",
        suffixes=("", "_years"),
    )

    return prepare_selection_pool_df(
        merged_df,
        run_id=run_id,
        song_owner_ids_by_song_id=song_owner_ids_by_song_id,
        apply_max_year_exclusion=True,
    )


def _owner_balance_metrics(owner_ids: list[str], owner_selection_counts: Counter) -> tuple[float, int, int]:
    if not owner_ids:
        return 0.0, 0, 0

    owner_counts = [owner_selection_counts[owner_id] for owner_id in owner_ids]
    avg_count = sum(owner_counts) / len(owner_counts)
    max_count = max(owner_counts) if owner_counts else 0
    new_owner_count = sum(1 for count in owner_counts if count == 0)
    return avg_count, max_count, new_owner_count


def _phase1_sort_key(candidate: dict, owner_selection_counts: Counter, artist_selection_counts: Counter) -> tuple:
    owner_ids = candidate.get("owner_ids") or []
    avg_owner_count, max_owner_count, new_owner_count = _owner_balance_metrics(owner_ids, owner_selection_counts)
    artist_key = _normalize_artist_key(candidate.get("primary_artist_name"))

    return (
        -int(candidate.get("owners_count") or 0),
        avg_owner_count,
        max_owner_count,
        -new_owner_count,
        artist_selection_counts[artist_key],
        candidate["song_id"],
    )


def _phase2_sort_key(
    candidate: dict,
    *,
    year_selection_counts: Counter,
    owner_selection_counts: Counter,
    artist_selection_counts: Counter,
) -> tuple:
    owner_ids = candidate.get("owner_ids") or []
    year_value = _normalize_year_value(candidate.get("year_final"))
    year_penalty = year_selection_counts[year_value] if year_value is not None else 0
    avg_owner_count, max_owner_count, new_owner_count = _owner_balance_metrics(owner_ids, owner_selection_counts)
    artist_penalty = artist_selection_counts[_normalize_artist_key(candidate.get("primary_artist_name"))]
    owners_count = int(candidate.get("owners_count") or 0)

    score = (
        owners_count
        - YEAR_PENALTY_WEIGHT * year_penalty
        - OWNER_AVG_PENALTY_WEIGHT * avg_owner_count
        - OWNER_MAX_PENALTY_WEIGHT * max_owner_count
        + NEW_OWNER_BONUS_WEIGHT * new_owner_count
        - ARTIST_PENALTY_WEIGHT * artist_penalty
    )

    return (
        -score,
        -owners_count,
        year_penalty,
        avg_owner_count,
        max_owner_count,
        -new_owner_count,
        artist_penalty,
        candidate["song_id"],
    )


def _register_selection(
    candidate: dict,
    *,
    year_selection_counts: Counter,
    owner_selection_counts: Counter,
    artist_selection_counts: Counter,
) -> None:
    year_value = _normalize_year_value(candidate.get("year_final"))
    if year_value is not None:
        year_selection_counts[year_value] += 1

    for owner_id in candidate.get("owner_ids") or []:
        owner_selection_counts[owner_id] += 1

    artist_selection_counts[_normalize_artist_key(candidate.get("primary_artist_name"))] += 1


def _select_candidates(
    eligible_records: list[dict],
    *,
    target_size: int,
    initial_selected_records: list[dict] | None = None,
    dedupe_key_field: str | None = None,
) -> list[dict]:
    if not eligible_records or target_size <= 0:
        initial_selected_records = initial_selected_records or []
        return [dict(record) for record in initial_selected_records[:target_size]]

    records_by_year: dict[int, list[dict]] = {}
    for record in eligible_records:
        year_value = _normalize_year_value(record.get("year_final"))
        if year_value is None:
            continue
        records_by_year.setdefault(year_value, []).append(record)

    selected_records: list[dict] = []
    selected_song_ids: set[str] = set()
    selected_dedupe_keys: set[str] = set()
    year_selection_counts: Counter = Counter()
    owner_selection_counts: Counter = Counter()
    artist_selection_counts: Counter = Counter()

    for seed_record in initial_selected_records or []:
        if len(selected_records) >= target_size:
            break
        seeded = dict(seed_record)
        selected_records.append(seeded)
        selected_song_ids.add(seeded["song_id"])
        dedupe_key = _normalize_dedupe_key(seeded.get(dedupe_key_field)) if dedupe_key_field else None
        if dedupe_key is not None:
            selected_dedupe_keys.add(dedupe_key)
        _register_selection(
            seeded,
            year_selection_counts=year_selection_counts,
            owner_selection_counts=owner_selection_counts,
            artist_selection_counts=artist_selection_counts,
        )

    phase1_years = sorted(records_by_year.keys())
    for year_value in phase1_years:
        if len(selected_records) >= target_size:
            break

        candidates_for_year = [
            record
            for record in records_by_year.get(year_value, [])
            if record["song_id"] not in selected_song_ids
            and (
                dedupe_key_field is None
                or _normalize_dedupe_key(record.get(dedupe_key_field)) not in selected_dedupe_keys
            )
        ]
        if not candidates_for_year:
            continue

        winner = min(
            candidates_for_year,
            key=lambda candidate: _phase1_sort_key(candidate, owner_selection_counts, artist_selection_counts),
        )
        winner = dict(winner)
        winner["selection_phase"] = "phase1_year_cover"
        selected_records.append(winner)
        selected_song_ids.add(winner["song_id"])
        dedupe_key = _normalize_dedupe_key(winner.get(dedupe_key_field)) if dedupe_key_field else None
        if dedupe_key is not None:
            selected_dedupe_keys.add(dedupe_key)
        _register_selection(
            winner,
            year_selection_counts=year_selection_counts,
            owner_selection_counts=owner_selection_counts,
            artist_selection_counts=artist_selection_counts,
        )

    remaining_records = [
        record
        for record in eligible_records
        if record["song_id"] not in selected_song_ids
        and (
            dedupe_key_field is None
            or _normalize_dedupe_key(record.get(dedupe_key_field)) not in selected_dedupe_keys
        )
    ]
    while len(selected_records) < target_size and remaining_records:
        winner = min(
            remaining_records,
            key=lambda candidate: _phase2_sort_key(
                candidate,
                year_selection_counts=year_selection_counts,
                owner_selection_counts=owner_selection_counts,
                artist_selection_counts=artist_selection_counts,
            ),
        )
        winner = dict(winner)
        winner["selection_phase"] = "phase2_fill"
        selected_records.append(winner)
        selected_song_ids.add(winner["song_id"])
        dedupe_key = _normalize_dedupe_key(winner.get(dedupe_key_field)) if dedupe_key_field else None
        if dedupe_key is not None:
            selected_dedupe_keys.add(dedupe_key)
        _register_selection(
            winner,
            year_selection_counts=year_selection_counts,
            owner_selection_counts=owner_selection_counts,
            artist_selection_counts=artist_selection_counts,
        )
        remaining_records = [
            record
            for record in remaining_records
            if record["song_id"] != winner["song_id"]
            and (
                dedupe_key_field is None
                or _normalize_dedupe_key(record.get(dedupe_key_field)) not in selected_dedupe_keys
            )
        ]

    return selected_records


def build_ranked_selection_df(
    selection_pool_df: pd.DataFrame,
    *,
    target_size: int,
    respect_max_year_exclusion: bool,
    initial_selected_df: pd.DataFrame | None = None,
    dedupe_key_field: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    eligible_mask = selection_pool_df["year_final"].notna()
    if respect_max_year_exclusion and "excluded_by_max_year_rule" in selection_pool_df.columns:
        eligible_mask &= ~selection_pool_df["excluded_by_max_year_rule"].fillna(False)

    eligible_df = selection_pool_df[eligible_mask].copy()
    initial_selected_records = (
        initial_selected_df.to_dict(orient="records")
        if initial_selected_df is not None and not initial_selected_df.empty
        else None
    )
    selected_records = _select_candidates(
        eligible_df.to_dict(orient="records"),
        target_size=target_size,
        initial_selected_records=initial_selected_records,
        dedupe_key_field=dedupe_key_field,
    )

    selected_df = pd.DataFrame(selected_records)
    if selected_df.empty:
        return pd.DataFrame(), eligible_df

    selected_df["selection_rank"] = pd.Series(range(1, len(selected_df) + 1), dtype="Int64")
    if "owner_ids" in selected_df.columns:
        selected_df["owner_ids"] = selected_df["owner_ids"].map(normalize_string_list)
    for column in ["owners_count", "year_candidate", "year_final"]:
        if column in selected_df.columns:
            selected_df[column] = selected_df[column].astype("Int64")

    return selected_df, eligible_df


def build_candidates_outputs(
    songs_df: pd.DataFrame,
    years_df: pd.DataFrame,
    *,
    run_id: str,
    song_owner_ids_by_song_id: dict[str, list[str]],
    target_size: int = TARGET_CANDIDATES,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidate_pool_df = _build_candidate_pool(
        songs_df,
        years_df,
        run_id=run_id,
        song_owner_ids_by_song_id=song_owner_ids_by_song_id,
    )

    selected_df, _eligible_df = build_ranked_selection_df(
        candidate_pool_df,
        target_size=target_size,
        respect_max_year_exclusion=True,
    )
    selected_records = selected_df.to_dict(orient="records")
    candidates_df = selected_df.copy()
    if candidates_df.empty:
        candidates_df = pd.DataFrame(columns=CANDIDATES_COLUMNS)
    else:
        candidates_df = candidates_df.reindex(columns=CANDIDATES_COLUMNS)
        for column in ["owners_count", "year_candidate", "year_final"]:
            candidates_df[column] = candidates_df[column].astype("Int64")

    review_rows = []
    for record in selected_records:
        review_rows.append(
            {
                "selection_rank": record["selection_rank"],
                **{
                    key: value
                    for key, value in record.items()
                    if key in CANDIDATES_COLUMNS
                },
            }
        )
    review_df = pd.DataFrame(review_rows, columns=REVIEW_COLUMNS)
    if not review_df.empty:
        for column in ["selection_rank", "owners_count", "year_candidate", "year_final"]:
            review_df[column] = review_df[column].astype("Int64")

    songs_with_year = int(candidate_pool_df["year_final"].notna().sum()) if not candidate_pool_df.empty else 0
    songs_missing_year = int(candidate_pool_df["year_final"].isna().sum()) if not candidate_pool_df.empty else 0
    excluded_count = int(candidate_pool_df["excluded_by_max_year_rule"].sum()) if not candidate_pool_df.empty else 0
    distinct_years_in_candidates = int(candidates_df["year_final"].nunique(dropna=True)) if not candidates_df.empty else 0

    year_counter = Counter(
        int(value)
        for value in candidates_df["year_final"].dropna().tolist()
    )
    owner_counter: Counter = Counter()
    artist_counter: Counter = Counter()
    for record in selected_records:
        owner_counter.update(record.get("owner_ids") or [])
        artist_counter.update([_normalize_artist_key(record.get("primary_artist_name"))])

    current_year = datetime.now().year
    non_null_years = candidate_pool_df["year_final"].dropna()
    max_year = int(non_null_years.max()) if not non_null_years.empty else None

    qc_row = {
        "run_id": run_id,
        "songs_input": len(candidate_pool_df),
        "songs_with_year": songs_with_year,
        "songs_missing_year": songs_missing_year,
        "max_year": max_year,
        "current_year": current_year,
        "excluded_by_max_year_rule": excluded_count,
        "distinct_years_in_candidates": distinct_years_in_candidates,
        "top_year_counts": _json_top_counts(year_counter),
        "top_owner_counts": _json_top_counts(owner_counter),
        "top_artist_counts": _json_top_counts(artist_counter),
        "candidates_final": len(candidates_df),
    }
    qc_df = pd.DataFrame([qc_row], columns=CANDIDATES_QC_COLUMNS)
    if qc_df["max_year"].notna().any():
        qc_df["max_year"] = qc_df["max_year"].astype("Int64")

    return candidates_df, review_df, qc_df


def run_candidates(config: RunConfig, paths: RunPaths) -> None:
    logger.info("Step: candidates")

    songs_path = paths.processed_dir / "songs.parquet"
    years_path = paths.processed_dir / "years_baseline.parquet"
    instances_path = paths.processed_dir / "instances.parquet"
    song_variant_map_path = paths.processed_dir / "song_variant_map.parquet"

    for required_path, step_name in [
        (songs_path, "identity"),
        (years_path, "years"),
        (instances_path, "instances"),
        (song_variant_map_path, "identity"),
    ]:
        if not required_path.exists():
            raise FileNotFoundError(f"{required_path} not found; run the {step_name} step before candidates")

    songs_df = read_parquet(songs_path)
    years_df = read_parquet(years_path)
    instances_df = read_parquet(instances_path)
    song_variant_map_df = read_parquet(song_variant_map_path)
    song_owner_ids_by_song_id = build_song_owner_ids_by_song_id(instances_df, song_variant_map_df)

    candidates_df, review_df, qc_df = build_candidates_outputs(
        songs_df,
        years_df,
        run_id=paths.run_id,
        song_owner_ids_by_song_id=song_owner_ids_by_song_id,
    )

    write_parquet_atomic(paths.processed_dir / "candidates.parquet", candidates_df)
    write_csv(paths.reports_dir / "candidates_qc.csv", qc_df)
    write_csv(paths.reports_dir / "candidates_review.csv", review_df)

    qc_row = qc_df.iloc[0].to_dict()
    logger.info(
        "OK | songs_input=%s | distinct_years_in_candidates=%s | excluded_by_max_year_rule=%s | candidates_final=%s",
        qc_row["songs_input"],
        qc_row["distinct_years_in_candidates"],
        qc_row["excluded_by_max_year_rule"],
        qc_row["candidates_final"],
    )
