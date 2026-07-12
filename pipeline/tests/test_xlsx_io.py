from __future__ import annotations

import pandas as pd
import pytest

from gitster.io_utils import read_xlsx, write_xlsx


def test_single_sheet_roundtrip(tmp_path):
    df = pd.DataFrame(
        {
            "song_id": ["s1", "s2"],
            "year": [1990, 2001],
            "tags": [["a", "b"], []],
        }
    )
    path = tmp_path / "single.xlsx"
    write_xlsx(path, df, sheet_name="review_template")

    loaded = read_xlsx(path, sheet_name="review_template")
    assert list(loaded.columns) == ["song_id", "year", "tags"]
    assert loaded["song_id"].tolist() == ["s1", "s2"]
    assert loaded["year"].tolist() == ["1990", "2001"]
    assert loaded["tags"].tolist() == ["a | b", ""]


def test_multi_sheet_roundtrip(tmp_path):
    main_df = pd.DataFrame({"song_id": ["s1"], "year_candidate": [1985]})
    audit_df = pd.DataFrame({"PROMPT_AUDITORIA_IA": ["fila uno", "fila dos"]})
    extra_df = pd.DataFrame({"k": ["a", "b"], "v": [1, 2]})

    path = tmp_path / "multi.xlsx"
    write_xlsx(
        path,
        main_df,
        sheet_name="review_template",
        extra_sheets=[("AI_AUDIT", audit_df), ("extra", extra_df)],
    )

    by_default = read_xlsx(path)
    assert by_default["song_id"].tolist() == ["s1"]

    by_name = read_xlsx(path, sheet_name="AI_AUDIT")
    assert list(by_name.columns) == ["PROMPT_AUDITORIA_IA"]
    assert by_name["PROMPT_AUDITORIA_IA"].tolist() == ["fila uno", "fila dos"]

    by_index = read_xlsx(path, sheet_name=1)
    assert by_index["PROMPT_AUDITORIA_IA"].tolist() == ["fila uno", "fila dos"]

    third = read_xlsx(path, sheet_name="extra")
    assert third["k"].tolist() == ["a", "b"]
    assert third["v"].tolist() == ["1", "2"]


def test_multi_sheet_missing_sheet_raises(tmp_path):
    path = tmp_path / "multi.xlsx"
    write_xlsx(
        path,
        pd.DataFrame({"a": [1]}),
        sheet_name="main",
        extra_sheets=[("other", pd.DataFrame({"b": [2]}))],
    )
    with pytest.raises(ValueError):
        read_xlsx(path, sheet_name="nope")


def test_duplicate_sheet_names_rejected(tmp_path):
    path = tmp_path / "dup.xlsx"
    with pytest.raises(ValueError):
        write_xlsx(
            path,
            pd.DataFrame({"a": [1]}),
            sheet_name="main",
            extra_sheets=[("main", pd.DataFrame({"b": [2]}))],
        )
