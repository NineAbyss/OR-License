
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

_SCORE_SUFFIXES = {".feather", ".csv", ".parquet"}
_ORDINAL_STAGE_KEYS = ("first", "second", "third", "fourth", "fifth", "sixth")
_SCORE_HORIZON_RE = re.compile(r"^score_(\d+)$")


def infer_period_num_from_tuning_params(tuning_params_list: Any, default: int = 1) -> int:
    candidates = _iter_tuning_param_dicts(tuning_params_list)
    for params in candidates:
        mp = params.get("multiperiod") or params.get("multiperiod_params") or {}
        if not isinstance(mp, dict):
            continue
        try:
            return max(int(mp.get("period_num", default)), 1)
        except (TypeError, ValueError):
            return max(int(default), 1)
    return max(int(default), 1)


def apply_score_path_auto_default(tuning_params_list: Any, fallback_score_source: Any) -> None:
    if _score_source_is_auto(fallback_score_source):
        return

    for params in _iter_tuning_param_dicts(tuning_params_list):
        if not _score_transformation_enabled(params):
            continue
        st_params = params.get("score_transformation_params")
        if not isinstance(st_params, dict):
            st_params = {}
            params["score_transformation_params"] = st_params
        if _score_source_is_auto(st_params.get("score_path")):
            st_params["score_path"] = fallback_score_source


def apply_score_period_auto_metadata(
    tuning_params_list: Any,
    score_source: Any,
) -> list[int] | None:
    horizons = infer_score_source_horizons(score_source)
    if horizons is None:
        return None

    for params in _iter_tuning_param_dicts(tuning_params_list):
        mp = _get_or_create_multiperiod_config(params)
        configured_period_num = _configured_period_num(mp)
        if configured_period_num is not None and configured_period_num != len(horizons):
            raise ValueError(
                "wide score file horizon count does not match "
                f"multiperiod.period_num: {len(horizons)} != {configured_period_num}"
            )

        configured_frequencies = _configured_period_frequency_list(mp)
        if configured_frequencies is not None and configured_frequencies != horizons:
            raise ValueError(
                "wide score file horizons do not match multiperiod.period_frequency_list: "
                f"{horizons} != {configured_frequencies}"
            )

        mp["period_num"] = len(horizons)
        mp["period_frequency_list"] = list(horizons)

    return list(horizons)


def _iter_tuning_param_dicts(tuning_params_list: Any) -> list[dict[str, Any]]:
    candidates: list[Any]
    if isinstance(tuning_params_list, dict):
        if any(key in tuning_params_list for key in _ORDINAL_STAGE_KEYS):
            candidates = [
                tuning_params_list[key]
                for key in _ORDINAL_STAGE_KEYS
                if isinstance(tuning_params_list.get(key), dict)
            ]
        else:
            candidates = [tuning_params_list]
    elif isinstance(tuning_params_list, Sequence) and not isinstance(tuning_params_list, str):
        candidates = list(tuning_params_list)
    else:
        candidates = []
    return [params for params in candidates if isinstance(params, dict)]


def _get_or_create_multiperiod_config(params: dict[str, Any]) -> dict[str, Any]:
    mp = params.get("multiperiod")
    if isinstance(mp, dict):
        return mp
    mp = params.get("multiperiod_params")
    if isinstance(mp, dict):
        return mp
    mp = {}
    params["multiperiod"] = mp
    return mp


