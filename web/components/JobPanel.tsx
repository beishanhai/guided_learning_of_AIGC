"use client";

import { formatMs } from "../lib/format";
import type { Job } from "../lib/types";
import styles from "./JobPanel.module.css";

const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "处理中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const STAGE_LABELS: Record<string, string> = {
  created: "已创建",
  queued: "排队",
  probing: "解析媒体",
  detecting: "检测镜头切点",
  extracting_frames: "抽取关键帧",
  transcribing: "识别台词",
  analyzing: "模型逐镜分析",
  assembling: "装配结果",
  comparing: "结构对比",
  generating_feedback: "生成反馈",
  done: "完成",
};

export function jobStatusLabel(status: string): string {
  return STATUS_LABELS[status] || status;
}

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] || stage || "—";
}

interface Props {
  job: Job | null;
  title?: string;
  onRetry?: () => void;
  onCancel?: () => void;
}

export default function JobPanel({ job, title = "任务进度", onRetry, onCancel }: Props) {
  if (!job) return null;
  const progress = Math.max(0, Math.min(100, job.progress || 0));
  const running = job.status === "queued" || job.status === "running";

  return (
    <div className={styles.wrap}>
      <div className="row-between">
        <div className="row" style={{ gap: 8 }}>
          <strong>{title}</strong>
          <span
            className={
              "badge " +
              (job.status === "succeeded"
                ? "badge-ok"
                : job.status === "failed"
                  ? "badge-danger"
                  : job.status === "cancelled"
                    ? "badge-warn"
                    : "badge-accent")
            }
          >
            {jobStatusLabel(job.status)}
          </span>
          <span className="dim">
            阶段：{stageLabel(job.stage)} · 尝试 {job.attempt}/{job.max_attempts}
          </span>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {running && onCancel ? (
            <button type="button" className="btn-ghost btn-sm" onClick={onCancel}>
              取消任务
            </button>
          ) : null}
          {job.status === "failed" && onRetry ? (
            <button type="button" className="btn-sm" onClick={onRetry}>
              重试（只重跑失败阶段）
            </button>
          ) : null}
        </div>
      </div>

      <div className="progress" style={{ marginTop: 10 }}>
        <div className="progress-fill" style={{ width: progress + "%" }} />
      </div>
      <div className="dim" style={{ marginTop: 4 }}>
        {progress}% · 任务 ID <span className="mono">{job.id}</span>
      </div>

      {job.partial ? (
        <div className="callout callout-warn" style={{ marginTop: 10 }}>
          <strong>部分镜头未完成。</strong>
          本结果标记为「部分完成」（partial=true），存在未能成功分析的镜头，请结合下方的警告与不确定性说明使用。
        </div>
      ) : null}

      {job.status === "failed" ? (
        <div className="callout callout-danger" style={{ marginTop: 10 }}>
          <strong>任务失败：</strong>
          <span className="mono">{job.error_code || "unknown_error"}</span>
          <div style={{ marginTop: 4 }}>{job.error_message || "服务端未返回错误说明"}</div>
        </div>
      ) : null}

      {job.status === "cancelled" ? (
        <div className="callout callout-warn" style={{ marginTop: 10 }}>
          任务已取消。可重新提交拆解请求。
        </div>
      ) : null}

      {job.stages && job.stages.length > 0 ? (
        <div className={styles.stages}>
          <table>
            <thead>
              <tr>
                <th style={{ width: 150 }}>阶段</th>
                <th style={{ width: 80 }}>状态</th>
                <th style={{ width: 90 }}>耗时</th>
                <th>输出摘要</th>
              </tr>
            </thead>
            <tbody>
              {job.stages.map((stage, index) => (
                <tr key={stage.stage + "-" + index}>
                  <td>{stageLabel(stage.stage)}</td>
                  <td>
                    <span
                      className={
                        "badge " +
                        (stage.status === "succeeded"
                          ? "badge-ok"
                          : stage.status === "failed"
                            ? "badge-danger"
                            : "badge")
                      }
                    >
                      {stage.status}
                    </span>
                  </td>
                  <td className="num">{formatMs(stage.duration_ms)}</td>
                  <td>
                    <div className="mono dim" style={{ wordBreak: "break-all" }}>
                      {Object.keys(stage.output_summary || {}).length === 0
                        ? "—"
                        : JSON.stringify(stage.output_summary)}
                    </div>
                    {stage.error ? <div className="delta-pos">{stage.error}</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
