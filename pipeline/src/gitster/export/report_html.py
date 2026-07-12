"""Rich HTML deck report for the modular pipeline.

Ported from the v2 pipeline deck report (summary stats, sortable and
filterable card table, theme toggle, print view) and adapted to per-player
expansions: the cards payload is the whole physical registry, and the table
can be filtered per expansion with client-side stat recomputation. The
year-coverage matrix of the previous compact report is kept as a section.

CSS/JS are loaded at build time from the stable assets directory
(assets/deck/report) and inlined into the document, mirroring the v2 pattern.
"""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime
from itertools import combinations
from pathlib import Path

import pandas as pd

from gitster.deck.registry import split_owners

logger = logging.getLogger(__name__)

_PIPELINE_ROOT = Path(__file__).resolve().parents[3]
DECK_REPORT_ASSETS_DIR = _PIPELINE_ROOT / "assets" / "deck" / "report"

SPOTIFY_TRACK_URL_PREFIX = "https://open.spotify.com/track/"

# Fallback palette when an expansion has no configured owner color.
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
    if isinstance(value, float) and pd.isna(value):
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


# --------------------------------------------------------------------------- year coverage matrix (preserved from the compact report)


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


def _build_coverage_rows(registry_df: pd.DataFrame) -> list[dict]:
    years_by_expansion = _years_by_expansion(registry_df)
    expansions = sorted(years_by_expansion)
    coverage_rows = [_coverage_row(expansion, [years_by_expansion[expansion]]) for expansion in expansions]
    for left, right in combinations(expansions, 2):
        coverage_rows.append(_coverage_row(f"{left} + {right}", [years_by_expansion[left], years_by_expansion[right]]))
    if len(expansions) > 2:
        coverage_rows.append(_coverage_row("ALL", [years_by_expansion[expansion] for expansion in expansions]))
    return coverage_rows


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


# --------------------------------------------------------------------------- SVG charts (ported from v2, trimmed)


