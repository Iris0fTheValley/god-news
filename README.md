# god-news

自动抓取全球正面新闻 → AI 翻译/脚本 → 两阶段人工审核 → 本地 TTS 语音合成 → 短视频产出。

## 快速开始

```powershell
git clone git@github.com:Iris0fTheValley/god-news.git
cd god-news

# 后端
py -3.11 -m venv .venv && .\.venv\Scripts\Activate.ps1
uv sync --extra dev --extra fetchers --locked
Copy-Item .env.example .env   # 编辑填入 API Key

# 前端
pnpm install
pnpm --filter @god-news/frontend dev

# 一键启动
.\start.cmd
```

离线演示（不需要 API Key、网络或 GPU）：

```powershell
.\scripts\start.ps1 -OfflineDemo
```

## 功能

- 四个固定来源自动抓取（大众新闻、Reddit、Guardian、Pikabu），三层 URL 抓取降级
- LLM 翻译 + 摘要 + AI 内容分类，人工初审可修订
- 初审批准后自动生成口播脚本并调用本地 GPT-SoVITS 合成语音
- 人工终审通过后产出 `ProductionManifest` 时间轴，并创建带输入资产快照的可审阅视频批次
- 软归档（ARCHIVED）、重开终审、故事编辑，完整审计追踪
- 角色管理、采集运行日志、视频批次编排、BGM 目录浏览、运维清理

## 管线

```
抓取 → 翻译/AI分类 → 人工初审 → 脚本 → TTS → 人工终审 → DONE
               ↑ 批准后才消耗本地 GPU          ↓
               ← ← ← 重开终审 ← ← ← ← ← ← ← ←
               任一状态 → ARCHIVED（软归档）
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Uvicorn（全异步） |
| 数据模型 | Pydantic v2 强类型领域模型 + 状态机 |
| 持久化 | SQLAlchemy 异步 + SQLite，乐观并发 |
| LLM | DeepSeek V4 Flash（可选 LM Studio 本地） |
| 记忆 | ChromaDB 本地嵌入式持久化 |
| TTS | GPT-SoVITS v2Pro，单 story loopback 子进程 |
| 前端 | React + Vite + TanStack Query，OpenAPI 自动生成类型 |
| 视频 | Remotion 9:16 工程骨架，消费 `ProductionManifest 1.0`；生产渲染器仍是可替换适配器 |

## 开发

```powershell
# 后端
python -m pytest --cov=god_news --cov-fail-under=75
python -m ruff check .
python -m mypy src/god_news

# 前端
pnpm --filter @god-news/frontend check
pnpm --filter @god-news/frontend test

# 视频
pnpm --filter @god-news/video check
pnpm --filter @god-news/video test
```

前端接口契约、已实现能力与诚实的运行边界见 `docs/frontend-api-mapping.md`。

## 当前运行边界

- 四个真实内容源只有在对应凭据、用途授权和站点条款均确认后才会启用；离线演示不访问真实网络。
- 视频批次、时间轴审阅和输入资产完整性校验已实现；真正的 Remotion 批量渲染进程仍需接入 `BatchVideoRenderer` 适配器。
- 角色中的 GPT/SoVITS 权重路径当前是可审计的元数据。现有 TTS 保持单语音实例，后续多角色合成应以独立适配器接入。
