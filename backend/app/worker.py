"""后台 Worker：独立进程消费 jobs 表。

用法：
    python -m app.worker                 # 常驻轮询
    python -m app.worker --once          # 处理一个任务后退出（CI/测试）
    python -m app.worker --max-jobs 5

可靠性（§3.2 / F14）：
- 启动时先恢复心跳过期的任务（重新排队或明确失败）；
- 每个任务独立会话与事务，异常不会让 Worker 整体退出；
- 空闲轮询间隔可配置，避免空转。
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time

from .config import get_settings
from .db import init_db, session_scope
from .models import Job, utcnow
from .pipeline.runner import process_job
from .queue import claim_next_job, recover_stale_jobs

_STOP = False


def _handle_signal(signum, frame) -> None:  # pragma: no cover - 信号处理
    global _STOP
    _STOP = True


def worker_id() -> str:
    return socket.gethostname() + ":" + str(os.getpid())


def process_once(identity: str) -> bool:
    """领取并处理一个任务；返回是否处理了任务。"""

    with session_scope() as session:
        recover_stale_jobs(session)
        job = claim_next_job(session, identity)
        if job is None:
            return False
        job_id = job.id
    # 在独立会话中执行，避免长事务锁住队列表
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return False
        process_job(session, job, worker_id=identity)
    return True


def run(*, once: bool = False, max_jobs: int = 0, poll: float | None = None) -> int:
    settings = get_settings()
    init_db()
    interval = poll if poll is not None else settings.worker_poll_interval_seconds
    identity = worker_id()
    handled = 0
    idle_since = time.monotonic()
    while not _STOP:
        try:
            did_work = process_once(identity)
        except Exception as exc:  # noqa: BLE001 - Worker 不因单任务异常退出
            print("[worker] 任务处理异常：" + type(exc).__name__ + ": " + str(exc)[:200], file=sys.stderr)
            did_work = False
        if did_work:
            handled += 1
            idle_since = time.monotonic()
            if once or (max_jobs and handled >= max_jobs):
                break
            continue
        if once:
            break
        if max_jobs and handled >= max_jobs:
            break
        if time.monotonic() - idle_since > 3600:
            print("[worker] 长时间空闲，正常退出", file=sys.stderr)
            break
        time.sleep(interval)
    return handled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拆镜学后台 Worker")
    parser.add_argument("--once", action="store_true", help="处理一个任务后退出")
    parser.add_argument("--max-jobs", type=int, default=0, help="最多处理 N 个任务后退出（0=不限）")
    parser.add_argument("--poll", type=float, default=None, help="空闲轮询间隔（秒）")
    args = parser.parse_args(argv)

    signal.signal(signal.SIGINT, _handle_signal)
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (AttributeError, ValueError):  # pragma: no cover - Windows
        pass

    handled = run(once=args.once, max_jobs=args.max_jobs, poll=args.poll)
    print("[worker] 退出，共处理 " + str(handled) + " 个任务，时间 " + utcnow().isoformat())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
