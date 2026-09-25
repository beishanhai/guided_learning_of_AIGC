"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, endpoints, getToken } from "../../../lib/api";
import { formatDateTime, formatDuration, formatSeconds } from "../../../lib/format";
import type {
  Alignment,
  Feedback,
  FeedbackEvidenceItem,
  MetricDelta,
  Submission,
  Suggestion,
} from "../../../lib/types";
import styles from "./submission.module.css";

const METRIC_ROWS: { key: string; label: string; unit: "count" | "ms" | "rate" }[] = [
  { key: "shot_count", label: "镜头数量", unit: "count" },
  { key: "shot_duration_mean_ms", label: "平均镜头时长", unit: "ms" },
  { key: "shot_duration_max_ms", label: "最长镜头", unit: "ms" },
  { key: "cut_rate_per_minute", label: "每分钟切点", unit: "rate" },
  { key: "duration_ms", label: "成片时长", unit: "ms" },
];

function formatMetric(value: unknown, unit: string): string {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  if (unit === "ms") return formatSeconds(number, 2);
  if (unit === "rate") return number.toFixed(2) + " 次/分";
  return String(number);
}

function certaintyLabel(certainty: string): string {
  if (certainty === "confirmed") return "已确认（按 shot_ref 对齐）";
  if (certainty === "candidate") return "候选匹配（需人工确认）";
  if (certainty === "unmatched") return "未匹配（允许）";
  return certainty;
}

function certaintyClass(certainty: string): string {
  if (certainty === "confirmed") return "badge badge-ok";
  if (certainty === "candidate") return "badge badge-warn";
  if (certainty === "unmatched") return "badge badge-danger";
  return "badge";
}

interface SuggestionDetail {
  reference: string;
  submission: string;
  diff: string;
}

function buildSuggestionDetail(
  suggestion: Suggestion,
  feedback: Feedback,
): SuggestionDetail {
  const metrics = feedback.metrics || {};
  const target = suggestion.target;

  if (target === "shot_count" || target === "shot_duration_mean_ms") {
    const delta = metrics[target];
    if (delta) {
      const unit = target === "shot_count" ? "count" : "ms";
      return {
        reference: formatMetric(delta.reference, unit),
        submission: formatMetric(delta.submission, unit),
        diff:
          delta.delta === null
            ? "无法计算"
            : (delta.delta > 0 ? "+" : "") + formatMetric(delta.delta, unit),
      };
    }
  }

  if (target === "scale_distribution") {
    const distribution = metrics.scale_distribution;
    if (distribution) {
      const referenceShots = Object.keys(distribution.reference || {}).filter(
        (key) => key !== "unknown" && (distribution.reference || {})[key] > 0,
      );
      const submissionShots = Object.keys(distribution.submission || {}).filter(
        (key) => key !== "unknown" && (distribution.submission || {})[key] > 0,
      );
      return {
        reference: referenceShots.length > 0 ? referenceShots.join("、") : "无可判定景别",
        submission: submissionShots.length > 0 ? submissionShots.join("、") : "无可判定景别",
        diff: "缺少：" + referenceShots.filter((key) => submissionShots.indexOf(key) < 0).join("、") || "无",
      };
    }
  }

  if (target === "alignment") {
    const unmatched = (feedback.alignments || []).filter(
      (item) => item.certainty === "unmatched" && item.reference_shot_ref,
    )[0];
    if (unmatched) {
      return {
        reference:
          unmatched.reference_shot_ref +
          "（" +
          formatDuration(unmatched.reference_time_ms) +
          "）" +
          (unmatched.reference_summary ? " · " + unmatched.reference_summary : ""),
        submission: "无对应镜头",
        diff: "参考片有、作业无",
      };
    }
  }

  return {
    reference: "见下方镜头对齐表与参考证据",
    submission: "见下方镜头对齐表与作业证据",
    diff: "见结构差异指标表",
  };
}

