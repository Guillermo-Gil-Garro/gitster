from __future__ import annotations

import sys
from pathlib import Path
import unittest

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gitster.identity import build_editorial_key, compute_base_title_norm, serialize_song_key
from gitster.catalog.songs import build_identity_outputs
from gitster.catalog.years import build_years_baseline_df
from gitster.deck.selection import select_modular_deck


class IdentityPostmergeTests(unittest.TestCase):
    def test_conservative_postmerge_collapses_isrc_split_when_editorial_match_is_strong(self) -> None:
        tracks_df = pd.DataFrame(
            [
                {
                    "track_id": "track_1964",
                    "track_name": "House Of The Rising Sun",
                    "primary_artist_id": "artist_animals",
                    "primary_artist_name": "The Animals",
                    "secondary_artist_ids": [],
                    "secondary_artist_names": [],
                    "isrc": "USA176460010",
                    "album_id": "album_1964",
                    "album_name": "The Animals",
                    "album_release_date_spotify": "1964-01-01",
                    "duration_ms": 271280,
                    "explicit": False,
                    "popularity": None,
                },
                {
                    "track_id": "track_1987",
                    "track_name": "House of the Rising Sun",
                    "primary_artist_id": "artist_animals",
                    "primary_artist_name": "The Animals",
                    "secondary_artist_ids": [],
                    "secondary_artist_names": [],
                    "isrc": "GBAYE6400209",
                    "album_id": "album_1987",
                    "album_name": "The Singles Plus",
                    "album_release_date_spotify": "1987-10-19",
                    "duration_ms": 269906,
                    "explicit": False,
                    "popularity": None,
                },
            ]
        )
        instances_df = pd.DataFrame(
            [
                {"track_id": "track_1964", "owner_id": "paula"},
                {"track_id": "track_1987", "owner_id": "blo"},
                {"track_id": "track_1987", "owner_id": "paula"},
            ]
        )

        variant_df, songs_df, stats = build_identity_outputs(
            tracks_df=tracks_df,
            instances_df=instances_df,
            run_id="test_run",
        )

        self.assertEqual(len(songs_df), 1)
        self.assertEqual(stats["postpass_group_merges"], 1)
        self.assertEqual(sorted(variant_df["song_id"].unique().tolist()), songs_df["song_id"].tolist())

        song_row = songs_df.iloc[0]
        self.assertEqual(song_row["song_key_type"], "postpass_conservative")
        self.assertEqual(song_row["winner_track_id"], "track_1987")
        self.assertEqual(song_row["owners_count"], 2)
        self.assertEqual(song_row["track_ids_merged"], ["track_1987", "track_1964"])
        self.assertEqual(song_row["album_release_date_spotify"], "1964-01-01")
        self.assertEqual(song_row["album_release_date_spotify_source"], "merged_group_min_date")
        self.assertEqual(song_row["album_release_date_spotify_track_id"], "track_1964")
        self.assertTrue(variant_df["winner_rule_path"].str.startswith("postpass_conservative>").all())

        years_df = build_years_baseline_df(songs_df, run_id="test_run")
        years_row = years_df.iloc[0]
        self.assertEqual(years_row["winner_track_id"], "track_1987")
        self.assertEqual(years_row["album_release_date_spotify"], "1964-01-01")
        self.assertEqual(years_row["album_release_date_spotify_source"], "merged_group_min_date")
        self.assertEqual(years_row["album_release_date_spotify_track_id"], "track_1964")
        self.assertEqual(years_row["year_candidate"], 1964)
        self.assertEqual(years_row["year_final"], 1964)

    def test_conservative_postmerge_keeps_remix_and_feat_apart(self) -> None:
        tracks_df = pd.DataFrame(
            [
                {
                    "track_id": "base_track",
                    "track_name": "My Song",
                    "primary_artist_id": "artist_a",
                    "primary_artist_name": "Artist A",
                    "secondary_artist_ids": [],
                    "secondary_artist_names": [],
                    "isrc": "AAA111",
                    "album_id": "album_base",
                    "album_name": "Album Base",
                    "album_release_date_spotify": "2000-01-01",
                    "duration_ms": 200000,
                    "explicit": False,
                    "popularity": None,
                },
                {
                    "track_id": "remix_track",
                    "track_name": "My Song (Remix)",
                    "primary_artist_id": "artist_a",
                    "primary_artist_name": "Artist A",
                    "secondary_artist_ids": [],
                    "secondary_artist_names": [],
                    "isrc": "AAA222",
                    "album_id": "album_remix",
                    "album_name": "Album Remix",
                    "album_release_date_spotify": "2001-01-01",
                    "duration_ms": 200500,
                    "explicit": False,
                    "popularity": None,
                },
                {
                    "track_id": "feat_track",
                    "track_name": "My Song",
                    "primary_artist_id": "artist_a",
                    "primary_artist_name": "Artist A",
                    "secondary_artist_ids": ["feat_b"],
                    "secondary_artist_names": ["Feat B"],
                    "isrc": "AAA333",
                    "album_id": "album_feat",
                    "album_name": "Album Feat",
                    "album_release_date_spotify": "2002-01-01",
                    "duration_ms": 200300,
                    "explicit": False,
                    "popularity": None,
                },
                {
                    "track_id": "other_artist_track",
                    "track_name": "My Song",
                    "primary_artist_id": "artist_b",
                    "primary_artist_name": "Artist B",
                    "secondary_artist_ids": [],
                    "secondary_artist_names": [],
                    "isrc": "AAA444",
                    "album_id": "album_other_artist",
                    "album_name": "Album Other Artist",
                    "album_release_date_spotify": "2003-01-01",
                    "duration_ms": 200100,
                    "explicit": False,
                    "popularity": None,
                },
            ]
        )
        instances_df = pd.DataFrame(
            [
                {"track_id": "base_track", "owner_id": "o1"},
                {"track_id": "remix_track", "owner_id": "o1"},
                {"track_id": "feat_track", "owner_id": "o1"},
                {"track_id": "other_artist_track", "owner_id": "o1"},
            ]
        )

        _variant_df, songs_df, stats = build_identity_outputs(
            tracks_df=tracks_df,
            instances_df=instances_df,
            run_id="test_run",
        )

        self.assertEqual(len(songs_df), 4)
        self.assertEqual(stats["postpass_group_merges"], 0)
        self.assertTrue((songs_df["album_release_date_spotify_source"] == "winner_track").all())
        self.assertTrue((songs_df["album_release_date_spotify_track_id"] == songs_df["winner_track_id"]).all())


