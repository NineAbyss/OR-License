
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


def harbor_executable() -> str:
    override = os.environ.get("ORLE_HARBOR_BIN")
    if override:
        return override
    return shutil.which("harbor") or str(Path.home() / ".local/bin/harbor")


def harbor_python() -> str:
    override = os.environ.get("ORLE_HARBOR_PYTHON")
    if override:
        return override
    executable = shutil.which(harbor_executable())
    if executable:
        adjacent = Path(executable).resolve().parent / "python"
        if adjacent.is_file():
            return str(adjacent)
    return sys.executable
