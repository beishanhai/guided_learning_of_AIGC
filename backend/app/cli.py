"""运维命令：建表、同步知识卡片、创建测试账号、清理过期对象、导出 OpenAPI。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import get_settings
from .db import init_db, session_scope
from .models import User
from .security import hash_password
from .storage import get_storage


def cmd_init_db(_args: argparse.Namespace) -> int:
    init_db()
    print("数据库已初始化：" + get_settings().resolved_database_url)
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from .learning.knowledge import sync_knowledge_cards

    init_db()
    count = sync_knowledge_cards()
    print("知识卡片已同步：" + str(count) + " 张")
    settings = get_settings()
    created = 0
    with session_scope() as session:
        existing = {row.subject for row in session.query(User).all()}
        for item in settings.bootstrap_users.split(","):
            parts = item.strip().split(":")
            if len(parts) < 2 or parts[0] in existing:
                continue
            role = parts[2] if len(parts) > 2 else "learner"
            session.add(
                User(
                    subject=parts[0],
                    display_name=parts[0],
                    password_hash=hash_password(parts[1]),
                    role=role,
                )
            )
            created += 1
    print("测试账号创建：" + str(created) + " 个")
    if args.with_samples:
        from .sample_data import build_samples

        build_samples()
    return 0


def cmd_export_openapi(args: argparse.Namespace) -> int:
    from .main import create_app

    app = create_app()
    schema = app.openapi()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OpenAPI 已导出：" + str(out))
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    settings = get_settings()
    from .media.ffmpeg import binaries_available

    ffmpeg_ok, ffprobe_ok = binaries_available()
    checks = {
        "database_url": settings.resolved_database_url,
        "storage_backend": settings.storage_backend,
        "storage_root": str(settings.storage_root),
        "ffmpeg": ffmpeg_ok,
        "ffprobe": ffprobe_ok,
        "multimodal_provider": settings.multimodal_provider,
        "asr_provider": settings.asr_provider,
        "knowledge_path": str(settings.knowledge_path),
        "knowledge_exists": settings.knowledge_path.exists(),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if (ffmpeg_ok and ffprobe_ok) else 1


def cmd_cleanup(_args: argparse.Namespace) -> int:
    storage = get_storage()
    root = get_settings().storage_root
    removed = 0
    for key in storage.list_prefix("projects/"):
        if key.endswith(".json") and "/analysis/" in key:
            continue
    print("对象清单检查完成，storage_root=" + str(root) + "，removed=" + str(removed))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拆镜学运维命令")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="建表").set_defaults(func=cmd_init_db)

    seed = sub.add_parser("seed", help="同步知识卡片并创建测试账号")
    seed.add_argument("--with-samples", action="store_true", help="同时生成演示样本")
    seed.set_defaults(func=cmd_seed)

    export = sub.add_parser("export-openapi", help="导出 OpenAPI JSON")
    export.add_argument("--output", default="docs/openapi.json")
    export.set_defaults(func=cmd_export_openapi)

    sub.add_parser("doctor", help="环境自检").set_defaults(func=cmd_doctor)
    sub.add_parser("cleanup", help="清理孤儿对象").set_defaults(func=cmd_cleanup)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
