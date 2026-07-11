from __future__ import annotations

import pandas as pd
import pytest

from gitster.deck.registry import (
    append_cards,
    delete_pending,
    load_registry,
    make_card_id,
    mark_printed,
    next_card_number,
    validate_registry,
)


def _cards(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "winner_track_id": "t" * 22,
        "title": "Song",
        "artists": "Artist",
        "year": 1999,
        "identity_version": "v2.1",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _card(song_id: str, owner: str, number: int, **extra) -> dict:
    return {
        "song_id": song_id,
        "card_id": make_card_id(owner, number),
        "owners": extra.pop("owners", owner),
        "expansion_anchor": owner,
        **extra,
    }


def test_append_and_load_roundtrip(tmp_path):
    appended = append_cards(
        tmp_path,
        _cards([_card("s1", "ana", 1), _card("s2", "ana", 2, owners="ana|bob")]),
        version="baseline",
        run_id="run1",
    )
    loaded = load_registry(tmp_path)

    assert len(loaded) == 2
    assert loaded["printed_status"].tolist() == ["pending", "pending"]
    assert loaded["version"].tolist() == ["baseline", "baseline"]
    assert loaded["card_id"].tolist() == appended["card_id"].tolist()
    assert loaded["year"].tolist() == [1999, 1999]


def test_append_rejects_duplicate_song(tmp_path):
    append_cards(tmp_path, _cards([_card("s1", "ana", 1)]), version="v1", run_id="r1")
    with pytest.raises(ValueError, match="already in the registry"):
        append_cards(tmp_path, _cards([_card("s1", "bob", 1)]), version="v2", run_id="r2")


def test_append_preserves_existing_rows(tmp_path):
    append_cards(tmp_path, _cards([_card("s1", "ana", 1)]), version="v1", run_id="r1")
    before = load_registry(tmp_path)

    append_cards(tmp_path, _cards([_card("s2", "bob", 1)]), version="v2", run_id="r2")
    after = load_registry(tmp_path)

    pd.testing.assert_frame_equal(after.iloc[:1].reset_index(drop=True), before)


def test_next_card_number_continues_per_expansion(tmp_path):
    append_cards(
        tmp_path,
        _cards([_card("s1", "ana", 1), _card("s2", "ana", 2), _card("s3", "bob", 1)]),
        version="v1",
        run_id="r1",
    )
    registry_df = load_registry(tmp_path)

    assert next_card_number(registry_df, "ana") == 3
    assert next_card_number(registry_df, "bob") == 2
    assert next_card_number(registry_df, "zoe") == 1


def test_mark_printed_and_delete_pending(tmp_path):
    append_cards(tmp_path, _cards([_card("s1", "ana", 1)]), version="v1", run_id="r1")
    append_cards(tmp_path, _cards([_card("s2", "ana", 2)]), version="v2", run_id="r2")

    assert mark_printed(tmp_path, version="v1") == 1
    registry_df = load_registry(tmp_path)
    assert registry_df.set_index("song_id")["printed_status"].to_dict() == {
        "s1": "printed",
        "s2": "pending",
    }

    assert delete_pending(tmp_path) == 1
    registry_df = load_registry(tmp_path)
    assert registry_df["song_id"].tolist() == ["s1"]


def test_anchor_must_be_among_owners(tmp_path):
    with pytest.raises(ValueError, match="not among its owners"):
        append_cards(
            tmp_path,
            _cards([_card("s1", "ana", 1, owners="bob")]),
            version="v1",
            run_id="r1",
        )


def test_validate_registry_detects_identity_drift(tmp_path):
    append_cards(tmp_path, _cards([_card("s1", "ana", 1)]), version="v1", run_id="r1")
    registry_df = load_registry(tmp_path)

    song_catalog_df = pd.DataFrame({"song_id": ["other_song"]})
    issues = validate_registry(registry_df, song_catalog_df)

    assert len(issues) == 1
    assert "identity drift" in issues[0]
