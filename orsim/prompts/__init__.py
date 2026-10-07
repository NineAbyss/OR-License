
from __future__ import annotations

from types import ModuleType

from orsim.language import normalize_language

from . import en

_MODULES: dict[str, ModuleType] = {"en": en}


def for_language(language: str | None = None) -> ModuleType:
    return _MODULES[normalize_language(language)]


def refusals(language: str | None = None) -> dict[str, str]:
    return dict(for_language(language).REFUSALS)


__all__ = ["for_language", "refusals"]
