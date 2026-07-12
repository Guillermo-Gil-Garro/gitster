from __future__ import annotations

import pandas as pd

from gitster.curation.sync import REVIEW_TEMPLATE_COLUMNS, _build_review_template_df


def _candidates_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "song_id": "s1",
        "winner_track_id": "t1",
        "title_display": "Song",
        "primary_artist_name": "Artist",
        "secondary_artist_names": [],
        "album_release_date_spotify": "1990-01-01",
        "year_candidate": 1990,
        "year_final": 1990,
        "year_candidate_source": "album_release_date",
        "year_override": pd.NA,
        "title_display_override": None,
        "artists_display_override": None,
        "curation_note": None,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def test_template_columns_and_track_url_and_owners():
    candidates_df = _candidates_df([{"song_id": "s1", "winner_track_id": "trk123"}])
    template_df = _build_review_template_df(
        candidates_df,
        owner_ids_by_song_id={"s1": ["o1", "o2"]},
        owner_names_by_id={"o1": "Ana"},
        album_name_by_track_id={"trk123": "Nevermind"},
    )

    assert list(template_df.columns) == REVIEW_TEMPLATE_COLUMNS
    row = template_df.iloc[0]
    assert row["track_url"] == "https://open.spotify.com/track/trk123"
    assert row["album_name"] == "Nevermind"
    assert row["owners"] == "Ana, o2"
    assert bool(row["year_suspect"]) is False
    assert row["suspect_reason"] == ""
    assert row["mb_match"] == ""
    assert pd.isna(row["ai_year"])


def test_reissue_album_name_flags_suspect():
    candidates_df = _candidates_df(
        [
            {"song_id": "s1", "winner_track_id": "t1"},
            {"song_id": "s2", "winner_track_id": "t2"},
            {"song_id": "s3", "winner_track_id": "t3"},
            {"song_id": "s4", "winner_track_id": "t4"},
        ]
    )
    template_df = _build_review_template_df(
        candidates_df,
        album_name_by_track_id={
            "t1": "Grandes Éxitos - Colección Definitiva",
            "t2": "Antología (Edición 25 Aniversario)",
            "t3": "Abbey Road (2019 Remaster)",
            "t4": "Nevermind",
        },
    )

    by_song = template_df.set_index("song_id")
    for song_id in ["s1", "s2", "s3"]:
        assert bool(by_song.loc[song_id, "year_suspect"]) is True
        assert "reissue-album-name" in by_song.loc[song_id, "suspect_reason"]
    assert bool(by_song.loc["s4", "year_suspect"]) is False
    assert by_song.loc["s4", "suspect_reason"] == ""


def test_late_vs_artist_median_flag():
    rows = [
        {"song_id": "a1", "primary_artist_name": "Queen", "year_candidate": 1974, "year_final": 1974},
        {"song_id": "a2", "primary_artist_name": "Queen", "year_candidate": 1975, "year_final": 1975},
        {"song_id": "a3", "primary_artist_name": "Queen", "year_candidate": 1976, "year_final": 1976},
        {"song_id": "a4", "primary_artist_name": "Queen", "year_candidate": 2011, "year_final": 2011},
        # Artist with only two songs: never flagged even with a large gap.
        {"song_id": "b1", "primary_artist_name": "Duo", "year_candidate": 1970, "year_final": 1970},
        {"song_id": "b2", "primary_artist_name": "Duo", "year_candidate": 2005, "year_final": 2005},
    ]
    candidates_df = _candidates_df(
        [{**row, "winner_track_id": f"t{index}"} for index, row in enumerate(rows)]
    )
    template_df = _build_review_template_df(candidates_df)

    by_song = template_df.set_index("song_id")
    assert bool(by_song.loc["a4", "year_suspect"]) is True
    assert by_song.loc["a4", "suspect_reason"] == "late-vs-artist-median"
    for song_id in ["a1", "a2", "a3", "b1", "b2"]:
        assert "late-vs-artist-median" not in by_song.loc[song_id, "suspect_reason"]


def test_mb_mismatch_flag_and_mb_match_values():
    candidates_df = _candidates_df(
        [
            {"song_id": "s1", "winner_track_id": "t1", "year_candidate": 1994, "year_final": 1994},
            {"song_id": "s2", "winner_track_id": "t2", "year_candidate": 1980, "year_final": 1980},
            {"song_id": "s3", "winner_track_id": "t3", "year_candidate": 1999, "year_final": 1999},
        ]
    )
    template_df = _build_review_template_df(
        candidates_df,
        isrc_by_song_id={"s1": "ISRC1", "s2": "ISRC2", "s3": "ISRC3"},
        mb_years_by_isrc={"ISRC1": 1971, "ISRC2": 1980, "ISRC3": None},
    )

    by_song = template_df.set_index("song_id")
    assert by_song.loc["s1", "mb_first_release_year"] == 1971
    assert by_song.loc["s1", "mb_match"] == "diff"
    assert by_song.loc["s1", "suspect_reason"] == "mb-mismatch"
    assert bool(by_song.loc["s1", "year_suspect"]) is True

    assert by_song.loc["s2", "mb_match"] == "same"
    assert bool(by_song.loc["s2", "year_suspect"]) is False

    assert pd.isna(by_song.loc["s3", "mb_first_release_year"])
    assert by_song.loc["s3", "mb_match"] == ""
    assert bool(by_song.loc["s3", "year_suspect"]) is False


def test_suspect_reasons_combine_with_semicolon():
    candidates_df = _candidates_df([{"song_id": "s1", "winner_track_id": "t1", "year_candidate": 2005}])
    template_df = _build_review_template_df(
        candidates_df,
        album_name_by_track_id={"t1": "Greatest Hits"},
        isrc_by_song_id={"s1": "ISRC1"},
        mb_years_by_isrc={"ISRC1": 1981},
    )
    assert template_df.iloc[0]["suspect_reason"] == "reissue-album-name;mb-mismatch"
