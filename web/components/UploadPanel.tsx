"use client";

import { useRef, useState } from "react";
import { ApiError, endpoints, sha256OfFile, uploadBytes } from "../lib/api";
import { formatBytes, formatDuration, formatSeconds } from "../lib/format";
import type { MediaValidation, MetaLimits } from "../lib/types";

type Step = "idle" | "checking" | "hashing" | "ticket" | "uploading" | "completing" | "done" | "error";

const STEP_LABELS: Record<Step, string> = {
  idle: "待上传",
  checking: "本地预检（时长/分辨率）",
  hashing: "计算文件校验值",
  ticket: "申请上传票据",
  uploading: "上传原始文件",
  completing: "服务端媒体验证",
  done: "校验通过",
  error: "失败",
};

const ALLOWED_EXTENSIONS = ["mp4", "mov", "m4v"];

/** 服务端错误码 -> 可执行的处理建议。 */
const ERROR_HINTS: Record<string, string> = {
  duration_out_of_range: "把成片剪辑到规定时长区间后重新导出（剪映：先裁掉多余片段再导出）。",
  resolution_too_large: "在导出设置里把分辨率降到 1080p 或更低后重新导出。",
  file_too_large: "降低码率或分辨率后重新导出，或只剪出需要分析的那一段。",
  unsupported_container: "导出为 .mp4 / .mov / .m4v（剪映默认就是 mp4）。",
  unsupported_codec: "把视频编码换成 H.264（剪映导出设置选 H.264，不要选 HEVC/H.265）。",
  broken_file: "文件可能已损坏，请重新导出一次。",
  decode_failed: "文件无法完整解码，请重新导出或改用 H.264。",
  media_toolchain_missing: "服务端缺少 ffmpeg/ffprobe，需要先安装再上传。",
  upload_incomplete: "上传未完成，请重新上传。",
  object_missing: "服务端没有收到文件，请重新上传。",
  empty_file: "文件内容为空。",
};

interface LocalProbe {
  durationMs: number;
  width: number;
  height: number;
}

/** 用浏览器读取本地文件的时长与分辨率，不消耗带宽。 */
function probeVideoLocally(file: File): Promise<LocalProbe> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;
    const cleanup = () => {
      URL.revokeObjectURL(url);
      video.removeAttribute("src");
    };
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error("读取本地媒体信息超时"));
    }, 8000);
    video.onloadedmetadata = () => {
      window.clearTimeout(timer);
      const result: LocalProbe = {
        durationMs: Math.round((video.duration || 0) * 1000),
        width: video.videoWidth || 0,
        height: video.videoHeight || 0,
      };
      cleanup();
      resolve(result);
    };
    video.onerror = () => {
      window.clearTimeout(timer);
      cleanup();
      reject(new Error("浏览器无法解析该文件的媒体信息"));
    };
    video.src = url;
  });
}

function extensionOf(name: string): string {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index + 1).toLowerCase() : "";
}

interface Props {
  projectId: string;
  limits?: MetaLimits | null;
  onUploaded?: (assetId: string) => void;
  buttonLabel?: string;
  hint?: string;
}

