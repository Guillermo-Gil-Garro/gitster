from __future__ import annotations

import pandas as pd

from gitster.deck.registry import make_card_id
from gitster.deck.selection import select_modular_deck


def _pool(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "winner_track_id": "t" * 22,
        "primary_artist_id": None,
        "primary_artist_name": "Artist",
        "album_id": None,
        "popularity_winner": 50,
        "editorial_guardrail_key": None,
    }
    records = []
    for index, row in enumerate(rows):
        record = {**defaults, "song_id": f"s{index:03d}", **row}
        record.setdefault("editorial_guardrail_key", f"g-{record['song_id']}")
        records.append(record)
    return pd.DataFrame(records)


def _registry(rows: list[dict]) -> pd.DataFrame:
    records = []
    for row in rows:
        owner = row["expansion_anchor"]
        records.append(
            {
                "song_id": row["song_id"],
                "winner_track_id": "t" * 22,
                "card_id": row.get("card_id", make_card_id(owner, row.get("number", 1))),
                "title": "Song",
                "artists": "Artist",
                "year": row.get("year", 1999),
                "owners": row.get("owners", owner),
                "expansion_anchor": owner,
                "printed_status": "printed",
                "version": "baseline",
                "identity_version": "v2.1",
                "run_id": "r0",
                "created_at": "2026-01-01T00:00:00",
                "printed_at": "2026-01-02T00:00:00",
            }
        )
    return pd.DataFrame(records)


def _empty_registry() -> pd.DataFrame:
    return pd.DataFrame(columns=["song_id", "expansion_anchor", "year", "owners"])


def test_no_global_duplicates_for_shared_songs():
    pool = _pool(
        [
            {"year_final": 1990, "owner_ids": ["ana", "bob"]},
            {"year_final": 1991, "owner_ids": ["ana"]},
            {"year_final": 1992, "owner_ids": ["bob"]},
        ]
    )
    result = select_modular_deck(
        pool,
        _empty_registry(),
        active_owner_ids=["ana", "bob"],
        target_sizes={"ana": 2, "bob": 2},
    )

    assert not result.new_cards_df["song_id"].duplicated().any()
    for row in result.new_cards_df.to_dict(orient="records"):
        assert row["expansion_anchor"] in row["owner_ids"]


def test_locked_cards_block_and_are_never_returned():
    pool = _pool(
        [
            {"song_id": "printed1", "year_final": 1990, "owner_ids": ["ana"]},
            {"year_final": 1991, "owner_ids": ["ana"]},
        ]
    )
    registry = _registry([{"song_id": "printed1", "expansion_anchor": "ana", "year": 1990}])

    result = select_modular_deck(
        pool,
        registry,
        active_owner_ids=["ana"],
        target_sizes={"ana": 2},
    )

    assert "printed1" not in set(result.new_cards_df["song_id"])
    summary = result.expansion_summary_df.iloc[0]
    assert summary["locked_cards"] == 1
    assert summary["new_cards"] == 1
    assert summary["total_cards"] == 2


def test_determinism_and_row_order_independence():
    rows = [
        {"year_final": 1990 + (index % 7), "owner_ids": ["ana"] if index % 2 else ["ana", "bob"]}
        for index in range(30)
    ]
    pool = _pool(rows)
    shuffled_pool = pool.sample(frac=1, random_state=7).reset_index(drop=True)

    kwargs = dict(active_owner_ids=["ana", "bob"], target_sizes={"ana": 5, "bob": 5})
    first = select_modular_deck(pool, _empty_registry(), **kwargs)
    second = select_modular_deck(pool, _empty_registry(), **kwargs)
    third = select_modular_deck(shuffled_pool, _empty_registry(), **kwargs)

    pd.testing.assert_frame_equal(first.new_cards_df, second.new_cards_df)
    assert first.new_cards_df["song_id"].tolist() == third.new_cards_df["song_id"].tolist()


