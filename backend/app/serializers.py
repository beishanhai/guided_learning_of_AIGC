"""ORM -> API 输出转换（含短期签名地址生成）。"""

from __future__ import annotations

from typing import Any

from .config import get_settings
from .models import Analysis, Asset, Feedback, Job, JobStage, LearningTask, Project, Shot, Submission, User
from .storage import get_storage


def iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def user_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "subject": user.subject,
        "display_name": user.display_name,
        "role": user.role,
        "created_at": iso(user.created_at),
    }


def asset_out(asset: Asset, *, with_url: bool = True) -> dict[str, Any]:
    url = ""
    if with_url and asset.status == "ready":
        try:
            url = get_storage().signed_url(asset.object_key)
        except Exception:  # noqa: BLE001
            url = ""
    return {
        "id": asset.id,
        "project_id": asset.project_id,
        "status": asset.status,
        "duration_ms": asset.duration_ms,
        "width": asset.width,
        "height": asset.height,
        "fps": asset.fps,
        "has_audio": asset.has_audio,
        "video_codec": asset.video_codec,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "sha256": asset.sha256,
        "is_vfr": asset.is_vfr,
        "rejection_code": asset.rejection_code,
        "rejection_reason": asset.rejection_reason,
        "playback_url": url,
        "created_at": iso(asset.created_at),
    }


def project_out(project: Project, *, asset_count: int = 0, analysis_count: int = 0) -> dict[str, Any]:
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "rights_note": project.rights_note,
        "created_at": iso(project.created_at),
        "deleted_at": iso(project.deleted_at),
        "asset_count": asset_count,
        "analysis_count": analysis_count,
    }


def stage_out(stage: JobStage) -> dict[str, Any]:
    return {
        "stage": stage.stage,
        "status": stage.status,
        "attempt": stage.attempt,
        "duration_ms": stage.duration_ms,
        "provider_request_id": stage.provider_request_id,
        "version": stage.version,
        "input_summary": stage.input_summary or {},
        "output_summary": stage.output_summary or {},
        "error": stage.error,
        "started_at": iso(stage.started_at),
        "finished_at": iso(stage.finished_at),
    }


def job_out(job: Job, *, with_stages: bool = True) -> dict[str, Any]:
    links: dict[str, str] = {}
    prefix = get_settings().api_prefix
    if job.result_type == "analysis" and job.result_id:
        links["analysis"] = prefix + "/analyses/" + job.result_id
    if job.result_type == "feedback" and job.result_id:
        links["feedback"] = prefix + "/feedback/" + job.result_id
    submission_id = str((job.payload or {}).get("submission_id") or "")
    if submission_id:
        links["submission"] = prefix + "/submissions/" + submission_id
        if job.result_id:
            links["submission_feedback"] = prefix + "/submissions/" + submission_id + "/feedback"
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "stage": job.stage,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "progress": job.progress,
        "partial": job.partial,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "result_type": job.result_type,
        "result_id": job.result_id,
        "estimated_cost_cny": job.estimated_cost_cny,
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
        "stages": [stage_out(item) for item in (job.stages if with_stages else [])],
        "links": links,
    }


def shot_out(shot: Shot, *, with_urls: bool = True) -> dict[str, Any]:
    storage = get_storage()
    frames = []
    for index, key in enumerate(shot.frame_keys or []):
        url = ""
        if with_urls:
            try:
                url = storage.signed_url(key)
            except Exception:  # noqa: BLE001
                url = ""
        frames.append({"frame_key": key, "url": url})
    knowledge = []
    return {
        "id": shot.id,
        "shot_ref": shot.shot_ref,
        "index": shot.index,
        "start_ms": shot.start_ms,
        "end_ms": shot.end_ms,
        "duration_ms": max(0, shot.end_ms - shot.start_ms),
        "observation": shot.observation,
        "shot_scale": shot.shot_scale,
        "camera_motion": shot.camera_motion,
        "interpretation": shot.interpretation,
        "alternative": shot.alternative,
        "narrative_function": shot.narrative_function,
        "dialogue": shot.dialogue,
        "frames": frames,
        "frame_keys": shot.frame_keys or [],
        "evidence": shot.evidence or [],
        "knowledge_ids": shot.knowledge_ids or [],
        "knowledge": knowledge,
        "unknowns": shot.unknowns or [],
        "confidence": shot.confidence,
        "review_status": shot.review_status,
        "source": shot.source,
    }


