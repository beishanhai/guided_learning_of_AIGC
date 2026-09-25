# 拆镜学 · Web 前端

Next.js（App Router）+ TypeScript 实现的学习闭环界面。只依赖 `next` / `react` / `react-dom` /
`typescript` / 三个 `@types` 包；样式为原生 CSS（`app/globals.css` + CSS Modules），
**没有引入 Tailwind 或任何 UI 库，没有外部字体或 CDN**。

## 环境要求

- Node 24 / npm 11（pnpm、yarn 未安装，请使用 npm）
- 后端 FastAPI 运行在 `http://127.0.0.1:8000`

## 如何启动

> 完整链路 = 后端 API（8000）+ 后端 Worker + 前端（3000），三者都要起。

### 方式一：一键启动（推荐）

**双击 `web\start.cmd`** 即可，或在任意终端执行：

```powershell
pwsh -File web\start.ps1
```

脚本按顺序完成并在每一步给出结果：

1. **预检**：`.venv` / `node` / `npm` / `ffmpeg` / `ffprobe`（缺 ffmpeg 只警告，不阻断）
2. **初始化**：`python -m app.cli seed`（幂等：建表 + 同步知识卡片 + 创建测试账号）
3. **后端**：拉起 uvicorn（8000）与 `app.worker`，轮询 `/api/v1/healthz` 直到就绪
4. **前端**：必要时 `npm install`，再启动 Next（3000），轮询首页直到就绪
5. 打印访问地址与日志目录，并自动打开浏览器

常用开关：

```powershell
pwsh -File web\start.ps1 -Mode prod      # 生产模式：npm run build + next start
pwsh -File web\start.ps1 -SkipSeed       # 跳过初始化
pwsh -File web\start.ps1 -SkipInstall    # 跳过 npm install
pwsh -File web\start.ps1 -ForceBuild     # 强制重新构建
pwsh -File web\start.ps1 -WithSamples    # 同时生成演示样片
pwsh -File web\start.ps1 -NoBrowser      # 不自动打开浏览器
pwsh -File web\start.ps1 -ApiPort 8010 -WebPort 3010
pwsh -File web\start.ps1 -Verify         # 起完自检后立即停止（CI / 冒烟）
```

**一键停止**：双击 `web\stop.cmd`，或 `pwsh -File web\stop.ps1`。
停止逻辑优先读 `var\run\pids.json` 精确终止进程树，读不到时回退按 8000 / 3000 端口查监听进程。

启动后的地址：

| 地址 | 用途 |
| --- | --- |
| <http://127.0.0.1:3000> | 前端界面（登录 `alice / alice-pass-123`） |
| <http://127.0.0.1:8000/docs> | 后端 API 文档 |
| <http://127.0.0.1:8000/api/v1/healthz> | 健康检查 |
| `var\run\logs\*.log` | api / worker / web 的 stdout 与 stderr |

脚本文件：`web\start.ps1`、`web\stop.ps1`、`web\start.cmd`、`web\stop.cmd`。
两个 `.ps1` 保持**纯 ASCII**：Windows PowerShell 5.1 会把无 BOM 的 `.ps1` 按系统 ANSI 代码页读取，
中文字面量会直接导致解析错误，所以脚本内提示一律英文，中文说明放在本 README 与界面里。

### 方式一之二：项目根脚本（等价，无预检/健康检查）

```powershell
Set-Location "D:\app\deepseek_HARNESS\ai_workspace\dsh_project\Learning_aigc"
pwsh -File scripts\dev.ps1
```

### 方式二：手动分进程启动

```powershell
# 1) 后端 API（终端 A）
Set-Location "D:\app\deepseek_HARNESS\ai_workspace\dsh_project\Learning_aigc\backend"
$env:PYTHONPATH="."
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) 后端 Worker（终端 B，缺了它任务会一直停在 queued）
Set-Location "D:\app\deepseek_HARNESS\ai_workspace\dsh_project\Learning_aigc\backend"
$env:PYTHONPATH="."
..\.venv\Scripts\python.exe -m app.worker

# 3) 前端（终端 C）
Set-Location "D:\app\deepseek_HARNESS\ai_workspace\dsh_project\Learning_aigc\web"
$env:npm_config_cache = "D:\app\deepseek_HARNESS\ai_workspace\dsh_project\Learning_aigc\var\npmcache"
$env:npm_config_update_notifier = "false"
npm install --no-audit --no-fund
npm run dev            # 开发服务器 http://127.0.0.1:3000
```

