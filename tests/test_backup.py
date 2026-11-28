import json
import sqlite3
from pathlib import Path

import fakeredis
import pytest

from td_api.backup import (
    BackupError,
    MemoryStore,
    backup_to,
    configured_interval,
    load_archive,
    restore_archive,
)


def _book(path: Path, cash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE account (cash TEXT)")
    conn.execute("INSERT INTO account (cash) VALUES (?)", (cash,))
    conn.commit()
    conn.close()


def _redis():
    client = fakeredis.FakeRedis(decode_responses=True)
    client.set("td:user:seq", "2")
    client.hset("td:user:1", mapping={"username": "desk", "password": "hash"})
    client.set("td:session:tok", "1", ex=500)
    client.set("other", "leave-me")
    return client


def test_backup_round_trip_moves_books_and_login(tmp_path):
    source_books = tmp_path / "users"
    _book(source_books / "1.db", "991700")
    legacy = tmp_path / "td.db"
    _book(legacy, "legacy")
    source_redis = _redis()
    store = MemoryStore()
    first = backup_to(store, source_books, source_redis, legacy, "td-backups", keep=14)
    assert first["files"] == 2
    assert first["redis_keys"] == 3
    assert store.list("td-backups/") == [first["key"]]

    target_books = tmp_path / "moved"
    target_legacy = tmp_path / "moved-legacy.db"
    target_redis = fakeredis.FakeRedis(decode_responses=True)
    target_redis.set("td:user:seq", "9")
    target_redis.set("other", "stay")
    result = restore_archive(store.get(first["key"]), target_books, target_redis, target_legacy, force=False)
    assert result["redis_keys"] == 3
    conn = sqlite3.connect(target_books / "1.db")
    assert conn.execute("SELECT cash FROM account").fetchone()[0] == "991700"
    conn.close()
    assert sqlite3.connect(target_legacy).execute("SELECT cash FROM account").fetchone()[0] == "legacy"
    assert target_redis.get("td:user:seq") == "2"
    assert target_redis.hget("td:user:1", "username") == "desk"
    assert target_redis.get("td:session:tok") == "1"
    assert target_redis.ttl("td:session:tok") > 0
    assert target_redis.get("other") == "stay"


def test_restore_refuses_to_cover_an_existing_book_until_forced(tmp_path):
    books = tmp_path / "users"
    _book(books / "1.db", "old")
    source = _redis()
    store = MemoryStore()
    saved = backup_to(store, books, source, None, "td-backups", keep=14)
    occupied = tmp_path / "occupied"
    _book(occupied / "1.db", "keep")
    with pytest.raises(BackupError, match="--force"):
        restore_archive(store.get(saved["key"]), occupied, fakeredis.FakeRedis(decode_responses=True), tmp_path / "nope.db", force=False)
    assert sqlite3.connect(occupied / "1.db").execute("SELECT cash FROM account").fetchone()[0] == "keep"


def test_force_restore_keeps_the_previous_file(tmp_path):
    books = tmp_path / "users"
    _book(books / "1.db", "new")
    store = MemoryStore()
    saved = backup_to(store, books, _redis(), None, "td-backups", keep=14)
    conn = sqlite3.connect(books / "1.db")
    conn.execute("UPDATE account SET cash = 'old'")
    conn.commit()
    conn.close()
    result = restore_archive(store.get(saved["key"]), books, fakeredis.FakeRedis(decode_responses=True), tmp_path / "nope.db", force=True)
    assert result["saved"]
    assert sqlite3.connect(books / "1.db").execute("SELECT cash FROM account").fetchone()[0] == "new"
    previous = sqlite3.connect(result["saved"][0])
    assert previous.execute("SELECT cash FROM account").fetchone()[0] == "old"


def test_old_backups_are_deleted_after_the_keep_limit(tmp_path):
    books = tmp_path / "users"
    _book(books / "1.db", "1")
    store = MemoryStore()
    keys = [backup_to(store, books, _redis(), None, "td-backups", keep=2)["key"] for _ in range(3)]
    assert store.list("td-backups/") == keys[-2:]


def test_archive_rejects_a_path_outside_the_package(tmp_path):
    import io
    import tarfile

    blob = io.BytesIO()
    with tarfile.open(fileobj=blob, mode="w:gz") as tar:
        payload = json.dumps({"version": 1, "files": [], "redis_keys": 0}).encode()
        info = tarfile.TarInfo("users/../../secret.db")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(BackupError, match="不认识的文件"):
        load_archive(blob.getvalue())


def test_interval_stays_off_until_oss_is_configured(monkeypatch):
    monkeypatch.delenv("TD_BACKUP_INTERVAL", raising=False)
    monkeypatch.delenv("TD_OSS_ENDPOINT", raising=False)
    assert configured_interval() == 0
    monkeypatch.setenv("TD_BACKUP_INTERVAL", "0")
    monkeypatch.setenv("TD_OSS_ENDPOINT", "https://oss-cn-hangzhou.aliyuncs.com")
    monkeypatch.setenv("TD_OSS_BUCKET", "td")
    monkeypatch.setenv("TD_OSS_ACCESS_KEY_ID", "id")
    monkeypatch.setenv("TD_OSS_ACCESS_KEY_SECRET", "secret")
    assert configured_interval() == 0
    monkeypatch.setenv("TD_BACKUP_INTERVAL", "3600")
    assert configured_interval() == 3600
    monkeypatch.delenv("TD_BACKUP_INTERVAL")
    assert configured_interval() == 24 * 3600
