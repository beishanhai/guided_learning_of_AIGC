/**
 * 统一 API 封装：基础地址、Bearer 注入、错误体解析、401 跳登录。
 *
 * 两个地址必须区分：
 * - API_BASE：含 /api/v1 前缀，用于调用接口；
 * - apiOrigin：只有协议 + 主机，用于把后端返回的**相对路径**（playback_url / upload_url /
 *   frame url）补成绝对地址。
 */
import type {
  Analysis,
  AnalysisSummary,
  AnalysisVersionsResponse,
  Asset,
  ExplanationsResponse,
  Feedback,
  Job,
  JobCreated,
  LearningTask,
  MediaValidation,
  Meta,
  Project,
  ShotsPatchRequest,
  Submission,
  TaskLevel,
  TokenResponse,
  UploadTicket,
  User,
} from "./types";

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000/api/v1"
).replace(/\/+$/, "");

/** 服务源（协议 + 主机 + 端口），用于拼相对路径。 */
export function apiOrigin(): string {
  try {
    return new URL(API_BASE).origin;
  } catch {
    return "";
  }
}

/** 把后端返回的相对地址补成绝对地址；已是绝对地址的原样返回。 */
export function resolveApiUrl(url?: string | null): string {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  const origin = apiOrigin();
  return origin + (url.startsWith("/") ? url : "/" + url);
}

/* ---------------- 会话 ---------------- */

const TOKEN_KEY = "chaijingxue.token";
const USER_KEY = "chaijingxue.user";

export function getToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function getStoredUser(): User | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: User): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* 存储不可用时忽略 */
  }
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

function redirectToLogin(reason: string): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/") return;
  window.location.assign("/?reason=" + encodeURIComponent(reason));
}

/* ---------------- 错误 ---------------- */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;
  readonly body: unknown;

  constructor(status: number, message: string, code: string, requestId: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.body = body;
  }
}

function toApiError(status: number, payload: unknown): ApiError {
  const body = (payload || {}) as Record<string, unknown>;
  const message =
    typeof body.message === "string" && body.message
      ? body.message
      : typeof body.detail === "string"
        ? body.detail
        : "请求失败（HTTP " + status + "）";
  const code = typeof body.code === "string" ? body.code : "http_" + status;
  const requestId = typeof body.request_id === "string" ? body.request_id : "";
  return new ApiError(status, message, code, requestId, payload);
}

/* ---------------- 核心请求 ---------------- */

interface RequestOptions {
  method?: string;
  json?: unknown;
  headers?: Record<string, string>;
  auth?: boolean;
  /** 允许 404 返回 null 而不是抛错（例如反馈尚未生成）。 */
  allow404?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", json, auth = true, allow404 = false } = options;
  const headers: Record<string, string> = { Accept: "application/json", ...(options.headers || {}) };
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = "Bearer " + token;
  }
  let body: BodyInit | undefined;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }

  let response: Response;
  try {
    response = await fetch(API_BASE + path, { method, headers, body, cache: "no-store" });
  } catch (error) {
    throw new ApiError(
      0,
      "无法连接后端服务（" + API_BASE + "），请确认后端已启动：" + (error as Error).message,
      "network_error",
      "",
      null,
    );
  }

  if (response.status === 401) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    clearSession();
    redirectToLogin("expired");
    throw toApiError(401, payload);
  }

  if (response.status === 404 && allow404) {
    return null as unknown as T;
  }

  if (!response.ok) {
    let payload: unknown = null;
    const text = await response.text();
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = { message: text.slice(0, 300) };
      }
    }
    throw toApiError(response.status, payload);
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  const text = await response.text();
  if (!text) return undefined as unknown as T;
  return JSON.parse(text) as T;
}

export const api = {
  get: <T,>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: "GET" }),
  post: <T,>(path: string, json?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", json }),
  patch: <T,>(path: string, json?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PATCH", json }),
  del: <T,>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: "DELETE" }),
};

/* ---------------- 幂等键 ---------------- */

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "idem-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

/* ---------------- 上传 ---------------- */

/**
 * PUT 原始文件字节到上传票据地址。
 * 票据地址可能是相对路径（本地存储），必须补 origin。
 */
export function uploadBytes(
  ticket: UploadTicket,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const url = resolveApiUrl(ticket.upload_url);
    const xhr = new XMLHttpRequest();
    xhr.open(ticket.upload_method || "PUT", url, true);
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
        return;
      }
      let payload: unknown = null;
      try {
        payload = JSON.parse(xhr.responseText);
      } catch {
        payload = { message: xhr.responseText.slice(0, 300) || "上传失败" };
      }
      reject(toApiError(xhr.status, payload));
    };
    xhr.onerror = () =>
      reject(new ApiError(0, "上传网络错误（" + url + "），请检查后端是否允许跨域 PUT", "network_error", "", null));
    xhr.send(file);
  });
}

/** 计算文件 sha256（可选，用于服务端核对）。 */
export async function sha256OfFile(file: File): Promise<string> {
  try {
    if (typeof crypto === "undefined" || !crypto.subtle) return "";
    const buffer = await file.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", buffer);
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  } catch {
    return "";
  }
}

/* ---------------- 下载 ---------------- */

/** 带 Authorization 取文本内容（用于 Markdown 导出），再交给调用方转 Blob 下载。 */
export async function fetchTextWithAuth(path: string): Promise<string> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = "Bearer " + token;
  const response = await fetch(API_BASE + path, { headers, cache: "no-store" });
  if (response.status === 401) {
    clearSession();
    redirectToLogin("expired");
    throw toApiError(401, null);
  }
  const text = await response.text();
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { message: text.slice(0, 300) };
    }
    throw toApiError(response.status, payload);
  }
  return text;
}