def _configured_period_num(mp: dict[str, Any]) -> int | None:
    if "period_num" not in mp:
        return None
    try:
        return max(int(mp["period_num"]), 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("multiperiod.period_num must be a positive integer") from exc


def _configured_period_frequency_list(mp: dict[str, Any]) -> list[int] | None:
    if "period_frequency_list" in mp:
        raw = mp["period_frequency_list"]
    elif "period_frequency" in mp:
        raw = mp["period_frequency"]
    else:
        return None

    if isinstance(raw, list | tuple):
        values = list(raw)
    else:
        values = [raw]
    try:
        result = [int(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise ValueError("multiperiod.period_frequency_list must contain integers") from exc
    if any(value <= 0 for value in result):
        raise ValueError("multiperiod.period_frequency_list values must be positive")
    return result


def _score_transformation_enabled(params: dict[str, Any]) -> bool:
    controls = params.get("controls", {})
    if isinstance(controls, dict):
        cfg = controls.get("score_transformation")
        if isinstance(cfg, dict):
            return bool(cfg.get("enabled", False))
        if cfg is not None:
            return bool(cfg)
    legacy_cfg = params.get("score_transformation")
    return bool(legacy_cfg)


def _score_source_is_auto(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "auto"}
    if isinstance(value, dict):
        if not value:
            return True
        return bool(value.get("auto", False))
    if isinstance(value, Sequence) and not isinstance(value, str):
        return len(value) == 0
    return False


def resolve_score_paths(score_source: Any) -> list[str]:
    if score_source is None:
        return []
    if isinstance(score_source, pd.DataFrame):
        return []
    if isinstance(score_source, str) and score_source == "":
        return []

    if isinstance(score_source, dict):
        values: list[Any] = []
        for key in ("paths", "files", "path", "directory", "dir"):
            if key in score_source:
                values.append(score_source[key])
        return resolve_score_paths(values)

    if isinstance(score_source, str | Path):
        path = Path(score_source).expanduser()
        if path.is_dir():
            return [
                str(item)
                for item in sorted(path.iterdir())
                if item.is_file() and item.suffix.lower() in _SCORE_SUFFIXES
            ]
        return [str(path)]

    if isinstance(score_source, Iterable):
        paths: list[str] = []
        for item in score_source:
            paths.extend(resolve_score_paths(item))
        return paths

    return [str(score_source)]


def expand_score_paths(score_source: Any, period_num: int) -> list[str]:
    paths = resolve_score_paths(score_source)
    if not paths:
        return []
    target = max(int(period_num), 1)
    while len(paths) < target:
        paths.append(paths[-1])
    return paths[:target]


def infer_score_source_horizons(score_source: Any) -> list[int] | None:
    raw_frames = _coerce_score_frames(score_source)
    if raw_frames is not None:
        if len(raw_frames) != 1:
            return None
        return infer_score_frame_horizons(raw_frames[0])

    paths = resolve_score_paths(score_source)
    if not paths or len(paths) != 1:
        return None

    columns = _read_score_columns(paths[0])
    horizons = _infer_score_horizons_from_columns(columns)
    if horizons is None:
        return None
    _validate_wide_score_columns(columns)
    return horizons


def infer_score_frame_horizons(frame: pd.DataFrame) -> list[int] | None:
    horizon_pairs = _score_horizon_columns(frame)
    if not horizon_pairs:
        return None
    return [horizon for horizon, _ in horizon_pairs]


def load_score_file(path: str | Path) -> pd.DataFrame:
    return normalize_score_frame(_read_score_table(path))


def _read_score_table(path: str | Path) -> pd.DataFrame:
    score_path = Path(path)
    suffix = score_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(score_path)
    elif suffix == ".parquet":
        return pd.read_parquet(score_path)
    return pd.read_feather(score_path)


def _read_score_columns(path: str | Path) -> list[str]:
    score_path = Path(path)
    suffix = score_path.suffix.lower()
    if suffix == ".csv":
        return [str(column) for column in pd.read_csv(score_path, nrows=0).columns]
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq

            return [str(column) for column in pq.ParquetFile(score_path).schema.names]
        except ImportError:
            return [str(column) for column in pd.read_parquet(score_path).columns]
    try:
        return [str(column) for column in pd.read_feather(score_path, columns=[]).columns]
    except TypeError:
        return [str(column) for column in pd.read_feather(score_path).columns]


def load_score_frames(score_source: Any, period_num: int | None = None) -> list[pd.DataFrame]:
    raw_frames = _coerce_score_frames(score_source)
    if raw_frames is None:
        paths = resolve_score_paths(score_source)
        if not paths:
            return []
        raw_frames = [_read_score_table(path) for path in paths]

    wide_indexes = [
        idx for idx, frame in enumerate(raw_frames) if infer_score_frame_horizons(frame) is not None
    ]
    if wide_indexes:
        if len(raw_frames) != 1 or wide_indexes != [0]:
            raise ValueError("wide score files must be supplied as a single file, not mixed")
        frames = split_wide_score_frame(raw_frames[0])
        if period_num is not None and len(frames) != max(int(period_num), 1):
            raise ValueError(
                "wide score file horizon count does not match requested period_num: "
                f"{len(frames)} != {max(int(period_num), 1)}"
            )
        return frames

    frames = [normalize_score_frame(frame) for frame in raw_frames]
    if period_num is None:
        return frames
    return expand_score_frames(frames, period_num)


def _coerce_score_frames(score_source: Any) -> list[pd.DataFrame] | None:
    if isinstance(score_source, pd.DataFrame):
        return [score_source]
    if isinstance(score_source, Sequence) and not isinstance(score_source, str | bytes):
        items = list(score_source)
        if items and all(isinstance(item, pd.DataFrame) for item in items):
            return [item for item in items if isinstance(item, pd.DataFrame)]
    return None


def split_wide_score_frame(frame: pd.DataFrame) -> list[pd.DataFrame]:
    horizon_pairs = _score_horizon_columns(frame)
    if not horizon_pairs:
        raise ValueError("wide score frame must contain at least one score_<horizon> column")
    _validate_wide_score_frame_columns(frame)

    frames: list[pd.DataFrame] = []
    for _, column in horizon_pairs:
        result = frame[["datetime", "instrument", column]].copy()
        result = result.rename(columns={column: "score"})
        frames.append(normalize_score_frame(result))
    return frames


def _validate_wide_score_frame_columns(frame: pd.DataFrame) -> None:
    _validate_wide_score_columns([str(column) for column in frame.columns])


def _validate_wide_score_columns(columns: Sequence[str]) -> None:
    required = {"datetime", "instrument"}
    column_set = set(columns)
    missing = required - column_set
    if missing:
        raise ValueError(f"wide score frame missing required columns: {sorted(missing)}")
    if "score" in column_set:
        raise ValueError("score frame cannot mix 'score' with 'score_<horizon>' columns")


def _score_horizon_columns(frame: pd.DataFrame) -> list[tuple[int, str]]:
    return _score_horizon_columns_from_names([str(column) for column in frame.columns])


def _infer_score_horizons_from_columns(columns: Sequence[str]) -> list[int] | None:
    horizon_pairs = _score_horizon_columns_from_names(columns)
    if not horizon_pairs:
        return None
    return [horizon for horizon, _ in horizon_pairs]


def _score_horizon_columns_from_names(columns: Sequence[str]) -> list[tuple[int, str]]:
    seen: dict[int, str] = {}
    for column in columns:
        match = _SCORE_HORIZON_RE.match(column)
        if match is None:
            continue
        horizon = int(match.group(1))
        if horizon <= 0:
            raise ValueError(f"score horizon column must be positive: {column}")
        if horizon in seen:
            raise ValueError(f"duplicate score horizon columns: {seen[horizon]!r} and {column!r}")
        seen[horizon] = str(column)
    return sorted((horizon, column) for horizon, column in seen.items())


def normalize_score_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"instrument", "score"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"score frame missing required columns: {sorted(missing)}")
    result = frame.copy()
    result["instrument"] = result["instrument"].astype(str)
    result["score"] = pd.to_numeric(result["score"], errors="coerce")
    return result


def expand_score_frames(frames: Sequence[pd.DataFrame], period_num: int) -> list[pd.DataFrame]:
    if not frames:
        return []
    target = max(int(period_num), 1)
    expanded: list[pd.DataFrame] = []
    for idx in range(target):
        source = frames[min(idx, len(frames) - 1)]
        expanded.append(normalize_score_frame(source).copy())
    return expanded


def score_payload_first_frame(score_payload: Any) -> pd.DataFrame:
    if isinstance(score_payload, pd.DataFrame):
        return score_payload
    if isinstance(score_payload, Sequence) and score_payload:
        first = score_payload[0]
        if isinstance(first, pd.DataFrame):
            return first
    return pd.DataFrame()


def score_payload_is_empty(score_payload: Any) -> bool:
    frame = score_payload_first_frame(score_payload)
    return bool(frame.empty)


def score_frames_to_pivots(
    frames: Sequence[pd.DataFrame],
    *,
    start_time: Any = None,
    end_time: Any = None,
) -> list[pd.DataFrame]:
    pivots: list[pd.DataFrame] = []
    for frame in frames:
        score_frame = normalize_score_frame(frame)
        if "datetime" not in score_frame.columns:
            raise ValueError("score frame missing required column: 'datetime'")
        score_frame = score_frame.copy()
        score_frame["datetime"] = pd.to_datetime(score_frame["datetime"])
        if start_time or end_time:
            start_mask = (
                score_frame["datetime"] >= pd.to_datetime(start_time) if start_time else True
            )
            end_mask = score_frame["datetime"] <= pd.to_datetime(end_time) if end_time else True
            score_frame = score_frame[start_mask & end_mask]
        pivot = score_frame.pivot_table(index="datetime", columns="instrument", values="score")
        pivot.index = pd.to_datetime(pivot.index).normalize()
        pivots.append(pivot.sort_index())
    return pivots


def load_score_pivots(
    score_source: Any,
    *,
    period_num: int,
    start_time: Any = None,
    end_time: Any = None,
) -> list[pd.DataFrame]:
    frames = load_score_frames(score_source, period_num=period_num)
    return score_frames_to_pivots(frames, start_time=start_time, end_time=end_time)


def expand_weight_pivots(weight: Any, period_num: int) -> list[pd.DataFrame]:
    if isinstance(weight, pd.DataFrame):
        frames = [weight]
    elif isinstance(weight, Sequence) and not isinstance(weight, str):
        frames = [frame for frame in weight if isinstance(frame, pd.DataFrame)]
    else:
        frames = []
    if not frames:
        return []
    target = max(int(period_num), 1)
    result: list[pd.DataFrame] = []
    for idx in range(target):
        frame = frames[min(idx, len(frames) - 1)].copy()
        frame.index = pd.to_datetime(frame.index).normalize()
        result.append(frame.sort_index())
    return result


def union_pivot_instruments(pivots: Sequence[pd.DataFrame]) -> list[str]:
    instruments: list[str] = []
    seen: set[str] = set()
    for pivot in pivots:
        for instrument in pivot.columns:
            inst = str(instrument)
            if inst not in seen:
                seen.add(inst)
                instruments.append(inst)
    return instruments


def pivot_date_bounds(pivots: Sequence[pd.DataFrame]) -> tuple[pd.Timestamp, pd.Timestamp]:
    non_empty = [pivot for pivot in pivots if not pivot.empty]
    if not non_empty:
        return pd.Timestamp("NaT"), pd.Timestamp("NaT")
    return (
        min(pd.Timestamp(pivot.index.min()) for pivot in non_empty),
        max(pd.Timestamp(pivot.index.max()) for pivot in non_empty),
    )


def infer_next_trade_date_from_pivots(
    pivots: Sequence[pd.DataFrame],
    end_time: str | None,
) -> str | None:
    if end_time is None:
        return None
    end_ts = pd.to_datetime(end_time).normalize()
    future_dates = [
        pd.Timestamp(value)
        for pivot in pivots
        for value in pivot.index
        if pd.Timestamp(value) > end_ts
    ]
    if not future_dates:
        return None
    return str(min(future_dates).strftime("%Y-%m-%d"))
