from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from typing import Any, Callable


class SnapshotStore:

    def __init__(self, namespace: str) -> None:
        root = os.environ.get("QUANT_PRO_SNAPSHOT_DIR")
        self.enabled = bool(root)
        self.mode = "replay"
        self.root = Path(root) / namespace if root else Path(__file__).resolve().parents[3] / "data/snapshot" / namespace
        index_path = self.root / "index.json"
        self._calls = {}
        if index_path.is_file():
            for identifier, record in json.loads(index_path.read_text(encoding="utf-8")).items():
                signature = (record["name"], record["args"], record["kwargs"])
                if signature in self._calls:
                    raise ValueError(f"duplicate replay call in {index_path}")
                self._calls[signature] = identifier

    def call(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any], live_call: Callable[[], Any]) -> Any:
        signature = (name, repr(args), repr(kwargs))
        identifier = self._calls.get(signature)
        if identifier is None:
            raise FileNotFoundError(f"offline snapshot missing for {name}{args!r}{kwargs!r}")
        path = self.root / f"{identifier}.pkl"
        with path.open("rb") as handle:
            return pickle.load(handle)
