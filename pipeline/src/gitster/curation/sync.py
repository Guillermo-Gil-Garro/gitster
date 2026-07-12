"""Curation sync: sync run catalogs to the global store and apply current curation to the run."""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd

from gitster.artist_display import (
    build_artists_display_current,
    resolve_final_artists_display,
)
from gitster.config import RunConfig
from gitster.curation.candidates import (
    build_candidates_outputs,
    build_song_owner_ids_by_song_id,
)
from gitster.curation.musicbrainz import get_mb_years_for_isrcs
from gitster.curation.store import (
    bootstrap_global_store,
    load_curation_current,
    resolve_global_store_dir,
    sync_song_catalog,
    sync_track_catalog,
)
from gitster.identity import IDENTITY_VERSION, normalize_string_list, normalize_string_scalar
from gitster.io_utils import read_parquet, write_csv, write_parquet_atomic, write_xlsx
from gitster.paths import RunPaths
from gitster.title_display import normalize_title_display


logger = logging.getLogger(__name__)

CURATION_APPLY_QC_COLUMNS = [
    "run_id",
    "songs_input",
    "songs_with_year_override",
    "songs_with_title_override",
    "songs_with_artists_override",
    "candidates_input",
    "candidates_output",
]

SONG_CURATION_COLUMNS = [
    "song_id",
    "year_override",
    "artists_display_override",
    "title_display_override",
    "curation_updated_at",
    "curation_run_id",
    "curation_note",
]

REVIEW_TEMPLATE_COLUMNS = [
    "song_id",
    "title_display",
    "artists_display",
    "owners",
    "track_url",
    "album_name",
    "album_release_date_spotify",
    "year_candidate",
    "year_final",
    "year_candidate_source",
    "year_suspect",
    "suspect_reason",
    "mb_first_release_year",
    "mb_match",
    "year_override",
    "ai_year",
    "ai_note",
    "title_display_override",
    "artists_display_override",
    "note",
]

SPOTIFY_TRACK_URL_TEMPLATE = "https://open.spotify.com/track/{track_id}"

ARTIST_MEDIAN_MIN_SONGS = 3
ARTIST_MEDIAN_LATE_YEARS = 6

# Album names that usually carry a reissue/compilation date instead of the original release year.
_REISSUE_ALBUM_PATTERN = re.compile(
    r"\b("
    r"remaster\w*|deluxe|anthology|antologia|greatest hits|best of|collection|coleccion|"
    r"recopilat\w*|singles|hits|essential\w*|live|en directo|en vivo|edition|edicion|"
    r"aniversario|anniversary"
    r")\b"
)

AI_AUDIT_SHEET_NAME = "AI_AUDIT"

AI_AUDIT_PROMPT_ROWS = [
    "Rol: eres un auditor de años de lanzamiento de canciones para un juego de cartas tipo Hitster. "
    "En cada carta se imprime el año de PRIMER lanzamiento de la canción; un año equivocado arruina la partida.",
    "Tarea: trabaja SOLO en la hoja 1 (review_template). Revisa exclusivamente las filas con year_suspect=TRUE "
    "o con mb_match=\"diff\". No toques el resto de filas.",
    "Objetivo: determinar el año de PRIMER lanzamiento de la grabación original. Ignora fechas de remasters, "
    "recopilatorios, reediciones deluxe y álbumes en directo. Para un remix cuenta el año del remix; para una "
    "versión/cover, el año de esa versión, no el de la canción original.",
    "Contexto: year_candidate viene de Spotify (album_release_date_spotify) y a menudo es la fecha de un remaster "
    "o de un recopilatorio, no la del lanzamiento original. suspect_reason explica la sospecha: "
    "reissue-album-name (nombre de álbum tipo reedición), late-vs-artist-median (año tardío frente a la mediana "
    "del artista), mb-mismatch (MusicBrainz discrepa).",
    "Método: busca evidencia del año original (si tienes acceso web: Wikipedia, Discogs, MusicBrainz). Contrasta "
    "con mb_first_release_year cuando exista. No es posible escuchar track_url; no inventes datos ni deduzcas el "
    "año solo por el estilo musical.",
    "Salida: escribe el año (4 dígitos) SOLO en la columna ai_year, y en ai_note una única línea con la evidencia "
    "y su fuente (p. ej. \"Wikipedia: single publicado en 1978\"). Si confirmas que year_candidate ya es correcto, "
    "escribe ese mismo año en ai_year con su evidencia.",
    "Prohibido adivinar: si no encuentras evidencia clara, DEJA ai_year y ai_note EN BLANCO. Un blanco vale más "
    "que un año dudoso.",
    "No modifiques year_override, note, title_display_override, artists_display_override ni ninguna otra columna: "
    "pertenecen al curador humano.",
    "Nota: en el import, un year_override manual siempre gana sobre ai_year.",
]


