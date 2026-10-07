
import os
import sys
from pathlib import Path

_GUARD_DIR = (
    Path(__file__).resolve().parents[3]
    / "harbor_integration" / "coding_agent" / "image"
)


def _install() -> None:
    if not os.environ.get("ORLE_SOLVER_STATUS_PATH"):
        return
    if str(_GUARD_DIR) not in sys.path:
        sys.path.insert(0, str(_GUARD_DIR))
    import orle_solver_guard

    orle_solver_guard.install(deadline=False, telemetry=False)


try:
    _install()
except Exception:
    pass
