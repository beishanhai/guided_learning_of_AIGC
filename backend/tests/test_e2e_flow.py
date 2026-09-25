"""端到端闭环：上传 -> 拆解 -> 学习任务 -> 作业 -> 反馈 -> 导出 -> 删除。

覆盖验收用例 F01、F03、F04、F05、F06、F07、F08、F09。
"""

from __future__ import annotations

from .conftest import run_worker, sample_path, upload_file


def _submit_analysis(client, headers, project_id, asset_id, intent="shot_language", idem="e2e-analysis-1"):
    response = client.post(
        "/api/v1/projects/" + project_id + "/analyses",
        json={"asset_id": asset_id, "intent": intent, "generate_task": True},
        headers={**headers, "Idempotency-Key": idem},
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def test_analysis_pipeline(client, alice_headers, uploaded_asset):
    project_id, asset_id = uploaded_asset
    job_id = _submit_analysis(client, alice_headers, project_id, asset_id)
    assert run_worker() >= 1

    job = client.get("/api/v1/jobs/" + job_id, headers=alice_headers).json()
    assert job["status"] == "succeeded", job
    assert [stage["stage"] for stage in job["stages"]][:3] == ["preprocessing", "analyzing", "teaching"]
    analysis_id = job["result_id"]

    analysis = client.get("/api/v1/analyses/" + analysis_id, headers=alice_headers).json()
    assert analysis["status"] in ("ready", "partial")
    shots = analysis["shots"]
    assert len(shots) >= 8, "20 秒 10 段硬切的样片应被切成至少 8 个镜头"

    for shot in shots:
        assert shot["observation"]
        assert isinstance(shot["unknowns"], list) and shot["unknowns"]
        assert shot["evidence"], "每个镜头都应有可跳转的证据时间点"
        for item in shot["evidence"]:
            assert shot["start_ms"] - 1 <= item["timestamp_ms"] <= shot["end_ms"] + 1000
    assert analysis["coverage"]["frames_truncated"] is False
    assert analysis["media"]["duration_ms"] > 0
    assert analysis["unknowns"]["items"]
    assert analysis["knowledge_version"]

    first = client.get(
        "/api/v1/analyses/" + analysis_id + "/explanations?intent=shot_language", headers=alice_headers
    ).json()
    second = client.get(
        "/api/v1/analyses/" + analysis_id + "/explanations?intent=narrative_rhythm", headers=alice_headers
    ).json()
    assert first["fact_timeline_unchanged"] is True
    assert first["explanations"][0]["intent_reading"] != second["explanations"][0]["intent_reading"]
    assert first["explanations"][0]["shot_ref"] == second["explanations"][0]["shot_ref"]


def test_task_templates_and_human_edit(client, alice_headers, uploaded_asset):
    project_id, asset_id = uploaded_asset
    job_id = _submit_analysis(
        client, alice_headers, project_id, asset_id, intent="narrative_rhythm", idem="e2e-analysis-2"
    )
    run_worker()
    job = client.get("/api/v1/jobs/" + job_id, headers=alice_headers).json()
    assert job["status"] == "succeeded", job
    analysis_id = job["result_id"]
    analysis = client.get("/api/v1/analyses/" + analysis_id, headers=alice_headers).json()

    task_ids = {}
    for level in ("imitate", "variant", "original"):
        created = client.post(
            "/api/v1/analyses/" + analysis_id + "/learning-tasks",
            json={"level": level, "intent": "narrative_rhythm"},
            headers=alice_headers,
        )
        assert created.status_code == 201, created.text
        task = created.json()
        assert task["objective"]
        assert 3 <= len(task["steps"]) <= 5
        assert task["submission_requirements"]
        assert len(task["rubric"]) == 4
        assert task["estimated_minutes"] > 0
        assert task["tools"]
        assert task["constraints"]
        task_ids[level] = task["id"]
    assert len(set(task_ids.values())) == 3

    shots = analysis["shots"]
    patched = client.patch(
        "/api/v1/analyses/" + analysis_id + "/shots",
        json={
            "expected_version": analysis["version"],
            "review_status": "confirmed",
            "shots": [{"shot_ref": shots[0]["shot_ref"], "end_ms": shots[0]["end_ms"]}],
        },
        headers=alice_headers,
    )
    assert patched.status_code == 200, patched.text
    new_version = patched.json()
    assert new_version["version"] == analysis["version"] + 1
    assert new_version["edited_by_user"] is True

    conflict = client.patch(
        "/api/v1/analyses/" + analysis_id + "/shots",
        json={"expected_version": analysis["version"], "shots": []},
        headers=alice_headers,
    )
    assert conflict.status_code == 409

    versions = client.get("/api/v1/analyses/" + analysis_id + "/versions", headers=alice_headers).json()
    old = [item for item in versions["versions"] if item["version"] == analysis["version"]][0]
    assert task_ids["imitate"] in old["learning_task_ids"]

    export = client.get("/api/v1/analyses/" + analysis_id + "/export?format=md", headers=alice_headers)
    assert export.status_code == 200
    text = export.content.decode("utf-8")
    assert "观察事实" in text and "不确定性" in text
    assert "v" + str(analysis["version"]) in text


def test_submission_and_feedback(client, alice_headers, uploaded_asset):
    project_id, asset_id = uploaded_asset
    job_id = _submit_analysis(
        client, alice_headers, project_id, asset_id, intent="shot_language", idem="e2e-analysis-3"
    )
    run_worker()
    analysis_id = client.get("/api/v1/jobs/" + job_id, headers=alice_headers).json()["result_id"]
    task = client.post(
        "/api/v1/analyses/" + analysis_id + "/learning-tasks",
        json={"level": "variant", "intent": "shot_language"},
        headers=alice_headers,
    ).json()

    submission_asset_id, complete = upload_file(
        client, alice_headers, project_id, sample_path("dissolve_30s.mp4")
    )
    assert complete.status_code == 200, complete.text
    submission = client.post(
        "/api/v1/learning-tasks/" + task["id"] + "/submissions",
        json={
            "asset_id": submission_asset_id,
            "learner_reason": "我合并了两个镜头，让信息更集中。",
            "storyboard_text": "镜头1：全景，3秒，为了交代环境。\n镜头2：近景，2秒。\n镜头3：特写，1秒。",
        },
        headers={**alice_headers, "Idempotency-Key": "e2e-submission-1"},
    )
    assert submission.status_code == 202, submission.text
    run_worker()
    submission_job = client.get(
        "/api/v1/jobs/" + submission.json()["job_id"], headers=alice_headers
    ).json()
    assert submission_job["status"] == "succeeded", submission_job

    submissions = client.get(
        "/api/v1/submissions?task_id=" + task["id"], headers=alice_headers
    ).json()
    assert submissions
    submission_id = submissions[0]["id"]
    assert submissions[0]["submission_analysis_id"]

    feedback_response = client.get(
        "/api/v1/submissions/" + submission_id + "/feedback", headers=alice_headers
    )
    assert feedback_response.status_code == 200, feedback_response.text
    body = feedback_response.json()
    assert body["suggestions"], "至少给出一条具体可执行建议"
    for suggestion in body["suggestions"]:
        assert suggestion["action"] and suggestion["goal_link"] and suggestion["target"]
    assert body["metrics"]["shot_count"]["reference"] > 0
    assert body["alignments"]
    assert body["storyboard_metrics"]["mode"] == "storyboard_text"


def test_silent_video_has_no_fabricated_dialogue(client, alice_headers):
    """F03：无声视频不得出现虚构台词，视觉流程照常完成。"""

    project = client.post(
        "/api/v1/projects", json={"title": "无声素材测试"}, headers=alice_headers
    ).json()
    asset_id, complete = upload_file(
        client, alice_headers, project["id"], sample_path("silent_18s.mp4")
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["asset"]["has_audio"] is False

    response = client.post(
        "/api/v1/projects/" + project["id"] + "/analyses",
        json={"asset_id": asset_id, "intent": "shot_language"},
        headers={**alice_headers, "Idempotency-Key": "e2e-silent-1"},
    )
    run_worker()
    job = client.get("/api/v1/jobs/" + response.json()["job_id"], headers=alice_headers).json()
    assert job["status"] == "succeeded", job
    analysis = client.get("/api/v1/analyses/" + job["result_id"], headers=alice_headers).json()
    assert analysis["transcript"]["segments"] == []
    for shot in analysis["shots"]:
        assert shot["dialogue"] == ""
