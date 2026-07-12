from __future__ import annotations

import json
import urllib.error
import urllib.request

import pandas as pd
import pytest

from gitster.curation import musicbrainz
from gitster.curation.musicbrainz import (
    MB_CACHE_FILENAME,
    MB_USER_AGENT,
    fetch_mb_first_release_year,
    get_mb_years_for_isrcs,
    parse_min_first_release_year,
)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _isrc_from_request(request) -> str:
    return request.full_url.split("/isrc/")[1].split("?")[0]


def test_parse_min_first_release_year_takes_minimum():
    payload = {
        "recordings": [
            {"first-release-date": "1977-10-14"},
            {"first-release-date": "1975"},
            {"first-release-date": ""},
            {},
        ]
    }
    assert parse_min_first_release_year(payload) == 1975


def test_parse_min_first_release_year_no_dates():
    assert parse_min_first_release_year({"recordings": [{}]}) is None
    assert parse_min_first_release_year({}) is None


def test_fetch_sets_user_agent_and_parses(monkeypatch):
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        return _FakeResponse({"recordings": [{"first-release-date": "1969-01-12"}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert fetch_mb_first_release_year("GBUM71029604") == 1969
    assert seen_requests[0].get_header("User-agent") == MB_USER_AGENT


def test_fetch_returns_none_on_404(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert fetch_mb_first_release_year("UNKNOWN0000") is None


def test_fetch_raises_on_other_http_errors(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        fetch_mb_first_release_year("ANY0000000")


def test_get_mb_years_caches_hits_and_misses(tmp_path, monkeypatch):
    payloads = {
        "ISRC1": {"recordings": [{"first-release-date": "1969-09-26"}]},
    }
    call_count = {"n": 0}

    def fake_urlopen(request, timeout=None):
        call_count["n"] += 1
        isrc = _isrc_from_request(request)
        if isrc in payloads:
            return _FakeResponse(payloads[isrc])
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(musicbrainz.time, "sleep", lambda seconds: None)

    results = get_mb_years_for_isrcs(["ISRC1", "ISRC2"], store_dir=tmp_path)
    assert results == {"ISRC1": 1969, "ISRC2": None}
    assert call_count["n"] == 2

    cache_df = pd.read_parquet(tmp_path / MB_CACHE_FILENAME)
    assert set(cache_df["isrc"]) == {"ISRC1", "ISRC2"}
    assert set(cache_df.columns) == {"isrc", "mb_year", "fetched_at"}

    # Second call must be fully served from cache, including the cached miss.
    def exploding_urlopen(request, timeout=None):
        raise AssertionError("network must not be hit for cached ISRCs")

    monkeypatch.setattr(urllib.request, "urlopen", exploding_urlopen)
    cached_results = get_mb_years_for_isrcs(["ISRC1", "ISRC2"], store_dir=tmp_path)
    assert cached_results == {"ISRC1": 1969, "ISRC2": None}


def test_get_mb_years_transient_errors_not_cached(tmp_path, monkeypatch):
    def failing_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    monkeypatch.setattr(musicbrainz.time, "sleep", lambda seconds: None)

    results = get_mb_years_for_isrcs(["ISRC9"], store_dir=tmp_path)
    assert results == {"ISRC9": None}
    assert not (tmp_path / MB_CACHE_FILENAME).exists()
