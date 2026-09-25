# 拆镜学（ChaiJingXue）

> 按《拆镜学：技术开发路线与验收文档 V1.0》实现的可运行原型：
> **上传参考视频 → 选择学习目标 → 查看可定位的镜头拆解与解释 → 完成迁移练习 → 提交作品 → 获得结构反馈**。

本仓库是**工程原型**，不是已验收产品。所有未达成项在"当前实现状态与差距"一节逐条列出，
不把建议指标写成已实现能力。

## 0. 先看简版演示（零构建依赖）

后端自带一个单页演示界面，不需要安装前端依赖就能跑通整条闭环：

```powershell
cd backend
$env:PYTHONPATH="."
..\.venv\Scripts\python.exe -m app.cli seed --with-samples     # 建表 + 30 张知识卡片 + 测试账号 + 合成样片

# 两个进程（符合文档 §3 的 API / Worker 分进程要求）
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
..\.venv\Scripts\python.exe -m app.worker
```

浏览器打开 **<http://127.0.0.1:8000/demo>**（测试账号 `alice / alice-pass-123` 已预填）：

1. 新建项目 → 选择 `samples/dev/fastcut_20s.mp4` → 上传并拆解；
2. 页面依次显示「上传票据 → 上传 → 服务端校验 → 拆解」的阶段状态；
3. 完成后可看镜头时间线、点证据时间点跳转播放器、切换学习意图、生成三级任务、导出 Markdown；
   再上传一份作业成片即可看到结构差异、镜头对齐与可执行建议。

命令行版真实服务端端到端冒烟（需上面的 API 与 Worker 已启动）：

```powershell
.\.venv\Scripts\python.exe tools\smoke_http.py
```

已验证结果（2026-09-24，本机）：

- 后端自动化用例 `12 passed`（`cd backend; python -m pytest tests -q`）；
- 真实 HTTP 冒烟：fastcut 拆出 10 个镜头、每镜头 3 个证据点，作业反馈 6 条建议 / 10 条对齐，
  Markdown 导出 8617 字符，`/demo` 页面 200；
- 合成夹具行为：fastcut 10 镜头、vertical 3 镜头、longtake 1 镜头、silent 1 镜头无台词、
  dissolve 识别出 2 处渐变转场；
- Next.js 前端：`npm run build` exit 0（7 条路由、0 类型错误），生产服务器启动后
  `/`、`/projects`、`/analyses/[id]`、`/tasks/[id]`、`/submissions/[id]` 全部 HTTP 200；
- 数据库迁移由 `alembic upgrade head` 建出 13 张业务表。

### 两种前端，按需选

| 界面 | 地址 | 依赖 | 用途 |
|---|---|---|---|
| 简版演示页 | <http://127.0.0.1:8000/demo> | 无（后端自带） | 30 秒走通闭环，演示/评审最省事 |
| 完整前端 | <http://127.0.0.1:3000> | `npm install` | 六个页面、时间线定位误差显示、阶段记录表、版本修正等完整交互 |

完整前端启动方式见 `web/README.md`（含沙箱下 `npm run dev` 的兼容说明）。

---

## 1. 这个原型现在能做什么

