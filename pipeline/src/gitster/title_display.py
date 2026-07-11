from __future__ import annotations

import re

from gitster.identity import normalize_string_scalar


_COLLABORATION_KEYWORDS = [
    "feat",
    "ft",
    "featuring",
    "with",
    "con",
    "w/",
    "junto a",
]

_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "from",
    "in",
    "into",
    "nor",
    "of",
    "off",
    "on",
    "onto",
    "or",
    "out",
    "over",
    "per",
    "so",
    "the",
    "to",
    "up",
    "upon",
    "via",
    "with",
    "yet",
    "vs",
    "v",
    "al",
    "ante",
    "bajo",
    "cabe",
    "con",
    "contra",
    "de",
    "del",
    "desde",
    "durante",
    "en",
    "entre",
    "hacia",
    "hasta",
    "mediante",
    "para",
    "por",
    "según",
    "sin",
    "sobre",
    "tras",
    "versus",
    "y",
    "e",
    "o",
    "u",
    "ni",
    "el",
    "la",
    "los",
    "las",
    "lo",
    "un",
    "una",
    "unos",
    "unas",
}

_ALWAYS_CAPITALIZE_WORDS = {
    "so",
}

_TRAILING_BLOCK_PATTERNS = [
    re.compile(r"^(?P<base>.*?)\s*\((?P<inner>[^()]*)\)\s*$"),
    re.compile(r"^(?P<base>.*?)\s*\[(?P<inner>[^\[\]]*)\]\s*$"),
]

_LETTER_PATTERN = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")
_LATIN_WORD_PATTERN = r"0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
_TITLE_TOKEN_PATTERN = re.compile(
    rf"^(?P<prefix>[^{_LATIN_WORD_PATTERN}]*)(?P<core>.*?)(?P<suffix>[^{_LATIN_WORD_PATTERN}]*)$"
)


def _looks_like_collaboration_block(text: str) -> bool:
    lowered = normalize_string_scalar(text)
    if lowered is None:
        return False
    lowered = lowered.casefold()

    if any(keyword in lowered for keyword in _COLLABORATION_KEYWORDS):
        return True

    return bool(re.search(r"(^|\s)x(\s|$)", lowered))


def _strip_trailing_collaboration_blocks(title: str) -> str:
    current = title.strip()
    while current:
        updated = current
        for pattern in _TRAILING_BLOCK_PATTERNS:
            match = pattern.match(current)
            if match is None:
                continue
            if not _looks_like_collaboration_block(match.group("inner")):
                continue
            updated = normalize_string_scalar(match.group("base")) or ""
            break
        if updated == current:
            break
        current = updated
    return current


def _is_special_token(core: str) -> bool:
    if not core:
        return False
    lowered = core.casefold()
    if lowered in _SMALL_WORDS:
        return False
    if re.fullmatch(r"(?:[A-Z]\.){2,}[A-Z]?\.?", core):
        return True
    if re.fullmatch(r"[IVXLCDM]+", core):
        return True
    if any(char.isdigit() for char in core):
        return True
    if len(core) <= 3 and core.isalpha() and core.isupper():
        return True
    if re.fullmatch(r"[A-Z0-9&/+]+(?:[-][A-Z0-9&/+]+)*", core) and any(char in core for char in "&/+"):
        return True
    return False


def _capitalize_letter_runs(text: str) -> str:
    if not text:
        return text

    characters = list(text.lower())
    should_capitalize = True
    index = 0

    while index < len(characters):
        if should_capitalize and _LETTER_PATTERN.fullmatch(characters[index] or ""):
            characters[index] = characters[index].upper()
            should_capitalize = False

        if characters[index] in {":", "?", "!", "/", "-"}:
            should_capitalize = True
        elif characters[index] == "." and "".join(characters[index : index + 3]) == "...":
            should_capitalize = True
            index += 2
        elif _LETTER_PATTERN.fullmatch(characters[index] or ""):
            should_capitalize = False

        index += 1

    return "".join(characters)


def _ends_subphrase(token: str) -> bool:
    stripped = token.rstrip("\"'”’)]}")
    return stripped.endswith("...") or stripped.endswith(":") or stripped.endswith("?") or stripped.endswith("!")


def _transform_token(token: str, *, is_first: bool, is_last: bool, is_subphrase_start: bool) -> str:
    match = _TITLE_TOKEN_PATTERN.match(token)
    if match is None:
        return token

    prefix = match.group("prefix")
    core = match.group("core")
    suffix = match.group("suffix")
    if not core:
        return token

    if suffix and _is_special_token(f"{core}{suffix}"):
        return f"{prefix}{core}{suffix}"
    if _is_special_token(core):
        return f"{prefix}{core}{suffix}"

    lowered = core.casefold()
    if (
        lowered in _SMALL_WORDS
        and lowered not in _ALWAYS_CAPITALIZE_WORDS
        and not is_first
        and not is_last
        and not is_subphrase_start
    ):
        return f"{prefix}{lowered}{suffix}"
    return f"{prefix}{_capitalize_letter_runs(core)}{suffix}"


def _apply_display_title_case(title: str) -> str:
    tokens = title.split()
    if not tokens:
        return title
    transformed_tokens: list[str] = []
    next_is_subphrase_start = True
    for index, token in enumerate(tokens):
        transformed_tokens.append(
            _transform_token(
                token,
                is_first=index == 0,
                is_last=index == len(tokens) - 1,
                is_subphrase_start=next_is_subphrase_start,
            )
        )
        next_is_subphrase_start = _ends_subphrase(token)
    return " ".join(transformed_tokens)


def normalize_title_display(value) -> str | None:
    title = normalize_string_scalar(value)
    if title is None:
        return None

    title = title.split(" - ", 1)[0].strip()
    title = _strip_trailing_collaboration_blocks(title)
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return normalize_string_scalar(value)

    return _apply_display_title_case(title)
