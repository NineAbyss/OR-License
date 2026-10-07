
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from quant_pro.infrastructure.config.env_substitution import substitute_env_vars

__all__ = ["load_yaml_with_env"]


def load_yaml_with_env(path: str | Path, *, strict: bool = True) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    substituted = substitute_env_vars(text, strict=strict)
    loaded = yaml.safe_load(substituted)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise TypeError(
            f"YAML at {path!s} must be a mapping at top level, got {type(loaded).__name__}"
        )
    return loaded
