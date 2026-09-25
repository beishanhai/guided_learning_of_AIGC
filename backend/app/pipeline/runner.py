"""流水线执行器：queued -> preprocessing -> analyzing -> teaching -> succeeded。

设计要点（§3.2 / §4）：
- 每个阶段写一条 JobStage，记录输入摘要、输出、耗时、供应商请求 ID 与版本；
- 只有可重试错误（429/超时/5xx）才自动重试，鉴权与参数错误直接失败；
- 单镜头分析失败不拖垮整条任务，写入 partial 标记与 unknowns；
- 删除标记在写库前再次检查，已删除项目不再回写（F13）；
- 取消请求在每个阶段与每个镜头之间检查。
"""

from __future__ import annotations

import base64
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import AppError
from ..learning.intents import build_shot_explanations, get_intent
from ..learning.knowledge import get_knowledge_base
from ..learning.metrics import compute_metrics
from ..learning.tasks import build_task
from ..media.ffmpeg import extract_audio_wav, extract_frame, make_analysis_copy
from ..models import Analysis, Asset, CleanupTask, Job, JobStage, ModelCall, Project, Shot, utcnow
from ..providers import get_asr_provider, get_vision_provider, retry_call
from ..providers.base import ShotContext, TranscriptResult
from ..storage import (
    analysis_json_key,
    frame_key,
    get_storage,
    safe_key,
)
from .keyframes import plan_frames
from .probe import probe_file
from .scenes import detect_shots
from .schema import normalize_finding


class JobCancelled(Exception):
    pass


