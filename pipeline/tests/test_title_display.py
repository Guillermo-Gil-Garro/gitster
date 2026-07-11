from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gitster.title_display import normalize_title_display


class TitleDisplayNormalizationTests(unittest.TestCase):
    def test_contractions_stopwords_and_punctuation(self) -> None:
        cases = {
            "Let'S Twist Again": "Let's Twist Again",
            "(I Can'T Get No) Satisfaction": "(I Can't Get No) Satisfaction",
            "For What It'S Worth": "For What It's Worth",
            "Hooked on A Feeling": "Hooked on a Feeling",
            "Un Beso Y una Flor": "Un Beso y una Flor",
            "LA Noche DE Anoche": "La Noche de Anoche",
            "Flashdance...what a Feeling": "Flashdance...What a Feeling",
            "I'M so Excited": "I'm So Excited",
        }

        for raw_title, expected_title in cases.items():
            with self.subTest(raw_title=raw_title):
                self.assertEqual(normalize_title_display(raw_title), expected_title)

    def test_preserves_special_tokens_and_strips_display_noise(self) -> None:
        cases = {
            "Twist And Shout - Remastered 2009": "Twist and Shout",
            "Alibi (with Pabllo Vittar & Yseult)": "Alibi",
            "USA": "USA",
            "AC/DC": "AC/DC",
            "G.O.A.T.": "G.O.A.T.",
        }

        for raw_title, expected_title in cases.items():
            with self.subTest(raw_title=raw_title):
                self.assertEqual(normalize_title_display(raw_title), expected_title)


if __name__ == "__main__":
    unittest.main()
