"""Orchestrates a modular deck build: pool → selection → packaging → registry →
renders → deck.json → report."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from gitster.config import RunConfig
from gitster.curation.store import resolve_global_store_dir
from gitster.deck.packaging import (
    build_new_card_rows,
    build_owner_name_map,
    build_track_url_map,
    card_rows_from_registry,
    registry_rows_from_cards,
)
from gitster.deck.pool import build_modular_pool
from gitster.deck.registry import (
    append_cards,
    delete_pending,
    load_registry,
    validate_registry,
)
from gitster.deck.selection import select_modular_deck
from gitster.export.deck_json import export_deck_json
from gitster.export.render_pdf import render_deck_pdfs
from gitster.export.report_html import write_deck_report
from gitster.identity import IDENTITY_VERSION
from gitster.io_utils import read_parquet, write_csv, write_xlsx
from gitster.paths import RunPaths

logger = logging.getLogger(__name__)

PRINT_SCOPES = ("new-only", "all")


def _pipeline_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_asset_paths() -> tuple[Path, Path]:
    root = _pipeline_root()
    return root / "assets" / "deck" / "backgrounds" / "front", root / "assets" / "deck" / "back" / "back_bg.png"


def _load_processed(paths: RunPaths, name: str) -> pd.DataFrame:
    artifact_path = paths.processed_dir / f"{name}.parquet"
    if not artifact_path.exists():
        raise FileNotFoundError(f"Missing {artifact_path}; run the ingest and curate steps first")
    return read_parquet(artifact_path)


def run_build_deck(
    config: RunConfig,
    paths: RunPaths,
    *,
    version: str,
    print_scope: str = "new-only",
    discard_pending: bool = False,
) -> None:
    if print_scope not in PRINT_SCOPES:
        raise ValueError(f"print_scope must be one of {PRINT_SCOPES}, got {print_scope!r}")

    songs_curated_df = _load_processed(paths, "songs_curated")
    years_curated_df = _load_processed(paths, "years_curated")
    instances_df = _load_processed(paths, "instances")
    song_variant_map_df = _load_processed(paths, "song_variant_map")

    store_dir = resolve_global_store_dir()
    if discard_pending:
        removed = delete_pending(store_dir)
        logger.info("Discarded %d pending (never printed) cards before selecting", removed)

    registry_df = load_registry(store_dir)
    issues = validate_registry(registry_df, songs_curated_df)
    for issue in issues:
        logger.warning("Registry issue: %s", issue)

    pool_df = build_modular_pool(
        songs_curated_df=songs_curated_df,
        years_curated_df=years_curated_df,
        instances_df=instances_df,
        song_variant_map_df=song_variant_map_df,
        run_id=paths.run_id,
    )
    logger.info("Selection pool: %d curated songs", len(pool_df))

    active_owner_ids = [owner.owner_id for owner in config.owners]
    target_sizes = {owner_id: config.deck.size_for(owner_id) for owner_id in active_owner_ids}
    result = select_modular_deck(
        pool_df,
        registry_df,
        active_owner_ids=active_owner_ids,
        target_sizes=target_sizes,
        artist_cap=config.deck.artist_cap_per_expansion,
        album_cap=config.deck.album_cap_per_expansion,
    )
    for owner_id, missing in result.underfilled.items():
        logger.warning("Expansion %s is underfilled by %d cards", owner_id, missing)

    owner_name_map = build_owner_name_map(instances_df)
    track_url_map = build_track_url_map(instances_df)
    owner_color_map = {owner.owner_id: owner.color for owner in config.owners}
    new_cards_df = build_new_card_rows(
        result.new_cards_df,
        registry_df,
        owner_name_map=owner_name_map,
        track_url_map=track_url_map,
        owner_color_map=owner_color_map,
    )

    if new_cards_df.empty:
        logger.info("No new cards to add: the printed collection already satisfies the targets")
        registry_after_df = registry_df
    else:
        registry_after_df = append_cards(
            store_dir,
            registry_rows_from_cards(new_cards_df, identity_version=IDENTITY_VERSION),
            version=version,
            run_id=paths.run_id,
        )

    write_csv(paths.reports_dir / "expansion_summary.csv", result.expansion_summary_df)
    if not new_cards_df.empty:
        report_cards_df = new_cards_df.copy()
        report_cards_df["secondary_artist_names"] = report_cards_df["secondary_artist_names"].map(
            lambda value: " | ".join(value) if isinstance(value, list) else value
        )
        write_csv(paths.reports_dir / "deck_new_cards.csv", report_cards_df)
        write_xlsx(paths.reports_dir / "deck_new_cards.xlsx", report_cards_df, sheet_name="new_cards")

    front_dir, back_bg_path = default_asset_paths()
    rendered_any = False
    for owner_id in active_owner_ids:
        if print_scope == "new-only":
            expansion_cards_df = new_cards_df[new_cards_df["expansion_anchor"] == owner_id]
        else:
            expansion_cards_df = card_rows_from_registry(
                registry_after_df[registry_after_df["expansion_anchor"] == owner_id],
                owner_name_map,
                owner_color_map,
            )
        if expansion_cards_df.empty:
            continue
        out_dir = paths.renders_dir / f"expansion_{owner_id}"
        written = render_deck_pdfs(
            expansion_cards_df,
            out_dir=out_dir,
            front_dir=front_dir,
            back_bg_path=back_bg_path,
        )
        rendered_any = True
        logger.info("Rendered %d PDFs for expansion %s in %s", len(written), owner_id, out_dir)

    if not rendered_any:
        logger.info("Nothing to render for print scope %s", print_scope)

    registry_snapshot_path = paths.reports_dir / "printed_registry_snapshot.csv"
    write_csv(registry_snapshot_path, registry_after_df)

    export_deck_json(registry_after_df, version=version, out_path=paths.reports_dir / "deck.json")
    write_deck_report(
        registry_df=registry_after_df,
        expansion_summary_df=result.expansion_summary_df,
        new_cards_df=new_cards_df,
        version=version,
        out_path=paths.reports_dir / "deck_report.html",
    )

    logger.info(
        "Deck build complete | new_cards=%d | collection_total=%d | version=%s",
        len(new_cards_df),
        len(registry_after_df),
        version,
    )
