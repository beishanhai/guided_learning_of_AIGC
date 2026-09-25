# 贡献指南（Contributing）

感谢你愿意参与拆镜学。提交任何内容前，请先读这份文件。

## 1. 许可与贡献者条款

本项目以 **GNU Affero General Public License v3.0（AGPL-3.0）** 发布，全文见 `LICENSE`。

提交 Pull Request 即表示你同意：

1. 你的贡献同样以 AGPL-3.0 授权（inbound = outbound）；
2. 你拥有所提交内容的著作权，或已获得授权；
3. 你提交的内容不包含未授权的第三方代码、素材、字体、模型权重或密钥。

**不要提交**任何你没有权利开源的影视素材、截图、音乐或字体。项目的示例视频由 `backend/app/sample_data.py`
用 FFmpeg 程序化生成，请沿用这个做法，不要上传真实影片。

若某段代码或素材来自别处，请在 PR 描述里写清来源、许可证，并同步更新 `THIRD_PARTY.md`。

## 2. 开发环境

```powershell
git clone <your-fork>
cd Learning_aigc
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
cd backend; $env:PYTHONPATH="."; ..\.venv\Scripts\python.exe -m app.cli seed --with-samples
```

需要系统安装 **FFmpeg 与 ffprobe**（并在 PATH 中）。前端需要 Node ≥20。

前端依赖与构建：

```powershell
cd web
$env:npm_config_cache="$PWD\..\var\npmcache"   # 受限环境下必须把 npm 缓存放进工作区
npm install --no-audit --no-fund
npm run build
```

一键起停：`powershell -File scripts\dev.ps1` / `powershell -File scripts\stop.ps1`。

## 3. 提交前自检（必做）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1        # 后端用例必须全绿
cd web; npm run build                                            # 前端必须 0 类型错误
```

如果你改了 API 契约，请同时更新 `docs/openapi.json`（`python -m app.cli export-openapi`）与 `docs/API契约.md`。
如果你改了数据库模型，请生成迁移：`python -m alembic revision --autogenerate -m "..."`，
不要依赖 `create_all`。

## 4. 代码约定

- Python：3.11+，类型注解齐全，行宽 120（`backend/pyproject.toml`）；注释写“为什么”，不写“是什么”。
- 前端：TypeScript，App Router + 原生 CSS + CSS Modules；**不引入 Tailwind 或 UI 库**。
- 外部模型调用只能出现在 `backend/app/providers/`` 下`，业务与学习规则不得感知具体供应商。
- 阈值、模型 ID、价格、超时一律走 `backend/app/config.py`（`CJX_*` 环境变量），不要硬编码进学习规则。
- **禁止**：把密钥、口令、签名 URL 写进代码、日志、测试或文档。
- 新增依赖前请说明理由，并同步更新 `backend/requirements.txt` 与 `THIRD_PARTY.md`。

## 5. 产品与内容约定（本项目特有）

拆镜学的核心承诺是"不把推测当事实"。改代码时请守住这几条：

1. 观察事实 / 表达假设 / 实践建议 / 证据 / 不确定项 必须分开输出，不得合并成一句结论；
2. 证据不足时必须输出 `unknown`，不得为了"看起来完整"而猜测景别、运镜或作者意图；
3. 没有接入真实模型时，产物必须显式标注 `provider=offline`，不得伪装成模型结果；
4. 单人单帧不能证明运镜；时间戳必须落在片长内；知识卡片 ID 必须真实存在于 `backend/knowledge/cards.yaml`；
5. 知识卡片内容需标注来源与审校人，不编造书名、页码、URL 或数据。

## 6. 提交信息与 PR

- 提交信息用祈使句，一次提交只做一件事，例如：`feat: 支持镜头边界人工修正生成新版本`；
- PR 描述里写：动机、改动点、验证方式（贴命令与结果）、未覆盖的风险；
- 涉及行为变更的 PR 必须带测试；只改文档的 PR 请在标题加 `docs:`。

## 7. 报告问题

功能缺陷请用 GitHub Issues 模板；**安全与隐私问题请勿公开开 issue**，走 `SECURITY.md` 里的私下渠道。