### 方式三：生产模式（本沙箱里最稳）

```powershell
Set-Location "D:\app\deepseek_HARNESS\ai_workspace\dsh_project\Learning_aigc\web"
$env:npm_config_cache = "D:\app\deepseek_HARNESS\ai_workspace\dsh_project\Learning_aigc\var\npmcache"
npm install --no-audit --no-fund
npm run build          # 构建 + 类型检查（无类型错误）
npm run start          # http://127.0.0.1:3000，同样需要后端在跑
```

### 只想验证前端能构建

```powershell
cd web
$env:npm_config_cache="$PWD\..\var\npmcache"
npm install --no-audit --no-fund
npm run build
```

后端需允许 `http://127.0.0.1:3000` 与 `http://localhost:3000` 跨域（后端默认
`CORS_ORIGINS` 已包含这两个地址，且 `allow_methods=["*"]`，上传用的 PUT 可直接跨域）。
前端读不到后端时会在页面上直接显示「无法连接后端服务（http://127.0.0.1:8000/api/v1）」。

## 后端地址配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | `http://127.0.0.1:8000/api/v1` | 含 `/api/v1` 前缀的接口基础地址 |

在 `web/` 下新建 `.env.local` 即可覆盖：

```
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api/v1
```

前端区分两个地址（见 `lib/api.ts`）：

- `API_BASE`：含 `/api/v1`，用于调用接口；
- `apiOrigin()`：只有协议 + 主机，用于把后端返回的**相对路径**补成绝对地址——
  `playback_url`（`/api/v1/media/<token>`）、`upload_url`（`/api/v1/assets/<id>/content?token=...`）、
  `shots[].frames[].url` 在本地存储时都是相对路径，必须补 origin 后才能 `<video src>` / PUT。

## 页面清单

| 路由 | 说明 |
| --- | --- |
| `/` | 登录页。账号口令登录；显示 `GET /meta` 的模型 provider、上传上限、时长限制、意图与任务级别；`providers.multimodal === "offline"` 时显著提示「当前为离线确定性分析，景别与运镜保持 unknown」 |
| `/projects` | 项目列表 + 新建项目 + 删除项目 |
| `/projects/[id]` | 项目详情：素材列表（内嵌播放器）、上传区（申请票据 → PUT 原始字节 → complete → 展示校验项与实际探测的时长/分辨率/帧率/编码/有无音轨）、提交拆解（选意图 + 是否同时生成学习任务）→ 轮询 job（展示 stage 与阶段记录）→ 完成跳分析页 |
| `/analyses/[id]` | 拆解工作台：左播放器 + 右镜头时间线（点击跳转，`video.currentTime = start_ms/1000`，实时显示定位误差）、镜头卡片分区（观察事实 / 表达假设 / 可尝试的替代设计 / 证据时间点 / 关联知识卡片 / 不确定性）、学习意图切换（重新拉取 explanations，事实时间线不变）、生成三级学习任务、导出 Markdown、人工修正镜头边界（PATCH 生成 v+1，409 提示重新加载） |
| `/tasks/[id]` | 学习任务：目标、先修知识、步骤、约束、提交要求、评价量表（0—4 分）、预计用时、可用工具；作业提交表单（上传成片 + 创作说明 + 可选文字分镜）→ 轮询 job → 跳反馈页 |
| `/submissions/[id]` | 反馈页：结构差异指标表（参考 / 作业 / 差异）、镜头对齐表（标注 `candidate` 与 `unmatched`，说明允许未匹配）、证据时间点、建议卡片（参考证据 → 作业证据 → 差异 → 与目标关系 → 可执行动作）、文字分镜评分单独一块 |

## 关键实现说明