export default function SubmissionPage() {
  const params = useParams<{ id: string }>();
  const submissionId = params?.id || "";
  const router = useRouter();

  const [authed, setAuthed] = useState(false);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [waiting, setWaiting] = useState(true);
  const [waitSeconds, setWaitSeconds] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const cancelRef = useRef({ cancelled: false });

  const load = useCallback(async () => {
    if (!submissionId) return;
    setLoading(true);
    setError("");
    cancelRef.current = { cancelled: false };
    try {
      const detail = await endpoints.getSubmission(submissionId);
      setSubmission(detail);
      const started = Date.now();
      for (;;) {
        const data = await endpoints.getFeedback(submissionId);
        if (data) {
          setFeedback(data);
          setWaiting(false);
          break;
        }
        setWaiting(true);
        setWaitSeconds(Math.round((Date.now() - started) / 1000));
        if (Date.now() - started > 15 * 60 * 1000) {
          setError("反馈超过 15 分钟仍未生成，请稍后在任务列表查看任务状态。");
          break;
        }
        if (cancelRef.current.cancelled) break;
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    } catch (err) {
      setError((err as ApiError).message || "读取反馈失败");
    } finally {
      setLoading(false);
      setWaiting(false);
    }
  }, [submissionId]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/?reason=required");
      return;
    }
    setAuthed(true);
    void load();
    return () => {
      cancelRef.current.cancelled = true;
    };
  }, [load, router]);


  if (!authed) {
    return (
      <div className="page">
        <div className="skeleton" style={{ height: 200 }} />
      </div>
    );
  }

  if (loading && !feedback) {
    return (
      <div className="page page-narrow stack">
        <h1>作业反馈</h1>
        <div className="callout callout-info">
          正在等待反馈生成…已等待 {waitSeconds} 秒（每 1.5 秒轮询
          <span className="mono"> GET /submissions/{submissionId}/feedback</span>，未生成时返回 404）。
        </div>
        <div className="skeleton" style={{ height: 22, width: "50%" }} />
        <div className="skeleton" style={{ height: 180 }} />
      </div>
    );
  }

  if (!feedback) {
    return (
      <div className="page page-narrow stack">
        <h1>作业反馈</h1>
        <div className="callout callout-danger">{error || "反馈尚未生成。"}</div>
        <div className="row">
          <button type="button" className="btn-primary btn-sm" onClick={() => void load()}>
            重新检查
          </button>
          <Link href="/projects">← 返回项目列表</Link>
        </div>
      </div>
    );
  }

  const alignments = feedback.alignments || [];
  const suggestions = feedback.suggestions || [];
  const referenceEvidence = (feedback.evidence || {}).reference || [];
  const submissionEvidence = (feedback.evidence || {}).submission || [];
  const storyboard = feedback.storyboard_metrics || {};
  const storyboardChecks = storyboard.checks || [];
  const hasStoryboard = storyboardChecks.length > 0;

  return (
    <div className="page stack">
      <div className="row-between">
        <div>
          <div className="dim">
            {submission ? <Link href={"/tasks/" + submission.task_id}>← 返回学习任务</Link> : null}
          </div>
          <h1>作业反馈</h1>
          <div className="row" style={{ gap: 8, marginTop: 4 }}>
            <span className="badge mono">submission {feedback.submission_id}</span>
            <span className="badge">复核状态 {feedback.review_status}</span>
            <span className="dim">生成于 {formatDateTime(feedback.created_at)}</span>
          </div>
        </div>
        <button type="button" className="btn-ghost btn-sm" onClick={() => void load()}>
          刷新
        </button>
      </div>

      <div className="callout callout-info">{feedback.summary}</div>

      <div className="row" style={{ gap: 8 }}>
        {submission ? (
          <>
            <Link href={"/analyses/" + submission.analysis_id}>
              <button type="button" className="btn-sm">
                打开参考拆解
              </button>
            </Link>
            {submission.submission_analysis_id ? (
              <Link href={"/analyses/" + submission.submission_analysis_id}>
                <button type="button" className="btn-sm">
                  打开作业拆解
                </button>
              </Link>
            ) : null}
          </>
        ) : null}
      </div>

      <section className="card">
        <div className="panel-title">结构差异指标（参考 / 作业 / 差异）</div>
        <p className="dim">
          只做可客观计算的对比：镜头数量、时长与切点频率。景别未知的镜头单独统计，不并入任何景别。
        </p>
        <table>
          <thead>
            <tr>
              <th style={{ width: 180 }}>指标</th>
              <th style={{ width: 140 }}>参考片</th>
              <th style={{ width: 140 }}>作业</th>
              <th>差异（作业 − 参考）</th>
            </tr>
          </thead>
          <tbody>
            {METRIC_ROWS.map((row) => {
              const delta = (feedback.metrics || {})[row.key] as MetricDelta | undefined;
              if (!delta) {
                return (
                  <tr key={row.key}>
                    <td>{row.label}</td>
                    <td className="num">—</td>
                    <td className="num">—</td>
                    <td className="num">—</td>
                  </tr>
                );
              }
              const numeric = delta.delta === null || delta.delta === undefined ? null : Number(delta.delta);
              return (
                <tr key={row.key}>
                  <td>{row.label}</td>
                  <td className="num">{formatMetric(delta.reference, row.unit)}</td>
                  <td className="num">{formatMetric(delta.submission, row.unit)}</td>
                  <td className={"num " + (numeric === null ? "" : numeric > 0 ? "delta-pos" : numeric < 0 ? "delta-neg" : "")}>
                    {numeric === null ? "—" : (numeric > 0 ? "+" : "") + formatMetric(numeric, row.unit)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <div className={styles.distributions}>
          <div>
            <h3>景别分布（不含 unknown）</h3>
            <table>
              <thead>
                <tr>
                  <th>景别</th>
                  <th style={{ width: 80 }}>参考</th>
                  <th style={{ width: 80 }}>作业</th>
                </tr>
              </thead>
              <tbody>
                {Array.from(
                  new Set([
                    ...Object.keys((feedback.metrics || {}).scale_distribution?.reference || {}),
                    ...Object.keys((feedback.metrics || {}).scale_distribution?.submission || {}),
                  ]),
                ).map((key) => (
                  <tr key={key}>
                    <td className="mono">{key}</td>
                    <td className="num">
                      {((feedback.metrics || {}).scale_distribution?.reference || {})[key] || 0}
                    </td>
                    <td className="num">
                      {((feedback.metrics || {}).scale_distribution?.submission || {})[key] || 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <h3>运镜分布</h3>
            <table>
              <thead>
                <tr>
                  <th>运镜</th>
                  <th style={{ width: 80 }}>参考</th>
                  <th style={{ width: 80 }}>作业</th>
                </tr>
              </thead>
              <tbody>
                {Array.from(
                  new Set([
                    ...Object.keys((feedback.metrics || {}).motion_distribution?.reference || {}),
                    ...Object.keys((feedback.metrics || {}).motion_distribution?.submission || {}),
                  ]),
                ).map((key) => (
                  <tr key={key}>
                    <td className="mono">{key}</td>
                    <td className="num">
                      {((feedback.metrics || {}).motion_distribution?.reference || {})[key] || 0}
                    </td>
                    <td className="num">
                      {((feedback.metrics || {}).motion_distribution?.submission || {})[key] || 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>


      <section className="card">
        <div className="panel-title">镜头对齐表（{alignments.length}）</div>
        <div className="callout callout-info">
          对齐策略：优先按任务分镜 ID（shot_ref）一一对应；没有对应 ID 时按「叙事功能 + 相对时间」提出候选匹配并标注
          <span className="mono"> certainty=candidate</span>；<strong>允许未匹配</strong>——
          <span className="mono">unmatched</span> 只表示结构差异，不等于错误（有意省略同样可以得分）。
        </div>
        {alignments.length === 0 ? (
          <div className="empty">没有可用的对齐结果。</div>
        ) : (
          <div className={styles.tableScroll}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 110 }}>参考镜头</th>
                  <th style={{ width: 160 }}>参考时间 / 摘要</th>
                  <th style={{ width: 110 }}>作业镜头</th>
                  <th style={{ width: 160 }}>作业时间 / 摘要</th>
                  <th style={{ width: 150 }}>对齐方法</th>
                  <th style={{ width: 130 }}>确定性</th>
                  <th>时长差 / 说明</th>
                </tr>
              </thead>
              <tbody>
                {alignments.map((item: Alignment, index: number) => (
                  <tr key={(item.reference_shot_ref || "-") + "_" + (item.submission_shot_ref || "-") + "_" + index}>
                    <td className="mono">{item.reference_shot_ref || "—"}</td>
                    <td>
                      <div>{formatDuration(item.reference_time_ms)}</div>
                      <div className="dim">{item.reference_summary || "—"}</div>
                    </td>
                    <td className="mono">{item.submission_shot_ref || "—"}</td>
                    <td>
                      <div>{formatDuration(item.submission_time_ms)}</div>
                      <div className="dim">{item.submission_summary || "—"}</div>
                    </td>
                    <td className="mono dim">{item.method}</td>
                    <td>
                      <span className={certaintyClass(item.certainty)}>{certaintyLabel(item.certainty)}</span>
                    </td>
                    <td>
                      {item.duration_delta_ms !== undefined ? (
                        <div className={"mono " + (item.duration_delta_ms > 0 ? "delta-pos" : "delta-neg")}>
                          {(item.duration_delta_ms > 0 ? "+" : "") + item.duration_delta_ms + " ms"}
                        </div>
                      ) : null}
                      <div className="dim">{item.note}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="panel-title">建议卡片（{suggestions.length}）</div>
        <p className="dim">
          每条建议固定结构：参考证据 → 作业证据 → 差异 → 与本次学习目标的关系 → 一个可执行动作。
        </p>
        <div className="stack" style={{ gap: 12 }}>
          {suggestions.map((suggestion) => {
            const detail = buildSuggestionDetail(suggestion, feedback);
            return (
              <article key={suggestion.id} className={styles.suggestion}>
                <div className="row-between">
                  <div className="row" style={{ gap: 8 }}>
                    <span className="badge badge-accent">优先级 {suggestion.priority}</span>
                    <span className="tag mono">{suggestion.target}</span>
                  </div>
                  <span className="dim mono">{suggestion.id}</span>
                </div>
                <div className={styles.suggestionGrid}>
                  <div>
                    <div className={styles.stepLabel}>参考证据</div>
                    <div>{detail.reference}</div>
                  </div>
                  <div>
                    <div className={styles.stepLabel}>作业证据</div>
                    <div>{detail.submission}</div>
                  </div>
                  <div>
                    <div className={styles.stepLabel}>差异</div>
                    <div>{detail.diff}</div>
                  </div>
                  <div>
                    <div className={styles.stepLabel}>与学习目标的关系</div>
                    <div>{suggestion.goal_link}</div>
                  </div>
                  <div className={styles.suggestionAction}>
                    <div className={styles.stepLabel}>可执行动作</div>
                    <div>{suggestion.action}</div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="card">
        <div className="panel-title">证据时间点</div>
        <div className="grid-2">
          <div>
            <h3>参考证据（{referenceEvidence.length} 个镜头）</h3>
            {referenceEvidence.length === 0 ? (
              <div className="dim">无。</div>
            ) : (
              <ul className={styles.evidenceList}>
                {referenceEvidence.map((item: FeedbackEvidenceItem) => (
                  <li key={"ref-" + item.shot_ref}>
                    <span className="mono">{item.shot_ref}</span>{" "}
                    {formatDuration(item.start_ms)} — {formatDuration(item.end_ms)}
                    <div className="dim">{item.observation || "—"}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3>作业证据（{submissionEvidence.length} 个镜头）</h3>
            {submissionEvidence.length === 0 ? (
              <div className="dim">无。</div>
            ) : (
              <ul className={styles.evidenceList}>
                {submissionEvidence.map((item: FeedbackEvidenceItem) => (
                  <li key={"sub-" + item.shot_ref}>
                    <span className="mono">{item.shot_ref}</span>{" "}
                    {formatDuration(item.start_ms)} — {formatDuration(item.end_ms)}
                    <div className="dim">{item.observation || "—"}</div>
                    {item.frames && item.frames.length > 0 ? (
                      <div className="dim mono" style={{ wordBreak: "break-all" }}>
                        证据帧：{item.frames.join("、")}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="panel-title">文字分镜评分（与成片评分分开呈现）</div>
        {!hasStoryboard ? (
          <div className="empty">本次未提交文字分镜，因此没有分镜文本评分。成片结构反馈不受影响。</div>
        ) : (
          <>
            <p className="dim">{storyboard.note || "这是文字分镜的确定性检查，不与成片结构评分合并。"}</p>
            <div className="row" style={{ gap: 8 }}>
              <span className="badge badge-accent">
                通过 {storyboard.passed_count || 0} / {storyboard.total_count || storyboardChecks.length} 项
              </span>
              <span className="badge">识别分镜描述 {storyboard.shot_lines || 0} 条</span>
              {storyboard.total_duration_ms ? (
                <span className="badge">合计时长 {formatSeconds(storyboard.total_duration_ms, 1)}</span>
              ) : null}
            </div>
            <table style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th style={{ width: 170 }}>检查项</th>
                  <th style={{ width: 90 }}>结果</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {storyboardChecks.map((check) => (
                  <tr key={check.key}>
                    <td className="mono">{check.key}</td>
                    <td>
                      <span className={"badge " + (check.passed ? "badge-ok" : "badge-warn")}>
                        {check.passed ? "通过" : "待改进"}
                      </span>
                    </td>
                    <td>{check.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(storyboard.scales_found || []).length > 0 ? (
              <div className="dim" style={{ marginTop: 8 }}>
                识别到的景别：{(storyboard.scales_found || []).join("、")}
              </div>
            ) : null}
          </>
        )}
      </section>

      <div className="callout callout-info">
        结构差异均为客观计算；语义评价与建议基于可核对证据，允许人工修改标签。反馈不合并为单一总分。
      </div>
    </div>
  );
}

