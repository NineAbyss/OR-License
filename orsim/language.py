
from __future__ import annotations

EN = "en"
DEFAULT_LANGUAGE = EN
SUPPORTED_LANGUAGES: tuple[str, ...] = (EN,)


def normalize_language(value: str | None) -> str:
    if value is None or not str(value).strip():
        return DEFAULT_LANGUAGE
    tag = str(value).strip().lower()
    if tag not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"unsupported simulator language: {value!r} "
            f"(expected one of {', '.join(SUPPORTED_LANGUAGES)})"
        )
    return tag
