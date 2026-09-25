"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMeta } from "../../../components/useMeta";
import { ApiError, downloadText, endpoints, getToken, resolveApiUrl } from "../../../lib/api";
import {
  formatDateTime,
  formatDuration,
  formatSeconds,
  functionLabel,
  isUnknown,
  motionLabel,
  scaleLabel,
  shotTone,
} from "../../../lib/format";
import type { Analysis, Asset, Shot, ShotExplanation, TaskLevel } from "../../../lib/types";
import styles from "./analysis.module.css";

const LEVELS: { key: TaskLevel; label: string; hint: string }[] = [
  { key: "imitate", label: "模仿", hint: "保留镜头数量与主要叙事功能" },
  { key: "variant", label: "变体", hint: "保留表达目标，改景别或顺序并说明理由" },
  { key: "original", label: "原创", hint: "只给主题、时长与表达目标" },
];

const FALLBACK_INTENTS = [
  { key: "shot_language", label: "镜头语言", goal: "" },
  { key: "narrative_rhythm", label: "叙事节奏", goal: "" },
];

export default function AnalysisPage() {
  const params = useParams<{ id: string }>();
  const analysisId = params?.id || "";
  const router = useRouter();
  const { meta } = useMeta();

  const [authed, setAuthed] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [asset, setAsset] = useState<Asset | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyAction, setBusyAction] = useState("");

  const [intent, setIntent] = useState("");
  const [explanations, setExplanations] = useState<Record<string, ShotExplanation>>({});
  const [intentNotice, setIntentNotice] = useState("");

  const [editRef, setEditRef] = useState("");
  const [editStart, setEditStart] = useState("");
  const [editEnd, setEditEnd] = useState("");
  const [editError, setEditError] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  const [seekInfo, setSeekInfo] = useState<{ target: number; actual: number } | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingSeekRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (!analysisId) return;
    setLoading(true);
    setError("");
    try {
      const data = await endpoints.getAnalysis(analysisId);
      setAnalysis(data);
      setIntent(data.intent || "shot_language");
      setAsset(null);
      try {
        setAsset(await endpoints.getAsset(data.asset_id));
      } catch {
        setAsset(null);
      }
    } catch (err) {
      setError((err as ApiError).message || "读取分析失败");
    } finally {
      setLoading(false);
    }
  }, [analysisId]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/?reason=required");
      return;
    }
    setAuthed(true);
    void load();
  }, [load, router]);

  const loadExplanations = useCallback(
    async (targetIntent: string) => {
      if (!analysisId || !targetIntent) return;
      try {
        const data = await endpoints.getExplanations(analysisId, targetIntent);
        const map: Record<string, ShotExplanation> = {};
        data.explanations.forEach((item) => {
          map[item.shot_ref] = item;
        });
        setExplanations(map);
        setIntentNotice(data.note + (data.fact_timeline_unchanged ? "（事实时间线未改变）" : ""));
      } catch (err) {
        setIntentNotice("");
        setError((err as ApiError).message || "读取意图解释失败");
      }
    },
    [analysisId],
  );

  useEffect(() => {
    if (analysis && intent) void loadExplanations(intent);
  }, [analysis, intent, loadExplanations]);

  const totalMs = useMemo(() => {
    if (!analysis || analysis.shots.length === 0) return 0;
    return analysis.shots.reduce((max, shot) => (shot.end_ms > max ? shot.end_ms : max), 0);
  }, [analysis]);

  function seekTo(ms: number) {
    const video = videoRef.current;
    const target = ms / 1000;
    pendingSeekRef.current = target;
    if (!video) {
      setSeekInfo({ target, actual: target });
      return;
    }
    video.currentTime = target;
    setSeekInfo({ target, actual: video.currentTime });
    void video.play().catch(() => undefined);
  }

  function onSeeked() {
    const video = videoRef.current;
    if (!video || pendingSeekRef.current === null) return;
    setSeekInfo({ target: pendingSeekRef.current, actual: video.currentTime });
    pendingSeekRef.current = null;
  }

  async function exportMarkdown() {
    if (!analysis) return;
    setBusyAction("export");
    setError("");
    try {
      const text = await endpoints.exportMarkdown(analysis.id);
      downloadText("chai-jing-analysis-v" + analysis.version + ".md", text);
      setNotice("Markdown 报告已开始下载。");
    } catch (err) {
      setError((err as ApiError).message || "导出失败");
    } finally {
      setBusyAction("");
    }
  }

  async function createTask(level: TaskLevel) {
    if (!analysis) return;
    setBusyAction("task-" + level);
    setError("");
    try {
      const task = await endpoints.createLearningTask(analysis.id, { level, intent });
      router.push("/tasks/" + task.id);
    } catch (err) {
      setError((err as ApiError).message || "生成学习任务失败");
    } finally {
      setBusyAction("");
    }
  }

  function beginEdit(shot: Shot) {
    setEditRef(shot.shot_ref);
    setEditStart(String(shot.start_ms));
    setEditEnd(String(shot.end_ms));
    setEditError("");
  }

  async function saveEdit(shot: Shot) {
    if (!analysis) return;
    const start = Number(editStart);
    const end = Number(editEnd);
    const durationLimit = asset ? asset.duration_ms : totalMs;
    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      setEditError("请输入整数毫秒值");
      return;
    }
    if (end <= start) {
      setEditError("结束时间必须大于开始时间");
      return;
    }
    if (start < 0 || (durationLimit && end > durationLimit)) {
      setEditError("时间区间必须落在片长 " + durationLimit + "ms 之内");
      return;
    }
    setSavingEdit(true);
    setEditError("");
    try {
      const updated = await endpoints.patchShots(analysis.id, {
        expected_version: analysis.version,
        review_status: "confirmed",
        shots: [{ shot_ref: shot.shot_ref, start_ms: Math.round(start), end_ms: Math.round(end) }],
      });
      setEditRef("");
      setNotice("人工修正已提交，生成新版本 v" + updated.version + "，正在切换到该版本…");
      router.replace("/analyses/" + updated.id);
    } catch (err) {
      const apiError = err as ApiError;
      if (apiError.status === 409) {
        setEditError("版本冲突（409）：分析已被更新，请点击「重新加载」后再修正。");
      } else {
        setEditError(apiError.message || "保存失败");
      }
    } finally {
      setSavingEdit(false);
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
        <div className="skeleton" style={{ height: 40, width: "40%" }} />
        <div className="skeleton" style={{ height: 260 }} />
        <div className="skeleton" style={{ height: 180 }} />
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="page stack">
        <div className="callout callout-danger">{error || "分析不存在或不可访问。"}</div>
        <div className="row">
          <Link href="/projects">← 返回项目列表</Link>
          <button type="button" className="btn-ghost btn-sm" onClick={() => void load()}>
            重新加载
          </button>
        </div>
      </div>
    );
  }

  const playbackUrl = asset ? resolveApiUrl(asset.playback_url) : "";
  const unknownItems = analysis.unknowns?.items || [];
  const partial = !!analysis.coverage?.partial;
  const intentOptions = meta && meta.intents.length > 0 ? meta.intents : FALLBACK_INTENTS;

  return (
    <div className="page stack">
      <div className="row-between">
        <div>
          <div className="dim">
            <Link href={"/projects/" + analysis.project_id}>← 返回项目</Link>
          </div>
          <h1>拆解工作台</h1>
          <div className="row" style={{ gap: 8, marginTop: 4 }}>
            <span className="badge badge-accent">版本 v{analysis.version}</span>
            <span className="badge">{analysis.shots.length} 个镜头</span>
            <span className="badge mono">{analysis.kind}</span>
            <span className="badge mono">{analysis.model_id || "unknown-model"}</span>
            <span className="dim">创建于 {formatDateTime(analysis.created_at)}</span>
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn-ghost btn-sm" onClick={() => void load()}>
            重新加载
          </button>
          <button
            type="button"
            className="btn-sm"
            onClick={() => void exportMarkdown()}
            disabled={busyAction === "export"}
          >
            {busyAction === "export" ? "导出中…" : "导出 Markdown"}
          </button>
        </div>
      </div>

      {partial ? (
        <div className="callout callout-warn">
          <strong>部分镜头未完成。</strong>
          该分析标记为 partial，以下内容只覆盖成功解析的镜头，未完成部分不计入统计。
        </div>
      ) : null}
      {notice ? <div className="callout callout-ok">{notice}</div> : null}
      {error ? <div className="callout callout-danger">{error}</div> : null}

      <div className={styles.workbench}>
        <div className="stack" style={{ gap: 12 }}>
          <div className="card">
            <div className="panel-title">参考片播放器</div>
            {playbackUrl ? (
              <video
                ref={videoRef}
                controls
                preload="metadata"
                src={playbackUrl}
                onSeeked={onSeeked}
                className={styles.video}
              />
            ) : (
              <div className="empty">
                播放地址不可用（素材未就绪或签名地址已过期，可点击「重新加载」刷新）。
              </div>
            )}
            <div className="kv" style={{ marginTop: 10 }}>
              <dt>片长</dt>
              <dd>{formatDuration(analysis.media?.duration_ms ?? (asset ? asset.duration_ms : 0))}</dd>
              <dt>分辨率</dt>
              <dd>
                {analysis.media?.width || asset?.width || 0} × {analysis.media?.height || asset?.height || 0}
              </dd>
              <dt>帧率</dt>
              <dd>{analysis.media?.fps ? Number(analysis.media.fps).toFixed(2) + " fps" : "—"}</dd>
              <dt>编码 / 容器</dt>
              <dd>
                {analysis.media?.video_codec || "—"} / {analysis.media?.container || "—"}
              </dd>
              <dt>音轨</dt>
              <dd>{analysis.media?.has_audio ? "有" : "无"}</dd>
            </div>
            {seekInfo ? (
              <div className="dim" style={{ marginTop: 8 }}>
                最近定位：目标 {seekInfo.target.toFixed(2)}s → 实际 {seekInfo.actual.toFixed(2)}s，误差{" "}
                {Math.abs(seekInfo.actual - seekInfo.target).toFixed(3)}s（目标 ≤ 0.3s）
              </div>
            ) : (
              <div className="dim" style={{ marginTop: 8 }}>
                点击时间线色块或镜头卡片中的证据时间点即可跳转（video.currentTime = start_ms / 1000，目标定位误差 ≤ 0.3
                秒）。
              </div>
            )}
          </div>

          <div className="card">
            <div className="panel-title">学习意图切换</div>
            <div className="row">
              {intentOptions.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={intent === item.key ? "btn-primary btn-sm" : "btn-sm"}
                  onClick={() => setIntent(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="dim" style={{ marginTop: 8 }}>
              {intentNotice ||
                "切换意图会重新拉取 explanations，只改变解释文案与练习重点；镜头边界与事实时间线保持不变。"}
            </div>
          </div>

          <div className="card">
            <div className="panel-title">生成学习任务</div>
            <div className="row">
              {LEVELS.map((level) => (
                <button
                  key={level.key}
                  type="button"
                  className="btn-sm"
                  disabled={busyAction === "task-" + level.key}
                  onClick={() => void createTask(level.key)}
                  title={level.hint}
                >
                  {busyAction === "task-" + level.key ? "生成中…" : level.label}
                </button>
              ))}
            </div>
            <div className="dim" style={{ marginTop: 8 }}>
              级别固定约束：模仿＝保留镜头数量与主要叙事功能；变体＝保留表达目标、改景别或顺序并说明理由；原创＝只给主题、时长与表达目标。
            </div>
          </div>
        </div>

        <div className="stack" style={{ gap: 12 }}>
          <div className="card">
            <div className="panel-title">
              镜头时间线
              <span className="dim">（按时间比例排列，点击跳转）</span>
            </div>
            {analysis.shots.length === 0 ? (
              <div className="empty">未解析到镜头。</div>
            ) : (
              <>
                <div className={styles.timeline}>
                  {analysis.shots.map((shot, index) => {
                    const width = totalMs > 0 ? ((shot.end_ms - shot.start_ms) / totalMs) * 100 : 0;
                    const left = totalMs > 0 ? (shot.start_ms / totalMs) * 100 : 0;
                    return (
                      <button
                        key={shot.shot_ref}
                        type="button"
                        className={styles.block}
                        style={{
                          left: left + "%",
                          width: Math.max(width, 0.6) + "%",
                          background: shotTone(index),
                        }}
                        title={
                          shot.shot_ref +
                          "  " +
                          formatDuration(shot.start_ms) +
                          " - " +
                          formatDuration(shot.end_ms)
                        }
                        onClick={() => seekTo(shot.start_ms)}
                      >
                        <span className={styles.blockLabel}>{index + 1}</span>
                      </button>
                    );
                  })}
                </div>
                <div className="row-between" style={{ marginTop: 6 }}>
                  <span className="dim">0:00</span>
                  <span className="dim">{formatDuration(totalMs)}</span>
                </div>
              </>
            )}
          </div>

          <div className="card">
            <div className="panel-title">阅读约定</div>
            <ul className="plain muted">
              <li>景别与运镜为 unknown 时一律显示「未知」，界面不做任何推测填充。</li>
              <li>观察事实来自可核对的时间轴与代表帧；表达假设与替代设计属于可讨论的解释。</li>
              <li>切换学习意图不会改变镜头边界、时间点与代表帧。</li>
            </ul>
            {analysis.coverage?.provider ? (
              <div className="dim" style={{ marginTop: 6 }}>
                provider: <span className="mono">{String(analysis.coverage.provider)}</span>
                {analysis.coverage.asr_provider ? " · ASR: " + String(analysis.coverage.asr_provider) : ""}
              </div>
            ) : null}
            {Array.isArray(analysis.coverage?.warnings) && analysis.coverage.warnings.length > 0 ? (
              <div className="callout callout-warn" style={{ marginTop: 8 }}>
                <strong>流程警告：</strong>
                <ul className="plain" style={{ marginTop: 4 }}>
                  {analysis.coverage.warnings.map((item, index) => (
                    <li key={index}>{String(item)}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </div>
      </div>


      {unknownItems.length > 0 ? (
        <div className="callout callout-warn">
          <strong>整片层面的不确定性（unknowns）：</strong>
          <ul className="plain" style={{ marginTop: 4 }}>
            {unknownItems.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
          {analysis.unknowns?.policy ? <div className="dim">{analysis.unknowns.policy}</div> : null}
        </div>
      ) : null}

      <h2>镜头卡片（{analysis.shots.length}）</h2>
      {analysis.shots.length === 0 ? <div className="empty">未解析到镜头。</div> : null}

      <div className="stack">
        {analysis.shots.map((shot, index) => {
          const explanation = explanations[shot.shot_ref];
          const editing = editRef === shot.shot_ref;
          const scaleUnknown = isUnknown(shot.shot_scale);
          const motionUnknown = isUnknown(shot.camera_motion);
          return (
            <article key={shot.shot_ref + "-" + index} className="card">
              <div className="row-between">
                <div className="row" style={{ gap: 10 }}>
                  <span className="badge badge-accent">{shot.shot_ref}</span>
                  <strong>
                    {formatDuration(shot.start_ms)} — {formatDuration(shot.end_ms)}
                  </strong>
                  <span className="dim">{formatSeconds(shot.duration_ms)}</span>
                  <span className={scaleUnknown ? "badge badge-warn" : "badge"}>{scaleLabel(shot.shot_scale)}</span>
                  <span className={motionUnknown ? "badge badge-warn" : "badge"}>{motionLabel(shot.camera_motion)}</span>
                  <span className="badge">{functionLabel(shot.narrative_function)}</span>
                  {shot.review_status === "confirmed" ? <span className="badge badge-ok">人工确认</span> : null}
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <button type="button" className="btn-sm" onClick={() => seekTo(shot.start_ms)}>
                    跳到起点
                  </button>
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={() => (editing ? setEditRef("") : beginEdit(shot))}
                  >
                    {editing ? "取消修正" : "修正边界"}
                  </button>
                </div>
              </div>

              {scaleUnknown || motionUnknown ? (
                <div className="callout callout-warn" style={{ margin: "10px 0" }}>
                  该镜头的{scaleUnknown ? "景别" : ""}
                  {scaleUnknown && motionUnknown ? " 与 " : ""}
                  {motionUnknown ? "运镜" : ""}
                  无法从画面可靠判定，按契约输出 unknown，界面显示为「未知」，不做猜测。
                </div>
              ) : null}

              {editing ? (
                <div className={styles.editBox}>
                  <div className="row" style={{ gap: 10, alignItems: "flex-end" }}>
                    <div>
                      <label htmlFor={"start-" + shot.shot_ref}>开始（ms）</label>
                      <input
                        id={"start-" + shot.shot_ref}
                        type="number"
                        value={editStart}
                        onChange={(event) => setEditStart(event.target.value)}
                        style={{ width: 130 }}
                      />
                    </div>
                    <div>
                      <label htmlFor={"end-" + shot.shot_ref}>结束（ms）</label>
                      <input
                        id={"end-" + shot.shot_ref}
                        type="number"
                        value={editEnd}
                        onChange={(event) => setEditEnd(event.target.value)}
                        style={{ width: 130 }}
                      />
                    </div>
                    <button
                      type="button"
                      className="btn-primary btn-sm"
                      disabled={savingEdit}
                      onClick={() => void saveEdit(shot)}
                    >
                      {savingEdit ? "提交中…" : "提交修正（生成 v" + (analysis.version + 1) + "）"}
                    </button>
                  </div>
                  <div className="dim" style={{ marginTop: 6 }}>
                    提交会带 expected_version={analysis.version}；若版本已变化，服务端返回 409，需要重新加载。
                  </div>
                  {editError ? (
                    <div className="callout callout-danger" style={{ marginTop: 8 }}>
                      {editError}
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className={styles.sections}>
                <section className={styles.section}>
                  <h3>观察事实</h3>
                  <p>{shot.observation || "（无可用观察）"}</p>
                  <div className="dim">
                    {scaleUnknown ? "景别：未知" : "景别：" + scaleLabel(shot.shot_scale)} ·{" "}
                    {motionUnknown ? "运镜：未知" : "运镜：" + motionLabel(shot.camera_motion)} ·{" "}
                    {functionLabel(shot.narrative_function)}
                  </div>
                  {shot.dialogue ? <div style={{ marginTop: 6 }}>台词：{shot.dialogue}</div> : null}
                  {explanation && explanation.fact_lines.length > 0 ? (
                    <ul className="plain dim" style={{ marginTop: 6 }}>
                      {explanation.fact_lines.map((line, lineIndex) => (
                        <li key={lineIndex}>{line}</li>
                      ))}
                    </ul>
                  ) : null}
                </section>

                <section className={styles.section}>
                  <h3>表达假设</h3>
                  <p>{shot.interpretation || "（模型未给出表达假设）"}</p>
                  {explanation && explanation.intent_reading ? (
                    <div className="callout callout-info" style={{ marginTop: 6 }}>
                      <div className="dim">
                        当前意图（{intent === "narrative_rhythm" ? "叙事节奏" : "镜头语言"}）解读
                      </div>
                      {explanation.intent_reading}
                    </div>
                  ) : null}
                </section>

                <section className={styles.section}>
                  <h3>可尝试的替代设计</h3>
                  <p>{shot.alternative || "（本次未给出替代设计）"}</p>
                </section>

                <section className={styles.section}>
                  <h3>证据时间点</h3>
                  {shot.evidence.length === 0 ? (
                    <div className="dim">无证据帧。</div>
                  ) : (
                    <div className="row" style={{ gap: 6 }}>
                      {shot.evidence.map((item, evidenceIndex) => (
                        <button
                          key={item.frame_key + "-" + evidenceIndex}
                          type="button"
                          className="btn-sm mono"
                          onClick={() => seekTo(item.timestamp_ms)}
                          title={item.frame_id}
                        >
                          {formatDuration(item.timestamp_ms)}
                        </button>
                      ))}
                    </div>
                  )}
                  {shot.frames.length > 0 ? (
                    <div className={styles.frames}>
                      {shot.frames.map((frame) => (
                        <img
                          key={frame.frame_key}
                          src={resolveApiUrl(frame.url)}
                          alt={frame.frame_key}
                          className={styles.frame}
                        />
                      ))}
                    </div>
                  ) : null}
                </section>

                <section className={styles.section}>
                  <h3>关联知识卡片</h3>
                  {shot.knowledge.length === 0 ? (
                    <div className="dim">
                      无关联卡片
                      {shot.knowledge_ids.length > 0 ? "（ID：" + shot.knowledge_ids.join("、") + "）" : ""}。
                    </div>
                  ) : (
                    <div className="stack" style={{ gap: 8 }}>
                      {shot.knowledge.map((card) => (
                        <div key={card.id} className="card-flat">
                          <div className="row-between">
                            <strong>{card.title}</strong>
                            <span className="tag mono">{card.id}</span>
                          </div>
                          <p style={{ marginTop: 6 }}>{card.content}</p>
                          {card.source ? <div className="dim">来源：{card.source}</div> : null}
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                <section className={styles.section}>
                  <h3>不确定性</h3>
                  {shot.unknowns.length === 0 ? (
                    <div className="dim">该镜头没有额外的不确定性标注。</div>
                  ) : (
                    <ul className="plain" style={{ color: "var(--warn)" }}>
                      {shot.unknowns.map((item, unknownIndex) => (
                        <li key={unknownIndex}>{item}</li>
                      ))}
                    </ul>
                  )}
                  <div className="dim" style={{ marginTop: 6 }}>
                    模型自报置信度 {shot.confidence || 0}（不作为唯一依据） · 复核状态 {shot.review_status} · 来源{" "}
                    {shot.source || "detector"} · 代表帧 {shot.frames.length} 张
                  </div>
                </section>
              </div>
            </article>
          );
        })}
      </div>


      <div className="card">
        <div className="panel-title">台词转录</div>
        {(analysis.transcript?.segments || []).length === 0 ? (
          <div className="empty">
            无台词片段（provider：{String(analysis.transcript?.provider || "—")}）
            {analysis.transcript?.note ? " · " + String(analysis.transcript.note) : ""}
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ width: 200 }}>时间</th>
                <th>文本</th>
              </tr>
            </thead>
            <tbody>
              {(analysis.transcript?.segments || []).map((segment, index) => (
                <tr key={index}>
                  <td>
                    <button
                      type="button"
                      className="btn-ghost btn-sm mono"
                      onClick={() => seekTo(segment.start_ms)}
                    >
                      {formatDuration(segment.start_ms)} — {formatDuration(segment.end_ms)}
                    </button>
                  </td>
                  <td>{segment.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <div className="panel-title">版本与技术信息</div>
        <div className="kv">
          <dt>分析 ID</dt>
          <dd className="mono">{analysis.id}</dd>
          <dt>素材 ID</dt>
          <dd className="mono">{analysis.asset_id}</dd>
          <dt>prompt / schema / knowledge / pipeline 版本</dt>
          <dd className="mono">
            {analysis.prompt_version} / {analysis.schema_version} / {analysis.knowledge_version} /{" "}
            {analysis.pipeline_version}
          </dd>
          <dt>是否人工编辑</dt>
          <dd>{analysis.edited_by_user ? "是" : "否"}</dd>
          <dt>复核状态</dt>
          <dd>{analysis.review_status}</dd>
        </div>
        <div className="dim" style={{ marginTop: 8 }}>
          每次人工修正镜头边界都会生成新版本（v{analysis.version + 1}），旧版本仍被下游学习任务引用。
        </div>
      </div>
    </div>
  );
}

