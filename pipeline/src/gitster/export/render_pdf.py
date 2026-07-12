"""Print-ready 4x3 card PDF renderer for GITSTER decks.

Renders three print variants (match / flip-long / flip-short) of A4 sheets
with 12 cards per side: text fronts and QR backs. The layout is
print-validated; do not change dimensions, ratios, fonts or fitting logic.
"""

from __future__ import annotations

import argparse
import logging
import re
from io import BytesIO
from math import ceil
from pathlib import Path

import pandas as pd
import qrcode
from qrcode.constants import ERROR_CORRECT_H
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)


CARD_MM = 65.0
QR_MM = 30.0
ROWS = 4
COLS = 3
PER_SHEET = ROWS * COLS

TEXT_SIDE_PAD_RATIO = 0.10

# Translucent plate behind the front text (legibility over any background) and
# the per-player color frame drawn inside the cut line on both faces.
PLATE_MARGIN_X_RATIO = 0.055
PLATE_BOTTOM_RATIO = 0.035
PLATE_TOP_RATIO = 0.925
PLATE_ALPHA = 0.0
PLATE_CORNER_MM = 3.0
# Default design: subtitle-style white halo behind every glyph (background
# stays fully visible) plus a small 40% plate under the owners footer only,
# whose tiny italic type is too thin for the halo to carry on loud areas.
TEXT_HALO = True
OWNERS_PLATE_ALPHA = 0.40
OWNERS_PLATE_MARGIN_X_RATIO = 0.07
OWNERS_PLATE_PAD_Y_RATIO = 0.012
OWNERS_PLATE_CORNER_MM = 1.6
FRAME_INSET_MM = 1.1
FRAME_WIDTH_MM = 1.6
TITLE_BOX_TOP_RATIO = 0.90
TITLE_BOX_BOTTOM_RATIO = 0.69
YEAR_BOX_TOP_RATIO = 0.60
YEAR_BOX_BOTTOM_RATIO = 0.38
ARTIST_BOX_TOP_RATIO = 0.34
ARTIST_BOX_BOTTOM_RATIO = 0.17
FOOTER_BOX_TOP_RATIO = 0.14
FOOTER_BOX_BOTTOM_RATIO = 0.05

_FEAT_TOKEN_PATTERN = re.compile(
    r"(?i)(?<![A-Za-zÀ-ÿ])(?:feat\.?|ft\.?|featuring)(?![A-Za-zÀ-ÿ])"
)


def mm_to_pt(value_mm: float) -> float:
    return value_mm * mm


def safe_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_inline_text(value) -> str:
    return " ".join(safe_str(value).split())


def normalize_artist_display_for_render(value) -> str:
    # Inlined from gitster_v2.artist_display.normalize_artist_display_for_layout:
    # canonicalize feat./ft./featuring tokens to a single " feat. " separator.
    normalized = normalize_inline_text(value)
    if not normalized:
        return ""

    normalized = _FEAT_TOKEN_PATTERN.sub(" feat. ", normalized)
    normalized = normalize_inline_text(normalized)
    match = _FEAT_TOKEN_PATTERN.search(normalized)
    if match is None:
        return normalized

    prefix = normalized[: match.start()].rstrip()
    suffix = normalized[match.end() :].lstrip()
    if not prefix:
        return normalize_inline_text(f"feat. {suffix}")
    if not suffix:
        return normalize_inline_text(f"{prefix} feat.")
    return normalize_inline_text(f"{prefix} feat. {suffix}")


def compute_grid(page_w: float, page_h: float, card_size: float, rows: int, cols: int) -> tuple[float, float]:
    total_w = cols * card_size
    total_h = rows * card_size
    return (page_w - total_w) / 2.0, (page_h - total_h) / 2.0


