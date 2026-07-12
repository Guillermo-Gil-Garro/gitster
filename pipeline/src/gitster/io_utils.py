from __future__ import annotations

import numbers
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

import pandas as pd


_XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_INVALID_SHEET_CHARS = set('[]:*?/\\')


def read_parquet(path: str | Path) -> pd.DataFrame:
    return pd.read_parquet(Path(path))


def write_parquet_atomic(path: str | Path, df: pd.DataFrame) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp_path, index=False)
    tmp_path.replace(path)


def write_csv(path: str | Path, df: pd.DataFrame) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")


def _serialize_excel_cell(value, *, list_separator: str) -> object:
    if value is None:
        return None
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            if item is None:
                continue
            if not isinstance(item, (list, tuple, set)) and pd.isna(item):
                continue
            text = str(item).strip()
            if text:
                items.append(text)
        return list_separator.join(items)
    if pd.isna(value):
        return None
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        numeric_value = float(value)
        if numeric_value.is_integer():
            return int(numeric_value)
    return value


def _excel_column_name(column_idx: int) -> str:
    name = ""
    value = column_idx
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _excel_column_index(column_name: str) -> int:
    value = 0
    for char in column_name:
        if not char.isalpha():
            continue
        value = value * 26 + (ord(char.upper()) - 64)
    return value


def _sanitize_sheet_name(sheet_name: str) -> str:
    cleaned = "".join("_" if char in _INVALID_SHEET_CHARS else char for char in sheet_name)
    cleaned = cleaned.strip() or "Sheet1"
    return cleaned[:31]


def _xlsx_cell_xml(cell_ref: str, value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return f'<c r="{cell_ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, numbers.Integral):
        return f'<c r="{cell_ref}"><v>{int(value)}</v></c>'
    if isinstance(value, numbers.Real):
        return f'<c r="{cell_ref}"><v>{value}</v></c>'

    text = str(value)
    return (
        f'<c r="{cell_ref}" t="inlineStr">'
        f'<is><t xml:space="preserve">{escape(text)}</t></is>'
        f"</c>"
    )


def _build_worksheet_xml(df: pd.DataFrame, *, list_separator: str) -> str:
    export_df = df.copy()
    for column in export_df.columns:
        serialized_values = [
            _serialize_excel_cell(value, list_separator=list_separator)
            for value in export_df[column].tolist()
        ]
        export_df[column] = pd.Series(serialized_values, index=export_df.index, dtype="object")

    column_widths: list[int] = []
    for column_name in export_df.columns:
        max_length = len(str(column_name))
        for value in export_df[column_name].tolist():
            text = "" if value is None else str(value)
            max_length = max(max_length, len(text))
        column_widths.append(min(max(max_length + 2, 12), 60))

    header_cells = [
        _xlsx_cell_xml(f"{_excel_column_name(column_idx)}1", column_name)
        for column_idx, column_name in enumerate(export_df.columns, start=1)
    ]
    row_xml_parts = [f'<row r="1">{"".join(header_cells)}</row>']

    for row_idx, row in enumerate(export_df.itertuples(index=False, name=None), start=2):
        cell_xml_parts = []
        for column_idx, value in enumerate(row, start=1):
            cell_ref = f"{_excel_column_name(column_idx)}{row_idx}"
            cell_xml = _xlsx_cell_xml(cell_ref, value)
            if cell_xml:
                cell_xml_parts.append(cell_xml)
        row_xml_parts.append(f'<row r="{row_idx}">{"".join(cell_xml_parts)}</row>')

    cols_xml = "".join(
        f'<col min="{column_idx}" max="{column_idx}" width="{width}" customWidth="1"/>'
        for column_idx, width in enumerate(column_widths, start=1)
    )
    last_col_letter = _excel_column_name(max(len(export_df.columns), 1))
    last_row = max(len(export_df) + 1, 1)

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews>'
        '<sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        "</sheetView>"
        "</sheetViews>"
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<cols>{cols_xml}</cols>"
        f"<sheetData>{''.join(row_xml_parts)}</sheetData>"
        f'<autoFilter ref="A1:{last_col_letter}{last_row}"/>'
        "</worksheet>"
    )


