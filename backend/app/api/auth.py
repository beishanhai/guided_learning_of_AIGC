"""鉴权：登录、注册（可用性由配置控制）、当前用户。"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..config import get_settings
from ..deps import CurrentUser, DbSession
from ..errors import Conflict, Forbidden, Unauthorized
from ..models import User
from ..schemas import LoginRequest, RegisterRequest, TokenOut
from ..security import create_token, hash_password, verify_password
from ..serializers import user_out

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenOut, summary="测试账号登录")
def login(payload: LoginRequest, db: DbSession) -> dict:
    settings = get_settings()
    user = db.execute(select(User).where(User.subject == payload.subject)).scalars().first()
    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise Unauthorized("账号或口令不正确")
    if not user.is_active:
        raise Forbidden("账号已停用")
    token = create_token({"sub": user.id, "role": user.role}, settings.secret_key, settings.token_ttl_seconds)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.token_ttl_seconds,
        "user": user_out(user),
    }


@router.post("/auth/register", response_model=TokenOut, status_code=201, summary="自助注册（仅开发环境）")
def register(payload: RegisterRequest, db: DbSession) -> dict:
    settings = get_settings()
    if not settings.allow_self_registration:
        raise Forbidden("当前环境不开放自助注册")
    existing = db.execute(select(User).where(User.subject == payload.subject)).scalars().first()
    if existing is not None:
        raise Conflict("账号已存在")
    user = User(
        subject=payload.subject,
        display_name=payload.display_name or payload.subject,
        password_hash=hash_password(payload.password),
        role="learner",
    )
    db.add(user)
    db.commit()
    token = create_token({"sub": user.id, "role": user.role}, settings.secret_key, settings.token_ttl_seconds)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.token_ttl_seconds,
        "user": user_out(user),
    }


@router.get("/auth/me", summary="当前用户")
def me(user: CurrentUser) -> dict:
    return user_out(user)