| 闭环环节 | 状态 | 说明 |
|---|---|---|
| 账号与项目 | 已实现 | 口令登录（PBKDF2）、用户数据隔离、项目增删查、软删除 |
| 视频上传 | 已实现 | 票据式上传 → 服务端 ffprobe + 完整解码校验；MP4/MOV、H.264、15—60 秒、≤1080p、≤100MB；无声视频可用 |
| 视频拆解 | 已实现 | FFmpeg 逐帧内容变化量 + 自适应阈值切分镜头；首/中/尾 + 长镜头加密采样（全片上限 60 帧）；台词（ASR 适配器）、景别、画面描述、运镜 |
| 运镜判定 | 受限于 provider | 单帧不判定运镜；接入多模态模型后才可能输出，否则一律 `unknown` |
| 学习目标 | 已实现 | 镜头语言 / 叙事节奏两种意图，复用同一份事实，改变解释与练习 |
| 决策解释 | 已实现 | 观察事实 / 表达假设 / 替代设计 / 证据时间点 / 不确定项 五段式分离 |
| 学习任务 | 已实现 | 模仿 / 变体 / 原创三级模板，含目标、先修知识、步骤、约束、提交要求、0—4 分量表、预计用时、工具说明 |
| 作业反馈 | 已实现 | 复用同一条分析流水线；确定性结构指标 + 镜头对齐（允许未匹配）+ 证据化建议 |
| 分镜草稿评分 | 已实现（P1） | 文字分镜确定性检查，与成片评分分开呈现 |
| 导出与删除 | 已实现 | Markdown 导出（与所选版本一致）；项目删除立即撤销访问并安排对象清理 |
| 受控生成实验 | 未实现 | P1 扩展项，本期不做 |
| 完整社区 / 原生 App | 未实现 | P2，明确不在本期范围 |

**AI 质量指标（镜头边界 F1 ≥0.85、核心事实准确率 ≥90% 等）尚未在授权真实样本集上测量**，
见第 6 节。

---

## 2. 架构

```
web/     Next.js + TypeScript   上传、播放器、镜头时间线、练习与反馈
backend/ FastAPI + Pydantic     鉴权、项目资源、OpenAPI 契约、异步任务编排
         app/pipeline           预处理（探测/切分/抽帧）→ 分析（ASR/视觉/校验）→ 教学（知识卡/任务）
         app/learning           学习意图映射、知识卡片检索、任务模板、结构对比、证据化反馈
         app/providers          供应商适配层（offline / openai_compatible / http ASR）
         app/worker.py          独立进程消费 jobs 表（可换成 Celery + Redis）
         knowledge/cards.yaml   知识卡片内容真源（人工审校后进版本控制）
deploy/  Dockerfile、反向代理示例
docs/    OpenAPI、部署、选型、许可、验收报告
samples/dev/ 合成开发夹具（**不是**验收样本集）
```

**数据流**（对应文档 §3.1）

1. 用户创建项目并上传；服务端验证实际媒体类型、时长与解码结果；
2. API 建任务返回 `job_id`（HTTP 202）；Worker 从私有存储读取原片；
3. 预处理输出统一时间基准、镜头段、关键帧与音轨；
4. 转写与视觉分析输出结构化事实、推测与证据（严格 JSON Schema 校验）；
5. 学习引擎检索知识卡片，生成解释与三级练习；
6. 用户提交作品，同一条流水线处理作业；
7. 对比引擎先算客观差异，再生成带证据的建议；
8. 结果落库；前端轮询 `GET /jobs/{id}` 展示阶段与进度。

**任务状态机**：`queued → preprocessing → analyzing → teaching → succeeded`；
异常终态 `failed` / `cancelled`，可带 `partial` 标记的部分结果。

---

## 3. 快速开始（Windows / 本地，无 Docker）

前置：Python ≥3.11、Node ≥20、**FFmpeg 与 ffprobe 在 PATH 中**。

```powershell
cd Learning_aigc

# 1) 后端依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt

# 2) 初始化：建表 + 同步知识卡片 + 测试账号 + 生成合成开发样片
cd backend
$env:PYTHONPATH="."
..\.venv\Scripts\python.exe -m app.cli seed --with-samples
..\.venv\Scripts\python.exe -m app.cli doctor      # 环境自检（ffmpeg/ffprobe/配置）

# 3) 启动 API（8000）与 Worker（两个进程，符合 §3 架构要求）
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
..\.venv\Scripts\python.exe -m app.worker          # 另开一个终端

# 4) 前端
cd ..\web
$env:npm_config_cache="$PWD\..\var\npmcache"
npm install
npm run dev                                        # http://127.0.0.1:3000
```

### 一键启动 / 一键停止

