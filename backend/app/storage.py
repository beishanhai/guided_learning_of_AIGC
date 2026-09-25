"""私有媒体存储抽象（§3 媒体存储 / §11 安全）。

- local 后端：文件落在私有的 var/storage 目录，只能通过短期签名地址访问；
- s3 后端：私有对象存储 + 预签名 URL（5 分钟有效）；
- 密钥/凭证只从服务端配置读取，不进入日志与导出（§11）。
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from .config import get_settings
from .errors import NotFound
from .security import create_token, decode_token


def safe_key(key: str) -> str:
    """拒绝路径穿越与绝对路径。"""

    normalized = key.replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("/"):
        raise ValueError("invalid storage key")
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError("invalid storage key")
    return "/".join(parts)


class Storage(ABC):
    @abstractmethod
    def put_file(self, key: str, src: Path, content_type: str | None = None) -> int: ...

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> int: ...

    @abstractmethod
    def open(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    def local_path(self, key: str) -> Path | None:
        return None

    def list_prefix(self, prefix: str) -> list[str]:
        return []

    def signed_url(self, key: str, ttl_seconds: int | None = None) -> str:
        settings = get_settings()
        ttl = ttl_seconds or settings.signed_url_ttl_seconds
        token = create_token({"k": safe_key(key), "p": "media"}, settings.secret_key, ttl)
        return settings.api_prefix + "/media/" + token

    def delete_prefix(self, prefix: str) -> int:
        removed = 0
        for key in self.list_prefix(prefix):
            self.delete(key)
            removed += 1
        return removed


class LocalStorage(Storage):
    """本地私有存储。目录默认在 backend/var/storage，不对外暴露静态目录。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / safe_key(key)

    def put_file(self, key: str, src: Path, content_type: str | None = None) -> int:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        return target.stat().st_size

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> int:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return len(data)

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not path.exists():
            raise NotFound("对象不存在")
        return open(path, "rb")

    def delete(self, key: str) -> None:
        path = self._path(key)
        for candidate in (path, path.with_suffix(path.suffix + ".json")):
            if candidate.exists():
                try:
                    candidate.unlink()
                except OSError:  # pragma: no cover - 沙箱/权限极端情况
                    pass

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def local_path(self, key: str) -> Path | None:
        path = self._path(key)
        return path if path.exists() else None

    def list_prefix(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        root = base if base.is_dir() else base.parent
        if not root.exists():
            return []
        keys: list[str] = []
        for item in root.rglob("*"):
            if item.is_file():
                keys.append(item.relative_to(self.root).as_posix())
        return keys


class S3Storage(Storage):
    """S3 兼容私有对象存储（生产路径）。boto3 未安装时直接报错，不静默降级。"""

    def __init__(self) -> None:
        try:
            import boto3  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise RuntimeError("storage_backend=s3 需要安装 boto3") from exc
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.ttl = settings.signed_url_ttl_seconds
        self.client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )

    def put_file(self, key: str, src: Path, content_type: str | None = None) -> int:
        extra = {"ContentType": content_type} if content_type else None
        self.client.upload_file(str(src), self.bucket, safe_key(key), ExtraArgs=extra)
        return src.stat().st_size

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> int:
        extra = {"ContentType": content_type} if content_type else None
        self.client.put_object(Bucket=self.bucket, Key=safe_key(key), Body=data, **(extra or {}))
        return len(data)

    def open(self, key: str) -> BinaryIO:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=safe_key(key))
        except Exception as exc:  # pragma: no cover - 依赖远端
            raise NotFound("对象不存在") from exc
        return obj["Body"]

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=safe_key(key))

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=safe_key(key))
            return True
        except Exception:
            return False

    def list_prefix(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=safe_key(prefix)):
            for item in page.get("Contents", []):
                keys.append(item["Key"])
        return keys

    def signed_url(self, key: str, ttl_seconds: int | None = None) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": safe_key(key)},
            ExpiresIn=ttl_seconds or self.ttl,
        )


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(settings.storage_root)


def reset_storage_cache() -> None:
    get_storage.cache_clear()


def verify_media_token(token: str) -> str:
    """校验短期媒体访问令牌，返回对象 key。"""

    settings = get_settings()
    payload = decode_token(token, settings.secret_key)
    if payload.get("p") != "media":
        raise NotFound("无效的媒体令牌")
    return payload["k"]


# ---- 对象 key 约定 ---------------------------------------------------------------
def asset_key(project_id: str, asset_id: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".bin"
    return "projects/" + project_id + "/assets/" + asset_id + "/original" + suffix


def frame_key(project_id: str, asset_id: str, name: str) -> str:
    return "projects/" + project_id + "/assets/" + asset_id + "/frames/" + name


def derived_key(project_id: str, asset_id: str, name: str) -> str:
    return "projects/" + project_id + "/assets/" + asset_id + "/derived/" + name


def export_key(project_id: str, analysis_id: str) -> str:
    return "projects/" + project_id + "/exports/" + analysis_id + ".md"


def analysis_json_key(project_id: str, asset_id: str, version: int) -> str:
    return "projects/" + project_id + "/assets/" + asset_id + "/analysis/v" + str(version) + ".json"
