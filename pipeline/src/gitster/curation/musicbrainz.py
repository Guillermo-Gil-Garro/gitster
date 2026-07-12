"""MusicBrainz enrichment: first-release years by ISRC, with a persistent cache in the global store."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from gitster.io_utils import write_parquet_atomic


logger = logging.getLogger(__name__)

# NOTE: no inc= parameter — the isrc endpoint returns recordings (with
# first-release-date) by default, and inc=recordings is rejected with HTTP 400.
MB_ISRC_URL_TEMPLATE = "https://musicbrainz.org/ws/2/isrc/{isrc}?fmt=json"
MB_USER_AGENT = "gitster/1.0 (https://github.com/Guillermo-Gil-Garro/gitster)"
MB_MIN_SECONDS_BETWEEN_REQUESTS = 1.1
MB_REQUEST_TIMEOUT_SECONDS = 30

MB_CACHE_FILENAME = "mb_first_release_years.parquet"
MB_CACHE_COLUMNS = ["isrc", "mb_year", "fetched_at"]

_YEAR_PATTERN = re.compile(r"^(\d{4})")


def parse_min_first_release_year(payload: dict) -> int | None:
    """Return the minimum year among the recordings' first-release-date fields, if any."""
    years: list[int] = []
    for recording in payload.get("recordings") or []:
        release_date = recording.get("first-release-date")
        if not release_date:
            continue
        match = _YEAR_PATTERN.match(str(release_date).strip())
        if match:
            years.append(int(match.group(1)))
    return min(years) if years else None


def fetch_mb_first_release_year(isrc: str) -> int | None:
    """Fetch the earliest first-release year for an ISRC; None when MusicBrainz does not know it (404)."""
    url = MB_ISRC_URL_TEMPLATE.format(isrc=isrc)
    request = urllib.request.Request(url, headers={"User-Agent": MB_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=MB_REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    return parse_min_first_release_year(payload)


def load_mb_cache(store_dir: Path) -> pd.DataFrame:
    cache_path = store_dir / MB_CACHE_FILENAME
    if not cache_path.exists():
        cache_df = pd.DataFrame(columns=MB_CACHE_COLUMNS)
        cache_df["mb_year"] = cache_df["mb_year"].astype("Int64")
        return cache_df

    cache_df = pd.read_parquet(cache_path)
    for column in MB_CACHE_COLUMNS:
        if column not in cache_df.columns:
            cache_df[column] = None
    cache_df = cache_df[MB_CACHE_COLUMNS]
    cache_df["mb_year"] = cache_df["mb_year"].astype("Int64")
    return cache_df


def get_mb_years_for_isrcs(isrcs: list[str], *, store_dir: Path) -> dict[str, int | None]:
    """Resolve first-release years for ISRCs, fetching only the ones missing from the cache.

    Cached misses (mb_year null) are honored and never re-fetched.
    """
    cache_df = load_mb_cache(store_dir)
    cached_years: dict[str, int | None] = {}
    for row in cache_df.to_dict(orient="records"):
        isrc = row["isrc"]
        mb_year = row["mb_year"]
        cached_years[isrc] = None if pd.isna(mb_year) else int(mb_year)

    unique_isrcs = sorted({isrc.strip() for isrc in isrcs if isrc and isinstance(isrc, str) and isrc.strip()})
    missing_isrcs = [isrc for isrc in unique_isrcs if isrc not in cached_years]

    results = {isrc: cached_years.get(isrc) for isrc in unique_isrcs}
    if not missing_isrcs:
        return results

    logger.info("MusicBrainz: fetching %d ISRCs (%d cached)", len(missing_isrcs), len(unique_isrcs) - len(missing_isrcs))
    new_rows: list[dict] = []
    last_request_time = 0.0
    try:
        for isrc in tqdm(missing_isrcs, desc="musicbrainz", unit="isrc"):
            elapsed = time.monotonic() - last_request_time
            if elapsed < MB_MIN_SECONDS_BETWEEN_REQUESTS:
                time.sleep(MB_MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
            last_request_time = time.monotonic()
            try:
                mb_year = fetch_mb_first_release_year(isrc)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                # Transient failure: do not cache, so the ISRC is retried next time.
                logger.warning("MusicBrainz lookup failed for isrc=%s: %s", isrc, error)
                continue
            results[isrc] = mb_year
            new_rows.append(
                {
                    "isrc": isrc,
                    "mb_year": mb_year,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    finally:
        if new_rows:
            new_df = pd.DataFrame(new_rows, columns=MB_CACHE_COLUMNS)
            new_df["mb_year"] = new_df["mb_year"].astype("Int64")
            combined_df = pd.concat([cache_df, new_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=["isrc"], keep="last")
            write_parquet_atomic(store_dir / MB_CACHE_FILENAME, combined_df)

    return results
