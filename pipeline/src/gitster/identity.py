from __future__ import annotations

import hashlib
import json
import re
import unicodedata

import pandas as pd


IDENTITY_VERSION = "v2.1"

_COLLAPSIBLE_FRAGMENT_PATTERNS = [
    re.compile(r"^radio edit$"),
    re.compile(r"^edit$"),
    re.compile(r"^remaster(?:ed)?(?: \d{2,4})?$"),
    re.compile(r"^live(?: .*)?$"),
    re.compile(r"^acoustic(?: .*)?$"),
    re.compile(r"^mono$"),
    re.compile(r"^stereo$"),
    re.compile(r"^instrumental$"),
    re.compile(r"^karaoke$"),
    re.compile(r"^demo$"),
    re.compile(r"^bonus track$"),
    re.compile(r"^version$"),
    re.compile(r"^from .+$"),
    re.compile(r"^soundtrack(?: version)?$"),
    re.compile(r"^ost(?: version)?$"),
    re.compile(r"^theme(?: from .+)?$"),
]

_TRAILING_FRAGMENT_PATTERNS = [
    re.compile(r"^(?P<base>.*?)\s*\((?P<tag>[^()]*)\)\s*$"),
    re.compile(r"^(?P<base>.*?)\s*\[(?P<tag>[^\[\]]*)\]\s*$"),
    re.compile(r"^(?P<base>.*?)\s*[-:]\s*(?P<tag>[^-:()\[\]]+)\s*$"),
]

_POSTMERGE_PROTECTED_FRAGMENT_PATTERNS = {
    "live": re.compile(r"^live(?: .*)?$"),
    "acoustic": re.compile(r"^acoustic(?: .*)?$"),
    "instrumental": re.compile(r"^instrumental$"),
    "karaoke": re.compile(r"^karaoke$"),
    "demo": re.compile(r"^demo$"),
    "mono": re.compile(r"^mono$"),
    "stereo": re.compile(r"^stereo$"),
}


def normalize_string_scalar(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        if pd.isna(value):
            return None
        value = str(value)

    cleaned = value.strip()
    return cleaned or None


def normalize_string_list(value) -> list[str]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple, set)):
        if pd.isna(value):
            return []
        value = [value]

    cleaned_items: list[str] = []
    seen: set[str] = set()
    for item in value:
        item_value = normalize_string_scalar(item)
        if item_value is None or item_value in seen:
            continue
        seen.add(item_value)
        cleaned_items.append(item_value)

    return cleaned_items


def normalize_secondary_artist_ids(value) -> tuple[str, ...]:
    return tuple(sorted(normalize_string_list(value)))


def ascii_fold_lower(value: str | None) -> str:
    raw = normalize_string_scalar(value) or ""
    folded = unicodedata.normalize("NFKD", raw)
    without_diacritics = "".join(ch for ch in folded if not unicodedata.combining(ch))
    normalized = re.sub(r"\s+", " ", without_diacritics.lower()).strip()
    return normalized


def title_contains_remix(value: str | None) -> bool:
    return bool(re.search(r"\bremix\b", ascii_fold_lower(value)))


def extract_trailing_title_fragments(value: str | None) -> list[str]:
    current = normalize_string_scalar(value)
    if current is None:
        return []

    fragments: list[str] = []
    current = current.strip()
    while current:
        updated = current
        matched_fragment = None
        for pattern in _TRAILING_FRAGMENT_PATTERNS:
            match = pattern.match(current)
            if match is None:
                continue
            matched_fragment = ascii_fold_lower(match.group("tag")).strip(" -:;,.!/'\"")
            updated = match.group("base").strip()
            break

        if matched_fragment is None or updated == current:
            break

        if matched_fragment:
            fragments.append(matched_fragment)
        current = updated

    return fragments


def extract_postmerge_protected_title_tags(value: str | None) -> tuple[str, ...]:
    protected_tags: list[str] = []
    seen: set[str] = set()
    for fragment in extract_trailing_title_fragments(value):
        for tag_name, pattern in _POSTMERGE_PROTECTED_FRAGMENT_PATTERNS.items():
            if tag_name in seen:
                continue
            if pattern.fullmatch(fragment):
                protected_tags.append(tag_name)
                seen.add(tag_name)
    return tuple(protected_tags)


def has_postmerge_protected_title_tags(value: str | None) -> bool:
    return bool(extract_postmerge_protected_title_tags(value))


def _is_collapsible_fragment(fragment: str) -> bool:
    normalized_fragment = ascii_fold_lower(fragment).strip(" -:;,.!/'\"")
    if not normalized_fragment or "remix" in normalized_fragment:
        return False

    return any(pattern.fullmatch(normalized_fragment) for pattern in _COLLAPSIBLE_FRAGMENT_PATTERNS)


def _trim_title_tail(value: str) -> tuple[str, bool]:
    current = value.strip()
    changed = False

    while current:
        updated = current
        for pattern in _TRAILING_FRAGMENT_PATTERNS:
            match = pattern.match(current)
            if match is None:
                continue

            fragment = match.group("tag")
            if not _is_collapsible_fragment(fragment):
                continue

            updated = match.group("base").strip(" -:;,.!/'\"")
            changed = True
            break

        if updated == current:
            break

        current = re.sub(r"\s+", " ", updated).strip()

    return current, changed


def compute_base_title_norm(title: str | None) -> tuple[str, bool, bool]:
    normalized_title = ascii_fold_lower(title)
    base_title_norm, had_collapsible_suffix = _trim_title_tail(normalized_title)
    if not base_title_norm:
        base_title_norm = normalized_title

    contains_remix = bool(re.search(r"\bremix\b", normalized_title))
    return base_title_norm, had_collapsible_suffix, contains_remix


def build_song_key(
    primary_artist_id: str | None,
    isrc: str | None,
    base_title_norm: str,
    feat_signature: tuple[str, ...],
) -> tuple[str, tuple]:
    normalized_primary_artist_id = normalize_string_scalar(primary_artist_id)
    normalized_isrc = normalize_string_scalar(isrc)

    if normalized_isrc is not None:
        return "isrc_first", (normalized_primary_artist_id, normalized_isrc.upper())

    return "fallback", (normalized_primary_artist_id, base_title_norm, feat_signature)


def build_editorial_key(
    primary_artist_id: str | None,
    base_title_norm: str | None,
    feat_signature,
) -> tuple[str | None, str, tuple[str, ...]]:
    return (
        normalize_string_scalar(primary_artist_id),
        normalize_string_scalar(base_title_norm) or "",
        normalize_secondary_artist_ids(feat_signature),
    )


def serialize_song_key(song_key: tuple) -> str:
    def to_jsonable(value):
        if isinstance(value, tuple):
            return [to_jsonable(item) for item in value]
        return value

    return json.dumps(to_jsonable(song_key), ensure_ascii=False, separators=(",", ":"))


def make_song_id(song_key: tuple) -> str:
    digest = hashlib.sha1(f"{IDENTITY_VERSION}|{serialize_song_key(song_key)}".encode("utf-8")).hexdigest()
    return digest


def make_postpass_song_id(editorial_key: tuple[str | None, str, tuple[str, ...]]) -> str:
    digest = hashlib.sha1(
        f"{IDENTITY_VERSION}|postpass_conservative|{serialize_song_key(editorial_key)}".encode("utf-8")
    ).hexdigest()
    return digest
