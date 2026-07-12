"""Rich HTML deck report for the modular pipeline.

Ported from the v2 pipeline deck report (summary stats, sortable and
filterable card table, theme toggle, print view) and adapted to per-player
expansions: the cards payload is the whole physical registry, and the table,
KPIs and charts can be filtered per expansion with client-side recomputation.

All charts (years histogram with bin toggle, owner appearances, owner
combinations, top artists) are rendered client-side in deck_report_base.js
from the embedded cards payload, so they always reflect the filtered subset.

CSS/JS are loaded at build time from the stable assets directory
(assets/deck/report) and inlined into the document, mirroring the v2 pattern.
"""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from gitster.deck.registry import split_owners

logger = logging.getLogger(__name__)

_PIPELINE_ROOT = Path(__file__).resolve().parents[3]
DECK_REPORT_ASSETS_DIR = _PIPELINE_ROOT / "assets" / "deck" / "report"

SPOTIFY_TRACK_URL_PREFIX = "https://open.spotify.com/track/"

# Fallback palette when an owner has no configured color.
_DEFAULT_CHIP_COLORS = ["#00E5FF", "#FF2BD6", "#8A5CFF", "#FFB000", "#2FE36D", "#FF3B3B"]


# --------------------------------------------------------------------------- assets


def _report_asset_paths() -> tuple[Path, Path]:
    return (
        DECK_REPORT_ASSETS_DIR / "deck_report_base.css",
        DECK_REPORT_ASSETS_DIR / "deck_report_base.js",
    )


def _read_report_asset_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Could not load deck report asset {path}") from exc


def _report_css() -> str:
    css_path, _js_path = _report_asset_paths()
    return _read_report_asset_text(css_path)


def _report_js() -> str:
    _css_path, js_path = _report_asset_paths()
    return _read_report_asset_text(js_path)


# --------------------------------------------------------------------------- helpers


def _as_text(value) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value)


def _parse_int(value) -> int | None:
    text = _as_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _primary_artist(artists: str) -> str:
    """Primary artist = the display string cut at the ' feat. ' marker."""
    return artists.split(" feat. ", 1)[0].strip()


# --------------------------------------------------------------------------- static tables


