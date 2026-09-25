"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import JobPanel from "../../../components/JobPanel";
import UploadPanel from "../../../components/UploadPanel";
import { useMeta } from "../../../components/useMeta";
import { ApiError, endpoints, getToken, newIdempotencyKey, pollJob } from "../../../lib/api";
import { describeConstraint, formatDateTime, intentLabel, levelLabel } from "../../../lib/format";
import type { Analysis, Job, LearningTask } from "../../../lib/types";
import styles from "./task.module.css";

export default function TaskPage() {
  const params = useParams<{ id: string }>();
  const taskId = params?.id || "";
  const router = useRouter();
  const { meta } = useMeta();

  const [authed, setAuthed] = useState(false);
  const [task, setTask] = useState<LearningTask | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [assetId, setAssetId] = useState("");
  const [learnerReason, setLearnerReason] = useState("");
  const [storyboardText, setStoryboardText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const cancelRef = useRef({ cancelled: false });

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError("");
    try {
      const data = await endpoints.getLearningTask(taskId);
      setTask(data);
      try {
        setAnalysis(await endpoints.getAnalysis(data.analysis_id));
      } catch {
        setAnalysis(null);
      }
    } catch (err) {
      setError((err as ApiError).message || "读取学习任务失败");
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/?reason=required");
      return;
    }
    setAuthed(true);
    void load();
  }, [load, router]);

  const resolveSubmissionId = useCallback(
    async (finished: Job): Promise<string> => {
      const list = await endpoints.listSubmissions(taskId);
      if (list.length > 0) return list[0].id;
      if (finished.result_id) {
        const feedback = await endpoints.getFeedbackById(finished.result_id);
        return feedback.submission_id;
      }
      return "";
    },
    [taskId],
  );

  const watchJob = useCallback(
    async (jobId: string) => {
      cancelRef.current = { cancelled: false };
      try {
        const finished = await pollJob(jobId, setJob, cancelRef.current);
        if (finished.status === "succeeded") {
          const submissionId = await resolveSubmissionId(finished);
          if (submissionId) {
            setNotice("反馈已生成，正在打开反馈页…");
            router.push("/submissions/" + submissionId);
          } else {
            setSubmitError("任务已完成，但未能定位作业记录，请到任务列表刷新查看。");
          }
        }
      } catch (err) {
        setSubmitError((err as ApiError).message || "轮询任务失败");
      }
    },
    [resolveSubmissionId, router],
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!assetId) {
      setSubmitError("请先上传并通过校验作业成片，或提交文字分镜（P1）后重试。");
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    setNotice("");
    setJob(null);
    try {
      const created = await endpoints.createSubmission(
        taskId,
        { asset_id: assetId, learner_reason: learnerReason, storyboard_text: storyboardText },
        newIdempotencyKey(),
      );
      if (created.idempotent_replay) {
        setNotice("该提交与此前重复，服务端复用了同一个任务（幂等重放）。");
      }
      void watchJob(created.job_id);
    } catch (err) {
      setSubmitError((err as ApiError).message || "提交作业失败");
    } finally {
      setSubmitting(false);
    }
  }

  if (!authed) {
    return (
      <div className="page">
        <div className="skeleton" style={{ height: 200 }} />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="page stack">
        <div className="skeleton" style={{ height: 40, width: "50%" }} />
        <div className="skeleton" style={{ height: 220 }} />
        <div className="skeleton" style={{ height: 220 }} />
      </div>
    );
  }

  if (!task) {
    return (
      <div className="page stack">
        <div className="callout callout-danger">{error || "学习任务不存在或不可访问。"}</div>
        <Link href="/projects">← 返回项目列表</Link>
      </div>
    );
  }

  return (
    <div className="page stack">
      <div className="row-between">
        <div>
          <div className="dim">
            <Link href={"/analyses/" + task.analysis_id}>← 返回拆解工作台</Link>
          </div>
          <h1>{task.title}</h1>
          <div className="row" style={{ gap: 8, marginTop: 4 }}>
            <span className="badge badge-accent">{levelLabel(task.level)}</span>
            <span className="badge">{intentLabel(task.intent)}</span>
            <span className="badge">预计 {task.estimated_minutes} 分钟</span>
            <span className="badge mono">v{task.version}</span>
            <span className="dim">创建于 {formatDateTime(task.created_at)}</span>
          </div>
        </div>
        <button type="button" className="btn-ghost btn-sm" onClick={() => void load()}>
          刷新
        </button>
      </div>

      {notice ? <div className="callout callout-ok">{notice}</div> : null}
      {error ? <div className="callout callout-danger">{error}</div> : null}

      <div className={styles.grid}>
        <section className="card">
          <div className="panel-title">学习目标</div>
          <p>{task.objective}</p>
          <div className="callout callout-info" style={{ marginTop: 8 }}>
            级别固定约束：
            {task.constraints && typeof task.constraints.level_note === "string"
              ? String(task.constraints.level_note)
              : "见任务约束"}
            。系统内自动生成不是完成任务的前提，可用外部工具制作后上传。
          </div>
        </section>

        <section className="card">
          <div className="panel-title">先修知识（{task.prerequisites.length}）</div>
          {task.prerequisites.length === 0 ? (
            <div className="empty">本任务没有先修知识卡片要求。</div>
          ) : (
            <div className="stack" style={{ gap: 10 }}>
              {task.prerequisites.map((item) => (
                <div key={item.knowledge_id} className="card-flat">
                  <div className="row-between">
                    <strong>{item.title}</strong>
                    <span className="tag mono">{item.knowledge_id}</span>
                  </div>
                  <p style={{ marginTop: 6 }}>{item.content}</p>
                  {item.source ? <div className="dim">来源：{item.source}</div> : null}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="card">
        <div className="panel-title">步骤</div>
        <ol className={styles.steps}>
          {task.steps.map((step, index) => (
            <li key={step.index || index}>
              <strong>{step.title}</strong>
              <div className="muted">{step.detail}</div>
            </li>
          ))}
        </ol>
      </section>

      <div className={styles.grid}>
        <section className="card">
          <div className="panel-title">约束</div>
          {!task.constraints || Object.keys(task.constraints).length === 0 ? (
            <div className="empty">本任务未附加结构约束。</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th style={{ width: 170 }}>约束键</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(task.constraints).map(([key, value]) => (
                  <tr key={key}>
                    <td className="mono dim">{key}</td>
                    <td>{describeConstraint(key, value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="card">
          <div className="panel-title">提交要求</div>
          <ul className="plain">
            {task.submission_requirements.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card">
        <div className="panel-title">评价量表（0—4 分）</div>
        <p className="dim">每个维度单独评分，不合并为单一总分。</p>
        <table>
          <thead>
            <tr>
              <th style={{ width: 180 }}>维度</th>
              <th style={{ width: 90 }}>满分</th>
              <th>评分尺度</th>
            </tr>
          </thead>
          <tbody>
            {task.rubric.map((item) => (
              <tr key={item.key}>
                <td>{item.criterion}</td>
                <td className="num">{item.max_score}</td>
                <td className="muted">{item.scale}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <div className="panel-title">可用工具</div>
        <ul className="plain">
          {task.tools.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      </section>

      <h2>提交作业</h2>

      {analysis ? (
        <UploadPanel
          projectId={analysis.project_id}
          limits={meta ? meta.limits : null}
          buttonLabel="上传作业成片并校验"
          hint="作业成片走与参考片同一条媒体验证流程；校验通过后会自动选中该素材。"
          onUploaded={(uploadedAssetId) => {
            setAssetId(uploadedAssetId);
            setNotice("作业成片已通过校验，已自动选为提交素材。");
          }}
        />
      ) : (
        <div className="callout callout-warn">
          未能读取参考分析（{task.analysis_id}），无法确定上传所属项目；请先打开拆解工作台确认分析可用。
        </div>
      )}

      <form className="card" onSubmit={submit}>
        <div className="panel-title">提交表单</div>

        <div className="field">
          <label htmlFor="asset-id">作业素材 ID（上传成功后自动填入）</label>
          <input
            id="asset-id"
            value={assetId}
            onChange={(event) => setAssetId(event.target.value.trim())}
            placeholder="例如 3f2c1a..."
            className="mono"
          />
          {assetId ? (
            <div className="dim" style={{ marginTop: 4 }}>
              将提交素材 {assetId}。服务端会校验其状态必须为「可用」。
            </div>
          ) : null}
        </div>

        <div className="field">
          <label htmlFor="reason">创作说明（想表达什么 / 为什么这样安排镜头 / 参考了本片的哪一处做法）</label>
          <textarea
            id="reason"
            value={learnerReason}
            onChange={(event) => setLearnerReason(event.target.value)}
            placeholder="用 3 句话写清你的表达意图与结构选择。"
            style={{ minHeight: 110 }}
          />
        </div>

        <div className="field">
          <label htmlFor="storyboard">文字分镜（可选，P1：文字分镜评分与成片评分分开呈现）</label>
          <textarea
            id="storyboard"
            value={storyboardText}
            onChange={(event) => setStoryboardText(event.target.value)}
            placeholder={"示例：\n镜头1：全景，3秒，交代环境。\n镜头2：中景，2秒，引入主体。\n镜头3：特写，2秒，强调情绪（因为要让观众注意到手部）。"}
            style={{ minHeight: 150 }}
          />
        </div>

        <div className="row">
          <button type="submit" className="btn-primary" disabled={submitting || !assetId}>
            {submitting ? "提交中…" : "提交作业并请求反馈"}
          </button>
          <span className="dim">提交后每 1.5 秒轮询一次任务状态，最多 15 分钟。</span>
        </div>

        {submitError ? (
          <div className="callout callout-danger" style={{ marginTop: 12 }}>
            {submitError}
          </div>
        ) : null}

        {job ? (
          <div style={{ marginTop: 14 }}>
            <JobPanel job={job} title="作业分析与反馈任务" />
          </div>
        ) : null}
      </form>
    </div>
  );
}
