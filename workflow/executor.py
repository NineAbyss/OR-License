
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Mapping

_SENSITIVE_ENV_NAME = re.compile(
    r"(?:^|_)(?:api_?key|access_?token|auth_?token|token|secret|password|"
    r"passwd|credential|private_?key|wlsaccessid|wlssecret|license(?:_key|_file)?)"
    r"(?:_|$)",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|bearer|secret|"
    r"password|passwd|credential|wlsaccessid|wlssecret)\b"
    r"(\s*[=:]\s*)([\"']?)([^\s,;\"']+)([\"']?)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
_OPENAI_STYLE_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_JWT_TOKEN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
    re.DOTALL,
)
_HIGH_ENTROPY_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Fa-f0-9]{32,}|[A-Za-z0-9_+/=-]{40,})(?![A-Za-z0-9])"
)


def _redact_sensitive_text(
    text: str,
    environment: Mapping[str, str] | None = None,
) -> str:
    redacted = str(text or "")
    for name, value in (environment or {}).items():
        secret = str(value or "")
        if _SENSITIVE_ENV_NAME.search(str(name)) and len(secret) >= 4:
            redacted = redacted.replace(secret, f"[REDACTED:{name}]")
    redacted = _PRIVATE_KEY_BLOCK.sub("[REDACTED:PRIVATE_KEY]", redacted)
    redacted = _BEARER_TOKEN.sub("Bearer [REDACTED:TOKEN]", redacted)
    redacted = _OPENAI_STYLE_KEY.sub("[REDACTED:API_KEY]", redacted)
    redacted = _JWT_TOKEN.sub("[REDACTED:JWT]", redacted)
    redacted = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2)}"
            f"{match.group(3)}[REDACTED]{match.group(5)}"
        ),
        redacted,
    )
    return _HIGH_ENTROPY_TOKEN.sub("[REDACTED:POSSIBLE_SECRET]", redacted)


def _read_regular_child_without_links(
    parent: Path,
    name: str,
    *,
    label: str,
    max_bytes: int | None = None,
) -> bytes:
    if not name or Path(name).name != name:
        raise ValueError(f"{label} must be a direct child")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(parent, directory_flags)
    file_fd = -1
    try:
        file_fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} is not a regular file")
        if metadata.st_nlink != 1:
            raise ValueError(f"{label} must not be a hard link")
        if max_bytes is not None and metadata.st_size > max_bytes:
            raise ValueError(f"{label} exceeds the formal size limit")
        with os.fdopen(file_fd, "rb") as handle:
            file_fd = -1
            data = handle.read() if max_bytes is None else handle.read(max_bytes + 1)
        if max_bytes is not None and len(data) > max_bytes:
            raise ValueError(f"{label} exceeds the formal size limit")
        return data
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(directory_fd)
