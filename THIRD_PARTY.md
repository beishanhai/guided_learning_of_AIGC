# 第三方组件、参考项目与许可声明

本文件是本仓库**唯一的第三方来源与许可声明汇总**。它回答三个问题：

1. 本仓库自己用什么许可证，别人要怎么遵守；
2. 本仓库直接依赖了哪些第三方组件，各自什么许可证；
3. 立项阶段调研过的开源项目分别是什么状态，本项目有没有用到它们的代码。

> 状态说明：**已核实** = 本次从官方渠道读到许可证原文；**未核实** = 只见到公开页面描述，
> 尚未取得 LICENSE / NOTICE / commit 锁定证据。未核实项一律**不得**被当作"可自由复用"。

---

## 1. 本仓库的许可证

**GNU Affero General Public License v3.0（AGPL-3.0）**，全文见仓库根目录 `LICENSE`。

Copyright (C) 2026 ChaiJingXue contributors

### 这意味着什么

| 你可以 | 你必须 |
|---|---|
| 自由使用、修改、分发本项目 | 保留版权与许可声明，衍生作品同样以 AGPL-3.0 发布 |
| 用于学习、教学、比赛、商业内部使用 | 分发时提供完整对应源码（Corresponding Source） |
| 基于它搭建网络服务 | **AGPL 第 13 条**：让通过网络与之交互的用户能获得源码 |

因此本项目在界面（`web/` 与 `/demo`）中提供了"源代码"入口；部署者**必须**把
`NEXT_PUBLIC_SOURCE_URL`（前端）指向你实际部署版本的源码地址，否则不满足 AGPL §13。

### 不提供担保

本项目按"现状"提供，不附带任何明示或默示担保。它是**教学与研究用原型**，其中的分析结果
（尤其是"表达假设"）不代表原作者意图，也不构成任何版权合法性判断。

---

## 2. 直接依赖（运行时 / 构建时）

### 2.1 Python 后端

| 组件 | 版本 | 许可证（公开信息） | 核实状态 |
|---|---|---|---|
| fastapi | 0.141.1 | MIT | 未核实 |
| starlette | 1.7.0 | BSD-3-Clause | 未核实 |
| uvicorn | 0.53.0 | BSD-3-Clause | 未核实 |
| pydantic / pydantic-core / pydantic-settings | 2.13.5 / 2.46.5 / 2.15.0 | MIT | 未核实 |
| SQLAlchemy | 2.0.54 | MIT | 未核实 |
| alembic | 1.20.0 | MIT | 未核实 |
| httpx / httpcore / h11 | 0.28.1 / 1.0.9 / 0.16.0 | BSD-3-Clause | 未核实 |
| PyYAML | 6.0.3 | MIT | 未核实 |
| celery / kombu / billiard / amqp / vine | 5.6.3 等 | BSD-3-Clause | 未核实 |
| redis (redis-py) | 8.1.0 | MIT | 未核实 |
| boto3 / botocore / s3transfer | 1.43.101 等 | Apache-2.0 | 未核实 |
| python-multipart | 0.0.32 | Apache-2.0 | 未核实 |
| pytest / pluggy / iniconfig | 9.1.1 等 | MIT | 未核实 |
| certifi / idna / urllib3 | — | MPL-2.0 / BSD-3-Clause / MIT | 未核实 |

### 2.2 前端

