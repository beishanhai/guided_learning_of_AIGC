# API 契约速查（/api/v1）

完整定义见 `docs/openapi.json`（由 `python -m app.cli export-openapi` 生成，共 35 个端点）。
需要登录的端点一律带 `Authorization: Bearer <token>`。

主要读写端点都带显式响应模型（`AnalysisOut` / `ShotOut` / `LearningTaskOut` / `FeedbackOut` / `JobOut` 等），
可直接用于生成前端类型。

## 错误体（所有失败响应）

```json
{ "code": "asset_not_ready", "message": "素材尚未通过服务端校验，不能提交分析", "request_id": "9f3c1a...", "details": null }
```

| HTTP | code | 场景 |
|---|---|---|
| 401 | unauthorized | 缺少/过期令牌 |
| 403 | forbidden | 账号停用、环境关闭自助注册 |
| 404 | not_found | 资源不存在 **或无权限**（统一 404，不泄露存在性） |
| 409 | version_conflict | 分析版本冲突、幂等键被不同请求体使用 |
| 413 | payload_too_large / file_too_large | 超过 100MB |
| 415 | unsupported_media / unsupported_codec / broken_file / decode_failed | 格式、编码、损坏、伪装扩展名 |
| 422 | unprocessable_entity / duration_out_of_range / resolution_too_large | 时长、分辨率、语义参数 |
| 429 | rate_limited | 限流 |
| 502 | upstream_provider_error | 外部模型错误（可重试标记在内部，不暴露给用户） |

## 资源与端点

### 系统
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 存活 + 数据库/存储/ffmpeg 状态 + 队列积压 |
| GET | `/readyz` | 就绪：知识卡片数、provider、queue 后端 |
| GET | `/meta` | 学习意图、任务级别、版本、provider、上传限制 |
| GET | `/meta/analysis-schema` | 分析结果 JSON Schema |

### 鉴权
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | `{subject,password}` → `{access_token,expires_in,user}` |
| POST | `/auth/register` | 仅 `allow_self_registration=true` 时开放 |
| GET | `/auth/me` | 当前用户 |

### 项目与素材
| 方法 | 路径 | 说明 |
|---|---|---|
| POST/GET | `/projects` | 创建 / 列表 |
| GET/DELETE | `/projects/{id}` | 详情 / 软删除（撤销访问 + 清理队列） |
| POST | `/projects/{id}/uploads` | `{filename,size_bytes,media_type}` → 上传票据 |
| PUT | `/assets/{id}/content?token=...` | 上传原始字节（本地存储路径） |
| POST | `/assets/{id}/complete` | 服务端媒体校验 → `{asset,validated,checks[]}` |
| GET | `/assets/{id}` · `/projects/{id}/assets` | 素材详情 / 列表（含短期播放地址） |
| GET | `/media/{token}` | 短期媒体访问（默认 300 秒） |

上传顺序：`uploads → PUT → complete → analyses`。
**上传完成前、媒体验证失败后不允许提交分析。**

### 拆解与教学
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/projects/{id}/analyses` | 202 + job_id；需 `Idempotency-Key` |
| GET | `/analyses/{id}` | 分镜、解释、证据、版本、coverage |
| GET | `/analyses/{id}/explanations?intent=` | 切换意图的解释（事实时间线不变） |
| PATCH | `/analyses/{id}/shots` | 人工修正，`expected_version` 不符返回 409，成功后版本 +1 |
| GET | `/analyses/{id}/versions` | 版本历史与各版本关联的学习任务 |
| POST | `/analyses/{id}/learning-tasks` | `{level:imitate|variant|original}` → 任务 |
| GET | `/analyses/{id}/export?format=md` | Markdown 下载（含 `X-Analysis-Version`） |

### 作业与反馈
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/learning-tasks/{id}/submissions` | 202 + job_id（复用分析流水线） |
| GET | `/submissions/{id}` · `/submissions?task_id=` | 作业详情 / 列表 |
| GET | `/submissions/{id}/feedback` | 反馈（未生成时 404，继续轮询 job） |
| GET | `/feedback/{id}` | 反馈详情 |

反馈对象字段：`summary`、`metrics`（参考/作业/差异）、`reference_metrics`、`submission_metrics`、
`alignments`（含 `certainty=candidate|unmatched`）、`suggestions`（含 `action` 与 `goal_link`）、
`evidence`（双方镜头与证据时间点）、`constraint_results`（任务约束逐条核对是否通过）、
`task_snapshot`（当时使用的任务快照）、`storyboard_metrics`（文字分镜评分，与成片评分分开）、`disclaimer`。
### 任务
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/jobs/{id}` | status/stage/attempt/progress/partial/error + stages[] + `links` |
| POST | `/jobs/{id}/cancel` | 请求取消；终态重复调用幂等 |
| POST | `/jobs/{id}/retry` | 重试（只重跑失败阶段） |
| GET | `/jobs?status=queued` | 任务列表 |

## 前端轮询约定

1. 提交分析/作业后拿到 `job_id`；
2. 每 1.5 秒 `GET /jobs/{id}`，展示 `stage` 与 `stages[].output_summary`（含 warnings）；
3. 终态：`succeeded` / `failed` / `cancelled`；失败展示 `error_code` + `error_message`；
4. `partial=true` 时必须显式提示"部分镜头未完成"，不要当成完全成功；
5. `links.analysis` / `links.feedback` 给出结果地址；提交作业的任务额外给出
   `links.submission` 与 `links.submission_feedback`，前端无需再靠列表接口反查作业 ID。
