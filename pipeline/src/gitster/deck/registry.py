"""Printed-cards registry: the append-only source of truth for the physical collection.

Lives in the global store as a single CSV (plus a parquet mirror for robust reads).
Invariants enforced here:
- a song_id exists at most once (one physical card, ever);
- card_id is unique and numbering per expansion is append-only;
- existing rows are immutable on append (only printed_status/printed_at may change,
  via mark_printed).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from gitster.io_utils import write_parquet_atomic

logger = logging.getLogger(__name__)

REGISTRY_COLUMNS = [
    "song_id",
    "winner_track_id",
    "card_id",
    "title",
    "artists",
    "year",
    "owners",
    "expansion_anchor",
    "printed_status",
    "version",
    "identity_version",
    "run_id",
    "created_at",
    "printed_at",
]

PRINTED_STATUS_VALUES = {"pending", "printed"}

_CARD_ID_PATTERN = re.compile(r"^GITSTER_(?P<owner>[A-Z0-9]+)_(?P<number>\d{3})$")

OWNERS_SEPARATOR = "|"


def _csv_path(store_dir: Path) -> Path:
    return store_dir / "printed_registry.csv"


def _parquet_path(store_dir: Path) -> Path:
    return store_dir / "printed_registry.parquet"


def _backups_dir(store_dir: Path) -> Path:
    return store_dir / "printed_registry_backups"


def make_card_id(owner_id: str, number: int) -> str:
    return f"GITSTER_{owner_id.upper()}_{number:03d}"


def split_owners(value: str | None) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [item for item in str(value).split(OWNERS_SEPARATOR) if item]


def join_owners(owner_ids: list[str]) -> str:
    return OWNERS_SEPARATOR.join(owner_ids)


def _empty_registry() -> pd.DataFrame:
    return pd.DataFrame(columns=REGISTRY_COLUMNS)


def _validate_frame(registry_df: pd.DataFrame, *, source: str) -> None:
    missing_columns = [column for column in REGISTRY_COLUMNS if column not in registry_df.columns]
    if missing_columns:
        raise ValueError(f"{source}: registry is missing columns {missing_columns}")

    duplicated_songs = registry_df["song_id"][registry_df["song_id"].duplicated()].tolist()
    if duplicated_songs:
        raise ValueError(f"{source}: duplicate song_id entries in registry: {duplicated_songs[:5]}")

    duplicated_cards = registry_df["card_id"][registry_df["card_id"].duplicated()].tolist()
    if duplicated_cards:
        raise ValueError(f"{source}: duplicate card_id entries in registry: {duplicated_cards[:5]}")

    bad_status = set(registry_df["printed_status"].dropna().unique()) - PRINTED_STATUS_VALUES
    if bad_status:
        raise ValueError(f"{source}: invalid printed_status values: {sorted(bad_status)}")

    for row in registry_df[["card_id", "expansion_anchor", "owners"]].to_dict(orient="records"):
        match = _CARD_ID_PATTERN.match(str(row["card_id"]))
        if match is None:
            raise ValueError(f"{source}: card_id {row['card_id']!r} does not match GITSTER_<OWNER>_<NNN>")
        anchor = str(row["expansion_anchor"])
        if match.group("owner") != anchor.upper():
            raise ValueError(
                f"{source}: card_id {row['card_id']!r} does not match its expansion_anchor {anchor!r}"
            )
        if anchor not in split_owners(row["owners"]):
            raise ValueError(
                f"{source}: card {row['card_id']!r} is anchored to {anchor!r} "
                f"but {anchor!r} is not among its owners {row['owners']!r}"
            )


def load_registry(store_dir: Path) -> pd.DataFrame:
    """Load the printed registry, or an empty frame if none exists yet."""
    csv_path = _csv_path(store_dir)
    if not csv_path.exists():
        return _empty_registry()

    registry_df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""])
    registry_df["year"] = registry_df["year"].astype("Int64")
    _validate_frame(registry_df, source=str(csv_path))
    return registry_df.reindex(columns=REGISTRY_COLUMNS)


def _write_registry(store_dir: Path, registry_df: pd.DataFrame) -> None:
    csv_path = _csv_path(store_dir)

    if csv_path.exists():
        backups_dir = _backups_dir(store_dir)
        backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backups_dir / f"printed_registry_{timestamp}.csv"
        backup_path.write_bytes(csv_path.read_bytes())

    tmp_path = csv_path.with_suffix(".csv.tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    registry_df.to_csv(tmp_path, index=False, encoding="utf-8")
    tmp_path.replace(csv_path)
    write_parquet_atomic(_parquet_path(store_dir), registry_df)


def next_card_number(registry_df: pd.DataFrame, expansion_anchor: str) -> int:
    """Next free per-expansion card number, continuing append-only numbering."""
    if registry_df.empty:
        return 1

    expansion_cards = registry_df[registry_df["expansion_anchor"] == expansion_anchor]
    if expansion_cards.empty:
        return 1

    numbers = [
        int(_CARD_ID_PATTERN.match(str(card_id)).group("number"))
        for card_id in expansion_cards["card_id"]
    ]
    return max(numbers) + 1


def append_cards(store_dir: Path, new_cards_df: pd.DataFrame, *, version: str, run_id: str) -> pd.DataFrame:
    """Append newly selected cards to the registry. Existing rows are never modified.

    new_cards_df must carry: song_id, winner_track_id, card_id, title, artists, year,
    owners (pipe-joined), expansion_anchor, identity_version.
    """
    registry_df = load_registry(store_dir)

    incoming_df = new_cards_df.copy()
    incoming_df["printed_status"] = "pending"
    incoming_df["version"] = version
    incoming_df["run_id"] = run_id
    incoming_df["created_at"] = datetime.now().isoformat(timespec="seconds")
    incoming_df["printed_at"] = None
    incoming_df = incoming_df.reindex(columns=REGISTRY_COLUMNS)

    overlap_songs = set(incoming_df["song_id"]) & set(registry_df["song_id"])
    if overlap_songs:
        raise ValueError(
            f"Refusing to append {len(overlap_songs)} songs already in the registry: "
            f"{sorted(overlap_songs)[:5]}"
        )
    overlap_cards = set(incoming_df["card_id"]) & set(registry_df["card_id"])
    if overlap_cards:
        raise ValueError(f"Refusing to append duplicate card_ids: {sorted(overlap_cards)[:5]}")

    combined_df = pd.concat([registry_df, incoming_df], ignore_index=True)
    _validate_frame(combined_df, source="append_cards")

    original_rows = combined_df.iloc[: len(registry_df)].reset_index(drop=True).astype(object)
    existing_rows = registry_df.reset_index(drop=True).astype(object)
    if not existing_rows.equals(original_rows):
        raise AssertionError("append_cards would have altered existing registry rows")

    _write_registry(store_dir, combined_df)
    logger.info("Appended %d cards to the printed registry (version=%s)", len(incoming_df), version)
    return combined_df


def mark_printed(store_dir: Path, *, version: str | None = None) -> int:
    """Flip pending cards to printed (optionally only those of one version)."""
    registry_df = load_registry(store_dir)
    mask = registry_df["printed_status"] == "pending"
    if version is not None:
        mask &= registry_df["version"] == version

    updated_count = int(mask.sum())
    if updated_count == 0:
        logger.info("No pending cards to mark as printed")
        return 0

    registry_df.loc[mask, "printed_status"] = "printed"
    registry_df.loc[mask, "printed_at"] = datetime.now().isoformat(timespec="seconds")
    _write_registry(store_dir, registry_df)
    logger.info("Marked %d cards as printed", updated_count)
    return updated_count


def delete_pending(store_dir: Path, *, version: str | None = None) -> int:
    """Remove never-printed (pending) cards so a new selection can regenerate them."""
    registry_df = load_registry(store_dir)
    mask = registry_df["printed_status"] == "pending"
    if version is not None:
        mask &= registry_df["version"] == version

    removed_count = int(mask.sum())
    if removed_count == 0:
        return 0

    _write_registry(store_dir, registry_df[~mask].reset_index(drop=True))
    logger.info("Removed %d pending cards from the printed registry", removed_count)
    return removed_count


def validate_registry(registry_df: pd.DataFrame, song_catalog_df: pd.DataFrame | None = None) -> list[str]:
    """Return a list of human-readable issues (empty when healthy)."""
    issues: list[str] = []
    try:
        _validate_frame(registry_df, source="registry")
    except ValueError as error:
        issues.append(str(error))

    if song_catalog_df is not None and not registry_df.empty:
        known_song_ids = set(song_catalog_df["song_id"].dropna())
        unknown = registry_df[~registry_df["song_id"].isin(known_song_ids)]
        for row in unknown[["card_id", "song_id"]].to_dict(orient="records"):
            issues.append(
                f"card {row['card_id']} references song_id {row['song_id']} "
                "not present in the song catalog (identity drift?)"
            )
    return issues
