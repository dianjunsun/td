"""用户和会话。身份放在 Redis，进程重启后仍然在。"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

SESSION_TTL = 30 * 24 * 3600
PBKDF2_ROUNDS = 200_000


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        self.message = message
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class User:
    id: str
    username: str
    admin: bool = False


class AuthStore:
    def __init__(self, client):
        self.redis = client

    @classmethod
    def connect(cls, url: str | None = None) -> AuthStore:
        target = url if url is not None else os.environ.get("TD_REDIS", "redis://127.0.0.1:6379/0")
        if target in ("memory", "memory://"):
            import fakeredis

            client = fakeredis.FakeRedis(decode_responses=True)
            return cls(client)
        import redis

        client = redis.Redis.from_url(target, decode_responses=True)
        try:
            client.ping()
        except redis.RedisError as exc:
            raise RuntimeError(f"连不上 Redis（{target}）。请先启动一个开启 AOF 的 Redis。") from exc
        return cls(client)

    def ping(self) -> None:
        self.redis.ping()

    def register(self, username: str, password: str) -> tuple[User, str]:
        name = _username(username)
        _password(password)
        user_id = str(self.redis.incr("td:user:seq"))
        if not self.redis.set(f"td:user:name:{name.casefold()}", user_id, nx=True):
            raise AuthError("用户名已存在", 400)
        self.redis.hset(
            f"td:user:{user_id}",
            mapping={
                "username": name,
                "password": _hash_password(password),
                "created_at": _now(),
            },
        )
        return self._user(user_id), self._open_session(user_id)

    def login(self, username: str, password: str) -> tuple[User, str]:
        name = username.strip()
        user_id = self.redis.get(f"td:user:name:{name.casefold()}")
        if not user_id:
            raise AuthError("用户名或密码不正确")
        stored = self.redis.hget(f"td:user:{user_id}", "password") or ""
        if not _verify_password(password, stored):
            raise AuthError("用户名或密码不正确")
        return self._user(user_id), self._open_session(user_id)

    def list_users(self) -> list[User]:
        found: list[str] = []
        for key in self.redis.scan_iter("td:user:*"):
            rest = key[len("td:user:"):]
            if rest.isdigit():
                found.append(rest)
        return [self._user(user_id) for user_id in sorted(found, key=int)]

    def logout(self, token: str) -> None:
        if token:
            self.redis.delete(f"td:session:{token}")

    def user_for_token(self, token: str) -> User | None:
        if not token:
            return None
        user_id = self.redis.get(f"td:session:{token}")
        if not user_id:
            return None
        self.redis.expire(f"td:session:{token}", SESSION_TTL)
        if not self.redis.exists(f"td:user:{user_id}"):
            return None
        return self._user(user_id)

    def _open_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.redis.set(f"td:session:{token}", user_id, ex=SESSION_TTL)
        return token

    def _user(self, user_id: str) -> User:
        username = self.redis.hget(f"td:user:{user_id}", "username") or user_id
        role = self.redis.hget(f"td:user:{user_id}", "role") or ""
        names = {item.strip().casefold() for item in os.environ.get("TD_ADMINS", "").split(",") if item.strip()}
        if role == "admin" or username.casefold() in names:
            admin = True
        elif role == "user":
            admin = False
        else:
            admin = user_id == "1"
        return User(id=user_id, username=username, admin=admin)


def _username(value: str) -> str:
    name = value.strip()
    if not 2 <= len(name) <= 32 or any(char.isspace() for char in name):
        raise AuthError("用户名需要 2 到 32 个字符，且不能有空格", 400)
    return name


def _password(value: str) -> None:
    if len(value) < 6:
        raise AuthError("密码至少 6 位", 400)


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS).hex()
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, digest = stored.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
    return hmac.compare_digest(check, digest)


def _now() -> str:
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