class StageFailed(Exception):
    def __init__(self, code: str, message: str, *, partial: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.partial = partial


def process_job(session: Session, job: Job, *, worker_id: str) -> Job:
    """任务入口：按类型分派，统一处理取消、失败与阶段记录。"""

    handlers = {
        "analyze_asset": _run_analysis,
        "analyze_submission": _run_submission,
        "cleanup_project": _run_cleanup,
    }
    handler = handlers.get(job.type)
    if handler is None:
        job.status = "failed"
        job.stage = "failed"
        job.error_code = "unknown_job_type"
        job.error_message = "未知任务类型：" + job.type
        job.finished_at = utcnow()
        return job

    started = time.monotonic()
    try:
        handler(session, job, worker_id=worker_id, started=started)
        if job.status not in ("cancelled", "failed"):
            job.status = "succeeded"
            job.stage = "succeeded"
            job.progress = 100
        job.finished_at = utcnow()
    except JobCancelled:
        job.status = "cancelled"
        job.stage = "cancelled"
        job.error_code = "cancelled"
        job.error_message = "任务已取消"
        job.finished_at = utcnow()
    except StageFailed as exc:
        job.status = "failed"
        job.stage = "failed"
        job.error_code = exc.code
        job.error_message = exc.message
        job.partial = job.partial or exc.partial
        job.finished_at = utcnow()
    except AppError as exc:
        job.status = "failed"
        job.stage = "failed"
        job.error_code = exc.code
        job.error_message = exc.message
        job.finished_at = utcnow()
    except Exception as exc:  # noqa: BLE001 - 兜底，避免任务永久停在处理中
        job.status = "failed"
        job.stage = "failed"
        job.error_code = "internal_error"
        job.error_message = type(exc).__name__ + ": " + str(exc)[:400]
        job.finished_at = utcnow()
    finally:
        job.locked_by = ""
        job.locked_at = None
        job.heartbeat_at = utcnow()
        session.add(job)
        session.flush()
    return job


# --------------------------------------------------------------------------------------
# 阶段辅助
# --------------------------------------------------------------------------------------
class Stage:
    def __init__(self, session: Session, job: Job, name: str) -> None:
        self.session = session
        self.job = job
        self.name = name
        self.record = JobStage(job_id=job.id, stage=name, status="running", started_at=utcnow())
        self._t0 = time.monotonic()
        self.session.add(self.record)
        self.session.flush()

    def __enter__(self) -> "Stage":
        self._check()
        self.job.stage = self.name
        if self.name == "preprocessing":
            self.job.status = "preprocessing"
        elif self.name == "analyzing":
            self.job.status = "analyzing"
        elif self.name == "teaching":
            self.job.status = "teaching"
        self.session.flush()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.record.duration_ms = int((time.monotonic() - self._t0) * 1000)
        self.record.finished_at = utcnow()
        self.record.attempt = self.job.attempt or 1
        if exc_type is not None:
            self.record.status = "failed"
            self.record.error = str(exc)[:400]
        else:
            self.record.status = "succeeded"
        self.session.add(self.record)
        self.session.flush()

    def _check(self) -> None:
        settings = get_settings()
        if self.job.cancel_requested:
            raise JobCancelled()
        if time.monotonic() - self._t0 > settings.analysis_max_runtime_seconds:
            raise StageFailed("timeout", "任务超过最大运行时长")

    def note(self, **kwargs: Any) -> None:
        summary = dict(self.record.input_summary or {})
        summary.update({k: v for k, v in kwargs.items() if k == "inputs"})
        outputs = self.record.output_summary or {}
        if "outputs" in kwargs:
            outputs.update(kwargs["outputs"])
        self.record.input_summary = summary
        self.record.output_summary = outputs
        self.session.add(self.record)

    def finish(self, *, version: str = "", provider_request_id: str = "", **outputs: Any) -> None:
        existing = dict(self.record.output_summary or {})
        existing.update(outputs)
        self.record.output_summary = existing
        self.record.version = version or get_settings().pipeline_version
        if provider_request_id:
            self.record.provider_request_id = provider_request_id
        self.session.add(self.record)
        self.session.flush()

    def checkpoint(self) -> None:
        """心跳 + 取消检查。"""

        self.job.heartbeat_at = utcnow()
        self.session.add(self.job)
        self.session.flush()
        if self.job.cancel_requested:
            raise JobCancelled()


def _project_deleted(session: Session, project_id: str | None) -> bool:
    if not project_id:
        return False
    project = session.get(Project, project_id)
    return project is None or project.deleted_at is not None


def _work_dir(job: Job) -> Path:
    path = get_settings().data_dir / "work" / job.id
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_model_call(
    session: Session,
    job: Job,
    *,
    provider: str,
    model_id: str,
    provider_request_id: str = "",
    usage: dict[str, Any] | None = None,
    latency_ms: int = 0,
    status: str = "ok",
    error_code: str = "",
    attempt: int = 1,
) -> float:
    """记录一次外部调用并估算成本（无 usage 时标为估算）。"""

    settings = get_settings()
    usage = usage or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cost = (
        prompt_tokens / 1_000_000.0 * settings.multimodal_input_price_per_mtok
        + completion_tokens / 1_000_000.0 * settings.multimodal_output_price_per_mtok
    )
    row = ModelCall(
        job_id=job.id,
        owner_id=job.owner_id,
        provider=provider,
        model_id=model_id,
        provider_request_id=provider_request_id,
        usage=usage,
        estimated_cost_cny=round(cost, 6),
        price_version=settings.multimodal_price_version,
        latency_ms=latency_ms,
        status=status,
        error_code=error_code,
        attempt=attempt,
    )
    session.add(row)
    session.flush()
    return cost


# --------------------------------------------------------------------------------------
# 拆解主流程
# --------------------------------------------------------------------------------------
def _run_analysis(session: Session, job: Job, *, worker_id: str, started: float) -> None:
    payload = job.payload or {}
    asset = session.get(Asset, str(payload.get("asset_id") or ""))
    if asset is None or asset.owner_id != job.owner_id:
        raise StageFailed("asset_not_found", "素材不存在或无权限")
    if asset.status != "ready":
        raise StageFailed("asset_not_ready", "素材尚未通过服务端校验，不能提交分析")
    settings = get_settings()
    kb = get_knowledge_base()
    intent = str(payload.get("intent") or "shot_language")
    kind = str(payload.get("kind") or "reference")
    generate_task = bool(payload.get("generate_task"))

    work = _work_dir(job)
    storage = get_storage()
    analysis_id = str(payload.get("analysis_id") or "")

    # ---------- preprocessing ----------
    prepared: dict[str, Any] = {}
    with Stage(session, job, "preprocessing") as stage:
        stage.note(inputs={"asset_id": asset.id, "object_key": asset.object_key, "intent": intent})
        local = _materialize(storage, asset.object_key, work / ("original" + Path(asset.object_key).suffix))
        probe = probe_file(local)
        media_copy_info: dict[str, Any] = {}
        analysis_copy = work / "analysis.mp4"
        if make_analysis_copy(local, analysis_copy, height=720):
            media_copy_info = {"analysis_copy": "720p", "analysis_copy_bytes": analysis_copy.stat().st_size}

        score_series = _scene_scores(local)
        detection = detect_shots(score_series, duration_ms=int(asset.duration_ms or probe["duration_ms"]))
        plan = plan_frames(detection.shots, duration_ms=int(asset.duration_ms or probe["duration_ms"]))

        frame_records: dict[str, list[dict[str, Any]]] = {}
        frame_paths: dict[str, list[Path]] = {}
        for item in plan.frames:
            stage.checkpoint()
            name = item.frame_id + ".jpg"
            out_path = work / "frames" / name
            if not extract_frame(local, item.timestamp_ms, out_path):
                continue
            key = frame_key(asset.project_id, asset.id, name)
            storage.put_file(key, out_path, content_type="image/jpeg")
            frame_records.setdefault(str(item.shot_index), []).append(
                {"frame_id": item.frame_id, "key": key, "timestamp_ms": item.timestamp_ms, "position": item.position}
            )
            frame_paths.setdefault(str(item.shot_index), []).append(out_path)

        coverage = {
            "shot_count": len(detection.shots),
            "frame_count": sum(len(v) for v in frame_records.values()),
            "frames_truncated": plan.truncated,
            "notes": (plan.notes or []) + detection.notes,
            "scene_threshold": detection.threshold,
            "scene_mean_score": detection.mean_score,
            "scene_std_score": detection.std_score,
            "transitions": detection.transitions,
        }
        prepared = {
            "local": local,
            "probe": probe,
            "detection": detection,
            "frame_records": frame_records,
            "frame_paths": frame_paths,
            "coverage": coverage,
            "media_copy_info": media_copy_info,
        }
        stage.finish(
            version=settings.pipeline_version,
            shot_count=len(detection.shots),
            frame_count=coverage["frame_count"],
            frames_truncated=plan.truncated,
            media_copy=media_copy_info,
        )

    # ---------- analyzing ----------
    with Stage(session, job, "analyzing") as stage:
        stage.note(inputs={"shots": len(prepared["detection"].shots), "provider": settings.multimodal_provider})
        transcript = _transcribe(job, asset, work, stage)
        transcript_by_shot = _assign_transcript(prepared["detection"].shots, transcript)

        provider = get_vision_provider()
        shots_data: list[dict[str, Any]] = []
        partial = False
        warnings: list[str] = []
        total_cost = 0.0
        for span in prepared["detection"].shots:
            stage.checkpoint()
            if time.monotonic() - started > settings.analysis_max_runtime_seconds:
                partial = True
                warnings.append("任务达到最大运行时长，后续镜头未完成分析")
                break
            if total_cost >= settings.cost_per_analysis_limit_cny > 0:
                partial = True
                warnings.append("已达到单次分析成本上限，后续镜头未调用模型")
                break
            frames = prepared["frame_paths"].get(str(span.index), [])
            context = ShotContext(
                index=span.index,
                shot_ref=span.shot_ref,
                start_ms=span.start_ms,
                end_ms=span.end_ms,
                duration_ms=span.duration_ms,
                frames=frames,
                frame_ids=[item["frame_id"] for item in prepared["frame_records"].get(str(span.index), [])],
                transcript=transcript_by_shot.get(span.shot_ref, ""),
                intent=intent,
            )
            attempt_counter = {"n": 1}

            def _call() -> Any:
                attempt_counter["n"] += 1
                t0 = time.monotonic()
                try:
                    finding = provider.analyze_shot(context, job_id=job.id)
                except Exception as exc:
                    record_model_call(
                        session,
                        job,
                        provider=provider.name,
                        model_id=provider.model_id,
                        latency_ms=int((time.monotonic() - t0) * 1000),
                        status="error",
                        error_code=type(exc).__name__,
                        attempt=attempt_counter["n"],
                    )
                    raise
                record_model_call(
                    session,
                    job,
                    provider=provider.name,
                    model_id=provider.model_id,
                    provider_request_id=getattr(finding, "provider_request_id", ""),
                    usage=(getattr(finding, "raw", {}) or {}).get("usage") or {},
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    attempt=attempt_counter["n"],
                )
                return finding

            try:
                finding = retry_call(_call)
                model, issues = normalize_finding(finding, duration_ms=int(asset.duration_ms), valid_tags=kb.tags)
            except AppError as exc:
                partial = True
                warnings.append(span.shot_ref + " 分析失败：" + exc.message)
                model, issues = normalize_finding(
                    {
                        "observation": "（该镜头分析失败，需人工复核）",
                        "shot_scale": "unknown",
                        "camera_motion": "unknown",
                        "interpretation": "",
                        "alternative": "",
                        "knowledge_tags": [],
                        "unknowns": ["供应商调用失败：" + exc.message],
                        "confidence": 0.0,
                    },
                    duration_ms=int(asset.duration_ms),
                    valid_tags=kb.tags,
                )
            except Exception as exc:  # noqa: BLE001
                partial = True
                warnings.append(span.shot_ref + " 分析异常：" + type(exc).__name__)
                model, issues = normalize_finding(
                    {
                        "observation": "（该镜头分析异常，需人工复核）",
                        "unknowns": ["内部异常：" + type(exc).__name__],
                    },
                    duration_ms=int(asset.duration_ms),
                    valid_tags=kb.tags,
                )

            total_cost = _job_cost(session, job)
            cards = kb.resolve(model.knowledge_tags, intent)
            evidence = [
                {"timestamp_ms": item["timestamp_ms"], "frame_id": item["frame_id"], "frame_key": item["key"]}
                for item in prepared["frame_records"].get(str(span.index), [])
            ]
            unknowns = list(model.unknowns)
            unknowns.extend(issues)
            if span.width_transition:
                unknowns.append("该处疑似渐变转场，边界需人工复核")
            if len(frames) < 2:
                unknowns.append("只有 1 张代表帧，无法判断运动")
            shots_data.append(
                {
                    "index": span.index,
                    "shot_ref": span.shot_ref,
                    "start_ms": span.start_ms,
                    "end_ms": span.end_ms,
                    "observation": model.observation,
                    "shot_scale": model.shot_scale,
                    "camera_motion": model.camera_motion,
                    "interpretation": model.interpretation,
                    "alternative": model.alternative,
                    "narrative_function": model.narrative_function,
                    "dialogue": transcript_by_shot.get(span.shot_ref, ""),
                    "frame_keys": [item["key"] for item in prepared["frame_records"].get(str(span.index), [])],
                    "evidence": evidence,
                    "knowledge_ids": [card.id for card in cards],
                    "unknowns": unknowns[:6],
                    "confidence": model.confidence,
                    "source": "detector",
                }
            )
            job.progress = min(90, 10 + int(70 * (span.index + 1) / max(1, len(prepared["detection"].shots))))
            session.add(job)
        stage.finish(
            version=settings.pipeline_version,
            provider=provider.name,
            model_id=provider.model_id,
            shots_analyzed=len(shots_data),
            partial=partial,
            warnings=warnings[:10],
            estimated_cost_cny=round(total_cost, 6),
        )

    if _project_deleted(session, asset.project_id):
        raise StageFailed("project_deleted", "项目已删除，结果不再写入")

    # ---------- teaching ----------
    with Stage(session, job, "teaching") as stage:
        stage.note(inputs={"intent": intent, "knowledge_version": kb.version})
        analysis = _persist_analysis(
            session,
            job=job,
            asset=asset,
            analysis_id=analysis_id,
            kind=kind,
            intent=intent,
            shots_data=shots_data,
            coverage=prepared["coverage"],
            probe=prepared["probe"],
            transcript=transcript,
            partial=partial,
            warnings=warnings,
        )
        explanations = build_shot_explanations(shots_data, intent)
        task_row = None
        if generate_task and kind == "reference":
            task_payload = _create_task(session, job=job, analysis=analysis, kb=kb)
            task_row = task_payload["task_id"]
        stage.finish(
            version=get_settings().knowledge_version,
            analysis_id=analysis.id,
            intent=intent,
            knowledge_cards=len(kb.cards),
            explanations=len(explanations),
            learning_task_id=task_row or "",
        )

    job.result_type = "analysis"
    job.result_id = analysis.id
    job.partial = job.partial or partial
    session.add(job)
    session.flush()


def _job_cost(session: Session, job: Job) -> float:
    rows = session.query(ModelCall).filter(ModelCall.job_id == job.id).all()
    return sum(float(row.estimated_cost_cny or 0.0) for row in rows)


def _materialize(storage: Any, key: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    local = storage.local_path(key)
    if local is not None:
        shutil.copyfile(local, dest)
        return dest
    with storage.open(key) as fh, open(dest, "wb") as out:
        shutil.copyfileobj(fh, out)
    return dest


def _scene_scores(local: Path) -> list[tuple[float, float]]:
    from ..media.ffmpeg import extract_scene_scores

    return extract_scene_scores(local)


def _transcribe(job: Job, asset: Asset, work: Path, stage: Stage) -> TranscriptResult:
    settings = get_settings()
    if not asset.has_audio:
        return TranscriptResult(segments=[], provider="none", note="素材无音轨，转写为空（不臆造台词）")
    if settings.asr_provider == "none":
        return TranscriptResult(
            segments=[], provider="none", note="未启用 ASR，台词列为空；视觉流程照常执行"
        )
    audio_path = work / "audio.wav"
    if not extract_audio_wav(_materialize(get_storage(), asset.object_key, work / "asr_source.mp4"), audio_path):
        return TranscriptResult(segments=[], provider="none", note="音轨提取失败，台词列为空")
    provider = get_asr_provider()

    def _call() -> TranscriptResult:
        return provider.transcribe(audio_path, duration_ms=int(asset.duration_ms), job_id=job.id)

    try:
        result = retry_call(_call)
        record_model_call(
            session=stage.session,
            job=job,
            provider=provider.name,
            model_id=provider.model_id,
            provider_request_id=result.provider_request_id,
        )
        return result
    except Exception as exc:  # noqa: BLE001 - 转写失败不阻塞视觉流程
        stage.session.add(
            JobStage(
                job_id=job.id,
                stage="analyzing:asr",
                status="failed",
                error=str(exc)[:200],
                output_summary={"note": "ASR 失败，视觉分析继续", "provider": provider.name},
            )
        )
        return TranscriptResult(segments=[], provider=provider.name, note="ASR 失败：" + type(exc).__name__)


def _assign_transcript(shots: list[Any], transcript: TranscriptResult) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for span in shots:
        texts = [
            seg.text
            for seg in transcript.segments
            if seg.end_ms > span.start_ms and seg.start_ms < span.end_ms
        ]
        mapping[span.shot_ref] = " ".join(texts).strip()
    return mapping


def _persist_analysis(
    session: Session,
    *,
    job: Job,
    asset: Asset,
    analysis_id: str,
    kind: str,
    intent: str,
    shots_data: list[dict[str, Any]],
    coverage: dict[str, Any],
    probe: dict[str, Any],
    transcript: TranscriptResult,
    partial: bool,
    warnings: list[str],
) -> Analysis:
    settings = get_settings()
    analysis = session.get(Analysis, analysis_id) if analysis_id else None
    if analysis is None:
        previous = (
            session.query(Analysis)
            .filter(Analysis.asset_id == asset.id)
            .order_by(Analysis.version.desc())
            .first()
        )
        version = (previous.version + 1) if previous else 1
        analysis = Analysis(
            asset_id=asset.id,
            project_id=asset.project_id,
            owner_id=job.owner_id,
            version=version,
            kind=kind,
        )
        session.add(analysis)
        session.flush()

    analysis.intent = intent
    analysis.status = "partial" if partial else "ready"
    analysis.model_id = settings.multimodal_model_id
    analysis.prompt_version = settings.prompt_version
    analysis.knowledge_version = settings.knowledge_version
    analysis.schema_version = settings.schema_version
    analysis.pipeline_version = settings.pipeline_version
    analysis.coverage = {
        **coverage,
        "warnings": warnings[:10],
        "partial": partial,
        "provider": settings.multimodal_provider,
        "asr_provider": transcript.provider,
        "asr_note": transcript.note,
        "is_demo_prebuilt": False,
    }
    analysis.transcript = {
        "language": transcript.language,
        "provider": transcript.provider,
        "note": transcript.note,
        "segments": [
            {"start_ms": seg.start_ms, "end_ms": seg.end_ms, "text": seg.text}
            for seg in transcript.segments
        ],
    }
    analysis.media = {
        "width": probe.get("width"),
        "height": probe.get("height"),
        "fps": probe.get("avg_fps"),
        "is_vfr": probe.get("is_vfr"),
        "duration_ms": probe.get("duration_ms"),
        "container": probe.get("format_name"),
        "video_codec": probe.get("video_codec"),
        "has_audio": probe.get("has_audio"),
    }
    analysis.metrics = compute_metrics(shots_data, duration_ms=int(asset.duration_ms))
    analysis.unknowns = {
        "items": sorted({u for shot in shots_data for u in (shot.get("unknowns") or [])}),
        "policy": "无法从画面或声音核实的内容一律列为未知，不用推测填充",
    }
    session.query(Shot).filter(Shot.analysis_id == analysis.id).delete()
    session.flush()
    for item in shots_data:
        session.add(
            Shot(
                analysis_id=analysis.id,
                index=item["index"],
                shot_ref=item["shot_ref"],
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                observation=item["observation"],
                shot_scale=item["shot_scale"],
                camera_motion=item["camera_motion"],
                interpretation=item["interpretation"],
                alternative=item["alternative"],
                narrative_function=item["narrative_function"],
                dialogue=item["dialogue"],
                transcript_segments=[],
                frame_keys=item["frame_keys"],
                evidence=item["evidence"],
                knowledge_ids=item["knowledge_ids"],
                unknowns=item["unknowns"],
                confidence=item["confidence"],
                source=item["source"],
            )
        )
    session.flush()

    try:
        payload = json.dumps(
            {
                "analysis_id": analysis.id,
                "version": analysis.version,
                "intent": intent,
                "shots": shots_data,
                "coverage": analysis.coverage,
            },
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        get_storage().put_bytes(
            analysis_json_key(asset.project_id, asset.id, analysis.version),
            payload,
            content_type="application/json",
        )
    except Exception:  # noqa: BLE001 - 归档失败不影响主流程
        pass
    return analysis


def _create_task(session: Session, *, job: Job, analysis: Analysis, kb: Any) -> dict[str, Any]:
    from ..models import LearningTask

    shots = _analysis_shots(analysis)
    duration_ms = (
        (analysis.media or {}).get("duration_ms")
        or (analysis.metrics or {}).get("duration_ms")
        or 0
    )
    payload = build_task(
        analysis={
            "title": "",
            "duration_ms": int(duration_ms),
            "shots": shots,
        },
        intent=analysis.intent,
        level="imitate",
        knowledge=kb,
    )
    row = LearningTask(
        analysis_id=analysis.id,
        owner_id=job.owner_id,
        project_id=analysis.project_id,
        intent=payload["intent"],
        level=payload["level"],
        title=payload["title"],
        objective=payload["objective"],
        prerequisites=payload["prerequisites"],
        steps=payload["steps"],
        constraints=payload["constraints"],
        submission_requirements=payload["submission_requirements"],
        rubric=payload["rubric"],
        estimated_minutes=payload["estimated_minutes"],
        tools=payload["tools"],
        reference_metrics=payload["reference_metrics"],
        knowledge_version=analysis.knowledge_version,
    )
    session.add(row)
    session.flush()
    return {"task_id": row.id}


def _analysis_shots(analysis: Analysis) -> list[dict[str, Any]]:
    return [
        {
            "shot_ref": shot.shot_ref,
            "start_ms": shot.start_ms,
            "end_ms": shot.end_ms,
            "observation": shot.observation,
            "shot_scale": shot.shot_scale,
            "camera_motion": shot.camera_motion,
            "interpretation": shot.interpretation,
            "alternative": shot.alternative,
            "narrative_function": shot.narrative_function,
            "dialogue": shot.dialogue,
            "frame_keys": shot.frame_keys,
            "evidence": shot.evidence,
            "knowledge_ids": shot.knowledge_ids,
            "unknowns": shot.unknowns,
        }
        for shot in analysis.shots
    ]


# --------------------------------------------------------------------------------------
# 作业提交分析与清理
# --------------------------------------------------------------------------------------
def _run_submission(session: Session, job: Job, *, worker_id: str, started: float) -> None:
    payload = job.payload or {}
    submission = None
    from ..models import Feedback, LearningTask, Submission

    submission = session.get(Submission, str(payload.get("submission_id") or ""))
    if submission is None or submission.owner_id != job.owner_id:
        raise StageFailed("submission_not_found", "作业不存在或无权限")
    analysis_ref = session.get(Analysis, submission.analysis_id)
    if analysis_ref is None:
        raise StageFailed("analysis_not_found", "参考分析不存在")
    task_row = session.get(LearningTask, submission.task_id)
    if task_row is None:
        raise StageFailed("task_not_found", "学习任务不存在")

    # 复用同一条分析流水线处理作业成片（F08）
    job.payload = {**payload, "asset_id": submission.asset_id, "intent": task_row.intent, "kind": "submission"}
    job.type = "analyze_asset"
    _run_analysis(session, job, worker_id=worker_id, started=started)
    job.type = "analyze_submission"
    session.add(job)
    session.flush()

    if job.result_id:
        submission.submission_analysis_id = job.result_id
        submission.status = "analyzed"
        session.add(submission)
        session.flush()

    with Stage(session, job, "teaching") as stage:
        stage.note(inputs={"submission_id": submission.id, "task_id": task_row.id})
        submission_analysis = session.get(Analysis, job.result_id) if job.result_id else None
        if submission_analysis is None:
            raise StageFailed("submission_analysis_missing", "作业分析结果缺失")
        reference_payload = {
            "intent": analysis_ref.intent,
            "duration_ms": analysis_ref.metrics.get("duration_ms") or 0,
            "shots": _analysis_shots(analysis_ref),
        }
        submission_payload = {
            "intent": task_row.intent,
            "duration_ms": submission_analysis.metrics.get("duration_ms") or 0,
            "shots": _analysis_shots(submission_analysis),
        }
        task_payload = {
            "intent": task_row.intent,
            "level": task_row.level,
            "constraints": task_row.constraints,
        }
        from ..learning.feedback import build_feedback

        feedback_payload = build_feedback(
            reference=reference_payload,
            submission=submission_payload,
            task=task_payload,
            storyboard_text=submission.storyboard_text or "",
        )
        row = Feedback(
            submission_id=submission.id,
            owner_id=job.owner_id,
            metrics=feedback_payload["metrics"],
            alignments=feedback_payload["alignments"],
            suggestions=feedback_payload["suggestions"],
            evidence=feedback_payload["evidence"],
            summary=feedback_payload["summary"],
            storyboard_metrics=feedback_payload["storyboard_metrics"],
            reference_metrics=feedback_payload["reference_metrics"],
            submission_metrics=feedback_payload["submission_metrics"],
            constraint_results=feedback_payload["constraint_results"],
            task_snapshot={
                "id": task_row.id,
                "level": task_row.level,
                "intent": task_row.intent,
                "title": task_row.title,
                "evaluation_focus": (task_row.constraints or {}).get("level_note", ""),
                "constraints": task_row.constraints,
            },
            disclaimer=feedback_payload["disclaimer"],
            review_status="unreviewed",
        )
        session.add(row)
        session.flush()
        stage.finish(
            version=get_settings().knowledge_version,
            feedback_id=row.id,
            suggestions=len(feedback_payload["suggestions"]),
            alignments=len(feedback_payload["alignments"]),
        )
        job.result_type = "feedback"
        job.result_id = row.id
        session.add(job)
        session.flush()


def _run_cleanup(session: Session, job: Job, *, worker_id: str, started: float) -> None:
    payload = job.payload or {}
    project_id = str(payload.get("project_id") or "")
    with Stage(session, job, "preprocessing") as stage:
        stage.note(inputs={"project_id": project_id})
        storage = get_storage()
        pending = (
            session.query(CleanupTask)
            .filter(CleanupTask.project_id == project_id, CleanupTask.status == "pending")
            .all()
        )
        removed = 0
        for task in pending:
            try:
                storage.delete(task.object_key)
                task.status = "done"
                task.processed_at = utcnow()
                removed += 1
            except Exception as exc:  # noqa: BLE001
                task.attempts += 1
                task.error = str(exc)[:200]
                if task.attempts >= 5:
                    task.status = "failed"
            session.add(task)
        # 兜底：按前缀清理派生对象（关键帧、导出、分析归档）
        prefix = "projects/" + project_id + "/"
        try:
            for key in storage.list_prefix(prefix):
                if key.endswith("/original.mp4") or "/assets/" in key:
                    continue
                storage.delete(key)
        except Exception:  # noqa: BLE001
            pass
        stage.finish(version=get_settings().pipeline_version, removed=removed, pending=len(pending))