def order_back_indices(rows: int, cols: int, mode: str) -> list[int]:
    front = list(range(rows * cols))
    if mode == "match":
        return front
    if mode == "flip-short":
        return [((rows - 1) - (index // cols)) * cols + (index % cols) for index in front]
    if mode == "flip-long":
        return [(index // cols) * cols + ((cols - 1) - (index % cols)) for index in front]
    raise ValueError(f"Unsupported mode: {mode}")


def chunk_rows(rows: list[dict], chunk_size: int) -> list[list[dict]]:
    return [rows[index : index + chunk_size] for index in range(0, len(rows), chunk_size)]


def make_qr_reader(payload: str, cache: dict[str, ImageReader]) -> ImageReader:
    cached_reader = cache.get(payload)
    if cached_reader is not None:
        return cached_reader

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=8,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="black", back_color="white")
    get_image = getattr(qr_image, "get_image", None)
    if callable(get_image):
        qr_image = get_image()
    qr_image = qr_image.convert("RGB")
    buffer = BytesIO()
    qr_image.save(buffer, format="PNG")
    buffer.seek(0)
    image_reader = ImageReader(buffer)
    cache[payload] = image_reader
    return image_reader


def string_width(text: str, font_name: str, font_size: int) -> float:
    return pdfmetrics.stringWidth(text, font_name, font_size)


def wrap_text(
    text: str,
    *,
    font_name: str,
    font_size: int,
    max_width: float,
    max_lines: int,
) -> tuple[list[str], bool]:
    normalized = " ".join(safe_str(text).split())
    if not normalized:
        return [], False

    words = normalized.split(" ")
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}".strip()
        if string_width(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
    lines.append(current)

    overflow = len(lines) > max_lines
    if overflow:
        lines = lines[:max_lines]
        while lines and string_width(lines[-1] + "…", font_name, font_size) > max_width and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        if lines:
            lines[-1] = lines[-1].rstrip(" .,:;-") + "…"
    return lines, overflow


def _line_segments_width(segments: list[dict], font_size: int) -> float:
    return sum(string_width(segment["text"], segment["font_name"], font_size) for segment in segments)


def _group_segments(group: list[dict], *, prefix_space: bool) -> list[dict]:
    segments: list[dict] = []
    for segment_index, segment in enumerate(group):
        segment_text = segment["text"]
        if prefix_space and segment_index == 0:
            segment_text = f" {segment_text}"
        elif segment_index > 0 and not segment_text.startswith(" "):
            segment_text = f" {segment_text}"
        segments.append(
            {
                "text": segment_text,
                "font_name": segment["font_name"],
            }
        )
    return segments


def _line_from_groups(groups: list[list[dict]]) -> list[dict]:
    line_segments: list[dict] = []
    for group_index, group in enumerate(groups):
        line_segments.extend(_group_segments(group, prefix_space=group_index > 0))
    return line_segments


def _line_groups_width(groups: list[list[dict]], font_size: int) -> float:
    return _line_segments_width(_line_from_groups(groups), font_size)


def _split_artist_chunks(text: str) -> list[str]:
    normalized = normalize_inline_text(text)
    if not normalized:
        return []

    chunks: list[str] = []
    current = ""
    for part in re.split(r"(\s*[|,]\s*)", normalized):
        if not part:
            continue
        if re.fullmatch(r"\s*[|,]\s*", part):
            separator = part.strip()
            current = f"{current.rstrip()}{separator}"
            continue
        if current:
            chunks.append(current.strip())
        current = part.strip()
    if current:
        chunks.append(current.strip())
    return chunks


def _build_artist_groups(artist_text: str) -> list[list[dict]]:
    normalized = normalize_artist_display_for_render(artist_text)
    if not normalized:
        return [[{"text": "—", "font_name": "Helvetica-Bold"}]]

    feat_match = re.search(r"(?i)\s+feat\.\s+", normalized)
    if feat_match is None:
        primary_chunks = _split_artist_chunks(normalized)
        return [
            [{"text": chunk, "font_name": "Helvetica-Bold"}]
            for chunk in primary_chunks or [normalized]
        ]

    primary_text = normalized[: feat_match.start()].strip()
    feat_token = normalized[feat_match.start() : feat_match.end()].strip()
    secondary_text = normalized[feat_match.end() :].strip()

    groups: list[list[dict]] = []
    primary_chunks = _split_artist_chunks(primary_text)
    if primary_chunks:
        for group_index, chunk in enumerate(primary_chunks):
            segments = [{"text": chunk, "font_name": "Helvetica-Bold"}]
            if group_index == len(primary_chunks) - 1:
                segments.append({"text": feat_token, "font_name": "Helvetica"})
            groups.append(segments)
    else:
        groups.append([{"text": feat_token, "font_name": "Helvetica"}])

    secondary_chunks = _split_artist_chunks(secondary_text)
    for chunk in secondary_chunks or ([secondary_text] if secondary_text else []):
        groups.append([{"text": chunk, "font_name": "Helvetica"}])

    return groups


def _fallback_split_group(group: list[dict]) -> list[list[dict]]:
    fallback_groups: list[list[dict]] = []
    for segment in group:
        words = normalize_inline_text(segment["text"]).split(" ")
        for word in words:
            normalized_word = safe_str(word)
            if not normalized_word:
                continue
            fallback_groups.append([{"text": normalized_word, "font_name": segment["font_name"]}])
    return fallback_groups or [group]


def _fit_ellipsis_on_last_line(segments: list[dict], *, font_size: int, max_width: float) -> list[dict]:
    trimmed_segments = [dict(segment) for segment in segments]
    if not trimmed_segments:
        return trimmed_segments

    trimmed_segments[-1]["text"] = trimmed_segments[-1]["text"].rstrip() + "…"
    while trimmed_segments and _line_segments_width(trimmed_segments, font_size) > max_width:
        last_text = trimmed_segments[-1]["text"].rstrip("…").rstrip()
        if not last_text:
            trimmed_segments.pop()
            if trimmed_segments:
                trimmed_segments[-1]["text"] = trimmed_segments[-1]["text"].rstrip() + "…"
            continue
        last_text = last_text[:-1].rstrip(" ,|")
        trimmed_segments[-1]["text"] = (last_text + "…") if last_text else "…"
        if trimmed_segments[-1]["text"] == "…" and len(trimmed_segments) > 1:
            trimmed_segments.pop()
            trimmed_segments[-1]["text"] = trimmed_segments[-1]["text"].rstrip() + "…"
    return trimmed_segments


def wrap_artist_groups(
    artist_text: str,
    *,
    font_size: int,
    max_width: float,
    max_lines: int,
) -> tuple[list[list[dict]], bool]:
    working_groups = [list(group) for group in _build_artist_groups(artist_text)]
    lines: list[list[list[dict]]] = []
    current_line: list[list[dict]] = []
    index = 0
    overflow_width = False

    while index < len(working_groups):
        group = working_groups[index]
        candidate_line = current_line + [group]
        if _line_groups_width(candidate_line, font_size) <= max_width:
            current_line = candidate_line
            index += 1
            continue

        if current_line:
            lines.append(current_line)
            current_line = []
            continue

        split_groups = _fallback_split_group(group)
        if split_groups == [group]:
            current_line = [group]
            overflow_width = _line_groups_width(current_line, font_size) > max_width
            index += 1
            continue

        working_groups = working_groups[:index] + split_groups + working_groups[index + 1 :]

    if current_line:
        lines.append(current_line)

    overflow = overflow_width or len(lines) > max_lines
    line_segments = [_line_from_groups(line_groups) for line_groups in lines[:max_lines]]
    if overflow and line_segments:
        line_segments[-1] = _fit_ellipsis_on_last_line(
            line_segments[-1],
            font_size=font_size,
            max_width=max_width,
        )
    return line_segments, overflow


def fit_artist_text_box(
    artist_text: str,
    *,
    max_width: float,
    max_height: float,
    max_lines: int,
    size_candidates: list[int],
    line_gap_factor: float,
    min_line_gap: float = 1.0,
) -> tuple[int, float, list[list[dict]]]:
    normalized_artist_text = artist_text or "—"
    for font_size in size_candidates:
        line_gap = max(min_line_gap, round(font_size * line_gap_factor, 1))
        lines, overflow = wrap_artist_groups(
            normalized_artist_text,
            font_size=font_size,
            max_width=max_width,
            max_lines=max_lines,
        )
        if overflow:
            continue
        if block_height(line_count=len(lines), font_size=font_size, line_gap=line_gap) <= max_height:
            return font_size, line_gap, lines

    smallest_size = size_candidates[-1]
    smallest_gap = max(min_line_gap, round(smallest_size * line_gap_factor, 1))
    lines, _overflow = wrap_artist_groups(
        normalized_artist_text,
        font_size=smallest_size,
        max_width=max_width,
        max_lines=max_lines,
    )
    return smallest_size, smallest_gap, lines


def fit_wrapped_text(
    text: str,
    *,
    font_name: str,
    max_width: float,
    max_lines: int,
    size_candidates: list[int],
) -> tuple[int, list[str]]:
    for font_size in size_candidates:
        lines, overflow = wrap_text(
            text,
            font_name=font_name,
            font_size=font_size,
            max_width=max_width,
            max_lines=max_lines,
        )
        if not overflow:
            return font_size, lines
    smallest_size = size_candidates[-1]
    lines, _overflow = wrap_text(
        text,
        font_name=font_name,
        font_size=smallest_size,
        max_width=max_width,
        max_lines=max_lines,
    )
    return smallest_size, lines


def _halo_offsets(font_size: float) -> list[tuple[float, float]]:
    radius = max(0.7, font_size * 0.06)
    diagonal = radius * 0.7071
    return [
        (-radius, 0.0),
        (radius, 0.0),
        (0.0, -radius),
        (0.0, radius),
        (-diagonal, -diagonal),
        (diagonal, -diagonal),
        (-diagonal, diagonal),
        (diagonal, diagonal),
    ]


def _draw_centred_halo(c: canvas.Canvas, x: float, y: float, text: str, font_size: float) -> None:
    if not TEXT_HALO:
        return
    c.saveState()
    c.setFillColor(colors.white)
    for dx, dy in _halo_offsets(font_size):
        c.drawCentredString(x + dx, y + dy, text)
    c.restoreState()


def _draw_string_halo(c: canvas.Canvas, x: float, y: float, text: str, font_size: float) -> None:
    if not TEXT_HALO:
        return
    c.saveState()
    c.setFillColor(colors.white)
    for dx, dy in _halo_offsets(font_size):
        c.drawString(x + dx, y + dy, text)
    c.restoreState()


def draw_centered_lines(
    c: canvas.Canvas,
    *,
    lines: list[str],
    font_name: str,
    font_size: int,
    x_center: float,
    y_top: float,
    line_gap: float,
    halo: bool = True,
) -> float:
    current_y = y_top
    c.setFont(font_name, font_size)
    for line in lines:
        if halo:
            _draw_centred_halo(c, x_center, current_y, line, font_size)
        c.drawCentredString(x_center, current_y, line)
        current_y -= font_size + line_gap
    return current_y


def draw_centered_rich_lines(
    c: canvas.Canvas,
    *,
    lines: list[list[dict]],
    font_size: int,
    x_center: float,
    y_top: float,
    line_gap: float,
) -> float:
    current_y = y_top
    for line_segments in lines:
        total_width = _line_segments_width(line_segments, font_size)
        current_x = x_center - (total_width / 2.0)
        for segment in line_segments:
            c.setFont(segment["font_name"], font_size)
            _draw_string_halo(c, current_x, current_y, segment["text"], font_size)
            c.drawString(current_x, current_y, segment["text"])
            current_x += string_width(segment["text"], segment["font_name"], font_size)
        current_y -= font_size + line_gap
    return current_y


def block_height(*, line_count: int, font_size: int, line_gap: float) -> float:
    if line_count <= 0:
        return 0.0
    return (line_count * font_size) + ((line_count - 1) * line_gap)


def fit_text_box(
    text: str,
    *,
    font_name: str,
    max_width: float,
    max_height: float,
    max_lines: int,
    size_candidates: list[int],
    line_gap_factor: float,
    min_line_gap: float = 1.0,
) -> tuple[int, float, list[str]]:
    normalized_text = text or "—"
    for font_size in size_candidates:
        line_gap = max(min_line_gap, round(font_size * line_gap_factor, 1))
        lines, overflow = wrap_text(
            normalized_text,
            font_name=font_name,
            font_size=font_size,
            max_width=max_width,
            max_lines=max_lines,
        )
        if overflow:
            continue
        if block_height(line_count=len(lines), font_size=font_size, line_gap=line_gap) <= max_height:
            return font_size, line_gap, lines

    smallest_size = size_candidates[-1]
    smallest_gap = max(min_line_gap, round(smallest_size * line_gap_factor, 1))
    lines, _overflow = wrap_text(
        normalized_text,
        font_name=font_name,
        font_size=smallest_size,
        max_width=max_width,
        max_lines=max_lines,
    )
    return smallest_size, smallest_gap, lines


def draw_centered_lines_in_box(
    c: canvas.Canvas,
    *,
    lines: list[str],
    font_name: str,
    font_size: int,
    x_center: float,
    box_top: float,
    box_bottom: float,
    line_gap: float,
    vertical_align: str,
    halo: bool = True,
) -> None:
    total_height = block_height(line_count=len(lines), font_size=font_size, line_gap=line_gap)
    box_height = max(0.0, box_top - box_bottom)

    if vertical_align == "top":
        y_top = box_top - font_size
    elif vertical_align == "bottom":
        y_top = box_bottom + total_height - font_size
    else:
        top_padding = max(0.0, (box_height - total_height) / 2.0)
        y_top = box_top - top_padding - font_size

    draw_centered_lines(
        c,
        lines=lines,
        font_name=font_name,
        font_size=font_size,
        x_center=x_center,
        y_top=y_top,
        line_gap=line_gap,
        halo=halo,
    )


def draw_centered_rich_lines_in_box(
    c: canvas.Canvas,
    *,
    lines: list[list[dict]],
    font_size: int,
    x_center: float,
    box_top: float,
    box_bottom: float,
    line_gap: float,
    vertical_align: str,
) -> None:
    total_height = block_height(line_count=len(lines), font_size=font_size, line_gap=line_gap)
    box_height = max(0.0, box_top - box_bottom)

    if vertical_align == "top":
        y_top = box_top - font_size
    elif vertical_align == "bottom":
        y_top = box_bottom + total_height - font_size
    else:
        top_padding = max(0.0, (box_height - total_height) / 2.0)
        y_top = box_top - top_padding - font_size

    draw_centered_rich_lines(
        c,
        lines=lines,
        font_size=font_size,
        x_center=x_center,
        y_top=y_top,
        line_gap=line_gap,
    )


def draw_cut_grid(
    c: canvas.Canvas,
    *,
    x0: float,
    y0: float,
    card_size: float,
    rows: int,
    cols: int,
    stroke_color,
    line_width: float,
) -> None:
    c.saveState()
    c.setStrokeColor(stroke_color)
    c.setLineWidth(line_width)
    for row_index in range(rows + 1):
        y = y0 + row_index * card_size
        c.line(x0, y, x0 + cols * card_size, y)
    for col_index in range(cols + 1):
        x = x0 + col_index * card_size
        c.line(x, y0, x, y0 + rows * card_size)
    c.restoreState()


def _parse_hex_color(value: str | None):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return colors.HexColor(text)
    except ValueError:
        logger.warning("Ignoring invalid owner color %r", value)
        return None


def draw_owner_frame(c: canvas.Canvas, *, x: float, y: float, w: float, h: float, owner_color: str | None) -> None:
    frame_color = _parse_hex_color(owner_color)
    if frame_color is None:
        return
    # Square corners on purpose: cards are cut as squares, so a rounded frame
    # would clash with the cut edge.
    inset = mm_to_pt(FRAME_INSET_MM)
    c.saveState()
    c.setStrokeColor(frame_color)
    c.setLineWidth(mm_to_pt(FRAME_WIDTH_MM))
    c.rect(
        x + inset,
        y + inset,
        w - 2 * inset,
        h - 2 * inset,
        stroke=1,
        fill=0,
    )
    c.restoreState()


def _draw_text_plate(c: canvas.Canvas, *, x: float, y: float, w: float, h: float) -> None:
    if PLATE_ALPHA <= 0:
        return
    plate_x = x + (w * PLATE_MARGIN_X_RATIO)
    plate_w = w - 2 * (w * PLATE_MARGIN_X_RATIO)
    plate_y = y + (h * PLATE_BOTTOM_RATIO)
    plate_h = (h * PLATE_TOP_RATIO) - (h * PLATE_BOTTOM_RATIO)
    c.saveState()
    c.setFillColor(colors.white)
    c.setFillAlpha(PLATE_ALPHA)
    c.roundRect(plate_x, plate_y, plate_w, plate_h, mm_to_pt(PLATE_CORNER_MM), stroke=0, fill=1)
    c.restoreState()


def draw_text_card(
    c: canvas.Canvas,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    background_reader: ImageReader,
    title: str,
    year_text: str,
    artist_text: str,
    owners_text: str,
    owner_color: str | None = None,
) -> None:
    c.drawImage(background_reader, x, y, w, h, mask="auto")
    _draw_text_plate(c, x=x, y=y, w=w, h=h)
    draw_owner_frame(c, x=x, y=y, w=w, h=h, owner_color=owner_color)

    x_center = x + (w / 2.0)
    pad_x = w * TEXT_SIDE_PAD_RATIO
    max_width = w - (2 * pad_x)

    title_box_top = y + (h * TITLE_BOX_TOP_RATIO)
    title_box_bottom = y + (h * TITLE_BOX_BOTTOM_RATIO)
    year_box_top = y + (h * YEAR_BOX_TOP_RATIO)
    year_box_bottom = y + (h * YEAR_BOX_BOTTOM_RATIO)
    artist_box_top = y + (h * ARTIST_BOX_TOP_RATIO)
    artist_box_bottom = y + (h * ARTIST_BOX_BOTTOM_RATIO)
    footer_box_top = y + (h * FOOTER_BOX_TOP_RATIO)
    footer_box_bottom = y + (h * FOOTER_BOX_BOTTOM_RATIO)

    c.setFillColor(colors.black)

    year_value = safe_str(year_text) or "—"
    year_size = 44 if year_value != "—" else 38
    year_center_y = (year_box_top + year_box_bottom) / 2.0
    year_baseline = year_center_y - (0.34 * year_size)
    c.setFont("Helvetica-Bold", year_size)
    _draw_centred_halo(c, x_center, year_baseline, year_value, year_size)
    c.drawCentredString(x_center, year_baseline, year_value)

    title_size, title_gap, title_lines = fit_text_box(
        title or "—",
        font_name="Helvetica-Bold",
        max_width=max_width,
        max_height=title_box_top - title_box_bottom,
        max_lines=3,
        size_candidates=[19, 18, 17, 16, 15, 14, 13, 12, 11, 10],
        line_gap_factor=0.10,
    )
    draw_centered_lines_in_box(
        c,
        lines=title_lines or ["—"],
        font_name="Helvetica-Bold",
        font_size=title_size,
        x_center=x_center,
        box_top=title_box_top,
        box_bottom=title_box_bottom,
        line_gap=title_gap,
        vertical_align="top",
    )

    artist_size, artist_gap, artist_lines = fit_artist_text_box(
        artist_text or "—",
        max_width=max_width,
        max_height=artist_box_top - artist_box_bottom,
        max_lines=3,
        size_candidates=[16, 15, 14, 13, 12, 11, 10, 9],
        line_gap_factor=0.08,
    )
    draw_centered_rich_lines_in_box(
        c,
        lines=artist_lines or [[{"text": "—", "font_name": "Helvetica-Bold"}]],
        font_size=artist_size,
        x_center=x_center,
        box_top=artist_box_top,
        box_bottom=artist_box_bottom,
        line_gap=artist_gap,
        vertical_align="center",
    )

    owners_size, owners_gap, owners_lines = fit_text_box(
        owners_text,
        font_name="Helvetica-Oblique",
        max_width=w - (2 * (w * 0.08)),
        max_height=footer_box_top - footer_box_bottom,
        max_lines=2,
        size_candidates=[10, 9, 8, 7, 6],
        line_gap_factor=0.08,
    )
    if owners_lines:
        if OWNERS_PLATE_ALPHA > 0:
            pad_y = h * OWNERS_PLATE_PAD_Y_RATIO
            plate_x = x + (w * OWNERS_PLATE_MARGIN_X_RATIO)
            c.saveState()
            c.setFillColor(colors.white)
            c.setFillAlpha(OWNERS_PLATE_ALPHA)
            c.roundRect(
                plate_x,
                footer_box_bottom - pad_y,
                w - 2 * (w * OWNERS_PLATE_MARGIN_X_RATIO),
                (footer_box_top - footer_box_bottom) + 2 * pad_y,
                mm_to_pt(OWNERS_PLATE_CORNER_MM),
                stroke=0,
                fill=1,
            )
            c.restoreState()
        draw_centered_lines_in_box(
            c,
            lines=owners_lines,
            font_name="Helvetica-Oblique",
            font_size=owners_size,
            x_center=x_center,
            box_top=footer_box_top,
            box_bottom=footer_box_bottom,
            line_gap=owners_gap,
            vertical_align="center",
            halo=False,
        )


def draw_qr_card(
    c: canvas.Canvas,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    background_reader: ImageReader,
    qr_payload: str,
    qr_cache: dict[str, ImageReader],
    owner_color: str | None = None,
) -> None:
    c.drawImage(background_reader, x, y, w, h, mask="auto")
    qr_size = min(mm_to_pt(QR_MM), min(w, h) * 0.82)
    qr_x = x + (w - qr_size) / 2.0
    qr_y = y + (h - qr_size) / 2.0
    qr_reader = make_qr_reader(qr_payload, qr_cache)
    c.drawImage(qr_reader, qr_x, qr_y, qr_size, qr_size, mask="auto")
    draw_owner_frame(c, x=x, y=y, w=w, h=h, owner_color=owner_color)


def generate_pdf(
    *,
    out_pdf: Path,
    cards: list[dict],
    mode: str,
    front_dir: Path,
    back_bg_path: Path,
) -> None:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = mm_to_pt(210), mm_to_pt(297)
    card_size = mm_to_pt(CARD_MM)
    x0, y0 = compute_grid(page_w, page_h, card_size, ROWS, COLS)

    back_bg_reader = ImageReader(str(back_bg_path))
    front_bg_cache: dict[str, ImageReader] = {}
    qr_cache: dict[str, ImageReader] = {}
    back_idx_map = order_back_indices(ROWS, COLS, mode)
    sheets = chunk_rows(cards, PER_SHEET)

    c = canvas.Canvas(str(out_pdf), pagesize=(page_w, page_h))
    for sheet_rows in sheets:
        padded_rows = sheet_rows + ([{}] * (PER_SHEET - len(sheet_rows)))

        for row_index in range(ROWS):
            for col_index in range(COLS):
                position_index = row_index * COLS + col_index
                card_row = padded_rows[position_index]
                cx = x0 + col_index * card_size
                cy = y0 + (ROWS - 1 - row_index) * card_size

                if not card_row:
                    c.setFillColor(colors.white)
                    c.rect(cx, cy, card_size, card_size, fill=1, stroke=0)
                    continue

                bg_id = safe_str(card_row.get("front_bg_id")) or "g01"
                bg_path = front_dir / f"{bg_id}.png"
                if bg_id not in front_bg_cache:
                    front_bg_cache[bg_id] = ImageReader(str(bg_path))
                draw_text_card(
                    c,
                    x=cx,
                    y=cy,
                    w=card_size,
                    h=card_size,
                    background_reader=front_bg_cache[bg_id],
                    title=safe_str(card_row.get("title_display")),
                    year_text=safe_str(card_row.get("year_final")),
                    artist_text=safe_str(card_row.get("artists_display_resolved")),
                    owners_text=safe_str(card_row.get("owners_display")),
                    owner_color=safe_str(card_row.get("owner_color")) or None,
                )

        draw_cut_grid(
            c,
            x0=x0,
            y0=y0,
            card_size=card_size,
            rows=ROWS,
            cols=COLS,
            stroke_color=colors.black,
            line_width=0.6,
        )
        c.showPage()

        for row_index in range(ROWS):
            for col_index in range(COLS):
                front_index = row_index * COLS + col_index
                back_index = back_idx_map[front_index]
                card_row = padded_rows[back_index]
                cx = x0 + col_index * card_size
                cy = y0 + (ROWS - 1 - row_index) * card_size

                if not card_row:
                    c.setFillColor(colors.white)
                    c.rect(cx, cy, card_size, card_size, fill=1, stroke=0)
                    continue

                draw_qr_card(
                    c,
                    x=cx,
                    y=cy,
                    w=card_size,
                    h=card_size,
                    background_reader=back_bg_reader,
                    qr_payload=safe_str(card_row.get("qr_payload")),
                    qr_cache=qr_cache,
                    owner_color=safe_str(card_row.get("owner_color")) or None,
                )

        draw_cut_grid(
            c,
            x0=x0,
            y0=y0,
            card_size=card_size,
            rows=ROWS,
            cols=COLS,
            stroke_color=colors.white,
            line_width=0.6,
        )
        c.showPage()

    c.save()


def render_deck_pdfs(
    cards_df: pd.DataFrame,
    *,
    out_dir: Path,
    front_dir: Path,
    back_bg_path: Path,
    file_prefix: str = "print_4x3",
) -> list[Path]:
    """Render the three print variants (match / long / short) for a deck.

    Expects the deck DataFrame with at least: selection_rank, title_display,
    year_final, artists_display_resolved, owners_display, front_bg_id,
    qr_payload. Returns the list of written PDF paths.
    """
    if not front_dir.exists():
        raise FileNotFoundError(f"Front backgrounds directory not found: {front_dir}")
    if not back_bg_path.exists():
        raise FileNotFoundError(f"Back background image not found: {back_bg_path}")

    deck_df = cards_df.fillna("")
    deck_df = deck_df.sort_values("selection_rank", kind="stable").reset_index(drop=True)
    cards = deck_df.to_dict(orient="records")

    out_dir.mkdir(parents=True, exist_ok=True)
    variants = [
        (f"{file_prefix}_match.pdf", "match"),
        (f"{file_prefix}_long.pdf", "flip-long"),
        (f"{file_prefix}_short.pdf", "flip-short"),
    ]
    total_sheets = ceil(len(cards) / PER_SHEET)
    total_pages = total_sheets * 2
    logger.info(
        "cards=%d sheets=%d pages_per_pdf=%d", len(cards), total_sheets, total_pages
    )

    written_paths: list[Path] = []
    for file_name, mode in variants:
        out_pdf = out_dir / file_name
        generate_pdf(
            out_pdf=out_pdf,
            cards=cards,
            mode=mode,
            front_dir=front_dir,
            back_bg_path=back_bg_path,
        )
        logger.info("OK -> %s", out_pdf)
        written_paths.append(out_pdf)
    return written_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Render print-ready 4x3 GITSTER PDFs")
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--front-dir", required=True)
    parser.add_argument("--back-bg", required=True)
    args = parser.parse_args()

    input_csv_path = Path(args.input_csv)
    if not input_csv_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv_path}")

    cards_df = pd.read_csv(input_csv_path)
    render_deck_pdfs(
        cards_df,
        out_dir=Path(args.out_dir),
        front_dir=Path(args.front_dir),
        back_bg_path=Path(args.back_bg),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[deck-render] %(message)s")
    main()
