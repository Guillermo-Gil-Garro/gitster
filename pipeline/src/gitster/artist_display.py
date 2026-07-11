from __future__ import annotations

import re
from typing import Any

from gitster.identity import normalize_string_list, normalize_string_scalar


ARTISTS_DISPLAY_PRIORITY_FIELDS = (
    "artists_display_override",
    "artists_display_resolved",
    "artists_display_current",
)

_FEAT_TOKEN_PATTERN = re.compile(r"(?i)(?<![A-Za-zÀ-ÿ])(?:feat\.?|ft\.?|featuring)(?![A-Za-zÀ-ÿ])")
_FEAT_SEGMENT_PATTERN = re.compile(r"(?i)\s+feat\.\s+")


def _row_value(row: Any, field: str):
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(field)
    return None


def normalize_nullable_string(value) -> str | None:
    return normalize_string_scalar(value)


def normalize_inline_text(value) -> str:
    return " ".join((normalize_nullable_string(value) or "").split())


def build_artists_display_current(primary_artist_name, secondary_artist_names) -> str | None:
    primary_name = normalize_nullable_string(primary_artist_name)
    secondary_names = normalize_string_list(secondary_artist_names)
    if primary_name is None:
        if not secondary_names:
            return None
        return " | ".join(secondary_names)
    if not secondary_names:
        return primary_name
    return f"{primary_name} feat. {' | '.join(secondary_names)}"


def resolve_final_artists_display(
    row: Any,
    *,
    allow_legacy_display: bool = True,
    allow_raw_fallback: bool = True,
) -> str | None:
    for field in ARTISTS_DISPLAY_PRIORITY_FIELDS:
        value = normalize_nullable_string(_row_value(row, field))
        if value is not None:
            return value

    if allow_legacy_display:
        legacy_value = normalize_nullable_string(_row_value(row, "artists_display"))
        if legacy_value is not None:
            return legacy_value

    if not allow_raw_fallback:
        return None

    return build_artists_display_current(
        _row_value(row, "primary_artist_name"),
        _row_value(row, "secondary_artist_names"),
    )


def resolve_final_artists_display_source(
    row: Any,
    *,
    allow_legacy_display: bool = True,
    allow_raw_fallback: bool = True,
) -> str | None:
    for field in ARTISTS_DISPLAY_PRIORITY_FIELDS:
        value = normalize_nullable_string(_row_value(row, field))
        if value is not None:
            return field

    if allow_legacy_display:
        legacy_value = normalize_nullable_string(_row_value(row, "artists_display"))
        if legacy_value is not None:
            return "artists_display"

    if allow_raw_fallback:
        fallback_value = build_artists_display_current(
            _row_value(row, "primary_artist_name"),
            _row_value(row, "secondary_artist_names"),
        )
        if fallback_value is not None:
            return "built_from_raw"

    return None


def normalize_artist_display_for_layout(value) -> str:
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


def split_artist_names_from_display(value) -> list[str]:
    normalized = normalize_artist_display_for_layout(value)
    if not normalized:
        return []

    feat_match = _FEAT_SEGMENT_PATTERN.search(normalized)
    if feat_match is None:
        if "|" in normalized:
            return [chunk.strip() for chunk in normalized.split("|") if chunk.strip()]
        return [normalized]

    primary_name = normalized[: feat_match.start()].strip()
    secondary_text = normalized[feat_match.end() :].strip()

    names: list[str] = []
    if primary_name:
        names.append(primary_name)
    names.extend(
        chunk.strip()
        for chunk in re.split(r"\s*[|,]\s*", secondary_text)
        if chunk.strip()
    )
    return names
