from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gitster.artist_display import (
    normalize_artist_display_for_layout,
    resolve_final_artists_display,
    resolve_final_artists_display_source,
    split_artist_names_from_display,
)


class ArtistDisplayResolutionTests(unittest.TestCase):
    def test_priority_prefers_override_then_resolved_then_current(self) -> None:
        override_row = {
            "artists_display_override": "Daft Punk",
            "artists_display_resolved": "Broken Resolved",
            "artists_display_current": "Broken Current",
            "primary_artist_name": "Broken Primary",
            "secondary_artist_names": ["Broken Secondary"],
        }
        self.assertEqual(resolve_final_artists_display(override_row), "Daft Punk")
        self.assertEqual(
            resolve_final_artists_display_source(override_row),
            "artists_display_override",
        )

        resolved_row = {
            "artists_display_override": None,
            "artists_display_resolved": "Atmosphere feat. Slug, Ant",
            "artists_display_current": "Atmosphere feat. Slug | Ant",
        }
        self.assertEqual(
            resolve_final_artists_display(resolved_row),
            "Atmosphere feat. Slug, Ant",
        )
        self.assertEqual(
            resolve_final_artists_display_source(resolved_row),
            "artists_display_resolved",
        )

        current_row = {
            "artists_display_override": None,
            "artists_display_resolved": None,
            "artists_display_current": "Deftones",
            "primary_artist_name": "Deftones",
            "secondary_artist_names": [],
        }
        self.assertEqual(resolve_final_artists_display(current_row), "Deftones")
        self.assertEqual(
            resolve_final_artists_display_source(current_row),
            "artists_display_current",
        )

    def test_layout_normalization_does_not_break_ft_inside_words(self) -> None:
        self.assertEqual(normalize_artist_display_for_layout("Deftones"), "Deftones")
        self.assertEqual(normalize_artist_display_for_layout("Daft Punk"), "Daft Punk")
        self.assertEqual(
            normalize_artist_display_for_layout("Gnarls Barkley ft Danger Mouse"),
            "Gnarls Barkley feat. Danger Mouse",
        )

    def test_split_artist_names_from_display_handles_real_curated_cases(self) -> None:
        cases = {
            "Deftones": ["Deftones"],
            "Daft Punk": ["Daft Punk"],
            "SFDK feat. Legendario, David Sainz": ["SFDK", "Legendario", "David Sainz"],
            "Atmosphere feat. Slug, Ant": ["Atmosphere", "Slug", "Ant"],
            "R de Rumba feat. Kase.O, Kamel": ["R de Rumba", "Kase.O", "Kamel"],
            "Gnarls Barkley feat. CeeLo Green, Danger Mouse": [
                "Gnarls Barkley",
                "CeeLo Green",
                "Danger Mouse",
            ],
        }

        for display_value, expected_names in cases.items():
            with self.subTest(display_value=display_value):
                self.assertEqual(
                    split_artist_names_from_display(display_value),
                    expected_names,
                )


if __name__ == "__main__":
    unittest.main()
