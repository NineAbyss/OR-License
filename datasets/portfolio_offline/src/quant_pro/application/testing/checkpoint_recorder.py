
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _safe_scalar(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (int, float, bool, str)):
        return v
    if isinstance(v, np.ndarray):
        if v.ndim == 0:
            return v.item()
        return f"ndarray(shape={v.shape})"
    return str(v)


class CheckpointRecorder:

    _instance: ClassVar[CheckpointRecorder | None] = None

    def __init__(self, output_dir: str, path_name: str) -> None:
        self._output_dir = Path(output_dir) / path_name
        self._path_name = path_name
        self._output_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def activate(cls, output_dir: str, path_name: str) -> CheckpointRecorder:
        os.environ["CHECKPOINT_DEBUG"] = "1"
        cls._instance = cls(output_dir, path_name)
        logger.info("CheckpointRecorder activated: %s/%s", output_dir, path_name)
        return cls._instance

    @classmethod
    def deactivate(cls) -> None:
        cls._instance = None

    @classmethod
    def get(cls) -> CheckpointRecorder | None:
        if os.environ.get("CHECKPOINT_DEBUG") != "1":
            return None
        return cls._instance

    def record(self, date: str, stage: str, **variables: Any) -> None:
        stage_dir = self._output_dir / date / stage
        stage_dir.mkdir(parents=True, exist_ok=True)

        meta: dict[str, Any] = {}
        arrays: dict[str, np.ndarray] = {}

        for name, value in variables.items():
            try:
                self._classify(name, value, meta, arrays, stage_dir)
            except Exception:
                logger.warning(
                    "checkpoint: failed to serialize %s at %s/%s", name, date, stage, exc_info=True
                )
                meta[name] = {"type": "ERROR", "value": str(type(value).__name__)}

        if arrays:
            np.savez_compressed(stage_dir / "arrays.npz", **arrays)

        with open(stage_dir / "meta.json", "w") as f:
            json.dump(meta, f, indent=2, default=str, ensure_ascii=False)

        n_arrays = len(arrays)
        n_scalars = sum(
            1 for v in meta.values() if isinstance(v, dict) and v.get("type") == "scalar"
        )
        logger.debug(
            "checkpoint: %s/%s/%s — %d arrays, %d scalars, %d other",
            self._path_name,
            date,
            stage,
            n_arrays,
            n_scalars,
            len(meta) - n_scalars,
        )

    def _classify(
        self,
        name: str,
        value: Any,
        meta: dict[str, Any],
        arrays: dict[str, np.ndarray],
        stage_dir: Path,
    ) -> None:
        if isinstance(value, np.ndarray):
            arrays[name] = value
            meta[name] = {
                "type": "ndarray",
                "shape": list(value.shape),
                "dtype": str(value.dtype),
                "min": _safe_scalar(value.min()) if value.size > 0 else None,
                "max": _safe_scalar(value.max()) if value.size > 0 else None,
            }
        elif isinstance(value, pd.DataFrame):
            raw = value.values
            if raw.dtype.kind in ("f", "i", "u"):
                arrays[f"{name}__values"] = raw.astype(float)
            meta[name] = {
                "type": "DataFrame",
                "shape": list(value.shape),
                "columns": [str(c) for c in value.columns],
                "index_sample": [str(i) for i in value.index[:10]],
            }
            value.to_pickle(stage_dir / f"{name}.pkl")
        elif isinstance(value, pd.Series):
            arr = value.values
            if arr.dtype.kind in ("f", "i", "u"):
                arrays[f"{name}__values"] = arr.astype(float)
            meta[name] = {
                "type": "Series",
                "shape": [len(value)],
                "dtype": str(arr.dtype),
                "index_sample": [str(i) for i in value.index[:10]],
            }
            value.to_pickle(stage_dir / f"{name}.pkl")
        elif isinstance(value, (int, float, bool)):
            meta[name] = {"type": "scalar", "value": _safe_scalar(value)}
        elif isinstance(value, str):
            meta[name] = {"type": "scalar", "value": value}
        elif isinstance(value, (list, tuple)):
            serialized = [_safe_scalar(v) for v in value[:500]]
            meta[name] = {"type": "list", "length": len(value), "value": serialized}
        elif isinstance(value, (set, frozenset)):
            serialized = sorted(str(v) for v in value)[:500]
            meta[name] = {"type": "set", "length": len(value), "value": serialized}
        elif isinstance(value, dict):
            serialized_dict = {str(k): _safe_scalar(v) for k, v in list(value.items())[:500]}
            meta[name] = {"type": "dict", "length": len(value), "value": serialized_dict}
        else:
            meta[name] = {"type": str(type(value).__name__), "value": "NOT_SERIALIZABLE"}