```powershell
# 双击 web\start.cmd 也可以；PowerShell 7 已安装时把 powershell 换成 pwsh
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1          # 预检 → seed → API(8000) + Worker + Web(3000) → 就绪自检
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Verify  # 起完自检后自动停止（CI/冒烟）
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1         # 停止全部
```

常用开关：`-Mode prod`（build + next start）、`-SkipSeed`、`-SkipInstall`、`-ForceBuild`、
`-WithSamples`、`-ApiPort 8010 -WebPort 3010`、`-NoBrowser`。
进程记录在 `var/run/pids.json`，日志在 `var/run/logs/{api,worker,web}.log`。

> 脚本一律保持 **纯 ASCII**：Windows PowerShell 5.1 会把无 BOM 的 `.ps1` 按系统 ANSI 代码页读取，
> 文件里的中文字面量会直接造成语法错误；中文说明只放在本文档与 `web/README.md`。
API 文档：<http://127.0.0.1:8000/docs>，OpenAPI 导出在 `docs/openapi.json`。
测试账号：`alice / alice-pass-123`、`bob / bob-pass-123`。

### Docker 单机部署

```bash
cp .env.example .env
# 必须设置 CJX_SECRET_KEY 与 POSTGRES_PASSWORD
docker compose up -d --build
docker compose exec api python -m app.cli seed
```

细节见 `docs/部署与运维.md`。

---

## 4. 模型与"离线模式"的重要说明

默认配置 `CJX_MULTIMODAL_PROVIDER=offline`：**没有接入多模态大模型**。
此时管线仍会真实执行镜头切分、抽帧、像素统计与结构计算，但：

- 景别一律 `unknown`（没有做人脸/物体检测，不强行归类）；
- 运镜一律 `unknown`（代表帧无法证明摄影机运动）；
- 解释来自可核对的统计与知识卡片规则，不冒充模型语义判断；
- 分析记录、导出报告与前端界面都会标注 `provider=offline`。

接入真实模型只需配置（不用改学习规则）：

```bash
CJX_MULTIMODAL_PROVIDER=openai_compatible
CJX_MULTIMODAL_BASE_URL=https://your-endpoint/v1
CJX_MULTIMODAL_API_KEY=...          # 只存在于服务端
CJX_MULTIMODAL_MODEL_ID=your-model
CJX_MULTIMODAL_PRICE_VERSION=2026-09-01
```

模型只输出符合 Schema 的 JSON，且**不能自造知识 ID**（只能给标签，由学习引擎解析为库里存在的卡片）。

---