| 组件 | 版本 | 许可证 | 核实状态 |
|---|---|---|---|
| next | 15.5.26 | MIT | 未核实 |
| react / react-dom | 19.1.0 | MIT | 未核实 |
| typescript | 5.7.x | Apache-2.0 | 未核实 |
| @types/* | — | MIT | 未核实 |

仅这些依赖，未引入 Tailwind、UI 组件库、外部字体或 CDN 资源。

### 2.3 系统与外部服务

| 组件 | 许可证 / 条款 | 对本项目的影响 |
|---|---|---|
| **FFmpeg / ffprobe** | LGPL-2.1+（构建若含 GPL 组件则整体 GPL） | 本项目**只以独立进程 + 参数数组调用**，不链接、不内联、不分发其二进制，因此不会把其条款传染到本仓库代码。若你改为静态链接或随仓库分发 FFmpeg 二进制，请自行复核授权 |
| PostgreSQL | PostgreSQL License（类 BSD） | 生产数据库，无传染性 |
| Redis | 7.2 及以前 BSD-3-Clause；7.4+ RSALv2 / SSPLv1 | 仅 `queue_backend=celery` 时需要；上线前确认版本与许可，必要时改用 Valkey |
| 多模态模型 API | 供应商商业条款 | 素材会发送给所选服务，部署者必须核对数据保留、跨境与删除条款并向用户告知 |
| 托管 ASR 服务 | 供应商商业条款 | 同上 |

---

## 3. 参考项目与致谢（**本项目未引入其中任何代码或素材**）

立项阶段调研过下列开源项目，用于**判断可行性与产品结构**。依据其公开 README 的功能描述，
我们只提取了"这类系统通常包含哪些环节"这一层认知，**没有复制、改写、内联、翻译任何源代码、
提示词、素材或数据集**，也没有把它们作为运行时依赖。

| 项目 | 公开能力（据其 README/公开页面） | 本项目实际取用 | 公开许可状态 | 核实状态 |
|---|---|---|---|---|
| [caoqc4/RemixKit](https://github.com/caoqc4/RemixKit) | 参考视频证据提取、结构分析、改编 brief、视频变体 | **仅思路**：确认"证据 → 结构 → 改编 brief"这条链路合理 | 未取得 LICENSE 证据 | **未核实** |
| [AKA-liang/one-daihuo](https://github.com/AKA-liang/one-daihuo) | 电商短视频分镜分析、商品替换、合成导出 | **仅思路**：生成扩展方向的可行性判断（本期未实现） | 未取得 LICENSE 证据 | **未核实** |
| [Danyangkk/viral-video-analyze](https://github.com/Danyangkk/viral-video-analyze) | 视频拆解、关键帧、结构分析、HTML 报告 | **仅思路**：报告的组织方式与关键时刻呈现 | 未取得 LICENSE 证据 | **未核实** |
| [Stupides9169/video-script-extraction-skill](https://github.com/Stupides9169/video-script-extraction-skill) | 时间码脚本、代表帧、不确定性标注 | **仅思路**：统一结果结构与不确定性表达 | 未取得 LICENSE 证据 | **未核实** |
| [Breakthrough/PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | 镜头切分与关键帧提取 | **未使用**。本项目改用 FFmpeg `lavfi.scene_score` + 自适应阈值自研实现，理由见 `docs/技术选型记录.md`；保留适配位以便未来替换 | **BSD 3-Clause**（Copyright (C) 2014, Brandon Castellano，读自其官方许可页） | 已核实（许可文本），未做 commit 锁定 |
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 基于 CTranslate2 的 Whisper 转写 | **未使用**。仅保留 HTTP ASR 适配位；默认 `asr_provider=none` | 代码 **MIT**（读自 PyPI 元数据）；**模型权重条款需单独核查** | 已核实（代码许可），权重未核实 |

### 3.1 为什么强调"未引入"

- 这些仓库的公开页面**不等于**已确认可自由复用；见其各自仓库的 LICENSE 与第三方声明；
- 本项目选择"组件组合 + 自研学习引擎"，就是为了避免继承未知鉴权、公开存储、明文密钥
  和不可用供应商适配器等风险；
- 本项目**不复制**任何第三方仓库的提示词或素材。

### 3.2 未来若要引入代码，必须走完这套准入流程

1. 记录 URL + **commit SHA** + LICENSE + NOTICE + 第三方组件与权重条款；
2. 在干净环境启动，并用 3 个自有样片跑通相关功能；
3. 确认接口是真实调用还是占位/模拟数据，并测试一个失败场景；
4. 评估代码结构、测试覆盖、未解决问题与最近提交（不只看 stars）；
5. 1 天内完成隔离验证，不满足则回到组件组合路线；
6. 以上全部完成后，**同步更新本文件**并在 PR 描述中给出证据。

未取证前，不要在代码、文档或演示中出现"基于 X 项目"之类的表述。

---

## 4. 商标与名称

"拆镜学 / ChaiJingXue"是本项目的名称，不授予任何商标许可。仓库中提及的第三方项目名称、
公司名称与产品名称归各自所有者所有，仅用于事实性指代。

---

## 5. 复核待办（首次公开发布前的门禁）

- [ ] 用 `pip-licenses` / `npm ls --json` 生成 SBOM，逐条核对第 2 节的许可证原文与哈希
- [ ] 确认 FFmpeg 的构建参数与调用方式（必须保持"独立进程、参数数组"）
- [ ] 确认 Redis 版本与许可，或改用 Valkey
- [ ] 确认所选模型 / ASR 服务的数据保留、跨境与删除条款，并写入用户告知
- [ ] 若将来引入第 3 节任一项目的代码，补 commit SHA 与许可证原文
- [ ] 在仓库根补 `NOTICE`（仅当引入 Apache-2.0 组件并需要保留其声明时）
- [ ] 把 `LICENSE` 中的版权主体替换为实际权利人（个人姓名或团队/机构名称）