def write_xlsx(
    path: str | Path,
    df: pd.DataFrame,
    *,
    sheet_name: str,
    list_separator: str = " | ",
    extra_sheets: list[tuple[str, pd.DataFrame]] | None = None,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sheets: list[tuple[str, pd.DataFrame]] = [(sheet_name, df)]
    sheets.extend(extra_sheets or [])

    sheet_names: list[str] = []
    for raw_name, _sheet_df in sheets:
        cleaned_name = _sanitize_sheet_name(raw_name)
        if cleaned_name in sheet_names:
            raise ValueError(f"Duplicate sheet name after sanitizing: {cleaned_name!r}")
        sheet_names.append(cleaned_name)

    worksheet_xmls = [
        _build_worksheet_xml(sheet_df, list_separator=list_separator)
        for _raw_name, sheet_df in sheets
    ]

    sheet_entries_xml = "".join(
        f'<sheet name="{escape(name)}" sheetId="{sheet_idx}" r:id="rId{sheet_idx}"/>'
        for sheet_idx, name in enumerate(sheet_names, start=1)
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheet_entries_xml}</sheets>"
        "</workbook>"
    )

    workbook_rel_entries = "".join(
        f'<Relationship Id="rId{sheet_idx}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{sheet_idx}.xml"/>'
        for sheet_idx in range(1, len(sheets) + 1)
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{workbook_rel_entries}"
        "</Relationships>"
    )

    package_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    worksheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{sheet_idx}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for sheet_idx in range(1, len(sheets) + 1)
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{worksheet_overrides}"
        "</Types>"
    )

    tmp_path = path.with_suffix(".tmp.xlsx")
    if tmp_path.exists():
        tmp_path.unlink()
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", package_rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        for sheet_idx, worksheet_xml in enumerate(worksheet_xmls, start=1):
            archive.writestr(f"xl/worksheets/sheet{sheet_idx}.xml", worksheet_xml)
    if path.exists():
        path.unlink()
    tmp_path.replace(path)


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    shared_strings: list[str] = []
    for item in root.findall(f"{{{_XLSX_MAIN_NS}}}si"):
        texts = [text_node.text or "" for text_node in item.findall(f".//{{{_XLSX_MAIN_NS}}}t")]
        shared_strings.append("".join(texts))
    return shared_strings


def _read_xlsx_cell(cell: ET.Element, shared_strings: list[str]) -> object:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        texts = [text_node.text or "" for text_node in cell.findall(f".//{{{_XLSX_MAIN_NS}}}t")]
        return "".join(texts)

    value_node = cell.find(f"{{{_XLSX_MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return ""

    raw_value = value_node.text
    if cell_type == "s":
        return shared_strings[int(raw_value)] if raw_value.isdigit() else raw_value
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"
    return raw_value


def read_xlsx(path: str | Path, *, sheet_name: str | int | None = 0) -> pd.DataFrame:
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relationship_targets = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in rels_root.findall(f"{{{_PKG_REL_NS}}}Relationship")
        }

        sheet_nodes = workbook_root.findall(f".//{{{_XLSX_MAIN_NS}}}sheet")
        if not sheet_nodes:
            return pd.DataFrame()

        selected_sheet = None
        if isinstance(sheet_name, str):
            for sheet_node in sheet_nodes:
                if sheet_node.attrib.get("name") == sheet_name:
                    selected_sheet = sheet_node
                    break
        else:
            sheet_idx = 0 if sheet_name is None else int(sheet_name)
            if 0 <= sheet_idx < len(sheet_nodes):
                selected_sheet = sheet_nodes[sheet_idx]

        if selected_sheet is None:
            raise ValueError(f"Sheet {sheet_name!r} not found in {path}")

        relation_id = selected_sheet.attrib.get(f"{{{_XLSX_REL_NS}}}id")
        if relation_id is None or relation_id not in relationship_targets:
            raise ValueError(f"Could not resolve sheet {selected_sheet.attrib.get('name')} in {path}")

        sheet_target = relationship_targets[relation_id].lstrip("/")
        if not sheet_target.startswith("xl/"):
            sheet_target = f"xl/{sheet_target}"

        shared_strings = _load_shared_strings(archive)
        worksheet_root = ET.fromstring(archive.read(sheet_target))

    row_maps: dict[int, dict[int, object]] = {}
    max_col = 0
    for row_node in worksheet_root.findall(f".//{{{_XLSX_MAIN_NS}}}sheetData/{{{_XLSX_MAIN_NS}}}row"):
        row_idx = int(row_node.attrib.get("r", "0"))
        row_map: dict[int, object] = {}
        for cell_node in row_node.findall(f"{{{_XLSX_MAIN_NS}}}c"):
            cell_ref = cell_node.attrib.get("r", "")
            column_letters = "".join(char for char in cell_ref if char.isalpha())
            column_idx = _excel_column_index(column_letters)
            if column_idx <= 0:
                continue
            row_map[column_idx] = _read_xlsx_cell(cell_node, shared_strings)
            max_col = max(max_col, column_idx)
        row_maps[row_idx] = row_map

    if max_col == 0:
        return pd.DataFrame()

    headers = [str(row_maps.get(1, {}).get(column_idx, "")).strip() for column_idx in range(1, max_col + 1)]
    data_rows = []
    for row_idx in sorted(index for index in row_maps.keys() if index != 1):
        row_map = row_maps[row_idx]
        data_rows.append([row_map.get(column_idx, "") for column_idx in range(1, max_col + 1)])

    return pd.DataFrame(data_rows, columns=headers)
