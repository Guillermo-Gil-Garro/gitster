"""Compact HTML report for a modular deck build: per-expansion stats and
year-coverage for expansion combinations (individual, pairs, full group)."""

from __future__ import annotations

import html
import logging
from itertools import combinations
from pathlib import Path

import pandas as pd

from gitster.deck.registry import split_owners

logger = logging.getLogger(__name__)

_STYLE = """
body { font-family: system-ui, sans-serif; margin: 2rem; color: #222; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
table { border-collapse: collapse; margin-top: 0.5rem; }
th, td { border: 1px solid #ccc; padding: 0.3rem 0.6rem; font-size: 0.85rem; text-align: left; }
th { background: #f2f2f2; }
td.num { text-align: right; }
.warn { color: #b00; font-weight: 600; }
"""


def _years_by_expansion(registry_df: pd.DataFrame) -> dict[str, set[int]]:
    years: dict[str, set[int]] = {}
    for record in registry_df.to_dict(orient="records"):
        if pd.isna(record.get("year")):
            continue
        years.setdefault(record["expansion_anchor"], set()).add(int(record["year"]))
    return years


def _coverage_row(label: str, year_sets: list[set[int]]) -> dict:
    combined: set[int] = set().union(*year_sets) if year_sets else set()
    if not combined:
        return {"combination": label, "cards_years": 0, "min": "", "max": "", "gaps": ""}
    span = range(min(combined), max(combined) + 1)
    gaps = [year for year in span if year not in combined]
    return {
        "combination": label,
        "cards_years": len(combined),
        "min": min(combined),
        "max": max(combined),
        "gaps": ", ".join(str(year) for year in gaps) if gaps else "none",
    }


def _table(rows: list[dict], columns: list[str]) -> str:
    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column, "")
            css = ' class="num"' if isinstance(value, (int, float)) and not isinstance(value, bool) else ""
            cells.append(f"<td{css}>{html.escape(str(value))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><tr>{header}</tr>{''.join(body_rows)}</table>"


def write_deck_report(
    *,
    registry_df: pd.DataFrame,
    expansion_summary_df: pd.DataFrame,
    new_cards_df: pd.DataFrame,
    version: str,
    out_path: Path,
) -> Path:
    years_by_expansion = _years_by_expansion(registry_df)
    expansions = sorted(years_by_expansion)

    coverage_rows = [_coverage_row(expansion, [years_by_expansion[expansion]]) for expansion in expansions]
    for left, right in combinations(expansions, 2):
        coverage_rows.append(_coverage_row(f"{left} + {right}", [years_by_expansion[left], years_by_expansion[right]]))
    if len(expansions) > 2:
        coverage_rows.append(_coverage_row("ALL", [years_by_expansion[expansion] for expansion in expansions]))

    summary_rows = expansion_summary_df.to_dict(orient="records")

    new_rows = []
    for record in new_cards_df.to_dict(orient="records"):
        new_rows.append(
            {
                "card_id": record.get("card_id"),
                "expansion": record.get("expansion_anchor"),
                "year": record.get("year_final"),
                "title": record.get("title_display"),
                "artists": record.get("artists_display_resolved"),
                "owners": ", ".join(split_owners(record.get("owners"))),
            }
        )

    sections = [
        f"<h1>Gitster deck report — {html.escape(version)}</h1>",
        f"<p>Physical collection: {len(registry_df)} cards across {len(expansions)} expansions. "
        f"New this run: {len(new_cards_df)}.</p>",
        "<h2>Expansions</h2>",
        _table(summary_rows, list(expansion_summary_df.columns)) if summary_rows else "<p>No expansion data.</p>",
        "<h2>Year coverage (single / pairs / all)</h2>",
        _table(coverage_rows, ["combination", "cards_years", "min", "max", "gaps"]),
        "<h2>New cards in this run</h2>",
        _table(new_rows, ["card_id", "expansion", "year", "title", "artists", "owners"])
        if new_rows
        else "<p>No new cards.</p>",
    ]

    document = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>Gitster deck report — {html.escape(version)}</title>"
        f"<style>{_STYLE}</style></head><body>{''.join(sections)}</body></html>"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    logger.info("Wrote deck report to %s", out_path)
    return out_path