def normalize_string_override(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    cleaned = str(value).strip()
    return cleaned or None


def coerce_year_override(value, *, strict: bool = False, song_id: str | None = None):
    if value is None or pd.isna(value):
        return pd.NA
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return pd.NA
    try:
        return int(value)
    except (TypeError, ValueError):
        if strict:
            song_suffix = f" for song_id={song_id}" if song_id else ""
            raise ValueError(f"Invalid year_override{song_suffix}: {value!r}") from None
        return pd.NA


def build_song_curation_frame(curation_df: pd.DataFrame) -> pd.DataFrame:
    if curation_df.empty:
        return pd.DataFrame(columns=SONG_CURATION_COLUMNS)

    filtered_df = curation_df[
        (curation_df["entity_type"] == "song") & (curation_df["identity_version"] == IDENTITY_VERSION)
    ].copy()
    if filtered_df.empty:
        return pd.DataFrame(columns=SONG_CURATION_COLUMNS)

    filtered_df["song_id"] = filtered_df["entity_id"]
    filtered_df["year_override"] = filtered_df["year_override"].apply(coerce_year_override)
    filtered_df["artists_display_override"] = filtered_df["artists_display_override"].apply(normalize_string_override)
    filtered_df["title_display_override"] = filtered_df["title_display_override"].apply(normalize_string_override)
    filtered_df["note"] = filtered_df["note"].apply(normalize_string_override)

    return filtered_df[
        [
            "song_id",
            "year_override",
            "artists_display_override",
            "title_display_override",
            "updated_at",
            "run_id",
            "note",
        ]
    ].rename(
        columns={
            "updated_at": "curation_updated_at",
            "run_id": "curation_run_id",
            "note": "curation_note",
        }
    )


def _load_apply_inputs(paths: RunPaths, *, require_tracks_snapshot: bool) -> dict[str, pd.DataFrame]:
    required_paths: list[tuple[Path, str]] = [
        (paths.processed_dir / "instances.parquet", "instances"),
        (paths.processed_dir / "songs.parquet", "identity"),
        (paths.processed_dir / "song_variant_map.parquet", "identity"),
        (paths.processed_dir / "years_baseline.parquet", "years"),
        (paths.processed_dir / "candidates.parquet", "candidates"),
    ]
    if require_tracks_snapshot:
        required_paths.insert(0, (paths.processed_dir / "tracks_snapshot.parquet", "tracks"))

    for required_path, step_name in required_paths:
        if not required_path.exists():
            raise FileNotFoundError(f"{required_path} not found; run the {step_name} step before this one")

    frames = {
        "instances": read_parquet(paths.processed_dir / "instances.parquet"),
        "songs": read_parquet(paths.processed_dir / "songs.parquet"),
        "song_variant_map": read_parquet(paths.processed_dir / "song_variant_map.parquet"),
        "years": read_parquet(paths.processed_dir / "years_baseline.parquet"),
        "candidates": read_parquet(paths.processed_dir / "candidates.parquet"),
    }
    tracks_snapshot_path = paths.processed_dir / "tracks_snapshot.parquet"
    if tracks_snapshot_path.exists():
        frames["tracks"] = read_parquet(tracks_snapshot_path)

    return frames


def _build_owner_names_by_id(instances_df: pd.DataFrame) -> dict[str, str]:
    if instances_df.empty or "owner_id" not in instances_df.columns or "owner_name" not in instances_df.columns:
        return {}

    owner_names: dict[str, str] = {}
    for row in instances_df[["owner_id", "owner_name"]].drop_duplicates().to_dict(orient="records"):
        owner_id = normalize_string_scalar(row.get("owner_id"))
        owner_name = normalize_string_scalar(row.get("owner_name"))
        if owner_id is not None and owner_name is not None and owner_id not in owner_names:
            owner_names[owner_id] = owner_name
    return owner_names


def _build_scalar_map(df: pd.DataFrame, key_column: str, value_column: str) -> dict[str, str]:
    if df.empty or key_column not in df.columns or value_column not in df.columns:
        return {}

    mapping: dict[str, str] = {}
    for row in df[[key_column, value_column]].dropna().to_dict(orient="records"):
        key = normalize_string_scalar(row[key_column])
        value = normalize_string_scalar(row[value_column])
        if key is not None and value is not None and key not in mapping:
            mapping[key] = value
    return mapping


def _build_songs_curated_df(songs_df: pd.DataFrame, song_curation_df: pd.DataFrame) -> pd.DataFrame:
    curated_df = songs_df.merge(song_curation_df, on="song_id", how="left")
    curated_df["title_display_raw"] = curated_df["title_display"]
    curated_df["title_display_original"] = curated_df["title_display_raw"]
    curated_df["title_display_current"] = curated_df["title_display_raw"].map(normalize_title_display)
    curated_df["title_display_current"] = curated_df["title_display_current"].combine_first(curated_df["title_display_raw"])
    curated_df["title_display_resolved"] = curated_df["title_display_override"].combine_first(
        curated_df["title_display_current"]
    )
    curated_df["title_display"] = curated_df["title_display_resolved"]
    curated_df["artists_display_current"] = curated_df.apply(
        lambda row: build_artists_display_current(
            row.get("primary_artist_name"),
            row.get("secondary_artist_names"),
        ),
        axis=1,
    )
    curated_df["artists_display_resolved"] = curated_df.apply(
        lambda row: resolve_final_artists_display(
            row,
            allow_legacy_display=False,
            allow_raw_fallback=True,
        ),
        axis=1,
    )
    curated_df["artists_display"] = curated_df["artists_display_resolved"]
    return curated_df


def _build_years_curated_df(years_df: pd.DataFrame, song_curation_df: pd.DataFrame) -> pd.DataFrame:
    curation_years_df = song_curation_df[
        ["song_id", "year_override", "curation_updated_at", "curation_run_id", "curation_note"]
    ].rename(columns={"year_override": "year_override_curation"})

    curated_df = years_df.merge(curation_years_df, on="song_id", how="left")
    curated_df["year_override"] = curated_df["year_override_curation"].combine_first(curated_df["year_override"])
    curated_df = curated_df.drop(columns=["year_override_curation"])
    curated_df["year_override"] = curated_df["year_override"].astype("Int64")
    curated_df["year_final"] = curated_df["year_override"].combine_first(curated_df["year_candidate"])
    curated_df["year_final"] = curated_df["year_final"].astype("Int64")
    return curated_df


def _attach_song_curation_columns(candidates_df: pd.DataFrame, songs_curated_df: pd.DataFrame) -> pd.DataFrame:
    song_columns = [
        "song_id",
        "winner_track_id",
        "title_display_raw",
        "title_display_current",
        "title_display_resolved",
        "artists_display_current",
        "artists_display_resolved",
        "artists_display",
        "secondary_artist_names",
        "year_override",
        "title_display_override",
        "artists_display_override",
        "curation_updated_at",
        "curation_run_id",
        "curation_note",
    ]
    return candidates_df.merge(
        songs_curated_df[song_columns],
        on=["song_id", "winner_track_id"],
        how="left",
    )


def _serialize_secondary_artist_names(value) -> str | None:
    names = normalize_string_list(value)
    if not names:
        return None
    return " | ".join(names)


def _build_artists_display_current(primary_artist_name, secondary_artist_names) -> str | None:
    return build_artists_display_current(primary_artist_name, secondary_artist_names)


def _fold_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _is_reissue_album_name(album_name) -> bool:
    if album_name is None or pd.isna(album_name):
        return False
    normalized = _fold_accents(str(album_name)).casefold()
    return _REISSUE_ALBUM_PATTERN.search(normalized) is not None


def _build_late_vs_artist_median_flags(template_df: pd.DataFrame) -> pd.Series:
    flags = pd.Series(False, index=template_df.index)
    if template_df.empty or "primary_artist_name" not in template_df.columns:
        return flags

    artist_keys = template_df["primary_artist_name"].map(
        lambda value: _fold_accents(str(value)).casefold().strip() if value is not None and not pd.isna(value) else None
    )
    years = pd.to_numeric(template_df["year_candidate"], errors="coerce")
    for artist_key, group_indexes in years.groupby(artist_keys).groups.items():
        if artist_key is None:
            continue
        group_years = years.loc[group_indexes].dropna()
        if len(group_years) < ARTIST_MEDIAN_MIN_SONGS:
            continue
        median_year = group_years.median()
        late_indexes = group_years[group_years - median_year >= ARTIST_MEDIAN_LATE_YEARS].index
        flags.loc[late_indexes] = True
    return flags


def _build_suspect_columns(template_df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    reissue_flags = template_df["album_name"].map(_is_reissue_album_name)
    late_flags = _build_late_vs_artist_median_flags(template_df)

    mb_years = pd.to_numeric(template_df["mb_first_release_year"], errors="coerce")
    candidate_years = pd.to_numeric(template_df["year_candidate"], errors="coerce")
    mb_mismatch_flags = mb_years.notna() & candidate_years.notna() & (mb_years != candidate_years)

    reasons = []
    for is_reissue, is_late, is_mb_mismatch in zip(reissue_flags, late_flags, mb_mismatch_flags):
        codes = []
        if is_reissue:
            codes.append("reissue-album-name")
        if is_late:
            codes.append("late-vs-artist-median")
        if is_mb_mismatch:
            codes.append("mb-mismatch")
        reasons.append(";".join(codes))

    suspect_reason = pd.Series(reasons, index=template_df.index, dtype="object")
    year_suspect = suspect_reason != ""
    return year_suspect, suspect_reason


def _build_review_template_df(
    candidates_curated_df: pd.DataFrame,
    *,
    owner_ids_by_song_id: dict[str, list[str]] | None = None,
    owner_names_by_id: dict[str, str] | None = None,
    album_name_by_track_id: dict[str, str] | None = None,
    isrc_by_song_id: dict[str, str] | None = None,
    mb_years_by_isrc: dict[str, int | None] | None = None,
) -> pd.DataFrame:
    owner_ids_by_song_id = owner_ids_by_song_id or {}
    owner_names_by_id = owner_names_by_id or {}
    album_name_by_track_id = album_name_by_track_id or {}
    isrc_by_song_id = isrc_by_song_id or {}
    mb_years_by_isrc = mb_years_by_isrc or {}

    template_df = candidates_curated_df.copy()
    if "secondary_artist_names" not in template_df.columns:
        template_df["secondary_artist_names"] = [[] for _ in range(len(template_df))]
    if "title_display_raw" not in template_df.columns:
        template_df["title_display_raw"] = template_df.get("title_display")
    if "title_display_current" not in template_df.columns:
        template_df["title_display_current"] = template_df["title_display_raw"].map(normalize_title_display)
    template_df["title_display_current"] = template_df["title_display_current"].combine_first(template_df["title_display_raw"])
    if "title_display_override" not in template_df.columns:
        template_df["title_display_override"] = None
    template_df["title_display"] = template_df["title_display_override"].combine_first(
        template_df["title_display_current"]
    )

    template_df["secondary_artist_names"] = template_df["secondary_artist_names"].map(_serialize_secondary_artist_names)
    if "artists_display_current" not in template_df.columns:
        template_df["artists_display_current"] = None
    template_df["artists_display_current"] = template_df["artists_display_current"].combine_first(
        template_df.apply(
            lambda row: _build_artists_display_current(
                row.get("primary_artist_name"),
                row.get("secondary_artist_names"),
            ),
            axis=1,
        )
    )
    template_df["artists_display"] = template_df.apply(resolve_final_artists_display, axis=1)

    template_df["track_url"] = template_df["winner_track_id"].map(
        lambda track_id: SPOTIFY_TRACK_URL_TEMPLATE.format(track_id=track_id)
        if track_id is not None and not pd.isna(track_id)
        else None
    )
    template_df["album_name"] = template_df["winner_track_id"].map(album_name_by_track_id)

    def _format_owners(song_id) -> str | None:
        owner_ids = owner_ids_by_song_id.get(song_id) or []
        owner_labels = [owner_names_by_id.get(owner_id, owner_id) for owner_id in owner_ids]
        return ", ".join(owner_labels) if owner_labels else None

    template_df["owners"] = template_df["song_id"].map(_format_owners)

    def _mb_year_for_song(song_id):
        isrc = isrc_by_song_id.get(song_id)
        if not isrc:
            return pd.NA
        mb_year = mb_years_by_isrc.get(isrc)
        return pd.NA if mb_year is None else mb_year

    template_df["mb_first_release_year"] = template_df["song_id"].map(_mb_year_for_song).astype("Int64")

    mb_years = template_df["mb_first_release_year"]
    candidate_years = pd.to_numeric(template_df["year_candidate"], errors="coerce")

    def _mb_match(mb_year, candidate_year) -> str:
        if pd.isna(mb_year) or pd.isna(candidate_year):
            return ""
        return "same" if int(mb_year) == int(candidate_year) else "diff"

    template_df["mb_match"] = [
        _mb_match(mb_year, candidate_year)
        for mb_year, candidate_year in zip(mb_years, candidate_years)
    ]

    year_suspect, suspect_reason = _build_suspect_columns(template_df)
    template_df["year_suspect"] = year_suspect
    template_df["suspect_reason"] = suspect_reason

    template_df["ai_year"] = pd.Series(pd.NA, index=template_df.index, dtype="Int64")
    template_df["ai_note"] = None
    if "curation_note" in template_df.columns:
        template_df["note"] = template_df["curation_note"]
    elif "note" not in template_df.columns:
        template_df["note"] = None

    if not template_df.empty:
        for column in ["year_candidate", "year_final", "year_override", "mb_first_release_year", "ai_year"]:
            if column in template_df.columns:
                template_df[column] = template_df[column].astype("Int64")

    return template_df.reindex(columns=REVIEW_TEMPLATE_COLUMNS)


def _build_ai_audit_df() -> pd.DataFrame:
    return pd.DataFrame({"PROMPT_AUDITORIA_IA": AI_AUDIT_PROMPT_ROWS})


def apply_current_curation_to_run(
    paths: RunPaths,
    *,
    store_dir: Path,
    sync_catalogs: bool,
    musicbrainz: bool = False,
) -> dict[str, int]:
    frames = _load_apply_inputs(paths, require_tracks_snapshot=sync_catalogs)
    songs_df = frames["songs"]
    years_df = frames["years"]
    candidates_df = frames["candidates"]

    track_catalog_rows = 0
    song_catalog_rows = 0
    if sync_catalogs:
        track_catalog_df = sync_track_catalog(store_dir, frames["tracks"])
        song_catalog_df = sync_song_catalog(store_dir, songs_df)
        track_catalog_rows = len(track_catalog_df)
        song_catalog_rows = len(song_catalog_df)

    curation_current_df = load_curation_current(store_dir)
    song_curation_df = build_song_curation_frame(curation_current_df)
    song_owner_ids_by_song_id = build_song_owner_ids_by_song_id(
        frames["instances"],
        frames["song_variant_map"],
    )

    songs_curated_df = _build_songs_curated_df(songs_df, song_curation_df)
    years_curated_df = _build_years_curated_df(years_df, song_curation_df)
    candidates_curated_df, _, _ = build_candidates_outputs(
        songs_curated_df,
        years_curated_df,
        run_id=paths.run_id,
        song_owner_ids_by_song_id=song_owner_ids_by_song_id,
    )
    candidates_curated_df = _attach_song_curation_columns(candidates_curated_df, songs_curated_df)

    owner_names_by_id = _build_owner_names_by_id(frames["instances"])
    album_name_by_track_id = (
        _build_scalar_map(frames["tracks"], "track_id", "album_name") if "tracks" in frames else {}
    )
    isrc_by_song_id = _build_scalar_map(songs_curated_df, "song_id", "isrc")

    mb_years_by_isrc: dict[str, int | None] = {}
    if musicbrainz and not candidates_curated_df.empty:
        candidate_isrcs = [
            isrc
            for isrc in (isrc_by_song_id.get(song_id) for song_id in candidates_curated_df["song_id"].tolist())
            if isrc
        ]
        mb_years_by_isrc = get_mb_years_for_isrcs(candidate_isrcs, store_dir=store_dir)

    review_template_df = _build_review_template_df(
        candidates_curated_df,
        owner_ids_by_song_id=song_owner_ids_by_song_id,
        owner_names_by_id=owner_names_by_id,
        album_name_by_track_id=album_name_by_track_id,
        isrc_by_song_id=isrc_by_song_id,
        mb_years_by_isrc=mb_years_by_isrc,
    )

    write_parquet_atomic(paths.processed_dir / "songs_curated.parquet", songs_curated_df)
    write_parquet_atomic(paths.processed_dir / "years_curated.parquet", years_curated_df)
    write_parquet_atomic(paths.processed_dir / "candidates_curated.parquet", candidates_curated_df)
    write_csv(paths.reports_dir / "candidates_review_template.csv", review_template_df)
    write_xlsx(
        paths.reports_dir / "candidates_review_template.xlsx",
        review_template_df,
        sheet_name="review_template",
        extra_sheets=[(AI_AUDIT_SHEET_NAME, _build_ai_audit_df())],
    )

    songs_with_year_override = int(songs_curated_df["year_override"].notna().sum()) if not songs_curated_df.empty else 0
    songs_with_title_override = (
        int(songs_curated_df["title_display_override"].notna().sum()) if not songs_curated_df.empty else 0
    )
    songs_with_artists_override = (
        int(songs_curated_df["artists_display_override"].notna().sum()) if not songs_curated_df.empty else 0
    )

    qc_row = {
        "run_id": paths.run_id,
        "songs_input": len(songs_df),
        "songs_with_year_override": songs_with_year_override,
        "songs_with_title_override": songs_with_title_override,
        "songs_with_artists_override": songs_with_artists_override,
        "candidates_input": len(candidates_df),
        "candidates_output": len(candidates_curated_df),
    }
    qc_df = pd.DataFrame([qc_row], columns=CURATION_APPLY_QC_COLUMNS)
    write_csv(paths.reports_dir / "curation_apply_qc.csv", qc_df)

    return {
        "track_catalog_rows": track_catalog_rows,
        "song_catalog_rows": song_catalog_rows,
        "songs_with_year_override": songs_with_year_override,
        "songs_with_title_override": songs_with_title_override,
        "songs_with_artists_override": songs_with_artists_override,
        "candidates_input": len(candidates_df),
        "candidates_output": len(candidates_curated_df),
    }


def run_curation_sync(config: RunConfig, paths: RunPaths, *, musicbrainz: bool = False) -> None:
    logger.info("Step: curation-sync")

    store_dir = resolve_global_store_dir()
    bootstrap_global_store(store_dir)
    stats = apply_current_curation_to_run(paths, store_dir=store_dir, sync_catalogs=True, musicbrainz=musicbrainz)

    logger.info(
        "OK | track_catalog_rows=%s | song_catalog_rows=%s | overrides_applied=%s | candidates_output=%s",
        stats["track_catalog_rows"],
        stats["song_catalog_rows"],
        stats["songs_with_year_override"] + stats["songs_with_title_override"] + stats["songs_with_artists_override"],
        stats["candidates_output"],
    )
