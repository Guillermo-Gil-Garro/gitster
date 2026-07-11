"""Modular deck selection: one expansion per player, locked against the printed registry.

Already-printed cards enter the selection as immutable seeds: they keep their
expansion anchor, block their song globally, and pre-load the per-expansion
year/artist/album counters so new picks fill the real gaps. The greedy loop then
round-robins over the expansions with the largest deficit and picks the candidate
that best improves year variety, shared-song coverage and artist diversity.

Hard constraints (never traded off):
- every card of expansion E has E among its owners;
- a song_id is selected at most once across the whole collection (including
  cards anchored to players that are not active in this run);
- editorial guardrail: no two cards for the same (artist, base title) identity;
- per-expansion caps for artist and album.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from gitster.deck.registry import split_owners
from gitster.identity import normalize_string_list, normalize_string_scalar

logger = logging.getLogger(__name__)

_MISSING_KEY = "__missing__"


@dataclass
class ExpansionState:
    owner_id: str
    target_size: int
    locked_count: int = 0
    year_counts: Counter = field(default_factory=Counter)
    artist_counts: Counter = field(default_factory=Counter)
    album_counts: Counter = field(default_factory=Counter)
    picked: list[dict] = field(default_factory=list)
    exhausted: bool = False

    @property
    def size(self) -> int:
        return self.locked_count + len(self.picked)

    @property
    def deficit(self) -> int:
        return self.target_size - self.size


@dataclass
class ModularSelectionResult:
    new_cards_df: pd.DataFrame
    expansion_summary_df: pd.DataFrame
    underfilled: dict[str, int]


def _normalize_year(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _artist_key(record: dict) -> str | None:
    key = normalize_string_scalar(record.get("primary_artist_id"))
    if key is None:
        key = normalize_string_scalar(record.get("primary_artist_name"))
    return key


def _album_key(record: dict) -> str | None:
    return normalize_string_scalar(record.get("album_id"))


def _sort_key(record: dict, state: ExpansionState) -> tuple:
    year_value = _normalize_year(record.get("year_final"))
    year_count = state.year_counts[year_value]
    owners_count = len(record.get("owner_ids") or [])
    artist_key = _artist_key(record) or _MISSING_KEY
    popularity = record.get("popularity_winner")
    popularity_missing = 1 if popularity is None or pd.isna(popularity) else 0
    popularity_value = 0.0 if popularity_missing else float(popularity)

    return (
        0 if year_count == 0 else 1,
        year_count,
        -(owners_count - 1),
        state.artist_counts[artist_key],
        popularity_missing,
        -popularity_value,
        year_value if year_value is not None else 10_000,
        record["song_id"],
    )


def _register(record: dict, state: ExpansionState) -> None:
    year_value = _normalize_year(record.get("year_final"))
    if year_value is not None:
        state.year_counts[year_value] += 1

    artist_key = _artist_key(record)
    if artist_key is not None:
        state.artist_counts[artist_key] += 1

    album_key = _album_key(record)
    if album_key is not None:
        state.album_counts[album_key] += 1


def _passes_caps(record: dict, state: ExpansionState, *, artist_cap: int, album_cap: int) -> bool:
    artist_key = _artist_key(record)
    if artist_key is not None and state.artist_counts[artist_key] >= artist_cap:
        return False

    album_key = _album_key(record)
    if album_key is not None and state.album_counts[album_key] >= album_cap:
        return False

    return True


def _seed_locked_cards(
    registry_df: pd.DataFrame,
    pool_by_song_id: dict[str, dict],
    states: dict[str, ExpansionState],
) -> None:
    for row in registry_df.to_dict(orient="records"):
        anchor = row["expansion_anchor"]
        state = states.get(anchor)
        if state is None:
            continue

        state.locked_count += 1
        pool_record = pool_by_song_id.get(row["song_id"])
        if pool_record is not None:
            _register(pool_record, state)
        else:
            year_value = _normalize_year(row.get("year"))
            if year_value is not None:
                state.year_counts[year_value] += 1


def select_modular_deck(
    pool_df: pd.DataFrame,
    registry_df: pd.DataFrame,
    *,
    active_owner_ids: list[str],
    target_sizes: dict[str, int],
    artist_cap: int = 3,
    album_cap: int = 2,
) -> ModularSelectionResult:
    """Select new cards for the active owners' expansions, honoring the registry.

    pool_df: the full curated song universe. Required columns: song_id,
    winner_track_id, year_final, owner_ids (list), primary_artist_id,
    primary_artist_name, album_id, popularity_winner; optional:
    editorial_guardrail_key. Extra columns pass through to the result.
    """
    states = {
        owner_id: ExpansionState(owner_id=owner_id, target_size=target_sizes[owner_id])
        for owner_id in sorted(active_owner_ids)
    }

    pool_records = pool_df.to_dict(orient="records")
    for record in pool_records:
        record["owner_ids"] = normalize_string_list(record.get("owner_ids"))
    pool_by_song_id = {record["song_id"]: record for record in pool_records}

    selected_song_ids: set[str] = set(registry_df["song_id"]) if not registry_df.empty else set()
    used_guardrail_keys: set[str] = set()
    for song_id in selected_song_ids:
        locked_record = pool_by_song_id.get(song_id)
        if locked_record is not None:
            guardrail_key = normalize_string_scalar(locked_record.get("editorial_guardrail_key"))
            if guardrail_key is not None:
                used_guardrail_keys.add(guardrail_key)

    if not registry_df.empty:
        _seed_locked_cards(registry_df, pool_by_song_id, states)

    eligible_records = [
        record
        for record in pool_records
        if _normalize_year(record.get("year_final")) is not None
    ]
    candidates_by_owner: dict[str, list[dict]] = {owner_id: [] for owner_id in states}
    for record in eligible_records:
        for owner_id in record["owner_ids"]:
            if owner_id in candidates_by_owner:
                candidates_by_owner[owner_id].append(record)

    pick_order = 0
    while True:
        open_states = [state for state in states.values() if not state.exhausted and state.deficit > 0]
        if not open_states:
            break

        state = min(open_states, key=lambda item: (-item.deficit, item.owner_id))
        candidates = [
            record
            for record in candidates_by_owner[state.owner_id]
            if record["song_id"] not in selected_song_ids
            and normalize_string_scalar(record.get("editorial_guardrail_key")) not in used_guardrail_keys
            and _passes_caps(record, state, artist_cap=artist_cap, album_cap=album_cap)
        ]
        if not candidates:
            state.exhausted = True
            logger.warning(
                "Expansion %s exhausted at %d/%d cards (playlist too small after caps/dedup)",
                state.owner_id,
                state.size,
                state.target_size,
            )
            continue

        winner = dict(min(candidates, key=lambda record: _sort_key(record, state)))
        pick_order += 1
        winner["expansion_anchor"] = state.owner_id
        winner["is_new"] = True
        winner["pick_order"] = pick_order

        selected_song_ids.add(winner["song_id"])
        guardrail_key = normalize_string_scalar(winner.get("editorial_guardrail_key"))
        if guardrail_key is not None:
            used_guardrail_keys.add(guardrail_key)
        _register(winner, state)
        state.picked.append(winner)

    new_records: list[dict] = []
    for owner_id in sorted(states):
        new_records.extend(states[owner_id].picked)
    new_cards_df = pd.DataFrame(new_records)
    if not new_cards_df.empty:
        new_cards_df = new_cards_df.sort_values("pick_order", kind="stable").reset_index(drop=True)

    _check_invariants(new_cards_df, registry_df)

    summary_rows = []
    underfilled: dict[str, int] = {}
    for owner_id, state in sorted(states.items()):
        summary_rows.append(
            {
                "owner_id": owner_id,
                "target_size": state.target_size,
                "locked_cards": state.locked_count,
                "new_cards": len(state.picked),
                "total_cards": state.size,
                "distinct_years": len(state.year_counts),
                "underfilled_by": max(state.deficit, 0),
            }
        )
        if state.deficit > 0:
            underfilled[owner_id] = state.deficit

    return ModularSelectionResult(
        new_cards_df=new_cards_df,
        expansion_summary_df=pd.DataFrame(summary_rows),
        underfilled=underfilled,
    )


def _check_invariants(new_cards_df: pd.DataFrame, registry_df: pd.DataFrame) -> None:
    if new_cards_df.empty:
        return

    duplicated = new_cards_df["song_id"][new_cards_df["song_id"].duplicated()].tolist()
    if duplicated:
        raise AssertionError(f"Selection produced duplicate song_ids: {duplicated[:5]}")

    if not registry_df.empty:
        overlap = set(new_cards_df["song_id"]) & set(registry_df["song_id"])
        if overlap:
            raise AssertionError(f"Selection re-picked songs already printed: {sorted(overlap)[:5]}")

    for row in new_cards_df[["song_id", "expansion_anchor", "owner_ids"]].to_dict(orient="records"):
        owner_ids = row["owner_ids"] if isinstance(row["owner_ids"], list) else split_owners(row["owner_ids"])
        if row["expansion_anchor"] not in owner_ids:
            raise AssertionError(
                f"Card for song {row['song_id']} anchored to {row['expansion_anchor']!r} "
                f"which is not among its owners {owner_ids}"
            )