- `lib/api.ts`：统一 fetch 封装 —— 基础地址、Bearer 注入、统一错误体 `{code,message,request_id}`
  解析（`ApiError`）、401 时清会话并跳登录、`uploadBytes`（XHR PUT，带进度）、
  `pollJob`（1.5 秒间隔，最多 15 分钟，终态 `succeeded/failed/cancelled`）、
  `sha256OfFile`（可选的文件校验值）、`fetchTextWithAuth` + `downloadText`（Markdown 导出）。
- `lib/types.ts`：所有返回结构的 TypeScript 类型。OpenAPI 中
  `additionalProperties: true` 的端点（`/meta`、`/analyses/{id}`、`/explanations`、
  `PATCH /shots`、`POST /learning-tasks`）按后端 `serializers.py` / `schemas.py` 的实现补充。
- 幂等：提交拆解与提交作业都使用 `Idempotency-Key`（`crypto.randomUUID()`），
  响应里 `idempotent_replay=true` 时会提示"服务端复用了同一个任务"。
- `partial=true` 的任务与分析会显式提示"部分镜头未完成"。
- 景别/运镜为 `unknown` 时界面显示「未知」并给出黄色提示，不做任何猜测填充。
- 上传前**本地预检**（`components/UploadPanel.tsx`）：选完文件立刻用 `<video>` 读取时长与分辨率，
  与 `GET /meta` 的 `limits` 比对，命中问题就地给出中文原因与处理办法，不再白传一遍；
  服务端仍会用同一套规则复核（浏览器读不出元数据时只警告，不阻断）。
- 服务端错误码会翻译成可执行建议（`duration_out_of_range` → 剪到 15—60 秒；
  `resolution_too_large` → 导出 1080p；`unsupported_codec` → 改用 H.264 等）。
- 所有空状态、加载态（骨架屏）、错误态（含 `code` / `request_id`）都有对应 UI。

## 常见问题

### 1) 上传总失败，是文件太大吗？

**先看错误码。** 服务端准入限制（`GET /meta` → `limits`，同时展示在上传区）：

| 项 | 限制 | 不通过时的 code |
| --- | --- | --- |
| 文件大小 | ≤ 100 MB | `file_too_large` (413) |
| 时长 | **15 — 60 秒** | `duration_out_of_range` (422) |
| 分辨率高度 | **≤ 1080px** | `resolution_too_large` (422) |
| 容器 | mp4 / mov / m4v | `unsupported_container` (415) |
| 视频编码 | H.264 | `unsupported_codec` (415) |
| 可解码 | 必须能完整解码 | `decode_failed` (415) |

真实例子：`2月9日.mp4`（12.4 MB，2560×1440，60fps，h264，时长 **5.04 秒**）——
**大小完全没问题**，是卡在时长与分辨率上。用后端自身的校验跑一遍：

```
duration_ms = 5038        # < 15000，超短
width x height = 2560 x 1440   # > 1080，超高
VALIDATE => REJECT  code= duration_out_of_range  status= 422
message = 时长需在 15—60 秒之间，实际 5.0 秒
```

剪映导出建议：**1080p / H.264 / mp4**，并且成片时长落在 15—60 秒
（如果只是想把某个片段拿来看，先剪出 15 秒以上的片段再导出）。

注意这两个限制来自后端 `backend/app/pipeline/probe.py::validate_probe`，
变化时会通过 `GET /meta` 自动反映到上传区的提示里。

### 2) 为什么桌面上会冒出很多终端窗口？

两个来源：

1. **启动脚本**：早期版本用 `Start-Process` 起 API / Worker / Web，会各开一个控制台窗口
   （再加 `start.cmd` 本身，一共 4 个）。现在 `start.ps1` 默认给三个服务加
   `-WindowStyle Hidden`，输出全部写进 `var\run\logs\*.log`，桌面上只剩你自己点开的那个窗口。
   想现场看输出时用 `pwsh -File web\start.ps1 -ShowWindows`。
2. **ffmpeg 子进程**：后端每次探测/抽帧都会调用 `ffmpeg`/`ffprobe`
   （`backend/app/media/ffmpeg.py::run_ffmpeg`），一次分析可能调用几十次。
   该函数目前没有传 `creationflags`，所以在 Windows 上只要父进程没有控制台，
   每个 ffmpeg 调用都会**新开一个控制台窗口并闪一下**。
   彻底修法是后端在 `subprocess.run` 上加一行（仅 Windows 生效）：

   ```python
   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
   ```

   在修掉之前，用 `start.ps1`（隐藏控制台）启动后端可以让 ffmpeg 子进程继承隐藏控制台，
   桌面上就不会再闪窗。

