from __future__ import annotations

import re

import pandas as pd

from gitster.identity import normalize_string_scalar


_YEAR_ONLY_PATTERN = re.compile(r"^(?P<year>\d{4})$")
_YEAR_MONTH_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})$")
_YEAR_DAY_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")

_PRECISION_RANK = {
    "day": 0,
    "month": 1,
    "year": 2,
    None: 3,
}


def infer_release_year_precision(value) -> tuple[int | None, str | None]:
    if value is None or pd.isna(value):
        return None, None

    raw_value = str(value).strip()
    if not raw_value:
        return None, None

    match = _YEAR_DAY_PATTERN.match(raw_value)
    if match is not None:
        return int(match.group("year")), "day"

    match = _YEAR_MONTH_PATTERN.match(raw_value)
    if match is not None:
        return int(match.group("year")), "month"

    match = _YEAR_ONLY_PATTERN.match(raw_value)
    if match is not None:
        return int(match.group("year")), "year"

    year_prefix = raw_value[:4]
    if year_prefix.isdigit():
        return int(year_prefix), None

    return None, None


def release_date_sort_key(value) -> tuple[int, int, int, int] | None:
    normalized_value = normalize_string_scalar(value)
    if normalized_value is None:
        return None

    year_value, precision = infer_release_year_precision(normalized_value)
    if year_value is None:
        return None

    month_value = 1
    day_value = 1
    if precision == "month":
        month_value = int(normalized_value[5:7])
    elif precision == "day":
        month_value = int(normalized_value[5:7])
        day_value = int(normalized_value[8:10])

    return (year_value, month_value, day_value, _PRECISION_RANK[precision])


def earliest_release_date_with_track_id(
    rows: list[dict],
    *,
    date_field: str = "album_release_date_spotify",
    track_id_field: str = "track_id",
) -> tuple[str | None, str | None]:
    best_date: str | None = None
    best_track_id: str | None = None
    best_key: tuple[int, int, int, int, int] | None = None

    for index, row in enumerate(rows):
        release_date = normalize_string_scalar(row.get(date_field))
        track_id = normalize_string_scalar(row.get(track_id_field))
        sort_key = release_date_sort_key(release_date)
        if sort_key is None:
            continue

        candidate_key = (*sort_key, index)
        if best_key is None or candidate_key < best_key:
            best_key = candidate_key
            best_date = release_date
            best_track_id = track_id

    return best_date, best_track_id