export default function UploadPanel({ projectId, limits, onUploaded, buttonLabel, hint }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>("idle");
  const [percent, setPercent] = useState(0);
  const [probe, setProbe] = useState<LocalProbe | null>(null);
  const [probeWarning, setProbeWarning] = useState("");
  const [precheck, setPrecheck] = useState<string[]>([]);
  const [validation, setValidation] = useState<MediaValidation | null>(null);
  const [error, setError] = useState<{ message: string; code: string; requestId: string; hint: string } | null>(null);

  const busy =
    step === "checking" || step === "hashing" || step === "ticket" || step === "uploading" || step === "completing";

  function reset() {
    setFile(null);
    setStep("idle");
    setPercent(0);
    setProbe(null);
    setProbeWarning("");
    setPrecheck([]);
    setValidation(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  /** 本地预检：能提前判定的问题就不要浪费一次上传（服务端仍会用同一套规则复核）。 */
  async function precheckFile(chosen: File): Promise<string[]> {
    const problems: string[] = [];
    setProbe(null);
    setProbeWarning("");
    if (!limits) return problems;

    if (chosen.size > limits.max_upload_bytes) {
      problems.push("文件 " + formatBytes(chosen.size) + " 超过上限 " + formatBytes(limits.max_upload_bytes));
    }
    const extension = extensionOf(chosen.name);
    if (extension && ALLOWED_EXTENSIONS.indexOf(extension) < 0) {
      problems.push("扩展名 ." + extension + " 不在允许的容器（mp4 / mov / m4v）内");
    }

    try {
      setStep("checking");
      const info = await probeVideoLocally(chosen);
      setProbe(info);
      if (info.durationMs > 0 && info.durationMs < limits.min_duration_ms) {
        problems.push(
          "时长 " + formatSeconds(info.durationMs, 2) + "，短于下限 " + formatSeconds(limits.min_duration_ms, 0),
        );
      }
      if (info.durationMs > limits.max_duration_ms) {
        problems.push(
          "时长 " + formatSeconds(info.durationMs, 1) + "，超过上限 " + formatSeconds(limits.max_duration_ms, 0),
        );
      }
      if (info.height > limits.max_height) {
        problems.push("高度 " + info.height + "px 超过上限 " + limits.max_height + "px");
      }
    } catch (err) {
      setProbeWarning((err as Error).message + "，将跳过本地预检，由服务端判定");
    }
    return problems;
  }

  async function onPick(chosen: File | null) {
    setValidation(null);
    setError(null);
    setPrecheck([]);
    setFile(chosen);
    setStep("idle");
    if (!chosen) return;
    const problems = await precheckFile(chosen);
    setPrecheck(problems);
    setStep("idle");
  }

  async function start() {
    const chosen = file || (inputRef.current && inputRef.current.files ? inputRef.current.files[0] : null);
    if (!chosen) {
      setError({ message: "请先选择一个视频文件", code: "no_file", requestId: "", hint: "" });
      setStep("error");
      return;
    }
    if (precheck.length > 0) {
      setError({
        message: "本地预检未通过，未发起上传：" + precheck.join("；"),
        code: "local_precheck_failed",
        requestId: "",
        hint: "按提示重新导出后重试；服务端会用同一套规则复核。",
      });
      setStep("error");
      return;
    }
    setError(null);
    setValidation(null);
    setPercent(0);
    try {
      setStep("hashing");
      const sha256 = await sha256OfFile(chosen);

      setStep("ticket");
      const ticket = await endpoints.createUpload(projectId, {
        filename: chosen.name,
        size_bytes: chosen.size,
        media_type: chosen.type || "video/mp4",
        sha256,
      });

      setStep("uploading");
      await uploadBytes(ticket, chosen, setPercent);

      setStep("completing");
      const result = await endpoints.completeUpload(ticket.asset_id);
      setValidation(result);
      setStep("done");
      if (onUploaded) onUploaded(result.asset.id);
    } catch (err) {
      const apiError = err as ApiError;
      const code = apiError.code || "unknown_error";
      setError({
        message: apiError.message || "上传失败",
        code,
        requestId: apiError.requestId || "",
        hint: ERROR_HINTS[code] || "",
      });
      setStep("error");
    }
  }

  return (
    <div className="card">
      <div className="panel-title">上传素材</div>
      <p className="dim">
        {hint ||
          "流程：选文件 → 本地预检 → 申请上传票据 → PUT 原始字节 → 服务端媒体验证。服务端校验真实媒体内容，不采信扩展名。"}
      </p>

      {limits ? (
        <div className="card-flat" style={{ marginBottom: 12 }}>
          <div className="dim">服务端准入限制（来自 GET /meta）</div>
          <div className="kv" style={{ marginTop: 6 }}>
            <dt>文件大小</dt>
            <dd>≤ {formatBytes(limits.max_upload_bytes)}</dd>
            <dt>时长</dt>
            <dd>
              {formatSeconds(limits.min_duration_ms, 0)} — {formatSeconds(limits.max_duration_ms, 0)}
            </dd>
            <dt>最大高度</dt>
            <dd>{limits.max_height}px（2560×1440 这类 2K 会被拒绝，请导出 1080p）</dd>
            <dt>容器 / 编码</dt>
            <dd>mp4 / mov / m4v，视频编码 H.264（不要 HEVC / H.265）</dd>
          </div>
        </div>
      ) : null}

      <div className="field">
        <label htmlFor="upload-file">视频文件</label>
        <input
          id="upload-file"
          ref={inputRef}
          type="file"
          accept="video/*,.mp4,.mov,.m4v"
          disabled={busy}
          onChange={(event) => {
            const picked = event.target.files && event.target.files[0] ? event.target.files[0] : null;
            void onPick(picked);
          }}
        />
        {file ? (
          <div className="dim" style={{ marginTop: 4 }}>
            {file.name} · {formatBytes(file.size)} · {file.type || "未知 MIME"}
          </div>
        ) : null}
        {probe ? (
          <div className="dim" style={{ marginTop: 2 }}>
            本地读取：时长 {formatDuration(probe.durationMs)} · {probe.width} × {probe.height}
          </div>
        ) : null}
      </div>

      {precheck.length > 0 ? (
        <div className="callout callout-danger">
          <strong>本地预检发现问题，上传会被服务端拒绝：</strong>
          <ul className="plain" style={{ marginTop: 4 }}>
            {precheck.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
          <div style={{ marginTop: 4 }}>
            处理办法：在剪映里按上面的限制重新导出（时长 15—60 秒、1080p、H.264、mp4）。
          </div>
        </div>
      ) : null}

      {probeWarning ? <div className="callout callout-warn">{probeWarning}</div> : null}

      <div className="row">
        <button type="button" className="btn-primary" onClick={start} disabled={busy || !file}>
          {busy ? "处理中…" : buttonLabel || "上传并校验"}
        </button>
        <button type="button" className="btn-ghost" onClick={reset} disabled={busy}>
          清空
        </button>
        <span className="dim">
          当前步骤：{STEP_LABELS[step]}
          {step === "uploading" ? " " + percent + "%" : ""}
        </span>
      </div>

      {busy || percent > 0 ? (
        <div className="progress" style={{ marginTop: 10 }}>
          <div
            className="progress-fill"
            style={{ width: (step === "uploading" ? percent : step === "done" ? 100 : 8) + "%" }}
          />
        </div>
      ) : null}

      {error ? (
        <div className="callout callout-danger" style={{ marginTop: 12 }}>
          <strong>上传或校验失败：</strong>
          <span className="mono">{error.code}</span>
          <div style={{ marginTop: 4 }}>{error.message}</div>
          {error.hint ? <div style={{ marginTop: 4 }}>建议：{error.hint}</div> : null}
          {error.requestId ? <div className="dim">request_id: {error.requestId}</div> : null}
        </div>
      ) : null}

      {validation ? (
        <div style={{ marginTop: 12 }}>
          <div className="callout callout-ok">素材已通过服务端校验（validated={String(validation.validated)}）。</div>
          <table style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>校验项</th>
                <th style={{ width: 80 }}>结果</th>
                <th>探测值</th>
              </tr>
            </thead>
            <tbody>
              {validation.checks.map((check, index) => (
                <tr key={check.check + "-" + index}>
                  <td className="mono">{check.check}</td>
                  <td>
                    <span className={"badge " + (check.passed ? "badge-ok" : "badge-danger")}>
                      {check.passed ? "通过" : "失败"}
                    </span>
                  </td>
                  <td className="mono dim" style={{ wordBreak: "break-all" }}>
                    {check.value === undefined || check.value === null ? "—" : JSON.stringify(check.value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="kv" style={{ marginTop: 12 }}>
            <dt>实际探测时长</dt>
            <dd>
              {formatDuration(validation.asset.duration_ms)}（{formatSeconds(validation.asset.duration_ms, 2)}）
            </dd>
            <dt>分辨率</dt>
            <dd>
              {validation.asset.width} × {validation.asset.height}
            </dd>
            <dt>帧率</dt>
            <dd>{validation.asset.fps ? validation.asset.fps.toFixed(2) + " fps" : "—"}</dd>
            <dt>编码</dt>
            <dd>{validation.asset.video_codec || "—"}</dd>
            <dt>音轨</dt>
            <dd>{validation.asset.has_audio ? "有音轨" : "无音轨"}</dd>
            <dt>可变帧率（VFR）</dt>
            <dd>{validation.asset.is_vfr ? "是（镜头边界可能需人工复核）" : "否"}</dd>
            <dt>文件大小</dt>
            <dd>{formatBytes(validation.asset.size_bytes)}</dd>
            <dt>素材 ID</dt>
            <dd className="mono">{validation.asset.id}</dd>
          </div>
        </div>
      ) : null}
    </div>
  );
}
