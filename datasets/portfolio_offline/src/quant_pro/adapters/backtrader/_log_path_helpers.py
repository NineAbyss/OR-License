
from __future__ import annotations

import os


def _derive_ei_log_path(persist_path: str) -> str:
    return os.path.join(persist_path, "enhanced_index.log") if persist_path else ""


def _derive_log_path(persist_path: str) -> str:
    return os.path.join(persist_path, "longshort.log") if persist_path else ""
