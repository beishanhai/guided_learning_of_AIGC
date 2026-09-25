"""对真实运行中的服务做端到端冒烟（HTTP，不用 TestClient）。

用法：先启动 uvicorn 与 app.worker，然后
    python tools/smoke_http.py [参考片路径] [作业片路径]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
API = BASE + "/api/v1"
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ref = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "dev" / "fastcut_20s.mp4"
    work = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "samples" / "dev" / "dissolve_30s.mp4"
    client = httpx.Client(timeout=60.0)

    health = client.get(API + "/healthz").json()
    print("healthz:", health["status"], "| ffmpeg", health["ffmpeg"], "| backlog", health["worker_backlog"])

    token = client.post(API + "/auth/login", json={"subject": "alice", "password": "alice-pass-123"}).json()
    headers = {"Authorization": "Bearer " + token["access_token"]}
    print("login:", token["user"]["subject"])

    project = client.post(API + "/projects", json={"title": "HTTP 冒烟 " + time.strftime("%H:%M:%S")}, headers=headers).json()
    print("project:", project["id"][:8])

    asset_id = upload(client, headers, project["id"], ref)
    intent = "shot_language"
    job = client.post(
        API + "/projects/" + project["id"] + "/analyses",
        json={"asset_id": asset_id, "intent": intent, "generate_task": True},
        headers={**headers, "Idempotency-Key": "smoke-" + asset_id},
    ).json()
    result = wait(client, headers, job["job_id"])
    analysis = client.get(API + "/analyses/" + result["result_id"], headers=headers).json()
    print("analysis v" + str(analysis["version"]), "| shots", len(analysis["shots"]),
          "| provider", analysis["coverage"]["provider"], "| status", analysis["status"])
    print("  metrics:", {k: analysis["metrics"][k] for k in ("shot_count", "shot_duration_mean_ms", "scale_unknown_count")})
    print("  first shot:", analysis["shots"][0]["shot_ref"], analysis["shots"][0]["shot_scale"],
          "| evidence", len(analysis["shots"][0]["evidence"]),
          "| knowledge", analysis["shots"][0]["knowledge_ids"])

    task = client.post(
        API + "/analyses/" + analysis["id"] + "/learning-tasks",
        json={"level": "variant", "intent": intent},
        headers=headers,
    ).json()
    print("task:", task["level"], "| steps", len(task["steps"]), "| rubric", len(task["rubric"]),
          "| minutes", task["estimated_minutes"])

    sub_asset = upload(client, headers, project["id"], work)
    sub = client.post(
        API + "/learning-tasks/" + task["id"] + "/submissions",
        json={"asset_id": sub_asset, "learner_reason": "我把两个镜头合并。",
              "storyboard_text": "镜头1：全景，3秒，为了交代环境。\n镜头2：近景，2秒。"},
        headers={**headers, "Idempotency-Key": "smoke-sub-" + sub_asset},
    ).json()
    sub_result = wait(client, headers, sub["job_id"])
    feedback = client.get(API + "/feedback/" + sub_result["result_id"], headers=headers).json()
    print("feedback:", len(feedback["suggestions"]), "suggestions |", len(feedback["alignments"]), "alignments",
          "| storyboard checks", feedback["storyboard_metrics"]["passed_count"], "/",
          feedback["storyboard_metrics"]["total_count"])
    for item in feedback["suggestions"][:2]:
        print("   -", item["target"], "->", item["action"][:60])

    export = client.get(API + "/analyses/" + analysis["id"] + "/export?format=md", headers=headers)
    print("export md:", export.status_code, len(export.text), "chars")

    demo = client.get(BASE + "/demo")
    print("demo page:", demo.status_code, len(demo.text), "chars")
    return 0


def upload(client: httpx.Client, headers: dict, project_id: str, path: Path) -> str:
    data = path.read_bytes()
    ticket = client.post(
        API + "/projects/" + project_id + "/uploads",
        json={"filename": path.name, "size_bytes": len(data), "media_type": "video/mp4"},
        headers=headers,
    ).json()
    url = ticket["upload_url"]
    if url.startswith("/"):
        url = BASE + url
    response = client.put(url, content=data, headers={"Content-Type": "video/mp4"})
    assert response.status_code == 204, response.text
    check = client.post(API + "/assets/" + ticket["asset_id"] + "/complete", headers=headers)
    assert check.status_code == 200, check.text
    asset = check.json()["asset"]
    print("upload:", path.name, asset["width"], "x", asset["height"], asset["video_codec"],
          "audio", asset["has_audio"])
    return ticket["asset_id"]


def wait(client: httpx.Client, headers: dict, job_id: str, timeout: float = 900.0) -> dict:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        job = client.get(API + "/jobs/" + job_id, headers=headers).json()
        line = job["status"] + "/" + job["stage"] + " " + str(job["progress"]) + "%"
        if line != last:
            print("   job:", line)
            last = line
        if job["status"] in ("succeeded", "failed", "cancelled"):
            assert job["status"] == "succeeded", job
            return job
        time.sleep(1.5)
    raise TimeoutError(job_id)


if __name__ == "__main__":
    raise SystemExit(main())