def _format_year_bin_label(bin_start: int, bin_size: int) -> str:
    bin_end = int(bin_start) + int(bin_size) - 1
    if (int(bin_start) // 100) == (int(bin_end) // 100):
        return f"{int(bin_start)}–{int(bin_end) % 100:02d}"
    return f"{int(bin_start)}–{int(bin_end)}"


def _build_year_bin_series(years: pd.Series, *, bin_size: int = 5) -> pd.Series:
    if years.empty:
        return pd.Series(dtype=int)
    year_values = [int(year) for year in years.tolist()]
    min_year = min(year_values)
    max_year = max(year_values)
    base_year = (min_year // bin_size) * bin_size
    top_year = (max_year // bin_size) * bin_size
    bucket_counts: dict[int, int] = {}
    for year in year_values:
        bucket_start = base_year + ((year - base_year) // bin_size) * bin_size
        bucket_counts[bucket_start] = bucket_counts.get(bucket_start, 0) + 1
    labels: list[str] = []
    values: list[int] = []
    for bucket_start in range(base_year, top_year + 1, bin_size):
        count = bucket_counts.get(bucket_start, 0)
        if count <= 0:
            continue
        labels.append(_format_year_bin_label(bucket_start, bin_size))
        values.append(count)
    return pd.Series(values, index=labels, dtype=int)


def _svg_chart_block(svg_markup: str, title: str) -> str:
    if not svg_markup:
        return "<p class='muted'>No data for chart.</p>"
    return f"<div class='chart-block'><div class='chart-title'>{html.escape(title)}</div>{svg_markup}</div>"


def _svg_vertical_bar_chart(
    series: pd.Series,
    title: str,
    *,
    bar_variant: str = "primary",
    width: int = 980,
    height: int = 320,
) -> str:
    if series is None or series.empty:
        return ""
    labels = [str(label) for label in series.index.tolist()]
    values = [int(value) for value in pd.to_numeric(series, errors="coerce").fillna(0).tolist()]
    if not any(values):
        return ""
    margin_left = 44
    margin_right = 16
    margin_top = 18
    margin_bottom = 72
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    max_value = max(max(values), 1)
    bar_slot = plot_width / max(len(values), 1)
    bar_width = max(10.0, min(48.0, bar_slot * 0.7))
    axis_y = height - margin_bottom
    grid_values = sorted({0, max_value // 2, max_value})
    label_step = 1 if len(labels) <= 16 else max(1, len(labels) // 12)
    bar_class = "chart-bar-secondary" if bar_variant == "secondary" else "chart-bar"
    parts = [
        f"<svg class='chart chart-svg' viewBox='0 0 {width} {height}' role='img' "
        f"aria-label='{html.escape(title, quote=True)}'>"
    ]
    for grid_value in grid_values:
        y = margin_top + plot_height - (plot_height * (grid_value / max_value))
        parts.append(f"<line class='chart-gridline' x1='{margin_left}' y1='{y:.2f}' x2='{width - margin_right}' y2='{y:.2f}' />")
        parts.append(f"<text class='chart-label' x='{margin_left - 8}' y='{y + 4:.2f}' text-anchor='end'>{grid_value}</text>")
    parts.append(f"<line class='chart-axis' x1='{margin_left}' y1='{axis_y}' x2='{width - margin_right}' y2='{axis_y}' />")
    for index, (label, value) in enumerate(zip(labels, values, strict=False)):
        x_center = margin_left + (index * bar_slot) + (bar_slot / 2.0)
        bar_height = plot_height * (value / max_value)
        y = axis_y - bar_height
        x = x_center - (bar_width / 2.0)
        parts.append(f"<rect class='{bar_class}' x='{x:.2f}' y='{y:.2f}' width='{bar_width:.2f}' height='{bar_height:.2f}' rx='4' ry='4' />")
        parts.append(f"<text class='chart-value' x='{x_center:.2f}' y='{max(y - 6, margin_top + 10):.2f}' text-anchor='middle'>{value}</text>")
        if index % label_step == 0 or index == len(labels) - 1:
            parts.append(f"<text class='chart-label' x='{x_center:.2f}' y='{axis_y + 18:.2f}' text-anchor='middle'>{html.escape(label)}</text>")
    parts.append("</svg>")
    return _svg_chart_block("".join(parts), title)


def _svg_horizontal_bar_chart(
    series: pd.Series,
    title: str,
    *,
    bar_variant: str = "primary",
    width: int = 980,
    row_height: int = 26,
) -> str:
    if series is None or series.empty:
        return ""
    labels = [str(label) for label in series.index.tolist()]
    values = [int(value) for value in pd.to_numeric(series, errors="coerce").fillna(0).tolist()]
    if not any(values):
        return ""
    height = max(160, 56 + (len(labels) * row_height))
    margin_left = min(300, max(140, 8 * max((len(label) for label in labels), default=10)))
    margin_right = 50
    margin_top = 18
    margin_bottom = 18
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    slot_height = plot_height / max(len(labels), 1)
    bar_height = max(12.0, min(18.0, slot_height * 0.62))
    max_value = max(max(values), 1)
    bar_class = "chart-bar-secondary" if bar_variant == "secondary" else "chart-bar"
    grid_values = sorted({0, max_value // 2, max_value})
    parts = [
        f"<svg class='chart chart-svg' viewBox='0 0 {width} {height}' role='img' "
        f"aria-label='{html.escape(title, quote=True)}'>"
    ]
    for grid_value in grid_values:
        x = margin_left + (plot_width * (grid_value / max_value))
        parts.append(f"<line class='chart-gridline' x1='{x:.2f}' y1='{margin_top}' x2='{x:.2f}' y2='{height - margin_bottom}' />")
        parts.append(f"<text class='chart-label' x='{x:.2f}' y='{height - 2:.2f}' text-anchor='middle'>{grid_value}</text>")
    for index, (label, value) in enumerate(zip(labels, values, strict=False)):
        y_center = margin_top + (index * slot_height) + (slot_height / 2.0)
        y = y_center - (bar_height / 2.0)
        bar_width = plot_width * (value / max_value)
        parts.append(f"<text class='chart-label-strong' x='{margin_left - 10}' y='{y_center + 4:.2f}' text-anchor='end'>{html.escape(label)}</text>")
        parts.append(f"<rect class='{bar_class}' x='{margin_left}' y='{y:.2f}' width='{bar_width:.2f}' height='{bar_height:.2f}' rx='4' ry='4' />")
        parts.append(f"<text class='chart-value' x='{margin_left + bar_width + 8:.2f}' y='{y_center + 4:.2f}' text-anchor='start'>{value}</text>")
    parts.append("</svg>")
    return _svg_chart_block("".join(parts), title)


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
        cards.append(
            {
                "_row_index": idx,
                "card_id": card_id,
                "expansion": _as_text(record.get("expansion_anchor")),
                "year": _parse_int(record.get("year")) or "",
                "title": _as_text(record.get("title")),
                "artists": _as_text(record.get("artists")),
                "owners": ", ".join(_owner_names(owner_ids, owner_name_map)),
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

    report_data = {
        "meta": {"report_id": f"gitster_deck:{version}", "version": version, "generated_at": generated_at},
        "cards": cards,
        "expansions": expansion_items,
    }
    report_data_json = json.dumps(report_data, ensure_ascii=False).replace("</", "<\\/")

    summary_rows = expansion_summary_df.to_dict(orient="records")
    coverage_rows = _build_coverage_rows(registry_df)

    years = pd.Series([card["year"] for card in cards if isinstance(card["year"], int)], dtype=int)
    year_bin_chart = _svg_vertical_bar_chart(_build_year_bin_series(years, bin_size=5), "Cards per 5-year bin")
    decade_chart = _svg_vertical_bar_chart(
        ((years // 10) * 10).value_counts().sort_index() if not years.empty else pd.Series(dtype=int),
        "Cards per decade",
        bar_variant="secondary",
    )
    expansion_chart = _svg_horizontal_bar_chart(
        pd.Series({item["name"]: item["cards"] for item in expansion_items if item["cards"]}, dtype=int),
        "Cards per expansion",
    )

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
    sections.append(
        "<details id='sec-expansions' open><summary>Expansion summary</summary><div class='card'>"
        + (
            _table_html(summary_rows, [str(column) for column in expansion_summary_df.columns], "tbl_expansion_summary")
            if summary_rows
            else "<p class='muted'>No expansion data.</p>"
        )
        + "</div></details>"
    )
    sections.append(
        "<details id='sec-coverage' open><summary>Year coverage (single / pairs / all)</summary><div class='card'>"
        + _table_html(coverage_rows, ["combination", "cards_years", "min", "max", "gaps"], "tbl_year_coverage")
        + "</div></details>"
    )
    sections.append(
        "<details id='sec-years' open><summary>Year distribution</summary><div class='card'>"
        + (year_bin_chart + decade_chart + expansion_chart or "<p class='muted'>No year data.</p>")
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
