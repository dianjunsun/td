"""把每人的 SQLite 账本和 Redis 里的登录数据备份到阿里云 OSS，并按同一份包恢复。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import tarfile
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("td.backup")

BACKUP_VERSION = 1
CN = ZoneInfo("Asia/Shanghai")
DEFAULT_PREFIX = "td-backups/"
DEFAULT_KEEP = 14
DEFAULT_INTERVAL = 24 * 3600
MAX_MEMBER = 512 * 1024 * 1024


class BackupError(Exception):
    pass


class MemoryStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise BackupError("找不到这份备份") from exc

    def list(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix) and key.endswith(".tar.gz"))

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class OssStore:
    def __init__(self, endpoint: str, bucket_name: str, key_id: str, secret: str):
        try:
            import oss2
        except ImportError as exc:
            raise BackupError("没有安装 oss2，请在虚拟环境里重新 pip install -e .") from exc
        auth = oss2.Auth(key_id, secret)
        self.bucket = oss2.Bucket(auth, endpoint, bucket_name)

    def put(self, key: str, data: bytes) -> None:
        self.bucket.put_object(key, data)

    def get(self, key: str) -> bytes:
        result = self.bucket.get_object(key)
        return result.read()

    def list(self, prefix: str) -> list[str]:
        import oss2

        keys = []
        for item in oss2.ObjectIterator(self.bucket, prefix=prefix):
            if item.key.endswith(".tar.gz"):
                keys.append(item.key)
        return sorted(keys)

    def delete(self, key: str) -> None:
        self.bucket.delete_object(key)


def oss_settings() -> dict[str, str]:
    values = {
        "endpoint": os.environ.get("TD_OSS_ENDPOINT", "").strip(),
        "bucket": os.environ.get("TD_OSS_BUCKET", "").strip(),
        "key_id": os.environ.get("TD_OSS_ACCESS_KEY_ID", "").strip(),
        "secret": os.environ.get("TD_OSS_ACCESS_KEY_SECRET", "").strip(),
        "prefix": _prefix(os.environ.get("TD_OSS_PREFIX", DEFAULT_PREFIX)),
    }
    missing = [name for name in ("endpoint", "bucket", "key_id", "secret") if not values[name]]
    if missing:
        labels = {
            "endpoint": "TD_OSS_ENDPOINT",
            "bucket": "TD_OSS_BUCKET",
            "key_id": "TD_OSS_ACCESS_KEY_ID",
            "secret": "TD_OSS_ACCESS_KEY_SECRET",
        }
        raise BackupError("OSS 还没配全，缺少 " + "、".join(labels[name] for name in missing))
    return values


def configured_interval() -> int:
    raw = os.environ.get("TD_BACKUP_INTERVAL")
    if raw is not None and raw.strip() != "":
        try:
            return max(0, int(raw))
        except ValueError as exc:
            raise BackupError("TD_BACKUP_INTERVAL 要是秒数") from exc
    try:
        oss_settings()
    except BackupError:
        return 0
    return DEFAULT_INTERVAL


def backup_keep() -> int:
    raw = os.environ.get("TD_BACKUP_KEEP", str(DEFAULT_KEEP))
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise BackupError("TD_BACKUP_KEEP 要是保留份数") from exc


def open_store():
    settings = oss_settings()
    return OssStore(settings["endpoint"], settings["bucket"], settings["key_id"], settings["secret"]), settings["prefix"]


def data_dir() -> Path:
    return Path(os.environ.get("TD_DATA_DIR", "data/users"))


def legacy_path() -> Path:
    return Path(os.environ.get("TD_LEGACY", "data/td.db"))


def connect_redis():
    from td_api.auth import AuthStore

    return AuthStore.connect(os.environ.get("TD_REDIS", "redis://127.0.0.1:6379/0")).redis


def export_redis(client) -> list[dict]:
    rows = []
    for key in client.scan_iter("td:*"):
        kind = client.type(key)
        ttl = int(client.ttl(key))
        if kind == "string":
            value = client.get(key)
        elif kind == "hash":
            value = client.hgetall(key)
        else:
            continue
        rows.append({"key": key, "type": kind, "value": value, "ttl": ttl})
    rows.sort(key=lambda item: item["key"])
    return rows


def import_redis(client, rows: list[dict]) -> int:
    for key in list(client.scan_iter("td:*")):
        client.delete(key)
    restored = 0
    for row in rows:
        key = row["key"]
        if not isinstance(key, str) or not key.startswith("td:") or ".." in key:
            raise BackupError("备份里的 Redis 键不合法")
        ttl = int(row.get("ttl") or -1)
        if row["type"] == "string":
            client.set(key, row["value"])
        elif row["type"] == "hash":
            client.delete(key)
            if row["value"]:
                client.hset(key, mapping=row["value"])
        else:
            raise BackupError(f"不认识的 Redis 类型 {row['type']}")
        if ttl > 0:
            client.expire(key, ttl)
        restored += 1
    return restored


def snapshot_sqlite(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_archive(root: Path, books: Path, redis_client, legacy: Path | None) -> dict:
    users = root / "users"
    users.mkdir(parents=True)
    files = []
    for path in sorted(books.glob("*.db")):
        if not path.is_file():
            continue
        target = users / path.name
        snapshot_sqlite(path, target)
        files.append({"path": f"users/{path.name}", "sha256": _sha256(target)})
    if legacy is not None and legacy.is_file():
        target = root / "legacy" / "td.db"
        snapshot_sqlite(legacy, target)
        files.append({"path": "legacy/td.db", "sha256": _sha256(target)})
    redis_rows = export_redis(redis_client)
    (root / "redis.json").write_text(json.dumps(redis_rows, ensure_ascii=False), encoding="utf-8")
    created_at = datetime.now(CN).isoformat(timespec="seconds")
    manifest = {
        "version": BACKUP_VERSION,
        "created_at": created_at,
        "files": files,
        "redis_keys": len(redis_rows),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest


def pack(root: Path, dest: Path) -> None:
    with tarfile.open(dest, "w:gz") as tar:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(root).as_posix())


def backup_to(store, books: Path, redis_client, legacy: Path | None, prefix: str, keep: int) -> dict:
    prefix = _prefix(prefix)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "root"
        root.mkdir()
        manifest = build_archive(root, books, redis_client, legacy)
        stamp = datetime.now(CN).strftime("%Y%m%dT%H%M%S%f%z")
        archive = Path(tmp) / f"{stamp}.tar.gz"
        pack(root, archive)
        key = f"{prefix}{stamp}.tar.gz"
        store.put(key, archive.read_bytes())
    removed = prune(store, prefix, keep)
    return {
        "key": key,
        "created_at": manifest["created_at"],
        "files": len(manifest["files"]),
        "redis_keys": manifest["redis_keys"],
        "removed": removed,
    }


def prune(store, prefix: str, keep: int) -> list[str]:
    keys = store.list(_prefix(prefix))
    if keep <= 0 or len(keys) <= keep:
        return []
    stale = keys[: len(keys) - keep]
    for key in stale:
        store.delete(key)
    return stale


def backup_from_env() -> dict:
    store, prefix = open_store()
    return backup_to(store, data_dir(), connect_redis(), legacy_path(), prefix, backup_keep())


def _member_bytes(tar: tarfile.TarFile, name: str) -> bytes:
    try:
        member = tar.getmember(name)
    except KeyError as exc:
        raise BackupError(f"备份包缺少 {name}") from exc
    if not member.isfile() or member.size > MAX_MEMBER:
        raise BackupError(f"备份包里的 {name} 不能读取")
    handle = tar.extractfile(member)
    if handle is None:
        raise BackupError(f"备份包里的 {name} 不能读取")
    return handle.read()


def load_archive(blob: bytes) -> tuple[dict, dict[str, bytes], list[dict]]:
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
        tmp.write(blob)
        tmp.flush()
        with tarfile.open(tmp.name, "r:gz") as tar:
            names = [item.name for item in tar.getmembers() if item.isfile()]
            for name in names:
                if not _allowed_name(name):
                    raise BackupError(f"备份包里有不认识的文件 {name}")
            manifest = json.loads(_member_bytes(tar, "manifest.json").decode("utf-8"))
            if manifest.get("version") != BACKUP_VERSION:
                raise BackupError("这份备份的版本不能在这里恢复")
            files = {}
            for item in manifest.get("files") or []:
                path = item["path"]
                if not _allowed_name(path):
                    raise BackupError(f"备份清单里的路径不合法 {path}")
                body = _member_bytes(tar, path)
                if hashlib.sha256(body).hexdigest() != item["sha256"]:
                    raise BackupError(f"{path} 的校验和和清单不一致")
                files[path] = body
            redis_rows = json.loads(_member_bytes(tar, "redis.json").decode("utf-8"))
    return manifest, files, redis_rows


def restore_archive(blob: bytes, books: Path, redis_client, legacy: Path, force: bool) -> dict:
    manifest, files, redis_rows = load_archive(blob)
    existing = sorted(path.name for path in books.glob("*.db")) if books.exists() else []
    legacy_exists = legacy.is_file()
    if (existing or legacy_exists) and not force:
        raise BackupError("目标已经有账本。确认覆盖请加 --force，原文件会先挪到 .before-restore")
    saved = []
    if force:
        stamp = datetime.now(CN).strftime("%Y%m%dT%H%M%S")
        hold = books / ".before-restore" / stamp
        for name in existing:
            hold.mkdir(parents=True, exist_ok=True)
            source = books / name
            target = hold / name
            source.replace(target)
            saved.append(str(target))
        if legacy_exists and any(path == "legacy/td.db" for path in files):
            hold.mkdir(parents=True, exist_ok=True)
            target = hold / "td.db"
            legacy.replace(target)
            saved.append(str(target))
    books.mkdir(parents=True, exist_ok=True)
    written = []
    for path, body in files.items():
        if path.startswith("users/"):
            dest = books / Path(path).name
        elif path == "legacy/td.db":
            dest = legacy
            dest.parent.mkdir(parents=True, exist_ok=True)
        else:
            raise BackupError(f"备份清单里的路径不合法 {path}")
        temporary = dest.with_suffix(dest.suffix + ".restore")
        temporary.write_bytes(body)
        temporary.replace(dest)
        written.append(str(dest))
    restored_keys = import_redis(redis_client, redis_rows)
    return {
        "created_at": manifest.get("created_at"),
        "files": written,
        "redis_keys": restored_keys,
        "saved": saved,
    }


def restore_key(store, key: str, books: Path, redis_client, legacy: Path, force: bool) -> dict:
    result = restore_archive(store.get(key), books, redis_client, legacy, force)
    result["key"] = key
    return result


def restore_from_env(key: str = "", file: str = "", latest: bool = False, force: bool = False) -> dict:
    if file:
        blob = Path(file).read_bytes()
        return restore_archive(blob, data_dir(), connect_redis(), legacy_path(), force)
    store, prefix = open_store()
    if latest or not key:
        keys = store.list(prefix)
        if not keys:
            raise BackupError("OSS 上还没有备份")
        key = keys[-1]
    return restore_key(store, key, data_dir(), connect_redis(), legacy_path(), force)


def list_from_env() -> list[str]:
    store, prefix = open_store()
    return store.list(prefix)


def serve_forever(stop: threading.Event, status: dict) -> None:
    try:
        interval = configured_interval()
    except BackupError as exc:
        status["enabled"] = False
        status["last_error"] = str(exc)
        log.warning("%s", exc)
        return
    status["enabled"] = interval > 0
    status["interval"] = interval
    if interval <= 0:
        return
    while not stop.is_set():
        try:
            result = backup_from_env()
            status["last_at"] = result["created_at"]
            status["last_key"] = result["key"]
            status["last_error"] = ""
            log.info("OSS 备份完成 %s", result["key"])
        except Exception as exc:
            status["last_error"] = str(exc)
            log.exception("OSS 备份失败")
        if stop.wait(interval):
            return


def _prefix(value: str) -> str:
    text = (value or DEFAULT_PREFIX).strip().strip("/")
    return f"{text}/" if text else DEFAULT_PREFIX


def _allowed_name(name: str) -> bool:
    if name in ("manifest.json", "redis.json", "legacy/td.db"):
        return True
    if not name.startswith("users/") or not name.endswith(".db"):
        return False
    rest = name[len("users/"):]
    return bool(rest) and "/" not in rest and ".." not in rest and rest != ".db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="账本和登录数据的 OSS 备份、迁移与恢复")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="立刻备份到 OSS")
    commands.add_parser("list", help="列出 OSS 上的备份")
    restore = commands.add_parser("restore", help="从 OSS 或本地包恢复。迁到新机器时用这一步")
    restore.add_argument("key", nargs="?", default="")
    restore.add_argument("--latest", action="store_true", help="使用最新一份")
    restore.add_argument("--file", default="", help="从本地 tar.gz 恢复，不访问 OSS")
    restore.add_argument("--force", action="store_true", help="覆盖已有账本，原文件先挪到 .before-restore")
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            result = backup_from_env()
            print(f"已备份 {result['key']}，账本 {result['files']} 个，Redis 键 {result['redis_keys']} 个")
            if result["removed"]:
                print(f"已删掉更早的 {len(result['removed'])} 份")
        elif args.command == "list":
            keys = list_from_env()
            if not keys:
                print("还没有备份")
            for key in keys:
                print(key)
        else:
            result = restore_from_env(args.key, args.file, args.latest, args.force)
            print(
                f"已恢复 {len(result['files'])} 个账本文件、{result['redis_keys']} 个 Redis 键。"
                "请先停掉服务再恢复；如果服务还在跑，现在重启一次。"
            )
            if result["saved"]:
                print("覆盖前的文件在 .before-restore")
    except BackupError as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
