
from __future__ import annotations

from pathlib import Path

import yaml


def _rebind_mount(value: str, socket_dir: Path) -> str:
    parts = value.split(":")
    if len(parts) >= 2 and parts[1] == "/orle-bridge":
        parts[0] = str(socket_dir)
    return ":".join(parts)


def rewrite_formal_compose(
    source: Path, socket_dir: Path, destination: Path, *, submission: Path | None = None
) -> Path:
    document = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
    try:
        service = document["services"]["main"]
        volumes = service["volumes"]
    except (KeyError, TypeError) as exc:
        raise ValueError("as-of task compose file has no main service volumes") from exc
    if not isinstance(volumes, list):
        raise ValueError("as-of task compose volumes must be a list")
    rebound = [
        _rebind_mount(value, Path(socket_dir)) if isinstance(value, str) else value
        for value in volumes
    ]
    if not any(
        isinstance(value, str) and value.split(":")[1:2] == ["/orle-bridge"]
        for value in rebound
    ):
        raise ValueError("as-of task compose has no /orle-bridge mount")
    if submission is not None:
        rebound.append(f"{Path(submission).resolve()}:/orle-formal-input/candidate.json:ro")
    service["volumes"] = rebound
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return destination
