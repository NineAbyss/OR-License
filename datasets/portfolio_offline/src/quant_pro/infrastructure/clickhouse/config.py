
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_pro.infrastructure.clickhouse.client import ClickHouseClient
from quant_pro.infrastructure.clickhouse.snapshot_client import SnapshotClickHouseClient
from quant_pro.infrastructure.config import load_yaml_with_env

DEFAULT_CLICKHOUSE_FALLBACK_IDS: tuple[str, ...] = ()
DEFAULT_SMOKE_SQLS: tuple[str, ...] = (
    "SELECT 1",
    "EXISTS TABLE ods.ods_quant_stock_marketdata_post_1day_di",
)


@dataclass(frozen=True)
class AttemptResult:
    database_id: str
    attempt_n: int
    ok: bool
    error: str | None
    latency_ms: float


@dataclass(frozen=True)
class ClickHouseClientBundle:
    client: Any
    database_id: str
    attempts: tuple[AttemptResult, ...]
    config_path: str

    @property
    def attempted_database_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.database_id for item in self.attempts))


class ClickHouseConnectionError(RuntimeError):
    pass


def _resolve_instance_id(requested: str | None, databases: dict[str, Any], path: str) -> str:
    if requested and requested in databases:
        return requested
    for name in ("clickhouse4", "clickhouse3", "clickhouse2", "clickhouse1"):
        if name in databases:
            return name
    if databases:
        return next(iter(databases))
    raise ClickHouseConnectionError(f"No 'databases' mapping in {path}")


def build_clickhouse_client_from_config(
    config_path: str | Path,
    database_id: str | None = None,
    *,
    fallback_database_ids: tuple[str, ...] = DEFAULT_CLICKHOUSE_FALLBACK_IDS,
    smoke_sqls: tuple[str, ...] = DEFAULT_SMOKE_SQLS,
    max_attempts_per_candidate: int = 3,
    initial_backoff_s: float = 1.0,
) -> ClickHouseClientBundle:
    del fallback_database_ids
    resolved_path = str(config_path)
    cfg = load_yaml_with_env(resolved_path, strict=False)
    databases = cfg.get("databases", {})
    if not isinstance(databases, dict):
        raise ClickHouseConnectionError(f"Invalid databases mapping in {resolved_path}")
    effective_id = _resolve_instance_id(database_id, databases, resolved_path)
    mode = os.environ.get("QUANT_PRO_SNAPSHOT_MODE", "").lower()
    offline_only = os.environ.get("QUANT_PRO_OFFLINE_ONLY", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if offline_only and mode != "replay":
        raise ClickHouseConnectionError(
            "QUANT_PRO_OFFLINE_ONLY requires QUANT_PRO_SNAPSHOT_MODE=replay"
        )
    if mode == "replay":
        return ClickHouseClientBundle(
            client=SnapshotClickHouseClient(),
            database_id=effective_id,
            attempts=(AttemptResult(effective_id, 1, True, None, 0.0),),
            config_path=resolved_path,
        )

    params = databases.get(effective_id)
    if not isinstance(params, dict):
        raise ClickHouseConnectionError(f"Database {effective_id!r} missing in {resolved_path}")
    clean = {key: value for key, value in params.items() if key != "type"}
    attempts: list[AttemptResult] = []
    for attempt in range(1, max_attempts_per_candidate + 1):
        started = time.monotonic()
        try:
            live = ClickHouseClient(**clean)
            for sql in smoke_sqls:
                live.query(sql)
            client: Any = (
                SnapshotClickHouseClient(live)
                if mode in ("record", "record_missing")
                else live
            )
            elapsed = (time.monotonic() - started) * 1000.0
            attempts.append(AttemptResult(effective_id, attempt, True, None, elapsed))
            return ClickHouseClientBundle(client, effective_id, tuple(attempts), resolved_path)
        except Exception as exc:
            elapsed = (time.monotonic() - started) * 1000.0
            attempts.append(
                AttemptResult(effective_id, attempt, False, f"{type(exc).__name__}: {exc}", elapsed)
            )
            if attempt < max_attempts_per_candidate:
                time.sleep(initial_backoff_s * (2 ** (attempt - 1)))
    raise ClickHouseConnectionError(
        f"ClickHouse {effective_id} unavailable: "
        + "; ".join(item.error or "unknown" for item in attempts)
    )
