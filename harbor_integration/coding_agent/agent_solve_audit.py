
from __future__ import annotations

import json
from pathlib import Path
import re


_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_TERMINAL = frozenset((
    "completed", "timeout", "disconnected", "shared_process_killed",
    "release_failed",
))


def summarize_session(path: Path, offset: int, session: str) -> dict[str, int]:
    if not isinstance(session, str) or _SESSION.fullmatch(session) is None:
        raise ValueError("invalid solver audit session")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("invalid solver audit offset")
    path = Path(path)
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            if offset > size:
                raise ValueError("solver audit was truncated")
            stream.seek(offset)
            raw = stream.read()
    except FileNotFoundError:
        if offset:
            raise ValueError("solver audit disappeared") from None
        raw = b""
    if raw and not raw.endswith(b"\n"):
        raise ValueError("incomplete solver audit row")

    calls: dict[str, str | None] = {}
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("malformed solver audit row") from exc
        if not isinstance(row, dict):
            raise ValueError("malformed solver audit row")
        if row.get("session") != session:
            continue
        event = row.get("event")
        if event != "start" and event not in _TERMINAL:
            continue
        call_id = row.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("solver audit call has no ID")
        if event == "start":
            if call_id in calls:
                raise ValueError("duplicate solver audit start")
            calls[call_id] = None
        elif call_id not in calls or calls[call_id] is not None:
            raise ValueError("unmatched solver audit completion")
        else:
            calls[call_id] = event

    if any(outcome is None for outcome in calls.values()):
        raise ValueError("unfinished solver audit call")
    completed = sum(outcome == "completed" for outcome in calls.values())
    return {
        "starts": len(calls),
        "completed": completed,
        "failed": len(calls) - completed,
    }
