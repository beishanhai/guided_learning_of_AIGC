"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import JobPanel from "../../../components/JobPanel";
import UploadPanel from "../../../components/UploadPanel";
import { useMeta } from "../../../components/useMeta";
import {
  ApiError,
  endpoints,
  getToken,
  newIdempotencyKey,
  pollJob,
  resolveApiUrl,
} from "../../../lib/api";
import {
  ASSET_STATUS_LABELS,
  formatBytes,
  formatDateTime,
  formatDuration,
  formatSeconds,
} from "../../../lib/format";
import type { Asset, Job, Project } from "../../../lib/types";

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const projectId = params?.id || "";
  const router = useRouter();
  const { meta } = useMeta();

  const [authed, setAuthed] = useState(false);
  const [project, setProject] = useState<Project | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [intent, setIntent] = useState("shot_language");
  const [generateTask, setGenerateTask] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [job, setJob] = useState<Job | null>(null);

  const cancelRef = useRef({ cancelled: false });
  const polledJobRef = useRef("");

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      const [projectData, assetData] = await Promise.all([
        endpoints.getProject(projectId),
        endpoints.listAssets(projectId),
      ]);
      setProject(projectData);
      setAssets(assetData);
      setSelectedAssetId((current) => {
        if (current && assetData.some((asset) => asset.id === current && asset.status === "ready")) return current;
        const firstReady = assetData.find((asset) => asset.status === "ready");
        return firstReady ? firstReady.id : "";
      });
    } catch (err) {
      setError((err as ApiError).message || "读取项目失败");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/?reason=required");
      return;
    }
    setAuthed(true);
    void load();
  }, [load, router]);

  useEffect(() => {
    if (!meta) return;
    setIntent((current) => (meta.intents.some((item) => item.key === current) ? current : meta.intents[0]?.key || current));
  }, [meta]);

  const watchJob = useCallback(
    async (jobId: string) => {
      polledJobRef.current = jobId;
      cancelRef.current = { cancelled: false };
      try {
        const finished = await pollJob(jobId, setJob, cancelRef.current);
        if (finished.status === "succeeded" && finished.result_type === "analysis" && finished.result_id) {
          setNotice("拆解完成，正在打开分析工作台…");
          router.push("/analyses/" + finished.result_id);
        } else if (finished.status === "succeeded") {
          setNotice("任务已完成。");
          await load();
        } else {
          await load();
        }
      } catch (err) {
        setSubmitError((err as ApiError).message || "轮询任务失败");
      }
    },
    [load, router],
  );

  async function submitAnalysis(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedAssetId) {
      setSubmitError("请先选择一个已通过校验的素材");
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    setNotice("");
    setJob(null);
    try {
      const created = await endpoints.createAnalysis(
        projectId,
        {
          asset_id: selectedAssetId,
          intent,
          generate_task: generateTask,
        },
        newIdempotencyKey(),
      );
      if (created.idempotent_replay) {
        setNotice("该请求与此前提交重复，服务端复用了同一个任务（幂等重放）。");
      }
      void watchJob(created.job_id);
    } catch (err) {
      setSubmitError((err as ApiError).message || "提交拆解任务失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelJob() {
    if (!job) return;
    cancelRef.current.cancelled = true;
    try {
      await endpoints.cancelJob(job.id);
      setNotice("已请求取消任务。");
    } catch (err) {
      setSubmitError((err as ApiError).message || "取消任务失败");
    }
  }

  async function retryJob() {
    if (!job) return;
    try {
      const created = await endpoints.retryJob(job.id);
      setNotice("已重新排队，只重跑失败阶段。");
      void watchJob(created.job_id);
    } catch (err) {
      setSubmitError((err as ApiError).message || "重试失败");
    }
  }

  if (!authed) {
    return (
      <div className="page">
        <div className="skeleton" style={{ height: 160 }} />
      </div>
    );
  }

  const readyAssets = assets.filter((asset) => asset.status === "ready");

  return (
    <div className="page stack">
      <div className="row-between">
        <div>
          <div className="dim">
            <Link href="/projects">← 返回项目列表</Link>
          </div>
          <h1>{project ? project.title : "项目详情"}</h1>
          {project ? (
            <p className="muted">
              {project.description || "（无描述）"} · 创建于 {formatDateTime(project.created_at)}
            </p>
          ) : null}
        </div>
        <button type="button" className="btn-ghost btn-sm" onClick={() => void load()} disabled={loading}>
          刷新
        </button>
      </div>

      {loading ? <div className="skeleton" style={{ height: 160 }} /> : null}
      {error ? <div className="callout callout-danger">{error}</div> : null}
      {notice ? <div className="callout callout-ok">{notice}</div> : null}

      {project ? (
        <div className="grid-2">
          <UploadPanel
            projectId={projectId}
            limits={meta ? meta.limits : null}
            buttonLabel="上传并校验"
            onUploaded={() => {
              void load();
            }}
          />

          <div className="card">
            <div className="panel-title">素材（{assets.length}）</div>
            {assets.length === 0 ? (
              <div className="empty">还没有素材。先在左侧上传一段参考短片。</div>
            ) : (
              <div className="stack" style={{ gap: 14 }}>
                {assets.map((asset) => (
                  <div key={asset.id} className="card-flat">
                    <div className="row-between">
                      <div className="mono">{asset.id}</div>
                      <span
                        className={
                          "badge " +
                          (asset.status === "ready"
                            ? "badge-ok"
                            : asset.status === "rejected"
                              ? "badge-danger"
                              : "badge-warn")
                        }
                      >
                        {ASSET_STATUS_LABELS[asset.status] || asset.status}
                      </span>
                    </div>

                    {asset.status === "ready" && asset.playback_url ? (
                      <video
                        controls
                        preload="metadata"
                        src={resolveApiUrl(asset.playback_url)}
                        style={{ marginTop: 8 }}
                      />
                    ) : null}

                    {asset.rejection_reason ? (
                      <div className="callout callout-danger" style={{ marginTop: 8 }}>
                        <span className="mono">{asset.rejection_code}</span> · {asset.rejection_reason}
                      </div>
                    ) : null}

                    <div className="kv" style={{ marginTop: 8 }}>
                      <dt>时长</dt>
                      <dd>
                        {formatDuration(asset.duration_ms)}（{formatSeconds(asset.duration_ms, 2)}）
                      </dd>
                      <dt>分辨率</dt>
                      <dd>
                        {asset.width} × {asset.height}
                      </dd>
                      <dt>帧率</dt>
                      <dd>{asset.fps ? asset.fps.toFixed(2) + " fps" : "—"}</dd>
                      <dt>编码</dt>
                      <dd>{asset.video_codec || "—"}</dd>
                      <dt>音轨</dt>
                      <dd>{asset.has_audio ? "有" : "无"}</dd>
                      <dt>大小</dt>
                      <dd>{formatBytes(asset.size_bytes)}</dd>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}

      <form className="card" onSubmit={submitAnalysis}>
        <div className="panel-title">提交拆解</div>
        {readyAssets.length === 0 ? (
          <div className="callout callout-warn">
            暂无可提交的素材。请先上传并通过服务端媒体验证（状态变为「可用」）。
          </div>
        ) : (
          <>
            <div className="field">
              <label htmlFor="asset-select">选择素材</label>
              <select
                id="asset-select"
                value={selectedAssetId}
                onChange={(event) => setSelectedAssetId(event.target.value)}
              >
                {readyAssets.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.id} · {formatDuration(asset.duration_ms)} · {asset.width}×{asset.height}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label>学习意图</label>
              <div className="row" style={{ gap: 16 }}>
                {(meta?.intents || []).map((item) => (
                  <label key={item.key} className="checkbox">
                    <input
                      type="radio"
                      name="intent"
                      value={item.key}
                      checked={intent === item.key}
                      onChange={() => setIntent(item.key)}
                    />
                    {item.label}
                  </label>
                ))}
              </div>
              {meta ? (
                <div className="dim" style={{ marginTop: 4 }}>
                  {(meta.intents.find((item) => item.key === intent) || {}).goal || ""}
                </div>
              ) : null}
            </div>

            <label className="checkbox" style={{ marginBottom: 12 }}>
              <input
                type="checkbox"
                checked={generateTask}
                onChange={(event) => setGenerateTask(event.target.checked)}
              />
              同时生成学习任务（模仿级别，可在分析页再生成变体与原创）
            </label>

            <div className="row">
              <button type="submit" className="btn-primary" disabled={submitting || !selectedAssetId}>
                {submitting ? "提交中…" : "提交拆解任务"}
              </button>
              <span className="dim">提交后每 1.5 秒轮询一次任务状态，最多 15 分钟。</span>
            </div>
          </>
        )}

        {submitError ? (
          <div className="callout callout-danger" style={{ marginTop: 12 }}>
            {submitError}
          </div>
        ) : null}

        {job ? (
          <div style={{ marginTop: 14 }}>
            <JobPanel job={job} title="拆解任务进度" onCancel={() => void cancelJob()} onRetry={() => void retryJob()} />
          </div>
        ) : null}
      </form>

      {project && project.analysis_count > 0 ? (
        <div className="callout callout-info">
          该项目已有 {project.analysis_count} 个分析版本。分析列表可通过项目 ID 查询：
          <span className="mono"> GET /analyses?project_id={projectId}</span>
        </div>
      ) : null}
    </div>
  );
}