def analysis_out(
    analysis: Analysis,
    *,
    with_urls: bool = True,
    knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shots = [shot_out(shot, with_urls=with_urls) for shot in analysis.shots]
    if knowledge:
        for shot in shots:
            shot["knowledge"] = [
                {
                    "id": card_id,
                    "title": knowledge[card_id]["title"],
                    "topic": knowledge[card_id]["topic"],
                    "content": knowledge[card_id]["content"],
                    "source": knowledge[card_id]["source"],
                }
                for card_id in shot["knowledge_ids"]
                if card_id in knowledge
            ]
    return {
        "id": analysis.id,
        "asset_id": analysis.asset_id,
        "project_id": analysis.project_id,
        "version": analysis.version,
        "kind": analysis.kind,
        "intent": analysis.intent,
        "status": analysis.status,
        "model_id": analysis.model_id,
        "prompt_version": analysis.prompt_version,
        "knowledge_version": analysis.knowledge_version,
        "schema_version": analysis.schema_version,
        "pipeline_version": analysis.pipeline_version,
        "coverage": analysis.coverage or {},
        "transcript": analysis.transcript or {},
        "media": analysis.media or {},
        "metrics": analysis.metrics or {},
        "unknowns": analysis.unknowns or {},
        "review_status": analysis.review_status,
        "edited_by_user": analysis.edited_by_user,
        "is_demo_prebuilt": analysis.is_demo_prebuilt,
        "created_at": iso(analysis.created_at),
        "shots": shots,
    }


def task_out(task: LearningTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "analysis_id": task.analysis_id,
        "intent": task.intent,
        "level": task.level,
        "title": task.title,
        "objective": task.objective,
        "prerequisites": task.prerequisites or [],
        "steps": task.steps or [],
        "constraints": task.constraints or {},
        "submission_requirements": task.submission_requirements or [],
        "rubric": task.rubric or [],
        "estimated_minutes": task.estimated_minutes,
        "tools": task.tools or [],
        "reference_metrics": task.reference_metrics or {},
        "version": task.version,
        "knowledge_version": task.knowledge_version,
        "created_at": iso(task.created_at),
    }


def submission_out(submission: Submission) -> dict[str, Any]:
    return {
        "id": submission.id,
        "task_id": submission.task_id,
        "asset_id": submission.asset_id,
        "analysis_id": submission.analysis_id,
        "submission_analysis_id": submission.submission_analysis_id,
        "learner_reason": submission.learner_reason,
        "storyboard_text": submission.storyboard_text,
        "status": submission.status,
        "version": submission.version,
        "created_at": iso(submission.created_at),
    }


def feedback_out(feedback: Feedback) -> dict[str, Any]:
    return {
        "id": feedback.id,
        "submission_id": feedback.submission_id,
        "summary": feedback.summary,
        "metrics": feedback.metrics or {},
        "alignments": feedback.alignments or [],
        "suggestions": feedback.suggestions or [],
        "evidence": feedback.evidence or {},
        "storyboard_metrics": feedback.storyboard_metrics or {},
        "reference_metrics": feedback.reference_metrics or {},
        "submission_metrics": feedback.submission_metrics or {},
        "constraint_results": feedback.constraint_results or [],
        "task_snapshot": feedback.task_snapshot or {},
        "disclaimer": feedback.disclaimer or "",
        "review_status": feedback.review_status,
        "created_at": iso(feedback.created_at),
    }
