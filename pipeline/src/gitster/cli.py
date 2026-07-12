"""Gitster pipeline CLI.

Typical flow:
    gitster ingest                      # Spotify → catalog artifacts for a new run
    gitster curate                      # apply global-store curation, export review files
    gitster curate --review-xlsx FILE   # import human review, then re-apply curation
    gitster build-deck --version baseline-2026-07
    gitster registry mark-printed --version baseline-2026-07
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from gitster.catalog import (
    run_identity,
    run_ingest,
    run_instances,
    run_tracks_snapshot,
    run_years_baseline,
)
from gitster.config import RunConfig, load_run_config
from gitster.curation import (
    run_audit_exports,
    run_candidates,
    run_curation_sync,
    run_review_import,
)
from gitster.curation.store import resolve_global_store_dir
from gitster.deck.build import PRINT_SCOPES, RENDER_SPLITS, run_build_deck
from gitster.deck.registry import load_registry, mark_printed, validate_registry
from gitster.identity import IDENTITY_VERSION
from gitster.io_utils import read_parquet
from gitster.paths import RunPaths, create_run_paths, write_run_manifest

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config/config.json"
DEFAULT_RUNS_ROOT = "runs"


def _latest_run_id(runs_root: Path) -> str:
    if not runs_root.exists():
        raise FileNotFoundError(f"No runs directory at {runs_root}; run 'gitster ingest' first")
    run_dirs = sorted(path.name for path in runs_root.iterdir() if path.is_dir())
    if not run_dirs:
        raise FileNotFoundError(f"No runs found under {runs_root}; run 'gitster ingest' first")
    return run_dirs[-1]


def _resolve_paths(args: argparse.Namespace, *, existing: bool) -> RunPaths:
    runs_root = Path(args.runs_root)
    run_id = args.run_id
    if existing and run_id is None:
        run_id = _latest_run_id(runs_root)
        logger.info("Using latest run: %s", run_id)
    return create_run_paths(runs_root, run_id=run_id, seed=args.seed)


def _load_config(args: argparse.Namespace) -> RunConfig:
    return load_run_config(args.config)


def _cmd_ingest(args: argparse.Namespace) -> None:
    config = _load_config(args)
    paths = _resolve_paths(args, existing=False)
    write_run_manifest(
        paths,
        config_path=str(args.config),
        identity_version=IDENTITY_VERSION,
        seed=args.seed,
        owners=[
            {"owner_id": owner.owner_id, "owner_name": owner.owner_name, "playlist": owner.playlist}
            for owner in config.owners
        ],
    )
    run_ingest(config, paths)
    run_instances(config, paths)
    run_tracks_snapshot(config, paths)
    run_identity(config, paths)
    run_years_baseline(config, paths)
    logger.info("Ingest complete for run %s", paths.run_id)


def _cmd_curate(args: argparse.Namespace) -> None:
    config = _load_config(args)
    paths = _resolve_paths(args, existing=True)

    run_candidates(config, paths)
    run_curation_sync(config, paths, musicbrainz=args.musicbrainz)

    if args.review_csv or args.review_xlsx:
        run_review_import(config, paths, review_csv=args.review_csv, review_xlsx=args.review_xlsx)
        run_curation_sync(config, paths, musicbrainz=args.musicbrainz)

    run_audit_exports(config, paths)
    logger.info("Curation complete for run %s", paths.run_id)


def _cmd_build_deck(args: argparse.Namespace) -> None:
    config = _load_config(args)
    paths = _resolve_paths(args, existing=True)
    run_build_deck(
        config,
        paths,
        version=args.version,
        print_scope=args.print_scope,
        discard_pending=args.discard_pending,
        render_split=args.render_split,
    )


def _cmd_run(args: argparse.Namespace) -> None:
    _cmd_ingest(args)
    args.run_id = None
    _cmd_curate(args)
    _cmd_build_deck(args)


def _cmd_registry(args: argparse.Namespace) -> None:
    store_dir = resolve_global_store_dir()
    if args.registry_command == "show":
        registry_df = load_registry(store_dir)
        if registry_df.empty:
            logger.info("Printed registry is empty")
            return
        by_expansion = registry_df.groupby("expansion_anchor").size().to_dict()
        by_status = registry_df.groupby("printed_status").size().to_dict()
        logger.info("Printed registry: %d cards", len(registry_df))
        logger.info("By expansion: %s", by_expansion)
        logger.info("By status: %s", by_status)
    elif args.registry_command == "validate":
        registry_df = load_registry(store_dir)
        song_catalog_path = store_dir / "song_catalog.parquet"
        song_catalog_df = read_parquet(song_catalog_path) if song_catalog_path.exists() else None
        issues = validate_registry(registry_df, song_catalog_df)
        if not issues:
            logger.info("Registry OK: %d cards, no issues", len(registry_df))
            return
        for issue in issues:
            logger.error("%s", issue)
        raise SystemExit(1)
    elif args.registry_command == "mark-printed":
        updated = mark_printed(store_dir, version=args.version)
        logger.info("Marked %d cards as printed", updated)


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="path to config JSON")
    parser.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT, help="directory holding run artifacts")
    parser.add_argument("--run-id", default=None, help="run id (default: new for ingest, latest otherwise)")
    parser.add_argument("--seed", type=int, default=666)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitster", description="Gitster deck pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="fetch playlists and build the song catalog")
    _add_common_arguments(ingest_parser)
    ingest_parser.set_defaults(handler=_cmd_ingest)

    curate_parser = subparsers.add_parser("curate", help="apply curation; optionally import a review file")
    _add_common_arguments(curate_parser)
    curate_parser.add_argument("--review-csv", default=None)
    curate_parser.add_argument("--review-xlsx", default=None)
    curate_parser.add_argument(
        "--musicbrainz",
        action="store_true",
        help="enrich the review template with MusicBrainz first-release years (slow, rate-limited)",
    )
    curate_parser.set_defaults(handler=_cmd_curate)

    build_parser_ = subparsers.add_parser("build-deck", help="select, package and render the modular deck")
    _add_common_arguments(build_parser_)
    build_parser_.add_argument("--version", required=True, help="print batch label, e.g. baseline-2026-07")
    build_parser_.add_argument("--print-scope", choices=PRINT_SCOPES, default="new-only")
    build_parser_.add_argument(
        "--discard-pending",
        action="store_true",
        help="drop never-printed pending cards from the registry before selecting",
    )
    build_parser_.add_argument(
        "--render-split",
        choices=RENDER_SPLITS,
        default="combined",
        help="one full-deck PDF (combined, default), one PDF per expansion, or both",
    )
    build_parser_.set_defaults(handler=_cmd_build_deck)

    run_parser = subparsers.add_parser("run", help="ingest + curate + build-deck in one go")
    _add_common_arguments(run_parser)
    run_parser.add_argument("--version", required=True)
    run_parser.add_argument("--print-scope", choices=PRINT_SCOPES, default="new-only")
    run_parser.add_argument("--render-split", choices=RENDER_SPLITS, default="combined")
    run_parser.add_argument("--discard-pending", action="store_true")
    run_parser.add_argument("--review-csv", default=None)
    run_parser.add_argument("--review-xlsx", default=None)
    run_parser.add_argument(
        "--musicbrainz",
        action="store_true",
        help="enrich the review template with MusicBrainz first-release years (slow, rate-limited)",
    )
    run_parser.set_defaults(handler=_cmd_run)

    registry_parser = subparsers.add_parser("registry", help="inspect or update the printed registry")
    registry_subparsers = registry_parser.add_subparsers(dest="registry_command", required=True)
    registry_subparsers.add_parser("show")
    registry_subparsers.add_parser("validate")
    mark_parser = registry_subparsers.add_parser("mark-printed")
    mark_parser.add_argument("--version", default=None, help="only cards of this print batch")
    registry_parser.set_defaults(handler=_cmd_registry)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except (FileNotFoundError, ValueError) as error:
        logger.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
