from __future__ import annotations

import pandas as pd

from gitster.export.report_html import (
    DECK_REPORT_ASSETS_DIR,
    _read_report_asset_text,
    _report_asset_paths,
    write_deck_report,
)


def _registry() -> pd.DataFrame:
    rows = [
        ("s1", "trk_ana_1", "GITSTER_ANA_001", "Alpha", "Artist One", 1990, "ana", "ana", "printed"),
        ("s2", "trk_ana_2", "GITSTER_ANA_002", "Beta", "Artist Two", 1992, "ana|bob", "ana", "printed"),
        ("s3", "trk_ana_3", "GITSTER_ANA_003", "Gamma", "Artist Three", 1994, "ana", "ana", "pending"),
        ("s4", "trk_bob_1", "GITSTER_BOB_001", "Delta", "Artist Four", 1991, "bob", "bob", "printed"),
        ("s5", "trk_bob_2", "GITSTER_BOB_002", "Epsilon", "Artist Five", 1993, "bob", "bob", "printed"),
        ("s6", "trk_bob_3", "GITSTER_BOB_003", "Zeta", "Artist Six", 2000, "bob|ana", "bob", "pending"),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "song_id",
            "winner_track_id",
            "card_id",
            "title",
            "artists",
            "year",
            "owners",
            "expansion_anchor",
            "printed_status",
        ],
    ).assign(version="v-test", identity_version="id-v1", run_id="run1", created_at="2026-07-12", printed_at=None)


def _expansion_summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"owner_id": "ana", "target_size": 3, "locked_cards": 2, "new_cards": 1, "total_cards": 3, "distinct_years": 3, "underfilled_by": 0},
            {"owner_id": "bob", "target_size": 4, "locked_cards": 3, "new_cards": 0, "total_cards": 3, "distinct_years": 3, "underfilled_by": 1},
        ]
    )


def _new_cards() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "card_id": "GITSTER_ANA_003",
                "expansion_anchor": "ana",
                "is_new": True,
                "title_display": "Gamma",
                "artists_display_resolved": "Artist Three",
                "year_final": 1994,
                "owners": "ana",
                "owners_display": "(Ana)",
                "track_url": "https://open.spotify.com/track/trk_ana_3",
                "front_bg_id": "g03",
                "owner_color": "#00E5FF",
            }
        ]
    )


def _write_report(tmp_path):
    out_path = tmp_path / "deck_report.html"
    return write_deck_report(
        registry_df=_registry(),
        expansion_summary_df=_expansion_summary(),
        new_cards_df=_new_cards(),
        version="v-test",
        out_path=out_path,
        owner_name_map={"ana": "Ana", "bob": "Bob"},
        owner_color_map={"ana": "#00E5FF", "bob": "#FF2BD6"},
    )


def test_report_contains_all_cards_and_payload(tmp_path):
    out_path = _write_report(tmp_path)
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")

    for card_id in [
        "GITSTER_ANA_001",
        "GITSTER_ANA_002",
        "GITSTER_ANA_003",
        "GITSTER_BOB_001",
        "GITSTER_BOB_002",
        "GITSTER_BOB_003",
    ]:
        assert card_id in text

    assert "https://open.spotify.com/track/trk_ana_1" in text
    # is_new flag derived from new_cards_df membership.
    assert '"card_id": "GITSTER_ANA_003", "expansion": "ana", "year": 1994, "title": "Gamma"' in text
    assert '"is_new": true' in text


def test_report_contains_expansion_filter_markup(tmp_path):
    text = _write_report(tmp_path).read_text(encoding="utf-8")

    assert "id='expansion-filter'" in text
    assert "data-expansion='__all'" in text
    assert "data-expansion='ana'" in text
    assert "data-expansion='bob'" in text
    # Chips tinted with the configured owner colors and labelled with owner names.
    assert "--chip-accent: #00E5FF" in text
    assert "--chip-accent: #FF2BD6" in text
    assert "Ana <span class='chip-count'>3</span>" in text
    assert "Bob <span class='chip-count'>3</span>" in text


def test_report_contains_year_coverage_matrix(tmp_path):
    text = _write_report(tmp_path).read_text(encoding="utf-8")

    assert "tbl_year_coverage" in text
    # ana alone: 1990/1992/1994 -> gaps 1991, 1993
    assert "1991, 1993" in text
    # bob alone: 1991/1993/2000 -> gaps include 1994..1999
    assert "1994, 1995, 1996, 1997, 1998, 1999" in text
    # pair ana + bob: union covers 1990-1994 and 2000 -> gaps 1995..1999
    assert "ana + bob" in text
    assert "1995, 1996, 1997, 1998, 1999" in text


def test_report_contains_expansion_summary_table(tmp_path):
    text = _write_report(tmp_path).read_text(encoding="utf-8")

    assert "tbl_expansion_summary" in text
    for column in ["owner_id", "target_size", "locked_cards", "new_cards", "total_cards", "distinct_years", "underfilled_by"]:
        assert column in text


class TestDeckReportAssetLoading:
    def test_assets_resolve_from_stable_dir(self):
        css_path, js_path = _report_asset_paths()
        assert css_path.parent == DECK_REPORT_ASSETS_DIR
        assert js_path.parent == DECK_REPORT_ASSETS_DIR
        assert DECK_REPORT_ASSETS_DIR.parts[-3:] == ("assets", "deck", "report")
        assert css_path.exists()
        assert js_path.exists()

    def test_assets_are_inlined_into_the_document(self, tmp_path):
        css_text = _read_report_asset_text(_report_asset_paths()[0])
        js_text = _read_report_asset_text(_report_asset_paths()[1])
        assert ":root" in css_text
        assert "initDeckTableUI" in js_text

        text = _write_report(tmp_path).read_text(encoding="utf-8")
        assert ".exp-chip" in text
        assert "function initDeckTableUI" in text
        assert "function sortTable" in text
