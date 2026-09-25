"""测试夹具：隔离的数据目录、SQLite 数据库、私有存储与测试账号。"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]
SAMPLES = WORKSPACE / "samples" / "dev"


def _configure_env(tmp_root: Path) -> None:
    os.environ["CJX_ENV"] = "test"
    os.environ["CJX_DATA_DIR"] = str(tmp_root / "var")
    os.environ["CJX_DATABASE_URL"] = "sqlite:///" + (tmp_root / "var" / "test.db").as_posix()
    os.environ["CJX_STORAGE_ROOT"] = str(tmp_root / "var" / "storage")
    os.environ["CJX_SECRET_KEY"] = "test-secret-key"
    os.environ["CJX_ALLOW_SELF_REGISTRATION"] = "true"
    os.environ["CJX_INLINE_JOBS"] = "false"
    os.environ["CJX_MULTIMODAL_PROVIDER"] = "offline"
    os.environ["CJX_ASR_PROVIDER"] = "none"
    os.environ["CJX_BOOTSTRAP_USERS"] = "alice:alice-pass-123:learner,bob:bob-pass-123:learner"
    os.environ["CJX_WORKER_POLL_INTERVAL_SECONDS"] = "0.01"


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    """工作区内的隔离运行目录。

    注意：不使用 pytest 默认的 tmp_path_factory —— 在受限沙箱/CI 下系统临时目录可能不可写，
    这里改为在 backend/var/pytest-runs 下创建，并显式用 os.makedirs（0o777）。
    """

    base = WORKSPACE / "backend" / "var" / "pytest-runs"
    base.mkdir(parents=True, exist_ok=True)
    root = base / ("run-" + uuid.uuid4().hex[:10])
    root.mkdir(parents=True, exist_ok=True)
    _configure_env(root)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _seed_users() -> None:
    from app.db import session_scope
    from app.models import User
    from app.security import hash_password

    with session_scope() as session:
        existing = {row.subject for row in session.query(User).all()}
        for subject, password in (("alice", "alice-pass-123"), ("bob", "bob-pass-123")):
            if subject in existing:
                continue
            session.add(
                User(
                    subject=subject,
                    display_name=subject,
                    password_hash=hash_password(password),
                    role="learner",
                )
            )


@pytest.fixture(scope="session")
def app(tmp_root: Path):
    from app.config import reset_settings_cache
    from app.db import init_db, reset_db_state
    from app.learning.knowledge import reset_knowledge_cache, sync_knowledge_cards
    from app.main import create_app
    from app.storage import reset_storage_cache

    reset_settings_cache()
    reset_db_state()
    reset_storage_cache()
    reset_knowledge_cache()
    init_db()
    sync_knowledge_cards()
    _seed_users()
    return create_app()


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


def login(client, subject: str = "alice", password: str = "alice-pass-123") -> dict:
    response = client.post("/api/v1/auth/login", json={"subject": subject, "password": password})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": "Bearer " + token}


@pytest.fixture(scope="session")
def alice_headers(client) -> dict:
    return login(client, "alice")


@pytest.fixture(scope="session")
def bob_headers(client) -> dict:
    return login(client, "bob", "bob-pass-123")


def run_worker(limit: int = 40) -> int:
    """把队列跑空（测试中直接调用 Worker 的单步处理）。"""

    from app.worker import process_once

    handled = 0
    for _ in range(limit):
        if not process_once("test-worker"):
            break
        handled += 1
    return handled


def sample_path(name: str) -> Path:
    path = SAMPLES / name
    assert path.exists(), "缺少样片：" + str(path) + "，请先运行 python -m app.cli seed --with-samples"
    return path


def upload_file(client, headers: dict, project_id: str, path: Path):
    """申请票据 -> PUT -> complete，返回 (asset_id, complete_response)。"""

    data = path.read_bytes()
    ticket = client.post(
        "/api/v1/projects/" + project_id + "/uploads",
        json={"filename": path.name, "size_bytes": len(data), "media_type": "video/mp4"},
        headers=headers,
    )
    assert ticket.status_code == 201, ticket.text
    body = ticket.json()
    upload_url = body["upload_url"]
    if upload_url.startswith("/"):
        upload_url = "http://testserver" + upload_url
    response = client.put(upload_url, content=data, headers={"Content-Type": "video/mp4"})
    assert response.status_code == 204, response.text
    complete = client.post("/api/v1/assets/" + body["asset_id"] + "/complete", headers=headers)
    return body["asset_id"], complete


@pytest.fixture(scope="session")
def uploaded_asset(client, alice_headers):
    """上传并验证 fastcut_20s.mp4，返回 (project_id, asset_id)。"""

    project = client.post(
        "/api/v1/projects",
        json={"title": "自动化测试项目", "description": "", "rights_note": "合成测试夹具"},
        headers=alice_headers,
    ).json()
    project_id = project["id"]
    asset_id, complete = upload_file(client, alice_headers, project_id, sample_path("fastcut_20s.mp4"))
    assert complete.status_code == 200, complete.text
    return project_id, asset_id