def _table_html(rows: list[dict], columns: list[str], table_id: str) -> str:
    if not rows:
        return "<p class='muted'>No data.</p>"
    parts: list[str] = [f"<table id='{html.escape(table_id)}' class='tbl'>", "<thead><tr>"]
    for index, column in enumerate(columns):
        parts.append(f"<th onclick=\"sortTable('{html.escape(table_id)}',{index})\">{html.escape(column)}</th>")
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for column in columns:
            value = row.get(column, "")
            css = " class='num'" if isinstance(value, (int, float)) and not isinstance(value, bool) else ""
            parts.append(f"<td{css}>{html.escape(_as_text(value))}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


# --------------------------------------------------------------------------- payload


def _owner_names(owner_ids: list[str], owner_name_map: dict[str, str]) -> list[str]:
    names: list[str] = []
    for owner_id in owner_ids:
        name = owner_name_map.get(owner_id) or owner_id
        if name not in names:
            names.append(name)
    return names


def _build_cards_payload(
    registry_df: pd.DataFrame,
    *,
    new_card_ids: set[str],
    owner_name_map: dict[str, str],
) -> list[dict]:
    cards: list[dict] = []
    records = registry_df.to_dict(orient="records")
    records.sort(key=lambda record: _as_text(record.get("card_id")))
    for idx, record in enumerate(records):
        card_id = _as_text(record.get("card_id"))
        track_id = _as_text(record.get("winner_track_id"))
        owner_ids = split_owners(record.get("owners"))
        artists = _as_text(record.get("artists"))
        cards.append(
            {
                "_row_index": idx,
                "card_id": card_id,
                "expansion": _as_text(record.get("expansion_anchor")),
                "year": _parse_int(record.get("year")) or "",
                "title": _as_text(record.get("title")),
                "artists": artists,
                "primary_artist": _primary_artist(artists),
                "owners": ", ".join(_owner_names(owner_ids, owner_name_map)),
                "owner_ids": owner_ids,
                "status": _as_text(record.get("printed_status")),
                "version": _as_text(record.get("version")),
                "is_new": card_id in new_card_ids,
                "spotify_url": f"{SPOTIFY_TRACK_URL_PREFIX}{track_id}" if track_id else "",
            }
        )
    return cards


def _build_expansion_items(
    cards: list[dict],
    expansion_summary_df: pd.DataFrame,
    *,
    owner_name_map: dict[str, str],
    owner_color_map: dict[str, str],
) -> list[dict]:
    counts: dict[str, int] = {}
    for card in cards:
        counts[card["expansion"]] = counts.get(card["expansion"], 0) + 1
    expansion_ids = set(counts)
    if "owner_id" in expansion_summary_df.columns:
        expansion_ids |= {_as_text(value) for value in expansion_summary_df["owner_id"].tolist() if _as_text(value)}
    items: list[dict] = []
    for index, expansion_id in enumerate(sorted(expansion_ids)):
        color = owner_color_map.get(expansion_id) or _DEFAULT_CHIP_COLORS[index % len(_DEFAULT_CHIP_COLORS)]
        items.append(
            {
                "id": expansion_id,
                "name": owner_name_map.get(expansion_id) or expansion_id,
                "color": color,
                "cards": counts.get(expansion_id, 0),
            }
        )
    return items


def _build_owner_lookup(
    cards: list[dict],
    expansion_items: list[dict],
    *,
    owner_name_map: dict[str, str],
    owner_color_map: dict[str, str],
) -> dict[str, dict[str, str]]:
    """Names and colors for every owner id the client-side charts may see."""
    owner_ids: set[str] = {item["id"] for item in expansion_items}
    for card in cards:
        owner_ids.update(card["owner_ids"])
    color_by_id = {item["id"]: item["color"] for item in expansion_items}
    names: dict[str, str] = {}
    colors: dict[str, str] = {}
    for index, owner_id in enumerate(sorted(owner_ids)):
        names[owner_id] = owner_name_map.get(owner_id) or owner_id
        colors[owner_id] = (
            owner_color_map.get(owner_id)
            or color_by_id.get(owner_id)
            or _DEFAULT_CHIP_COLORS[index % len(_DEFAULT_CHIP_COLORS)]
        )
    return {"names": names, "colors": colors}


# --------------------------------------------------------------------------- HTML sections


def _render_header(*, version: str, generated_at: str, total_cards: int, expansion_count: int, new_count: int) -> str:
    return (
        "<header class='report-header'>"
        "<h1>Gitster Deck Report</h1>"
        "<div class='header-meta'>"
        f"<span class='header-badge'><strong>version</strong>{html.escape(version)}</span>"
        f"<span class='header-badge'><strong>cards</strong>{total_cards}</span>"
        f"<span class='header-badge'><strong>expansions</strong>{expansion_count}</span>"
        f"<span class='header-badge'><strong>new this run</strong>{new_count}</span>"
        f"<span class='header-badge'><strong>generated</strong>{html.escape(generated_at)}</span>"
        "</div>"
        "<div class='header-actions pdf-hide' id='header-actions'>"
        "<button id='theme-toggle' type='button' class='btn btn-pill btn-icon theme-toggle' aria-label='Toggle theme' title='Theme' aria-pressed='true'>"
        "<svg viewBox='0 0 24 24' aria-hidden='true' focusable='false'>"
        "<circle cx='12' cy='12' r='8.5' fill='none' stroke='currentColor' stroke-width='1.8'/>"
        "<path d='M12 3.5 A8.5 8.5 0 0 1 12 20.5 Z' fill='currentColor' opacity='0.4'/>"
        "</svg><span class='btn-label'>Light</span></button>"
        "<button id='pdf-export' type='button' class='btn btn-pill btn-icon pdf-export-btn' aria-label='Export PDF' title='Export PDF'>"
        "<svg viewBox='0 0 24 24' aria-hidden='true' focusable='false'>"
        "<circle cx='12' cy='12' r='8.5' fill='none' stroke='currentColor' stroke-width='1.8'/>"
        "<path d='M9 8.5h5l2 2v5H9z' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linejoin='round'/>"
        "<path d='M14 8.5v2h2' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linejoin='round'/>"
        "</svg><span class='btn-label'>PDF</span></button>"
        "</div></header>"
    )


def _render_summary_stats(cards: list[dict], expansion_count: int) -> str:
    years = [card["year"] for card in cards if isinstance(card["year"], int)]
    printed = sum(1 for card in cards if card["status"] == "printed")
    pending = sum(1 for card in cards if card["status"] == "pending")
    new_count = sum(1 for card in cards if card["is_new"])
    tiles = [
        ("visible cards", "stat-visible", f"{len(cards)} / {len(cards)}"),
        ("expansions", "stat-expansions", expansion_count),
        ("distinct years", "stat-years", len(set(years))),
        ("min year", "stat-min-year", min(years) if years else "-"),
        ("max year", "stat-max-year", max(years) if years else "-"),
        ("printed", "stat-printed", printed),
        ("pending", "stat-pending", pending),
        ("new this run", "stat-new", new_count),
    ]
    parts = ["<div class='card' id='sec-summary'><h2>Summary</h2><div class='grid'>"]
    for label, stat_id, value in tiles:
        parts.append(
            f"<div class='kpi'><div class='muted'>{html.escape(label)}</div>"
            f"<div><b id='{html.escape(stat_id)}'>{html.escape(str(value))}</b></div></div>"
        )
    parts.append("</div><p class='muted'>Stats recompute over the rows matching the active table filters.</p></div>")
    return "".join(parts)


def _render_expansion_chips(expansion_items: list[dict], total_cards: int) -> str:
    parts = ["<div id='expansion-filter' class='exp-chips' role='group' aria-label='Expansion filter'>"]
    parts.append(
        "<button type='button' class='exp-chip active' data-expansion='__all' aria-pressed='true'>"
        f"All <span class='chip-count'>{total_cards}</span></button>"
    )
    for item in expansion_items:
        color = html.escape(_as_text(item["color"]), quote=True)
        parts.append(
            f"<button type='button' class='exp-chip' data-expansion='{html.escape(item['id'], quote=True)}' "
            f"style='--chip-accent: {color}' aria-pressed='false'>"
            "<span class='chip-dot'></span>"
            f"{html.escape(item['name'])} <span class='chip-count'>{item['cards']}</span></button>"
        )
    parts.append("</div>")
    return "".join(parts)


def _render_deck_table_section(expansion_items: list[dict], total_cards: int) -> str:
    return (
        f"<div class='card' id='deck-table-section'><h2>Cards ({total_cards})</h2>"
        + _render_expansion_chips(expansion_items, total_cards)
        + "<div class='deck-controls'>"
        "<input id='deck-search' type='text' placeholder='Free text search...'/>"
        "<input id='deck-year-min' type='number' placeholder='Year min'/>"
        "<input id='deck-year-max' type='number' placeholder='Year max'/>"
        "<button id='deck-reset' type='button' class='btn'>Reset filters</button>"
        "<button id='deck-export' type='button' class='btn'>Export CSV (filtered)</button>"
        "</div>"
        "<div id='deck-table-stats' class='muted' aria-live='polite'></div>"
        "<div class='table-wrap'><table id='deck-table' class='tbl'><thead></thead><tbody></tbody></table></div>"
        "</div>"
    )


def _render_charts_section() -> str:
    """Empty chart hosts; deck_report_base.js renders into them from the payload."""
    return (
        "<div class='card' id='sec-charts'><h2>Charts (visible cards)</h2>"
        "<p class='muted'>Charts follow the active table filters (expansion, search, year range).</p>"
        "<div class='chart-block'>"
        "<div class='chart-head'><div class='chart-title'>Cards per year</div>"
        "<div id='year-bin-toggle' class='bin-toggle pdf-hide' role='group' aria-label='Year bin size'>"
        "<button type='button' class='btn bin-btn' data-bin='1'>1y</button>"
        "<button type='button' class='btn bin-btn active' data-bin='5'>5y</button>"
        "<button type='button' class='btn bin-btn' data-bin='10'>10y</button>"
        "</div></div>"
        "<div id='chart-years' class='chart-host'></div>"
        "</div>"
        "<div class='chart-block'>"
        "<div class='chart-title'>Owner appearances</div>"
        "<div id='chart-owner-appearances' class='chart-host'></div>"
        "</div>"
        "<div class='chart-block'>"
        "<div class='chart-title'>Owner combinations</div>"
        "<div id='chart-owner-combos' class='chart-host'></div>"
        "<div id='chart-owner-combos-note' class='muted'></div>"
        "</div>"
        "<div class='chart-block'>"
        "<div class='chart-title'>Top 10 artists</div>"
        "<div id='chart-top-artists' class='chart-host'></div>"
        "</div>"
        "</div>"
    )


def _render_new_cards_section(new_cards_df: pd.DataFrame) -> str:
    rows: list[dict] = []
    for record in new_cards_df.to_dict(orient="records"):
        rows.append(
            {
                "card_id": _as_text(record.get("card_id")),
                "expansion": _as_text(record.get("expansion_anchor")),
                "year": _parse_int(record.get("year_final")) or "",
                "title": _as_text(record.get("title_display")),
                "artists": _as_text(record.get("artists_display_resolved")),
                "owners": ", ".join(split_owners(record.get("owners"))),
            }
        )
    body = (
        _table_html(rows, ["card_id", "expansion", "year", "title", "artists", "owners"], "tbl_new_cards")
        if rows
        else "<p class='muted'>No new cards in this run.</p>"
    )
    return (
        f"<details id='sec-new' open><summary>New cards in this run ({len(rows)})</summary>"
        f"<div class='card'>{body}</div></details>"
    )


# --------------------------------------------------------------------------- entry point


def write_deck_report(
    *,
    registry_df: pd.DataFrame,
    expansion_summary_df: pd.DataFrame,
    new_cards_df: pd.DataFrame,
    version: str,
    out_path: Path,
    owner_name_map: dict[str, str] | None = None,
    owner_color_map: dict[str, str] | None = None,
) -> Path:
    owner_name_map = owner_name_map or {}
    owner_color_map = owner_color_map or {}
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_card_ids: set[str] = set()
    if not new_cards_df.empty and "card_id" in new_cards_df.columns:
        new_card_ids = {_as_text(value) for value in new_cards_df["card_id"].tolist() if _as_text(value)}

    cards = _build_cards_payload(registry_df, new_card_ids=new_card_ids, owner_name_map=owner_name_map)
    expansion_items = _build_expansion_items(
        cards,
        expansion_summary_df,
        owner_name_map=owner_name_map,
        owner_color_map=owner_color_map,
    )
    owner_lookup = _build_owner_lookup(
        cards,
        expansion_items,
        owner_name_map=owner_name_map,
        owner_color_map=owner_color_map,
    )

    report_data = {
        "meta": {"report_id": f"gitster_deck:{version}", "version": version, "generated_at": generated_at},
        "cards": cards,
        "expansions": expansion_items,
        "owners": owner_lookup,
    }
    report_data_json = json.dumps(report_data, ensure_ascii=False).replace("</", "<\\/")

    summary_rows = expansion_summary_df.to_dict(orient="records")

    sections: list[str] = []
    sections.append(
        _render_header(
            version=version,
            generated_at=generated_at,
            total_cards=len(cards),
            expansion_count=len(expansion_items),
            new_count=len(new_card_ids),
        )
    )
    sections.append(_render_summary_stats(cards, len(expansion_items)))
    sections.append(_render_deck_table_section(expansion_items, len(cards)))
    sections.append(_render_charts_section())
    sections.append(
        "<details id='sec-expansions' open><summary>Expansion summary</summary><div class='card'>"
        + (
            _table_html(summary_rows, [str(column) for column in expansion_summary_df.columns], "tbl_expansion_summary")
            if summary_rows
            else "<p class='muted'>No expansion data.</p>"
        )
        + "</div></details>"
    )
    sections.append(_render_new_cards_section(new_cards_df))
    sections.append(
        f"<p class='muted'>Generated {html.escape(generated_at)} | version {html.escape(version)} | "
        f"{len(cards)} cards in the physical collection.</p>"
    )

    document = (
        "<!doctype html><html lang='en' class='theme-dark'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Gitster Deck Report — {html.escape(version)}</title>"
        f"<style>{_report_css()}</style>"
        f"<script>{_report_js()}</script></head><body>"
        f"<script type='application/json' id='report-data'>{report_data_json}</script>"
        + "".join(sections)
        + "</body></html>"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    logger.info("Wrote deck report to %s", out_path)
    return out_path
