
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def bt_log(datas: Any, txt: str, dt: datetime | None = None) -> None:
    dt = dt or datas[0].datetime.date(0)
    logger.info("%s, %s", dt.isoformat(), txt)


def bt_to_log(dt: datetime, txt: str, log_path: str) -> None:
    dt_str = dt.strftime("%Y-%m-%d")
    with open(log_path, "a") as file:
        file.write(f"[{dt_str}] {txt}\n")
