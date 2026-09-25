"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, endpoints, getToken } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import type { Project } from "../../lib/types";

export default function ProjectsPage() {
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [rightsNote, setRightsNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setProjects(await endpoints.listProjects());
    } catch (err) {
      setError((err as ApiError).message || "读取项目列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/?reason=required");
      return;
    }
    setAuthed(true);
    void load();
  }, [load, router]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setCreating(true);
    setCreateError("");
    try {
      const project = await endpoints.createProject({
        title: title.trim(),
        description: description.trim(),
        rights_note: rightsNote.trim(),
      });
      setTitle("");
      setDescription("");
      setRightsNote("");
      setNotice("项目「" + project.title + "」已创建。");
      await load();
    } catch (err) {
      setCreateError((err as ApiError).message || "创建项目失败");
    } finally {
      setCreating(false);
    }
  }

  async function remove(project: Project) {
    if (!window.confirm("确认删除项目「" + project.title + "」？素材与分析记录将一并不可见。")) return;
    try {
      await endpoints.deleteProject(project.id);
      setNotice("项目已删除。");
      await load();
    } catch (err) {
      setError((err as ApiError).message || "删除项目失败");
    }
  }

  if (!authed) {
    return (
      <div className="page page-narrow">
        <div className="skeleton" style={{ height: 120 }} />
      </div>
    );
  }

  return (
    <div className="page stack">
      <div className="row-between">
        <div>
          <h1>项目</h1>
          <p className="muted">一个项目 = 一部参考短片 + 若干次拆解与学习任务。</p>
        </div>
        <button type="button" className="btn-ghost btn-sm" onClick={() => void load()} disabled={loading}>
          刷新
        </button>
      </div>

      {notice ? <div className="callout callout-ok">{notice}</div> : null}
      {error ? <div className="callout callout-danger">{error}</div> : null}

      <div className="grid-2">
        <form className="card" onSubmit={create}>
          <div className="panel-title">新建项目</div>
          <div className="field">
            <label htmlFor="p-title">标题（必填）</label>
            <input id="p-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：3 分钟短片节奏拆解" />
          </div>
          <div className="field">
            <label htmlFor="p-desc">描述</label>
            <textarea
              id="p-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="这次想练什么？"
            />
          </div>
          <div className="field">
            <label htmlFor="p-rights">版权说明</label>
            <textarea
              id="p-rights"
              value={rightsNote}
              onChange={(e) => setRightsNote(e.target.value)}
              placeholder="素材来源与使用权限说明（仅用于个人学习分析）"
              style={{ minHeight: 60 }}
            />
          </div>
          <button type="submit" className="btn-primary" disabled={creating || !title.trim()}>
            {creating ? "创建中…" : "创建项目"}
          </button>
          {createError ? (
            <div className="callout callout-danger" style={{ marginTop: 12 }}>
              {createError}
            </div>
          ) : null}
        </form>

        <div className="card">
          <div className="panel-title">项目列表（{projects.length}）</div>
          {loading ? (
            <div className="stack">
              <div className="skeleton" />
              <div className="skeleton" style={{ width: "70%" }} />
              <div className="skeleton" style={{ width: "85%" }} />
            </div>
          ) : projects.length === 0 ? (
            <div className="empty">还没有项目。在左侧填写标题后创建第一个项目。</div>
          ) : (
            <div className="stack" style={{ gap: 10 }}>
              {projects.map((project) => (
                <div key={project.id} className="card-flat">
                  <div className="row-between">
                    <Link href={"/projects/" + project.id} style={{ fontSize: 15, fontWeight: 600 }}>
                      {project.title}
                    </Link>
                    <button type="button" className="btn-danger btn-sm" onClick={() => void remove(project)}>
                      删除
                    </button>
                  </div>
                  {project.description ? (
                    <p className="muted" style={{ marginTop: 6 }}>
                      {project.description}
                    </p>
                  ) : null}
                  <div className="row" style={{ gap: 8, marginTop: 6 }}>
                    <span className="badge">素材 {project.asset_count}</span>
                    <span className="badge">分析 {project.analysis_count}</span>
                    <span className="dim">创建于 {formatDateTime(project.created_at)}</span>
                  </div>
                  {project.rights_note ? (
                    <div className="dim" style={{ marginTop: 6 }}>
                      版权说明：{project.rights_note}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
