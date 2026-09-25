"""上传、媒体验证与私有媒体访问。

流程：POST /projects/{id}/uploads 取上传票据 -> PUT object -> POST /assets/{id}/complete 触发服务端校验。
上传完成前、媒体验证失败后，不允许提交分析（§5.3）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..config import get_settings
from ..deps import CurrentUser, DbSession, current_user, owned_asset, owned_project
from ..errors import NotFound, PayloadTooLarge, Unauthorized, UnsupportedMedia
from ..media.ffmpeg import binaries_available
from ..models import Asset
from ..pipeline.probe import probe_file, validate_decodable, validate_probe
from ..schemas import AssetOut, MediaValidationOut, UploadRequest, UploadTicketOut
from ..security import create_token, decode_token
from ..serializers import asset_out
from ..storage import asset_key, get_storage, verify_media_token

router = APIRouter(tags=["assets"])

CHUNK = 1024 * 1024


@router.post(
    "/projects/{project_id}/uploads",
    response_model=UploadTicketOut,
    status_code=201,
    summary="申请上传地址（短时有效）",
)
def create_upload(project_id: str, payload: UploadRequest, db: DbSession, user: CurrentUser) -> dict:
    project = owned_project(db, project_id, user)
    settings = get_settings()
    if payload.size_bytes > settings.max_upload_bytes:
        raise PayloadTooLarge(
            "文件超过上限 " + str(settings.max_upload_bytes // (1024 * 1024)) + "MB",
            code="file_too_large",
        )
    suffix = Path(payload.filename).suffix.lower()
    if suffix and suffix.lstrip(".") not in settings.allowed_containers:
        raise UnsupportedMedia(
            "只接受 " + "、".join("." + item for item in settings.allowed_containers) + " 容器",
            code="unsupported_container",
        )
    asset = Asset(
        project_id=project.id,
        owner_id=user.id,
        object_key="pending",
        original_filename=payload.filename,
        media_type=payload.media_type,
        size_bytes=payload.size_bytes,
        sha256=payload.sha256,
        rights_note=project.rights_note,
        status="pending",
    )
    db.add(asset)
    db.flush()
    asset.object_key = asset_key(project.id, asset.id, payload.filename)
    db.add(asset)
    db.commit()

    storage = get_storage()
    if settings.storage_backend == "s3":
        upload_url = storage.signed_url(asset.object_key, ttl_seconds=settings.signed_url_ttl_seconds)
        method = "PUT"
        note = "S3 预签名上传地址，过期后需重新申请"
    else:
        token = create_token(
            {"k": asset.object_key, "p": "upload", "a": asset.id},
            settings.secret_key,
            settings.signed_url_ttl_seconds,
        )
        upload_url = settings.api_prefix + "/assets/" + asset.id + "/content?token=" + token
        method = "PUT"
        note = "本地私有存储上传地址；服务端会校验实际内容而不是扩展名"
    return {
        "asset_id": asset.id,
        "project_id": project.id,
        "object_key": asset.object_key,
        "upload_url": upload_url,
        "upload_method": method,
        "expires_in": settings.signed_url_ttl_seconds,
        "max_bytes": settings.max_upload_bytes,
        "note": note,
    }


def _authorize_upload(db: DbSession, asset_id: str, token: str | None, authorization: str | None) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise NotFound("素材不存在")
    settings = get_settings()
    if token:
        try:
            payload = decode_token(token, settings.secret_key)
        except Exception as exc:  # noqa: BLE001
            raise Unauthorized("上传地址无效或已过期") from exc
        if payload.get("p") != "upload" or payload.get("a") != asset_id or payload.get("k") != asset.object_key:
            raise Unauthorized("上传地址与素材不匹配")
        return asset
    if authorization:
        user = current_user(db, authorization)
        if user.id != asset.owner_id:
            raise NotFound("素材不存在")
        return asset
    raise Unauthorized("缺少上传令牌")


@router.put("/assets/{asset_id}/content", status_code=204, summary="上传原始文件（签名地址或 Bearer 令牌）")
async def upload_content(
    asset_id: str,
    request: Request,
    db: DbSession,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    asset = _authorize_upload(db, asset_id, token, authorization)
    settings = get_settings()
    if asset.status == "deleted":
        raise NotFound("素材不存在")
    declared = request.headers.get("content-length")
    if declared and int(declared) > settings.max_upload_bytes:
        raise PayloadTooLarge("文件超过上限", code="file_too_large")

    storage = get_storage()
    tmp = settings.data_dir / "work" / "uploads"
    tmp.mkdir(parents=True, exist_ok=True)
    target = tmp / (asset.id + ".part")
    digest = hashlib.sha256()
    total = 0
    with open(target, "wb") as fh:
        async for chunk in request.stream():
            total += len(chunk)
            if total > settings.max_upload_bytes:
                fh.close()
                try:
                    target.unlink()
                except OSError:
                    pass
                raise PayloadTooLarge("文件超过上限", code="file_too_large")
            digest.update(chunk)
            fh.write(chunk)
    if total == 0:
        raise UnsupportedMedia("上传内容为空", code="empty_file")
    storage.put_file(asset.object_key, target, content_type=asset.media_type)
    try:
        target.unlink()
    except OSError:
        pass
    asset.size_bytes = total
    if not asset.sha256:
        asset.sha256 = digest.hexdigest()
    asset.status = "uploaded"
    db.add(asset)
    db.commit()


@router.post("/assets/{asset_id}/complete", response_model=MediaValidationOut, summary="确认上传并触发服务端媒体验证")
def complete_upload(asset_id: str, db: DbSession, user: CurrentUser) -> dict:
    asset = owned_asset(db, asset_id, user)
    settings = get_settings()
    if asset.status not in ("uploaded", "ready", "rejected"):
        raise UnsupportedMedia("上传尚未完成，不能触发校验", code="upload_incomplete")
    if not get_storage().exists(asset.object_key):
        asset.status = "rejected"
        asset.rejection_code = "object_missing"
        asset.rejection_reason = "上传对象不存在"
        db.add(asset)
        db.commit()
        raise UnsupportedMedia("上传对象不存在，请重新上传", code="object_missing")

    checks: list[dict] = []
    local = _local_copy(asset.object_key, asset.id)
    ffmpeg_ok, ffprobe_ok = binaries_available()
    checks.append({"check": "ffmpeg_available", "passed": ffmpeg_ok and ffprobe_ok})
    if not (ffmpeg_ok and ffprobe_ok):
        asset.status = "rejected"
        asset.rejection_code = "media_toolchain_missing"
        asset.rejection_reason = "服务端缺少 ffmpeg/ffprobe"
        db.add(asset)
        db.commit()
        raise UnsupportedMedia("服务端缺少媒体处理工具", code="media_toolchain_missing")

    try:
        probe = probe_file(local)
    except Exception as exc:  # noqa: BLE001
        asset.status = "rejected"
        asset.rejection_code = "broken_file"
        asset.rejection_reason = "无法解析媒体文件（可能损坏或伪造扩展名）"
        db.add(asset)
        db.commit()
        raise UnsupportedMedia("无法解析媒体文件", code="broken_file", details={"error": str(exc)[:200]}) from exc

    checks.append({"check": "container", "passed": True, "value": probe.get("format_name")})
    checks.append({"check": "video_codec", "passed": True, "value": probe.get("video_codec")})
    try:
        validate_probe(probe)
        checks.append({"check": "duration_and_resolution", "passed": True,
                       "value": {"duration_ms": probe["duration_ms"], "height": probe["height"]}})
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "invalid_media")
        reason = getattr(exc, "message", str(exc))
        asset.status = "rejected"
        asset.rejection_code = code
        asset.rejection_reason = reason
        db.add(asset)
        db.commit()
        raise

    try:
        validate_decodable(local)
        checks.append({"check": "decode", "passed": True})
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "decode_failed")
        reason = getattr(exc, "message", str(exc))
        asset.status = "rejected"
        asset.rejection_code = code
        asset.rejection_reason = reason
        db.add(asset)
        db.commit()
        raise

    asset.status = "ready"
    asset.rejection_code = ""
    asset.rejection_reason = ""
    asset.duration_ms = int(probe.get("duration_ms") or 0)
    asset.width = int(probe.get("width") or 0)
    asset.height = int(probe.get("height") or 0)
    asset.fps = float(probe.get("avg_fps") or 0.0)
    asset.has_audio = bool(probe.get("has_audio"))
    asset.video_codec = str(probe.get("video_codec") or "")
    asset.audio_codec = str(probe.get("audio_codec") or "")
    asset.container = str(probe.get("format_name") or "")
    asset.is_vfr = bool(probe.get("is_vfr"))
    asset.probe = probe
    asset.size_bytes = int(probe.get("size_bytes") or asset.size_bytes)
    db.add(asset)
    db.commit()
    return {"asset": asset_out(asset), "validated": True, "checks": checks}


def _local_copy(object_key: str, asset_id: str) -> Path:
    storage = get_storage()
    settings = get_settings()
    local = storage.local_path(object_key)
    if local is not None:
        return local
    dest_dir = settings.data_dir / "work" / "verify"
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(object_key).suffix or ".bin"
    dest = dest_dir / (asset_id + suffix)
    with storage.open(object_key) as src, open(dest, "wb") as out:
        while True:
            chunk = src.read(CHUNK)
            if not chunk:
                break
            out.write(chunk)
    return dest


@router.get("/assets/{asset_id}", response_model=AssetOut, summary="素材详情（含短期播放地址）")
def get_asset(asset_id: str, db: DbSession, user: CurrentUser) -> dict:
    return asset_out(owned_asset(db, asset_id, user))


@router.get("/projects/{project_id}/assets", response_model=list[AssetOut], summary="项目素材列表")
def list_assets(project_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    project = owned_project(db, project_id, user)
    rows = (
        db.execute(select(Asset).where(Asset.project_id == project.id).order_by(Asset.created_at.desc()))
        .scalars()
        .all()
    )
    return [asset_out(asset) for asset in rows]


@router.get("/media/{token}", summary="短期媒体访问（默认 5 分钟有效）")
def get_media(token: str, db: DbSession) -> StreamingResponse:
    key = verify_media_token(token)
    storage = get_storage()
    if not storage.exists(key):
        raise NotFound("对象不存在或已过期")
    stream = storage.open(key)
    media_type = "video/mp4"
    if key.endswith(".jpg") or key.endswith(".jpeg"):
        media_type = "image/jpeg"
    elif key.endswith(".json"):
        media_type = "application/json"
    elif key.endswith(".md"):
        media_type = "text/markdown; charset=utf-8"
    return StreamingResponse(stream, media_type=media_type, headers={"Cache-Control": "private, max-age=60"})
