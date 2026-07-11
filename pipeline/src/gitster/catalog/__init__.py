"""Catalog chain: ingest -> instances -> tracks -> identity -> years."""

from gitster.catalog.ingest import run_ingest
from gitster.catalog.instances import run_instances
from gitster.catalog.songs import run_identity
from gitster.catalog.tracks import run_tracks_snapshot
from gitster.catalog.years import run_years_baseline

__all__ = [
    "run_ingest",
    "run_instances",
    "run_tracks_snapshot",
    "run_identity",
    "run_years_baseline",
]
