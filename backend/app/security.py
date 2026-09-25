"""口令哈希与会话令牌。

为降低依赖面，使用标准库 hashlib.pbkdf2_hmac 与 hmac 实现令牌，
不引入第三方 JWT 库。密钥只存在于服务端环境变量（§11）。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

PBKDF2_ITERATIONS = 210_000
_ALGO = "pbkdf2_sha256"
_SEP = "$"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return _SEP.join([_ALGO, str(iterations), _b64e(salt), _b64e(digest)])


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iters, salt_b64, digest_b64 = encoded.split(_SEP)
        if algo != _ALGO:
            return False
        salt = _b64d(salt_b64)
        expected = _b64d(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
    except (ValueError, binascii.Error, TypeError):
        return False
    return hmac.compare_digest(expected, actual)


class TokenError(Exception):
    pass


def create_token(payload: dict[str, Any], secret: str, ttl_seconds: int) -> str:
    body = dict(payload)
    now = int(time.time())
    body.setdefault("iat", now)
    body["exp"] = now + int(ttl_seconds)
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return _b64e(raw) + "." + _b64e(sig)


def decode_token(token: str, secret: str) -> dict[str, Any]:
    try:
        body_b64, sig_b64 = token.split(".")
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    raw = _b64d(body_b64)
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64d(sig_b64)):
        raise TokenError("bad signature")
    payload = json.loads(raw.decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("token expired")
    return payload


def new_id(prefix: str = "") -> str:
    """字符串 UUID 主键，同时兼容 SQLite 与 PostgreSQL。"""

    value = str(uuid.uuid4())
    return prefix + value if prefix else value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_hash(payload: Any) -> str:
    """稳定哈希，用于幂等键冲突检测。"""

    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sign_payload(payload: str, secret: str) -> str:
    return _b64e(hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest())
