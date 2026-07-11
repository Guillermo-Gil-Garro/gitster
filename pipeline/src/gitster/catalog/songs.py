"""Catalog step: group track variants into songs (SHA1-based identity)."""

from __future__ import annotations

import logging

import pandas as pd

from gitster.config import RunConfig
from gitster.identity import (
    IDENTITY_VERSION,
    build_editorial_key,
    build_song_key,
    compute_base_title_norm,
    extract_postmerge_protected_title_tags,
    has_postmerge_protected_title_tags,
    make_song_id,
    make_postpass_song_id,
    normalize_secondary_artist_ids,
    normalize_string_list,
    normalize_string_scalar,
)
from gitster.io_utils import read_parquet, write_parquet_atomic
from gitster.paths import RunPaths
from gitster.release_dates import earliest_release_date_with_track_id

logger = logging.getLogger(__name__)


SONG_VARIANT_MAP_COLUMNS = [
    "run_id",
    "identity_version",
    "track_id",
    "song_id",
    "winner_track_id",
    "merge_allowed",
    "no_merge_reason",
    "winner_rule_path",
]

SONGS_COLUMNS = [
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


def _first_non_null_string(values: list[object]) -> str | None:
    for value in values:
        normalized = normalize_string_scalar(value)
        if normalized is not None:
            return normalized
    return None


def _compute_track_owner_context(instances_df: pd.DataFrame) -> tuple[dict[str, int], dict[str, set[str]]]:
    if instances_df.empty:
        return {}, {}

    owner_pairs = instances_df[["track_id", "owner_id"]].copy()
    owner_pairs = owner_pairs.dropna(subset=["track_id", "owner_id"])

    owners_by_track_id: dict[str, set[str]] = {}
    for row in owner_pairs.to_dict(orient="records"):
        track_id = normalize_string_scalar(row.get("track_id"))
        owner_id = normalize_string_scalar(row.get("owner_id"))
        if track_id is None or owner_id is None:
            continue
        owners_by_track_id.setdefault(track_id, set()).add(owner_id)

    owners_count_by_track_id = {
        track_id: len(owner_ids)
        for track_id, owner_ids in owners_by_track_id.items()
    }
    return owners_count_by_track_id, owners_by_track_id


def _popularity_value(value) -> int:
    if value is None or pd.isna(value):
        return -1
    return int(value)


def _duration_ms_value(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _prepare_candidate(row: dict, order_idx: int, owners_count_by_track_id: dict[str, int], owners_by_track_id: dict[str, set[str]]) -> dict | None:
    track_id = normalize_string_scalar(row.get("track_id"))
    if track_id is None:
        return None

    secondary_artist_ids = normalize_string_list(row.get("secondary_artist_ids"))
    feat_signature = normalize_secondary_artist_ids(secondary_artist_ids)
    base_title_norm, had_collapsible_suffix, contains_remix = compute_base_title_norm(row.get("track_name"))
    song_key_type, song_key = build_song_key(
        normalize_string_scalar(row.get("primary_artist_id")),
        normalize_string_scalar(row.get("isrc")),
        base_title_norm,
        feat_signature,
    )

    return {
        "order_idx": order_idx,
        "track_id": track_id,
        "track_name": normalize_string_scalar(row.get("track_name")),
        "primary_artist_id": normalize_string_scalar(row.get("primary_artist_id")),
        "primary_artist_name": normalize_string_scalar(row.get("primary_artist_name")),
        "secondary_artist_ids": secondary_artist_ids,
        "secondary_artist_names": normalize_string_list(row.get("secondary_artist_names")),
        "feat_signature": list(feat_signature),
        "isrc": normalize_string_scalar(row.get("isrc")),
        "album_id": normalize_string_scalar(row.get("album_id")),
        "album_name": normalize_string_scalar(row.get("album_name")),
        "album_release_date_spotify": normalize_string_scalar(row.get("album_release_date_spotify")),
        "duration_ms": _duration_ms_value(row.get("duration_ms")),
        "explicit": row.get("explicit"),
        "popularity": row.get("popularity"),
        "popularity_sort": _popularity_value(row.get("popularity")),
        "owners_count_track": owners_count_by_track_id.get(track_id, 0),
        "owner_ids_track": owners_by_track_id.get(track_id, set()),
        "base_title_norm": base_title_norm,
        "editorial_key": build_editorial_key(
            normalize_string_scalar(row.get("primary_artist_id")),
            base_title_norm,
            feat_signature,
        ),
        "song_key_type": song_key_type,
        "song_key": song_key,
        "song_id": make_song_id(song_key),
        "had_collapsible_suffix": had_collapsible_suffix,
        "contains_remix": contains_remix,
        "protected_title_tags": list(extract_postmerge_protected_title_tags(row.get("track_name"))),
        "has_protected_variant_tag": has_postmerge_protected_title_tags(row.get("track_name")),
    }


def _winner_sort_key(candidate: dict) -> tuple:
    return (
        -candidate["owners_count_track"],
        -candidate["popularity_sort"],
        candidate["had_collapsible_suffix"],
        candidate["track_id"],
    )


def _winner_rule_path(candidates: list[dict]) -> str:
    if len(candidates) == 1:
        return "single_variant"

    max_owners_count = max(item["owners_count_track"] for item in candidates)
    remaining = [item for item in candidates if item["owners_count_track"] == max_owners_count]
    if len(remaining) == 1:
        return "owners_count"

    max_popularity = max(item["popularity_sort"] for item in remaining)
    remaining = [item for item in remaining if item["popularity_sort"] == max_popularity]
    if len(remaining) == 1:
        return "owners_count>popularity"

    min_suffix_flag = min(item["had_collapsible_suffix"] for item in remaining)
    remaining = [item for item in remaining if item["had_collapsible_suffix"] == min_suffix_flag]
    if len(remaining) == 1:
        return "owners_count>popularity>title_without_collapsible_suffix"

    return "owners_count>popularity>title_without_collapsible_suffix>track_id"


def _no_merge_reason(candidate: dict) -> str:
    if candidate["contains_remix"]:
        return "remix_title"
    if candidate["song_key_type"] == "isrc_first":
        return "song_key_unique_isrc"
    return "song_key_unique_fallback"


def _build_song_row(
    *,
    run_id: str,
    song_id: str,
    song_key_type: str,
    ordered_candidates: list[dict],
    winner: dict,
    album_release_date_spotify: str | None,
    album_release_date_spotify_source: str,
    album_release_date_spotify_track_id: str | None,
) -> dict:
    merged_track_ids = [winner["track_id"]] + [
        candidate["track_id"]
        for candidate in ordered_candidates
        if candidate["track_id"] != winner["track_id"]
    ]
    title_display = _first_non_null_string([candidate["track_name"] for candidate in ordered_candidates])
    if title_display is None:
        title_display = winner["base_title_norm"]
    if title_display is None or title_display == "":
        title_display = winner["track_id"]

    song_owner_ids: set[str] = set()
    for candidate in ordered_candidates:
        song_owner_ids.update(candidate["owner_ids_track"])

    return {
        "run_id": run_id,
        "identity_version": IDENTITY_VERSION,
        "song_id": song_id,
        "winner_track_id": winner["track_id"],
        "song_key_type": song_key_type,
        "track_ids_merged": merged_track_ids,
        "title_display": title_display,
        "base_title_norm": winner["base_title_norm"],
        "primary_artist_id": winner["primary_artist_id"],
        "primary_artist_name": winner["primary_artist_name"],
        "secondary_artist_ids": winner["secondary_artist_ids"],
        "secondary_artist_names": winner["secondary_artist_names"],
        "feat_signature": winner["feat_signature"],
        "isrc": winner["isrc"],
        "album_id": winner["album_id"],
        "album_release_date_spotify": album_release_date_spotify,
        "album_release_date_spotify_source": album_release_date_spotify_source,
        "album_release_date_spotify_track_id": album_release_date_spotify_track_id,
        "explicit": winner["explicit"],
        "popularity_winner": winner["popularity"],
        "owners_count": len(song_owner_ids),
    }


def _build_initial_song_group(song_id: str, candidates: list[dict]) -> dict:
    ordered_candidates = sorted(candidates, key=lambda item: item["order_idx"])
    winner = min(ordered_candidates, key=_winner_sort_key)
    return {
        "song_id": song_id,
        "editorial_key": winner["editorial_key"],
        "primary_artist_id": winner["primary_artist_id"],
        "base_title_norm": winner["base_title_norm"],
        "feat_signature": list(winner["feat_signature"]),
        "song_key_type": winner["song_key_type"],
        "winner": winner,
        "ordered_candidates": ordered_candidates,
        "winner_rule_path": _winner_rule_path(ordered_candidates),
        "contains_remix": any(candidate["contains_remix"] for candidate in ordered_candidates),
        "has_protected_variant_tag": any(candidate["has_protected_variant_tag"] for candidate in ordered_candidates),
        "duration_ms": winner["duration_ms"],
    }


def _can_postmerge_groups(left_group: dict, right_group: dict, *, max_duration_diff_ms: int = 8000) -> bool:
    if left_group["primary_artist_id"] != right_group["primary_artist_id"]:
        return False
    if left_group["base_title_norm"] != right_group["base_title_norm"]:
        return False
    if left_group["feat_signature"] != right_group["feat_signature"]:
        return False
    if left_group["contains_remix"] or right_group["contains_remix"]:
        return False
    if left_group["has_protected_variant_tag"] or right_group["has_protected_variant_tag"]:
        return False

    left_duration_ms = left_group["duration_ms"]
    right_duration_ms = right_group["duration_ms"]
    if left_duration_ms is None or right_duration_ms is None:
        return False

    return abs(left_duration_ms - right_duration_ms) <= max_duration_diff_ms


def _merge_postpass_components(groups: list[dict]) -> list[list[dict]]:
    if len(groups) <= 1:
        return [groups]

    parent = list(range(len(groups)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index in range(len(groups)):
        for right_index in range(left_index + 1, len(groups)):
            if _can_postmerge_groups(groups[left_index], groups[right_index]):
                union(left_index, right_index)

    components: dict[int, list[dict]] = {}
    for index, group in enumerate(groups):
        components.setdefault(find(index), []).append(group)

    return [
        sorted(component_groups, key=lambda item: item["winner"]["order_idx"])
        for _, component_groups in sorted(
            components.items(),
            key=lambda item: min(group["winner"]["order_idx"] for group in item[1]),
        )
    ]


def build_identity_outputs(
    *,
    tracks_df: pd.DataFrame,
    instances_df: pd.DataFrame,
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    owners_count_by_track_id, owners_by_track_id = _compute_track_owner_context(instances_df)

    candidates_by_song_id: dict[str, list[dict]] = {}
    for order_idx, row in enumerate(tracks_df.to_dict(orient="records")):
        candidate = _prepare_candidate(row, order_idx, owners_count_by_track_id, owners_by_track_id)
        if candidate is None:
            continue
        candidates_by_song_id.setdefault(candidate["song_id"], []).append(candidate)

    initial_song_groups = [
        _build_initial_song_group(song_id, candidates)
        for song_id, candidates in candidates_by_song_id.items()
    ]
    initial_song_groups = sorted(initial_song_groups, key=lambda item: item["winner"]["order_idx"])

    groups_by_editorial_key: dict[tuple, list[dict]] = {}
    for group in initial_song_groups:
        groups_by_editorial_key.setdefault(group["editorial_key"], []).append(group)

    variant_rows: list[dict] = []
    song_rows: list[dict] = []
    postpass_group_merges = 0

    for editorial_key_groups in groups_by_editorial_key.values():
        for component_groups in _merge_postpass_components(editorial_key_groups):
            component_groups = sorted(component_groups, key=lambda item: item["winner"]["order_idx"])
            merged_in_postpass = len(component_groups) > 1
            postpass_group_merges += max(len(component_groups) - 1, 0)

            ordered_candidates = sorted(
                [
                    candidate
                    for group in component_groups
                    for candidate in group["ordered_candidates"]
                ],
                key=lambda item: item["order_idx"],
            )
            winner = min(ordered_candidates, key=_winner_sort_key)
            winner_rule_path = _winner_rule_path(ordered_candidates)
            if merged_in_postpass:
                final_song_id = make_postpass_song_id(winner["editorial_key"])
                final_song_key_type = "postpass_conservative"
                final_winner_rule_path = f"postpass_conservative>{winner_rule_path}"
                earliest_release_date, earliest_release_track_id = earliest_release_date_with_track_id(
                    ordered_candidates,
                    date_field="album_release_date_spotify",
                    track_id_field="track_id",
                )
                if earliest_release_date is not None:
                    final_album_release_date_spotify = earliest_release_date
                    final_album_release_date_spotify_track_id = earliest_release_track_id
                    final_album_release_date_spotify_source = (
                        "winner_track"
                        if earliest_release_track_id == winner["track_id"]
                        else "merged_group_min_date"
                    )
                else:
                    final_album_release_date_spotify = winner["album_release_date_spotify"]
                    final_album_release_date_spotify_track_id = winner["track_id"]
                    final_album_release_date_spotify_source = "winner_track"
            else:
                final_song_id = component_groups[0]["song_id"]
                final_song_key_type = component_groups[0]["song_key_type"]
                final_winner_rule_path = component_groups[0]["winner_rule_path"]
                final_album_release_date_spotify = winner["album_release_date_spotify"]
                final_album_release_date_spotify_track_id = winner["track_id"]
                final_album_release_date_spotify_source = "winner_track"

            merge_allowed = len(ordered_candidates) > 1
            for candidate in ordered_candidates:
                variant_rows.append(
                    {
                        "run_id": run_id,
                        "identity_version": IDENTITY_VERSION,
                        "track_id": candidate["track_id"],
                        "song_id": final_song_id,
                        "winner_track_id": winner["track_id"],
                        "merge_allowed": merge_allowed,
                        "no_merge_reason": None if merge_allowed else _no_merge_reason(candidate),
                        "winner_rule_path": final_winner_rule_path,
                    }
                )

            song_rows.append(
                _build_song_row(
                    run_id=run_id,
                    song_id=final_song_id,
                    song_key_type=final_song_key_type,
                    ordered_candidates=ordered_candidates,
                    winner=winner,
                    album_release_date_spotify=final_album_release_date_spotify,
                    album_release_date_spotify_source=final_album_release_date_spotify_source,
                    album_release_date_spotify_track_id=final_album_release_date_spotify_track_id,
                )
            )

    variant_df = pd.DataFrame(variant_rows, columns=SONG_VARIANT_MAP_COLUMNS)
    songs_df = pd.DataFrame(song_rows, columns=SONGS_COLUMNS)
    stats = {
        "tracks_input": len(variant_df),
        "song_ids": len(songs_df),
        "merges_realized": len(variant_df) - len(songs_df),
        "postpass_group_merges": postpass_group_merges,
    }
    return variant_df, songs_df, stats


def run_identity(_config: RunConfig, paths: RunPaths) -> None:
    logger.info("Catalog step: identity")

    tracks_snapshot_path = paths.processed_dir / "tracks_snapshot.parquet"
    if not tracks_snapshot_path.exists():
        raise FileNotFoundError(f"Missing {tracks_snapshot_path}; run tracks before identity")

    instances_path = paths.processed_dir / "instances.parquet"
    if not instances_path.exists():
        raise FileNotFoundError(f"Missing {instances_path}; run instances before identity")

    tracks_df = read_parquet(tracks_snapshot_path)
    instances_df = read_parquet(instances_path)
    variant_df, songs_df, stats = build_identity_outputs(
        tracks_df=tracks_df,
        instances_df=instances_df,
        run_id=paths.run_id,
    )

    write_parquet_atomic(paths.processed_dir / "song_variant_map.parquet", variant_df)
    write_parquet_atomic(paths.processed_dir / "songs.parquet", songs_df)
    logger.info(
        "OK | tracks_input=%s | song_ids=%s | merges_realized=%s | postpass_group_merges=%s",
        stats["tracks_input"],
        stats["song_ids"],
        stats["merges_realized"],
        stats["postpass_group_merges"],
    )