class DeckGuardrailTests(unittest.TestCase):
    """The editorial guardrail must keep a single physical card per editorial
    song (same primary artist + base title), across expansions."""

    def _build_guardrail_pool(self) -> pd.DataFrame:
        house_key = serialize_song_key(
            build_editorial_key("artist_animals", compute_base_title_norm("House of the Rising Sun")[0], [])
        )
        gloria_key = serialize_song_key(
            build_editorial_key("artist_them", compute_base_title_norm("Gloria")[0], [])
        )
        return pd.DataFrame(
            [
                {
                    "song_id": "song_1964",
                    "winner_track_id": "track_1964",
                    "title_display": "House of the Rising Sun",
                    "primary_artist_id": "artist_animals",
                    "primary_artist_name": "The Animals",
                    "album_id": None,
                    "popularity_winner": 50,
                    "year_final": 1964,
                    "owner_ids": ["paula"],
                    "editorial_guardrail_key": house_key,
                },
                {
                    "song_id": "song_1987",
                    "winner_track_id": "track_1987",
                    "title_display": "House of the Rising Sun",
                    "primary_artist_id": "artist_animals",
                    "primary_artist_name": "The Animals",
                    "album_id": None,
                    "popularity_winner": 60,
                    "year_final": 1987,
                    "owner_ids": ["blo", "paula"],
                    "editorial_guardrail_key": house_key,
                },
                {
                    "song_id": "song_other",
                    "winner_track_id": "track_other",
                    "title_display": "Gloria",
                    "primary_artist_id": "artist_them",
                    "primary_artist_name": "Them",
                    "album_id": None,
                    "popularity_winner": 40,
                    "year_final": 1965,
                    "owner_ids": ["guille"],
                    "editorial_guardrail_key": gloria_key,
                },
            ]
        )

    def test_guardrail_keeps_one_editorial_duplicate_across_expansions(self) -> None:
        pool_df = self._build_guardrail_pool()
        empty_registry = pd.DataFrame(columns=["song_id", "expansion_anchor", "year", "owners"])

        result = select_modular_deck(
            pool_df,
            empty_registry,
            active_owner_ids=["blo", "guille", "paula"],
            target_sizes={"blo": 1, "guille": 1, "paula": 1},
        )

        selected_songs = result.new_cards_df["song_id"].tolist()
        self.assertEqual(len(selected_songs), 2)
        self.assertIn("song_other", selected_songs)
        self.assertEqual(sum(song_id in {"song_1964", "song_1987"} for song_id in selected_songs), 1)

    def test_guardrail_selection_is_deterministic(self) -> None:
        pool_df = self._build_guardrail_pool()
        empty_registry = pd.DataFrame(columns=["song_id", "expansion_anchor", "year", "owners"])
        kwargs = dict(active_owner_ids=["blo", "guille", "paula"], target_sizes={"blo": 1, "guille": 1, "paula": 1})

        first = select_modular_deck(pool_df, empty_registry, **kwargs)
        second = select_modular_deck(pool_df, empty_registry, **kwargs)

        pd.testing.assert_frame_equal(first.new_cards_df, second.new_cards_df)


if __name__ == "__main__":
    unittest.main()