## 5. 测试与验证

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
# 等价于：cd backend ; $env:PYTHONPATH="." ; ..\.venv\Scripts\python.exe -m pytest tests -q
```

覆盖：F01 闭环、F02 非法素材、F03 无声不臆造台词、F04 证据时间点、F05 意图切换事实不变、
F06 事实/推测分离、F07 三级任务、F08 作业反馈、F09 人工修正生成新版本、F10 幂等、
F11 重试与失败终态、F12 越权、F13 删除、F14 Worker 恢复、F15 提示注入。

---

## 6. 当前实现状态与差距（务必阅读）

**已完成**：P0 全链路（除下列受限于外部服务的部分）、P1 分镜草稿评分与 Markdown 导出。

**未完成 / 未验证**：

| 项 | 状态 | 影响 |
|---|---|---|
| 授权真实样本集（30 条，10 调参 + 20 留出） | 未准备 | 仓库内只有合成夹具，**不能**用于任何质量指标统计 |
| 镜头边界 F1、事实准确率、解释可用率、反馈可执行率 | 未测量 | 第 9 节质量门禁全部为"未测" |
| 分析时延 P95 / 并发 / 成本预算 | 未测量 | 无真实供应商账单，费用只能写"待核算" |
| 真实 ASR（faster-whisper 或托管服务） | 仅适配器 | 默认 `asr_provider=none`，台词列为空 |
| 真实多模态模型 | 仅适配器 | 默认 offline，景别/运镜为 unknown |
| 受控视频生成（P1） | 未实现 | 明确列入版本限制 |
| 学习效果探索试用（10 人前后测） | 未开展 | 不能宣称教学有效 |
| 备份恢复演练、干净环境部署复现 | 脚本齐备未演练 | 属 M5 交付项 |
| 开源许可证法务复核 | 清单已列 | 见 `THIRD_PARTY.md`（含参考项目声明） |

**工程结论建议**：功能闭环可演示、工程结构可按文档验收流程执行；
**AI 质量与学习效果结论均为"未测/未开展"**，不得合并表述为"全部通过"。

---

## 7. 安全与隐私要点

- 原片默认私有；访问一律走 5 分钟短期签名地址（`CJX_SIGNED_URL_TTL_SECONDS=300`）；
- FFmpeg 以参数数组执行，不拼接 shell；每次调用有超时与输出量上限；
- 密钥只在服务端环境变量；日志过滤器对 `token=` / `api_key` / `authorization` 做脱敏；
- 无权限资源统一返回 404（不泄露存在性）；
- 不启用任意 URL 抓取；
- 项目删除立即撤销应用内访问，对象清理进入 `cleanup_tasks` 队列，备份保留策略见部署文档。

---

## 8. 文档索引

| 文件 | 内容 |
|---|---|
| `docs/openapi.json` | 35 个端点的完整契约（`python -m app.cli export-openapi` 生成） |
| `docs/API契约.md` | 面向前端/评审的接口与错误码速查 |
| `docs/技术选型记录.md` | M0：选型理由、锁定版本、未采用方案与原因 |
| `docs/部署与运维.md` | 部署、备份恢复、删除、回滚、健康检查 |
| `docs/验收报告.md` | §13 模板的实测记录（含"未测"如实标注） |
| `THIRD_PARTY.md` | 第三方依赖许可 + **参考项目致谢与"未引入代码"声明** |
| `LICENSE` | AGPL-3.0 全文 |
| `CONTRIBUTING.md` | 贡献流程、代码约定、提交前自检 |
| `SECURITY.md` | 漏洞报告渠道与隐私/安全设计约束 |
| `CHANGELOG.md` | 版本变更记录 |
| `CODE_OF_CONDUCT.md` | 行为准则 |
| `.github/workflows/ci.yml` | CI：后端用例 + 前端构建 |
| `samples/dev/README.md` | 合成夹具说明（不是验收样本集） |

---

## 9. 许可证与引用

本项目以 **GNU Affero General Public License v3.0（AGPL-3.0）** 发布，全文见 `LICENSE`。

Copyright (C) 2026 ChaiJingXue contributors

- 你可以自由使用、修改、分发；衍生作品需同样以 AGPL-3.0 发布；
- **如果你把它部署成网络服务**，必须让通过网络与之交互的用户拿到对应源码（AGPL 第 13 条）。
  仓库已在界面提供"源代码"入口，部署时请把 `NEXT_PUBLIC_SOURCE_URL`（前端）与
  `web/app/layout.tsx` 中的默认值指向你实际部署版本的源码地址。

```bash
# 首次发布前请替换成你的仓库地址
NEXT_PUBLIC_SOURCE_URL=https://github.com/<your-org>/<your-repo>
```

> `LICENSE` 中的版权主体目前写的是 "ChaiJingXue contributors"，请按实际情况替换为你的姓名或团队名称。

### 第三方与参考项目

依赖组件的许可证、以及立项阶段调研过的开源项目（RemixKit / one-daihuo / viral-video-analyze /
video-script-extraction-skill / PySceneDetect / faster-whisper）**各自的状态与"本项目未引入其任何代码"的声明**，
统一写在 `THIRD_PARTY.md`。引入任何第三方代码前请先读该文件的 §3.2 准入流程。

本项目为教学与研究用原型，按"现状"提供，不附带任何担保；分析结果中的"表达假设"不代表原作者意图，
也不构成版权合法性判断。