## 关于 `scripts/sandbox-compat.cjs`（沙箱兼容层）

本机运行的 DSH 文件沙箱禁止进程通过命名管道建立 stdio / IPC，因此 Next 的两处默认行为会失败，
`npm run build` 与 `npm run dev` 都会报 `spawn EPERM`。兼容层针对性地处理了这两点：

1. **构建**：Next 默认用 `child_process` 派生 jest-worker 构建 worker → EPERM。
   于是 `next.config.mjs` 打开 `experimental.workerThreads = true`、`cpus = 1`、
   `webpackBuildWorker = false`，改用 worker_threads；
   但 Next 15 会把 `nextConfig.generateBuildId`（默认 `()=>null`）与
   `nextConfig.exportPathMap` 这类**函数**一起 postMessage 给静态生成 worker，
   于是抛 `DataCloneError`。兼容层包裹 `Worker.prototype.postMessage`，只在结构化克隆
   失败时把不可克隆成员（函数 / symbol）降级为可克隆数据（保留共享引用与循环引用）。
2. **开发服务器**：`next dev` 会 `fork` 出 `server/lib/start-server` 子进程并用 IPC 握手，
   fork 的 IPC 通道在 Windows 上就是命名管道 → EPERM。兼容层拦截指向 start-server 的
   `fork`，改为在**当前进程内**启动服务器，并用事件对象模拟
   `nextWorkerReady → nextWorkerOptions → nextServerReady` 握手，对 Next 调用方协议一致。

该文件只通过 `--require` 在 `npm run build / dev / start` 时加载，不进入任何业务代码。
调试：`$env:CJ_SANDBOX_COMPAT_DEBUG="1"` 会打印被降级的成员路径与 fork 拦截日志。

在不受此类限制的普通环境里可以直接用官方 CLI（`npx next build` / `npx next dev`），
上述实验开关与兼容层都不是必需的。

## 目录结构

```
web/
├─ app/
│  ├─ layout.tsx            # 深色主题外壳 + 顶栏
│  ├─ globals.css           # 设计系统（深色电影感，原生 CSS）
│  ├─ page.tsx              # / 登录 + 服务元信息
│  ├─ projects/page.tsx     # /projects
│  ├─ projects/[id]/        # /projects/[id]
│  ├─ analyses/[id]/        # /analyses/[id]
│  ├─ tasks/[id]/           # /tasks/[id]
│  └─ submissions/[id]/     # /submissions/[id]
├─ start.ps1                # 一键启动（预检 → seed → API → Worker → Web → 自检）
├─ stop.ps1                 # 一键停止（pids.json，回退按端口）
├─ start.cmd / stop.cmd     # 双击入口（自动选 pwsh 或 powershell）
├─ scripts/
│  └─ sandbox-compat.cjs    # 受限沙箱下的构建/启动兼容层
├─ components/
│  ├─ TopNav.tsx            # 顶栏 + 登录状态
│  ├─ UploadPanel.tsx       # 上传 → 票据 → PUT → complete → 校验结果
│  ├─ JobPanel.tsx          # 任务进度（stage / 阶段记录 / partial / 错误体）
│  └─ useMeta.ts            # GET /meta 钩子
└─ lib/
   ├─ api.ts                # 统一 fetch 封装
   ├─ types.ts              # API 类型
   └─ format.ts             # 时间/字节/枚举标签格式化
```

一键启动会在项目根目录生成：

```
var/run/pids.json           # 本次活动启动的三个进程，stop.ps1 用它精确停止
var/run/logs/api.log        # uvicorn stdout / api.err.log stderr
var/run/logs/worker.log     # app.worker stdout / worker.err.log stderr
var/run/logs/web.log        # next dev|start stdout / web.err.log stderr
var/npmcache/               # 工作区内的 npm 缓存（沙箱不允许写 C 盘缓存目录）
```
