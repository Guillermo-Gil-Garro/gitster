from __future__ import annotations

import pandas as pd
import pytest

from gitster.curation.review_import import _build_review_state_df


def _review_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "song_id": "s1",
        "year_override": "",
        "artists_display_override": "",
        "title_display_override": "",
        "note": "",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def test_year_override_wins_over_ai_year():
    review_df = _review_df(
        [{"song_id": "s1", "year_override": "1988", "ai_year": "1975", "ai_note": "Wikipedia: 1975", "note": "manual check"}]
    )
    state_df = _build_review_state_df(review_df)
    row = state_df.iloc[0]
    assert row["year_override"] == 1988
    assert row["note"] == "manual check"


def test_ai_year_used_when_no_manual_override():
    review_df = _review_df(
        [{"song_id": "s1", "ai_year": "1975", "ai_note": "Wikipedia: single publicado en 1975"}]
    )
    state_df = _build_review_state_df(review_df)
    row = state_df.iloc[0]
    assert row["year_override"] == 1975
    assert row["note"] == "[AI] Wikipedia: single publicado en 1975"


def test_ai_year_with_empty_ai_note_and_user_note_preserved():
    review_df = _review_df(
        [{"song_id": "s1", "ai_year": "1969", "ai_note": "", "note": "ya revisada"}]
    )
    state_df = _build_review_state_df(review_df)
    row = state_df.iloc[0]
    assert row["year_override"] == 1969
    assert row["note"] == "[AI] | ya revisada"


def test_no_year_override_nor_ai_year():
    review_df = _review_df([{"song_id": "s1", "ai_year": "", "ai_note": ""}])
    state_df = _build_review_state_df(review_df)
    row = state_df.iloc[0]
    assert pd.isna(row["year_override"])
    assert row["note"] is None


def test_old_template_without_ai_columns_still_imports():
    review_df = _review_df([{"song_id": "s1", "year_override": "2001", "note": "old file"}])
    assert "ai_year" not in review_df.columns
    state_df = _build_review_state_df(review_df)
    row = state_df.iloc[0]
    assert row["year_override"] == 2001
    assert row["note"] == "old file"


def test_invalid_ai_year_raises():
    review_df = _review_df([{"song_id": "s1", "ai_year": "19x5"}])
    with pytest.raises(ValueError, match="ai_year"):
        _build_review_state_df(review_df)