def test_adding_player_only_appends_expansion_and_deltas():
    base_rows = [
        {"song_id": f"ana{index}", "year_final": 1990 + index, "owner_ids": ["ana"]} for index in range(3)
    ] + [{"song_id": f"bob{index}", "year_final": 1990 + index, "owner_ids": ["bob"]} for index in range(3)]
    base_pool = _pool([dict(row) for row in base_rows])

    baseline = select_modular_deck(
        base_pool,
        _empty_registry(),
        active_owner_ids=["ana", "bob"],
        target_sizes={"ana": 3, "bob": 3},
    )
    registry = _registry(
        [
            {
                "song_id": row["song_id"],
                "expansion_anchor": row["expansion_anchor"],
                "year": row["year_final"],
            }
            for row in baseline.new_cards_df.to_dict(orient="records")
        ]
    )
    registry["card_id"] = [
        make_card_id(anchor, number)
        for anchor, number in zip(
            registry["expansion_anchor"],
            registry.groupby("expansion_anchor").cumcount() + 1,
        )
    ]

    extended_rows = base_rows + [
        {"song_id": f"zoe{index}", "year_final": 1990 + index, "owner_ids": ["zoe"]} for index in range(2)
    ] + [
        {"song_id": "shared_az", "year_final": 2001, "owner_ids": ["ana", "zoe"]},
    ]
    extended_pool = _pool([dict(row) for row in extended_rows])

    second = select_modular_deck(
        extended_pool,
        registry,
        active_owner_ids=["ana", "bob", "zoe"],
        target_sizes={"ana": 4, "bob": 3, "zoe": 3},
    )

    new_songs = set(second.new_cards_df["song_id"])
    assert new_songs.isdisjoint(set(registry["song_id"]))

    by_anchor = second.new_cards_df.groupby("expansion_anchor")["song_id"].apply(set).to_dict()
    # zoe (largest deficit) takes the shared song; ana's gap stays open but the
    # combined collection still holds the song exactly once
    assert by_anchor.get("zoe") == {"zoe0", "zoe1", "shared_az"}
    assert "bob" not in by_anchor
    assert result_is_underfilled(second, "ana", by=1)


def result_is_underfilled(result, owner_id: str, *, by: int) -> bool:
    return result.underfilled.get(owner_id) == by


def test_artist_and_album_caps_are_hard_limits():
    rows = [
        {"year_final": 1990 + index, "owner_ids": ["ana"], "primary_artist_id": "artistX", "album_id": None}
        for index in range(5)
    ]
    pool = _pool(rows)
    result = select_modular_deck(
        pool,
        _empty_registry(),
        active_owner_ids=["ana"],
        target_sizes={"ana": 5},
        artist_cap=2,
    )

    assert len(result.new_cards_df) == 2
    assert result.underfilled == {"ana": 3}


def test_guardrail_prevents_same_editorial_song_twice():
    pool = _pool(
        [
            {"year_final": 1990, "owner_ids": ["ana"], "editorial_guardrail_key": "same-song"},
            {"year_final": 1991, "owner_ids": ["bob"], "editorial_guardrail_key": "same-song"},
        ]
    )
    result = select_modular_deck(
        pool,
        _empty_registry(),
        active_owner_ids=["ana", "bob"],
        target_sizes={"ana": 1, "bob": 1},
    )

    assert len(result.new_cards_df) == 1


def test_anti_clique_spreads_co_owners():
    # sam's playlist: 3 songs shared only with ruth, 3 shared only with blo,
    # same years pairwise. Without the owner-set softener the song_id tiebreak
    # would let one pair dominate; with it, co-owners alternate.
    rows = []
    for index, (co_owner, year) in enumerate(
        [("ruth", 1990), ("ruth", 1991), ("ruth", 1992), ("blo", 1990), ("blo", 1991), ("blo", 1992)]
    ):
        rows.append(
            {
                "year_final": year,
                "owner_ids": ["sam", co_owner],
                "primary_artist_name": f"Artist{index}",
            }
        )
    pool = _pool(rows)

    result = select_modular_deck(
        pool,
        _empty_registry(),
        active_owner_ids=["sam"],
        target_sizes={"sam": 4},
    )

    co_owners = [
        (set(row["owner_ids"]) - {"sam"}).pop()
        for row in result.new_cards_df.to_dict(orient="records")
    ]
    assert sorted(co_owners) == ["blo", "blo", "ruth", "ruth"]


def test_year_variety_preferred_within_expansion():
    pool = _pool(
        [
            {"year_final": 1990, "owner_ids": ["ana"], "popularity_winner": 99},
            {"year_final": 1990, "owner_ids": ["ana"], "popularity_winner": 98},
            {"year_final": 1991, "owner_ids": ["ana"], "popularity_winner": 1},
        ]
    )
    result = select_modular_deck(
        pool,
        _empty_registry(),
        active_owner_ids=["ana"],
        target_sizes={"ana": 2},
    )

    assert sorted(result.new_cards_df["year_final"].tolist()) == [1990, 1991]
