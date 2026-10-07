
from __future__ import annotations

import os
import re

__all__ = ["MissingEnvVarError", "substitute_env_vars"]

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::([^}]*))?\}")


class MissingEnvVarError(Exception):
    pass


def substitute_env_vars(yaml_str: str, *, strict: bool = True) -> str:

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2)
        value = os.environ.get(var_name)
        if value is not None:
            return value
        if default is not None:
            return default
        if strict:
            raise MissingEnvVarError(
                f"Environment variable ${{{var_name}}} is not set and no default "
                f"was provided (pattern: {match.group(0)})."
            )
        return ""

    return _ENV_VAR_PATTERN.sub(_replace, yaml_str)
