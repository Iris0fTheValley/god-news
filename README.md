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
- 初审批准后自动生成口播脚本；脚本人工审核批准后，才可显式启动本地 GPT-SoVITS 合成语音
- 人工终审通过后产出 `ProductionManifest` 时间轴，并创建带输入资产快照的可审阅视频批次
- 软归档（ARCHIVED）、重开终审、故事编辑，完整审计追踪
- 角色管理、采集运行日志、视频批次编排、BGM 目录浏览、运维清理

## 管线

```
抓取 → 翻译/AI分类 → 人工初审 → 生成口播 → 人工审口播 → 手动 TTS → 人工终审 → DONE
                                                          ↑ 仅此处显式消耗本地 GPU
                                             终审改稿 ───┘
任一非归档状态 → ARCHIVED（软归档）
```

## 审核与手动合成

生产状态路径为：

`FETCHED → TRANSLATED → PENDING_FIRST_REVIEW → PROCESSING_SCRIPT → SCRIPT_READY → PENDING_TTS → PROCESSING_TTS → PENDING_SECOND_REVIEW → DONE`。

`SCRIPT_READY` 是口播脚本的人工审核门。批准后故事进入 `PENDING_TTS`；客户端必须以当前乐观锁版本显式发起合成，服务才会启动本地 TTS：

```http
POST /api/v1/stories/{story_id}/reviews/script
Content-Type: application/json

{"expected_story_version": 5, "decision": "approve", "reviewer_id": "script-editor"}
```

```http
POST /api/v1/stories/{story_id}/synthesize
Content-Type: application/json

{"expected_story_version": 6}
```

TTS 失败会安全回到 `PENDING_TTS` 并保留 `last_failure`，需要使用新版本再次手动触发；`/resume` 不会越过 `SCRIPT_READY` 或 `PENDING_TTS` 自动合成。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Uvicorn（全异步） |
| 数据模型 | Pydantic v2 强类型领域模型 + 状态机 |
| 持久化 | SQLAlchemy 异步 + SQLite，乐观并发 |
| LLM | DeepSeek V4 Flash（可选 LM Studio 本地） |
| 记忆 | ChromaDB 本地嵌入式持久化 |
| TTS | GPT-SoVITS v2Pro，单个串行 loopback 子进程；按段切换角色与七情绪参考材料 |
| 前端 | React + Vite + TanStack Query，OpenAPI 自动生成类型 |
| 视频 | 可替换的本地 Remotion 适配器；同一 `ProductionManifest 1.0` 生成 9:16 与 16:9，经 ffprobe 和 SHA-256 验证 |

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
- 视频批次、时间轴审阅、审核输入快照和真实 Remotion 双格式渲染已接入；`GOD_NEWS_VIDEO_RENDERER_ENABLED=false` 仍是安全默认值。当前主持人只是明确标注的可替换槽位，Live2D 与 EpisodePlan 尚未完成。
- 已启用 TTS 的角色使用独立的权重对、七组情绪参考音频/文本与可选参考语言；合成器按段选择角色和情绪。为保护显存，不同权重永不并存，切换时会先终止旧本地子进程。
- 固定内容源的网络采集节奏由后端强制：同一来源两次网络采集完成之间不少于 30 秒，全局最多两个采集请求并行。前端不提供频率设置；随仓库启动命令固定为单 worker，若未来部署多进程/多实例，须先替换为持久化租约适配器。
