"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useMeta } from "../components/useMeta";
import { ApiError, clearSession, endpoints, getStoredUser, getToken, setSession } from "../lib/api";
import { formatBytes, formatSeconds } from "../lib/format";
import type { User } from "../lib/types";
import styles from "./page.module.css";

export default function LoginPage() {
  const router = useRouter();
  const { meta, loading: metaLoading, error: metaError } = useMeta();

  const [subject, setSubject] = useState("alice");
  const [password, setPassword] = useState("alice-pass-123");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [currentUser, setCurrentUser] = useState<User | null>(null);

  useEffect(() => {
    setCurrentUser(getToken() ? getStoredUser() : null);
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const reason = params.get("reason");
      if (reason === "expired") setNotice("登录状态已失效，请重新登录。");
      if (reason === "required") setNotice("请先登录后再访问该页面。");
    }
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await endpoints.login(subject.trim(), password);
      setSession(result.access_token, result.user);
      setCurrentUser(result.user);
      router.push("/projects");
    } catch (err) {
      setError((err as ApiError).message || "登录失败");
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    clearSession();
    setCurrentUser(null);
  }

  const offline = !!meta && meta.providers.multimodal === "offline";

  return (
    <div className="page page-narrow stack">
      <div>
        <h1>拆镜学</h1>
        <p className="muted">
          上传参考短片 → 拆解镜头结构 → 选择学习意图 → 生成三级学习任务 → 提交作业 → 获得证据化结构反馈。
        </p>
      </div>

      {notice ? <div className="callout callout-warn">{notice}</div> : null}

      {currentUser ? (
        <div className="card">
          <div className="panel-title">已登录</div>
          <p className="muted">
            当前账号：<strong>{currentUser.display_name || currentUser.subject}</strong>（{currentUser.subject} ·{" "}
            {currentUser.role}）
          </p>
          <div className="row">
            <Link href="/projects">
              <button type="button" className="btn-primary">
                进入项目列表
              </button>
            </Link>
            <button type="button" className="btn-ghost" onClick={logout}>
              退出登录
            </button>
          </div>
        </div>
      ) : (
        <form className="card" onSubmit={submit}>
          <div className="panel-title">账号口令登录</div>
          <div className="field">
            <label htmlFor="subject">账号</label>
            <input
              id="subject"
              value={subject}
              autoComplete="username"
              onChange={(event) => setSubject(event.target.value)}
              placeholder="alice"
            />
          </div>
          <div className="field">
            <label htmlFor="password">口令</label>
            <input
              id="password"
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="alice-pass-123"
            />
          </div>
          <button type="submit" className="btn-primary btn-block" disabled={busy || !subject || !password}>
            {busy ? "登录中…" : "登录"}
          </button>
          {error ? (
            <div className="callout callout-danger" style={{ marginTop: 12 }}>
              {error}
            </div>
          ) : null}
          <p className="dim" style={{ marginTop: 10 }}>
            测试账号：alice / alice-pass-123 · bob / bob-pass-123
          </p>
        </form>
      )}

      <section className="card">
        <div className="panel-title">服务元信息（GET /meta）</div>

        {metaLoading ? (
          <div className="stack">
            <div className="skeleton" style={{ width: "60%" }} />
            <div className="skeleton" style={{ width: "80%" }} />
            <div className="skeleton" style={{ width: "45%" }} />
          </div>
        ) : metaError ? (
          <div className="callout callout-danger">
            {metaError}
            <div className="dim" style={{ marginTop: 6 }}>
              前端默认后端地址 http://127.0.0.1:8000/api/v1 ；可用 NEXT_PUBLIC_API_BASE 覆盖。
            </div>
          </div>
        ) : meta ? (
          <div className="stack">
            <div
              className={"callout " + (offline ? "callout-warn" : "callout-ok")}
              style={{ fontSize: 14 }}
            >
              {offline ? (
                <>
                  <strong>当前为离线确定性分析，景别与运镜保持 unknown。</strong>
                  <div style={{ marginTop: 4 }}>
                    多模态 provider = <span className="mono">{meta.providers.multimodal}</span>
                    。系统不会猜测画面语义：景别（shot_scale）与运镜（camera_motion）一律输出
                    <span className="mono"> unknown</span>，界面上显示为「未知」；仅提供可核对的确定性统计
                    （镜头切点、时长、代表帧、画面变化量）。接入真实多模态模型后本提示会自动消失。
                  </div>
                </>
              ) : (
                <>
                  <strong>已接入多模态模型：</strong>
                  <span className="mono">
                    {" "}
                    {meta.providers.multimodal}
                    {meta.providers.multimodal_model_id ? " / " + meta.providers.multimodal_model_id : ""}
                  </span>
                  <div style={{ marginTop: 4 }}>景别与运镜由模型判定，无法判定时仍会显示「未知」。</div>
                </>
              )}
            </div>

            <div className={styles.metaGrid}>
              <div className="card-flat">
                <div className="dim">多模态 provider</div>
                <div className="mono">{meta.providers.multimodal || "—"}</div>
                <div className="dim" style={{ marginTop: 8 }}>
                  模型 ID
                </div>
                <div className="mono">{meta.providers.multimodal_model_id || "—"}</div>
                <div className="dim" style={{ marginTop: 8 }}>
                  台词（ASR）
                </div>
                <div className="mono">{meta.providers.asr || "—"}</div>
              </div>
              <div className="card-flat">
                <div className="dim">存储 / 队列</div>
                <div className="mono">{meta.providers.storage || "—"}</div>
                <div className="mono" style={{ marginTop: 4 }}>
                  {meta.providers.queue || "—"}
                </div>
                <div className="dim" style={{ marginTop: 8 }}>
                  知识卡片
                </div>
                <div className="mono">{meta.knowledge_card_count} 张</div>
                <div className="dim" style={{ marginTop: 8 }}>
                  版本
                </div>
                <div className="mono">
                  prompt {meta.versions.prompt} · schema {meta.versions.schema} · knowledge{" "}
                  {meta.versions.knowledge} · pipeline {meta.versions.pipeline}
                </div>
              </div>
              <div className="card-flat">
                <div className="dim">上传与时长限制</div>
                <div className="mono">单文件上限 {formatBytes(meta.limits.max_upload_bytes)}</div>
                <div className="mono">
                  时长 {formatSeconds(meta.limits.min_duration_ms, 0)} — {formatSeconds(meta.limits.max_duration_ms, 0)}
                </div>
                <div className="mono">最大高度 {meta.limits.max_height}px</div>
                <div className="mono">每片最多 {meta.limits.max_frames_per_asset} 帧</div>
                <div className="mono">播放地址有效期 {meta.limits.signed_url_ttl_seconds} 秒</div>
              </div>
            </div>

            <div>
              <h3>学习意图（两种，复用同一份底层事实）</h3>
              <div className="grid-2">
                {meta.intents.map((intent) => (
                  <div key={intent.key} className="card-flat">
                    <div className="row-between">
                      <strong>{intent.label}</strong>
                      <span className="tag mono">{intent.key}</span>
                    </div>
                    <p className="muted" style={{ marginTop: 6 }}>
                      {intent.goal}
                    </p>
                    <div className="dim">练习重点：{intent.practice_emphasis}</div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h3>三级学习任务</h3>
              <table>
                <thead>
                  <tr>
                    <th>级别</th>
                    <th>固定约束</th>
                    <th>学习者修改</th>
                    <th>评价焦点</th>
                  </tr>
                </thead>
                <tbody>
                  {meta.task_levels.map((level) => (
                    <tr key={level.key}>
                      <td>{level.label}</td>
                      <td>{level.fixed_constraint}</td>
                      <td>{level.learner_change}</td>
                      <td>{level.evaluation_focus}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {meta.disclosure ? <div className="callout callout-info">{meta.disclosure}</div> : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
