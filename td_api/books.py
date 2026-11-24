"""每个用户一份 SQLite 账本。身份在 Redis，成交记录仍按用户隔开。"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

from td_api.db import Database
from td_api.service import Service


class Books:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._services: dict[str, Service] = {}
        self._lock = threading.Lock()

    def service_for(self, user_id: str) -> Service:
        with self._lock:
            service = self._services.get(user_id)
            if service is None:
                database = Database(str(self._path(user_id)))
                database.init()
                service = Service(database)
                self._services[user_id] = service
            return service

    def _path(self, user_id: str) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / f"{user_id}.db"
        if path.exists():
            return path
        legacy = Path(os.environ.get("TD_LEGACY", "data/td.db"))
        if user_id == "1" and legacy.is_file() and legacy.resolve() != path.resolve():
            shutil.copy2(legacy, path)
        return path
