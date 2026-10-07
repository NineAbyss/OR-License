
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_SAVE_DIR: str | None = None


def _resolve_default_save_dir() -> str:
    global _DEFAULT_SAVE_DIR
    if _DEFAULT_SAVE_DIR is None:
        home = os.path.abspath(os.path.expanduser("~"))
        base = tempfile.gettempdir()
        if os.path.commonpath([os.path.abspath(base), home]) == home:
            base = "/tmp"
        _DEFAULT_SAVE_DIR = tempfile.mkdtemp(
            prefix=f"portfolio_backtest_todo_{os.getpid()}_", dir=base
        )
    return _DEFAULT_SAVE_DIR


class TodoRecorder:

    name: str = "default"

    def _get_default_save_dir(self) -> str:
        return _resolve_default_save_dir()

    def set_save_dir(self, savedir: str) -> None:
        self.savedir = savedir
        if not os.path.exists(self.savedir):
            try:
                os.makedirs(self.savedir, exist_ok=True)
            except (OSError, PermissionError) as e:
                logger.warning("无法创建目录 %s: %s", self.savedir, e)
                self.savedir = self._get_default_save_dir()
                os.makedirs(self.savedir, exist_ok=True)

    def __init__(
        self,
        name: str,
        record: bool,
        replay: bool,
        skip: bool,
        savedir: str | None = None,
    ) -> None:
        if savedir is None:
            self.savedir = self._get_default_save_dir()
        else:
            self.set_save_dir(savedir)
        self.is_need_record = record
        self.is_need_replay = replay
        self.is_need_skip = skip
        self.name = name
        self.max_date_record_path = os.path.join(self.savedir, f"{name}_max_date")

    def _get_file_path(self, dt: datetime) -> str:
        date_str = dt.strftime("%Y-%m-%d")
        return os.path.join(self.savedir, f"{self.name}_{date_str}.csv")

    def _get_max_date(self) -> datetime | None:
        if not os.path.exists(self.max_date_record_path):
            return None
        try:
            with open(self.max_date_record_path) as f:
                max_date_str = f.read().strip()
            return pd.to_datetime(max_date_str)
        except (OSError, PermissionError, ValueError) as e:
            logger.warning("无法读取最大日期记录: %s", e)
            return None

    def _update_max_date(self, dt: datetime) -> None:
        date_str = dt.strftime("%Y-%m-%d")
        max_date = self._get_max_date()
        if max_date is None or dt > max_date:
            try:
                with open(self.max_date_record_path, "w") as f:
                    f.write(date_str)
            except (OSError, PermissionError) as e:
                logger.warning("无法更新最大日期记录: %s", e)

    def record(self, todo: pd.DataFrame, dt: datetime) -> None:
        if not self.is_need_record or todo is None:
            return
        savepath = self._get_file_path(dt)
        try:
            todo.to_csv(savepath)
            self._update_max_date(dt)
        except (OSError, PermissionError) as e:
            logger.warning("无法记录数据到 %s: %s", savepath, e)

    def replay(self, dt: datetime) -> tuple[pd.DataFrame | None, bool]:
        if not self.is_need_replay:
            return None, False
        savepath = self._get_file_path(dt)
        if not os.path.exists(savepath):
            max_date = self._get_max_date()
            if max_date is None or dt < max_date:
                return None, self.is_need_skip
            else:
                return None, False
        try:
            todo = pd.read_csv(savepath)
            return todo, self.is_need_skip
        except (OSError, PermissionError, pd.errors.EmptyDataError) as e:
            logger.warning("无法读取数据文件 %s: %s", savepath, e)
            return None, False


__all__ = ["TodoRecorder"]