export function downloadText(filename: string, text: string, mime = "text/markdown;charset=utf-8"): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/* ---------------- 轮询任务 ---------------- */

export const JOB_POLL_INTERVAL_MS = 1500;
export const JOB_POLL_TIMEOUT_MS = 15 * 60 * 1000;
export const TERMINAL_JOB_STATUSES = ["succeeded", "failed", "cancelled"];

export function isTerminalJob(status: string): boolean {
  return TERMINAL_JOB_STATUSES.indexOf(status) >= 0;
}

/**
 * 轮询 GET /jobs/{id}，1.5 秒一次，最多 15 分钟。
 * onUpdate 收到每一次的状态；返回终态任务。
 */
export async function pollJob(
  jobId: string,
  onUpdate: (job: Job) => void,
  signal?: { cancelled: boolean },
): Promise<Job> {
  const startedAt = Date.now();
  for (;;) {
    const job = await api.get<Job>("/jobs/" + encodeURIComponent(jobId));
    onUpdate(job);
    if (isTerminalJob(job.status)) return job;
    if (Date.now() - startedAt > JOB_POLL_TIMEOUT_MS) {
      throw new ApiError(0, "任务轮询超过 15 分钟仍未结束，请稍后在任务列表中查看结果", "poll_timeout", "", job);
    }
    if (signal && signal.cancelled) return job;
    await new Promise((resolve) => setTimeout(resolve, JOB_POLL_INTERVAL_MS));
  }
}

/* ---------------- 端点封装 ---------------- */

export const endpoints = {
  meta: () => api.get<Meta>("/meta", { auth: false }),

  login: (subject: string, password: string) =>
    api.post<TokenResponse>("/auth/login", { subject, password }, { auth: false }),

  listProjects: () => api.get<Project[]>("/projects"),
  createProject: (payload: { title: string; description?: string; rights_note?: string }) =>
    api.post<Project>("/projects", payload),
  getProject: (id: string) => api.get<Project>("/projects/" + encodeURIComponent(id)),
  deleteProject: (id: string) => api.del<void>("/projects/" + encodeURIComponent(id)),

  listAssets: (projectId: string) => api.get<Asset[]>("/projects/" + encodeURIComponent(projectId) + "/assets"),
  getAsset: (assetId: string) => api.get<Asset>("/assets/" + encodeURIComponent(assetId)),
  createUpload: (
    projectId: string,
    payload: { filename: string; size_bytes: number; media_type?: string; sha256?: string },
  ) => api.post<UploadTicket>("/projects/" + encodeURIComponent(projectId) + "/uploads", payload),
  completeUpload: (assetId: string) =>
    api.post<MediaValidation>("/assets/" + encodeURIComponent(assetId) + "/complete"),

  createAnalysis: (
    projectId: string,
    payload: { asset_id: string; intent: string; generate_task: boolean; expected_version?: number | null },
    idempotencyKey: string,
  ) =>
    api.post<JobCreated>("/projects/" + encodeURIComponent(projectId) + "/analyses", payload, {
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  listAnalyses: (projectId: string) =>
    api.get<AnalysisSummary[]>("/analyses?project_id=" + encodeURIComponent(projectId)),

  getAnalysis: (id: string) => api.get<Analysis>("/analyses/" + encodeURIComponent(id)),
  getExplanations: (id: string, intent: string) =>
    api.get<ExplanationsResponse>(
      "/analyses/" + encodeURIComponent(id) + "/explanations?intent=" + encodeURIComponent(intent),
    ),
  patchShots: (id: string, payload: ShotsPatchRequest) =>
    api.patch<Analysis>("/analyses/" + encodeURIComponent(id) + "/shots", payload),
  listVersions: (id: string) =>
    api.get<AnalysisVersionsResponse>("/analyses/" + encodeURIComponent(id) + "/versions"),
  createLearningTask: (id: string, payload: { level: TaskLevel; intent?: string }) =>
    api.post<LearningTask>("/analyses/" + encodeURIComponent(id) + "/learning-tasks", payload),
  exportMarkdown: (id: string) =>
    fetchTextWithAuth("/analyses/" + encodeURIComponent(id) + "/export?format=md"),

  getJob: (id: string) => api.get<Job>("/jobs/" + encodeURIComponent(id)),
  cancelJob: (id: string) => api.post<JobCreated>("/jobs/" + encodeURIComponent(id) + "/cancel"),
  retryJob: (id: string) => api.post<JobCreated>("/jobs/" + encodeURIComponent(id) + "/retry"),

  getLearningTask: (id: string) => api.get<LearningTask>("/learning-tasks/" + encodeURIComponent(id)),
  listLearningTasks: (analysisId: string) =>
    api.get<LearningTask[]>("/learning-tasks?analysis_id=" + encodeURIComponent(analysisId)),
  createSubmission: (
    taskId: string,
    payload: { asset_id: string; learner_reason?: string; storyboard_text?: string },
    idempotencyKey: string,
  ) =>
    api.post<JobCreated>("/learning-tasks/" + encodeURIComponent(taskId) + "/submissions", payload, {
      headers: { "Idempotency-Key": idempotencyKey },
    }),

  listSubmissions: (taskId: string) =>
    api.get<Submission[]>("/submissions?task_id=" + encodeURIComponent(taskId)),
  getSubmission: (id: string) => api.get<Submission>("/submissions/" + encodeURIComponent(id)),
  getFeedback: (id: string) =>
    api.get<Feedback | null>("/submissions/" + encodeURIComponent(id) + "/feedback", { allow404: true }),
  getFeedbackById: (id: string) => api.get<Feedback>("/feedback/" + encodeURIComponent(id)),
};
