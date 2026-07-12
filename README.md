# god-news

`god-news` 是一个配置驱动、两阶段人工审核前置的异步内容生产实验系统。当前链路是：

```text
互联网/文本 → 抓取 → 来源清洗 → 翻译/摘要/AI 分类 → 人工初审
                                                   ↓ 批准后才消耗本地 GPU
                                             脚本 → 本地 TTS → 人工终审 → DONE
```

生产主线保留以下七个状态；`ARCHIVED` 是显式软归档终态，不混入制作进度。失败信息单独持久化，之后通过 `resume` 从安全检查点继续：

```text
FETCHED → TRANSLATED → PENDING_FIRST_REVIEW → PROCESSING_SCRIPT
        → SCRIPT_READY → PENDING_SECOND_REVIEW → DONE

任一未归档状态 → ARCHIVED
DONE → PENDING_SECOND_REVIEW  （重开终审）
```

## 已实现

- FastAPI + Uvicorn 全异步 API；Pydantic v2 领域模型，不把供应商裸响应泄漏到业务层。
- SQLite/SQLAlchemy 异步持久化、乐观并发版本和完整状态转换/审核记录。
- 固定三层 URL 抓取降级：Jina Reader → DrissionPage → 独立 Scrapy + Trafilatura 子进程；第三层在入口正文不足时执行有深度/页数上限的同站爬取。
- DeepSeek V4 Flash 默认 LLM；可配置切换至 LM Studio 的 OpenAI-compatible Chat Completions。
- LLM 前召回、后写入的 `MemoryProvider` 端口；当前适配器是嵌入式持久化 ChromaDB，记忆故障可 fail-open，永远不作为状态真源。
- 初审批准前绝不生成脚本或启动 TTS。
- GPT-SoVITS `api_v2.py` 每个 story 启动一次 loopback 子进程，批量完成该 story 后退出；超时会回收进程树。
- 终审可请求修改脚本并重合成；`production-manifest` 输出未来视频模块可直接消费的时间轴。
- 无网络、无 API Key、无 GPU 的确定性端到端测试适配器。
- 大众新闻、Reddit、Guardian、Pikabu 四套独立强类型来源契约/清洗器，保留归因、权利、媒体与来源专属字段。
- React/Vite 制作台：故事队列（搜索+分类筛选+删除归档）、源证据、AI 分类复核、两阶段审核（带二次确认对话框）、分段脚本编辑（Ctrl+Z/Y 撤销栈）、逐段音频、审计时间轴和 FSM 状态迁移日志。
- 角色管理、采集运行日志、视频批次、BGM 离线目录浏览和运维操作页面均为完整 UI 壳，API 类型由 OpenAPI 自动生成。
- 全局 Toast 通知（带撤销按钮）、不可逆操作确认对话框、? 键快捷键面板、统一空状态占位。
- Remotion 9:16 渲染包：消费 `ProductionManifest 1.0`，支持字幕、本地 BGM、黑屏片头/转场及 Live2D/差分图类型预留；当前渲染器为桩，待 Remotion Node 子进程桥接。

## 目录

```text
src/god_news/
├── api/                 # HTTP 传输、错误边界、trace_id
├── application/         # 审核闸门与确定性用例编排
├── domain/              # 强类型模型、制作主线 + 软归档 FSM、可替换端口
├── infrastructure/      # DB、抓取、LLM、记忆、TTS 适配器
├── sources/             # 四个固定来源的原始契约、清洗器与健康政策
├── workers/             # DrissionPage/Scrapy 一次性隔离进程
├── config.py            # 唯一运行时配置入口
└── container.py         # 组合根；替换实现只发生在这里
frontend/                # React/Vite 人工审核制作台
video/                   # Remotion 组合、校验与隔离渲染 CLI
scripts/                 # OpenAPI、启动/停止工具
```

## 安装

需要 Python 3.11–3.13。主应用与 GPT-SoVITS 使用各自的 Python 环境，不要升级 vendor runtime。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
uv sync --extra dev --extra fetchers --locked
Copy-Item .env.example .env
```

仓库中的 `uv.lock` 固定了已验证的完整依赖解析。如果没有 `uv`，可改用
`python -m pip install -e ".[dev,fetchers]"`，但该方式只遵循版本范围，不具备锁文件级复现性。

编辑本地 `.env`：

- `GOD_NEWS_DEEPSEEK_API_KEY`：只填新建的 Key。聊天中出现过的 Key 已泄漏，必须先吊销。
- 默认模型已经是官方 ID `deepseek-v4-flash`；翻译任务默认关闭 thinking。
- 切换 LM Studio 时同时设置 `GOD_NEWS_LLM_PROVIDER=local` 和 `GOD_NEWS_LOCAL_LLM_ENABLED=true`。
- ChromaDB 默认保存到 `./data/chroma`；collection 和本地 embedding function 都可由 `.env` 配置。
- 单篇送入 LLM 的正文默认上限为 60,000 字符；超限会显式失败并保留 `FETCHED` 检查点，不会静默截断。可按模型上下文调整 `GOD_NEWS_MAX_SOURCE_CHARACTERS`。
- GPT-SoVITS 默认指向本机 `J:/AI friend/GPT-SoVITS-v2pro-20250604`。

### 一键启动

完成 `.env` 后可直接双击仓库根目录的 `start.cmd`，或从 PowerShell 启动：

```powershell
.\scripts\start.ps1
# 前端 http://127.0.0.1:5173
# 后端 http://127.0.0.1:8000

.\scripts\stop.ps1
```

首次启动会在缺少环境时执行锁文件安装。启动器保存并校验自己创建的 PID，前后端均以隐藏子进程运行，日志写入 `logs/dev/`；重复执行会复用已健康运行的服务。URL/文本、目标语言、时长、风格、speaker、emotion、speed 和 pitch 均可在新建故事表单配置。

无需 Key、网络或 GPU 的演示模式：

```powershell
.\scripts\start.ps1 -OfflineDemo
```

它仍走真实 HTTP、React、制作主线状态机、两次人工点击和 WAV 播放，只把抓取/LLM/TTS 换为确定性测试适配器。该模式不能作为真实来源或模型验收证据。

也可只运行后端：

```powershell
god-news
# OpenAPI: http://127.0.0.1:8000/docs
```

应用默认只监听 loopback。当前没有用户认证；在加入认证、出站网络隔离和反向代理策略前，不要暴露到局域网或公网。

`GET /api/v1/health/ready` 会在统一截止时间内调用 LLM 的 `GET /models`、检查 ChromaDB heartbeat/collection，并预检 GPT-SoVITS YAML、权重、参考稿和 3–10 秒 WAV；它不会为探活加载 TTS 模型或触发 embedding 模型下载。

## API 最短流程

1. `POST /api/v1/stories`：提交 URL 或文本，返回状态应为 `PENDING_FIRST_REVIEW`。
2. `POST /api/v1/stories/{id}/reviews/first`：携带刚读取的 `expected_story_version`；`approve` 后才生成脚本与本地音频。
3. `POST /api/v1/stories/{id}/reviews/second`：再次携带最新 version；`approve` 后进入 `DONE`。
4. `GET /api/v1/stories/{id}/production-manifest`：获取音频对齐时间轴。
5. `POST /api/v1/stories/{id}/resume`：从 `FETCHED`、`PROCESSING_SCRIPT`、`SCRIPT_READY`，或缺音频的终审状态恢复。
6. `DELETE /api/v1/stories/{id}`：软归档，保留证据和审计；默认列表隐藏归档，按 ID 仍可读取。
7. `POST /api/v1/stories/{id}/reopen`：仅将 `DONE` 重开至 `PENDING_SECOND_REVIEW`。
8. `PATCH /api/v1/stories/{id}`：携带 `expected_story_version`，可编辑独立的 editorial title、style 与 target duration，不会改动来源证据。
9. `GET /api/v1/metrics/classification`：返回人工初审后的分类接受数与准确率。
10. `GET/POST /api/v1/roles`：管理旁白与主持人人设（名称、语速音高、TTS 权重路径）。
11. `GET/POST /api/v1/source-runs`：查看采集运行记录与逐条目结果详情。
12. `GET/POST /api/v1/video/batches`：创建视频批次、提交时间轴审阅、发起渲染（渲染器桩）。
13. `GET /api/v1/video/bgm`：浏览本地 BGM 文件夹中可用音轨。
14. `POST /api/v1/operations/retention/runs` + `GET /api/v1/operations/runs` + `GET /api/v1/operations/schedules`：手动清理过期媒体文件、查看运维历史和调度状态。

文本数据源请求示例：

```json
{
  "source": {
    "kind": "text",
    "title": "Offline fixture",
    "language": "en",
    "text": "A sufficiently detailed source article goes here."
  },
  "target_language": "zh-CN",
  "style": "准确、克制的短视频旁白",
  "target_duration_seconds": 90,
  "speaker_id": "narrator",
  "emotion": "neutral",
  "speed": 1.0,
  "pitch": 0.0
}
```

审核 decision 只能是 `approve` 或 `request_changes`。初审可修订译文、摘要、关键点、AI 分类、候选池建议和脚本偏好；终审的 `request_changes` 可附带强类型 `revised_script`，系统会生成新 revision 音频并仍停留在终审。AI 分类原值与人工最终值同时保留，准确率不会因人工覆盖而失去依据。

## 四个固定来源

`POST /api/v1/sources/items` 是网络适配器与核心管线之间的强类型边界。四个清洗器分别处理大众新闻、Reddit、Guardian 和 Pikabu，统一输出规范 URL、NFKC 文本、UTC 时间、内容哈希、标签、媒体、归因和权利审查标记。URL 哈希与正文哈希都有数据库唯一约束；重复内容返回带原 story ID 的 409。

`GET /api/v1/sources/health` 把 `configured`、`authorized`、`reachable`、`contract_ok` 分开报告，避免“域名能打开”被误报成“来源可合法投入 AI”。默认政策是：

- Reddit 只接官方 OAuth Data API，需要 client ID/secret、明确 user-agent 和 API 使用授权。
- Guardian 只接官方 Content API，需要 Key 以及与 AI 用途相符的许可确认。
- 大众新闻和 Pikabu 只允许经确认的公开页面契约；不调用未公开私有 API，遇 CAPTCHA 停止。
- 每条内容仍保留独立版权/转载人工复核，不因来源级授权自动放行。

仓库内四份 fixture 已分别通过清洗、入库和去重测试；真实抓取成功不能由 fixture 代替，必须在操作者完成相应授权配置后单独记录。

## 前端与 Remotion

```powershell
pnpm --filter @god-news/frontend check
pnpm --filter @god-news/video check
pnpm --filter @god-news/video render -- --input .\video\example\video-props.json --output .\out\story.mp4
```

前端类型只从后端 OpenAPI 生成，禁止维护第二套 Story/FSM 类型。前端接口映射与后端待实现项见 `docs/frontend-api-mapping.md`。Remotion CLI 只接受本地资产，把音频/BGM 按 SHA-256 复制到一次性 public 目录，拒绝远程 URI，完成后清理临时目录。当前 Live2D 与差分图字段是明确的渲染器预留，不会假装已经实现角色驱动。

每次审核还应由客户端生成并发送稳定的 `review_id`。相同 ID 和相同请求可安全重试，不会重复启动 TTS；相同 ID 对应不同请求会返回 409。审核记录绑定 story version、译文哈希、脚本 revision 和音频 bundle 哈希，避免“批准的到底是哪一版”失去审计证据。

## GPT-SoVITS 约束

本机核查确认自动化入口是 `api_v2.py`，不是旧 `api.py`、批处理脚本或代理脚本。适配器会：

- 从 vendor YAML 复制出每个任务独立的临时配置，不改原文件。
- 默认把 `custom` 切到真正的 `v2Pro` 底模；不会误用 YAML 内失效的 `E:` 路径。
- 只绑定 `127.0.0.1`，轮询 `/openapi.json` 就绪，使用 `POST /tts`，最后调用 `/control?command=exit` 并兜底杀进程树。
- 一个 story 内复用一次模型加载，多个 story 的 TTS 并发固定为 1。

已训练的 `Neuro` 权重属于 v2，不属于 v2Pro。若要使用 Neuro，必须显式设置 profile 为 `v2`，并同时设置对应 GPT 与 SoVITS 权重；禁止混搭版本。

GPT-SoVITS 原生支持 `speed`，但没有 `pitch`、结构化 `emotion` 或直接 `speaker_id` 参数。因此领域接口保留这些字段，而当前适配器对未配置 speaker、非 neutral emotion 和非零 pitch 明确报错，绝不静默忽略。

LM Studio 的约 21.2 GB GGUF 与 TTS 很可能无法同时驻留 24 GB GPU。使用本地 LLM 时，应在初审批准前卸载 LM Studio 模型，或在部署层增加统一 GPU 租约；默认 DeepSeek 云端模式没有该冲突。

本机真实验收（2026-07-11）已用严格 `v2Pro` profile 完成一次冷启动与单段合成：约 49 秒后得到 32 kHz、单声道、约 2.98 秒的 WAV；参考音频、有效运行配置、GPT/SoVITS 权重和音频文件哈希均生成，结束后 vendor Python 进程为零且显存回落。该验收不属于默认自动测试，因为它会真实占用 GPU。

## ChromaDB 记忆层

默认 `GOD_NEWS_MEMORY_PROVIDER=chromadb`。适配器通过 `PersistentClient` 保存到本地目录，所有同步 Chroma/embedding 操作都串行放入专用工作线程，不阻塞 FastAPI 事件循环。collection 固定使用 cosine 距离；写入 ID 是完整 `MemoryWrite` 的版本化规范哈希，同一知识重复写入会执行幂等 `upsert`。metadata 保存 `agent_id`、`story_id`、类别、批准标记和来源/正文哈希，召回在数据库查询层同时过滤 `agent_id` 与 `approved=true`，返回后还会再次校验。

`GOD_NEWS_MEMORY_CHROMA_EMBEDDING_FUNCTION=default` 与 `GOD_NEWS_MEMORY_CHROMA_EMBEDDING_MODEL=all-MiniLM-L6-v2` 对应 Chroma 自带的本地 ONNX 模型。它首次执行实际语义写入/查询时可能联网下载模型到用户缓存；缓存完成后推理完全本地。自动测试注入小型确定性 embedding，不访问网络。若将来改变 embedding 或距离度量，必须使用新的 collection 名称，不能把不同向量空间混进已有索引。

`GOD_NEWS_MEMORY_RECALL_FAIL_OPEN` 只控制召回失败时是否允许无记忆继续。知识写入发生在业务状态持久化之后，失败会记录但不会谎报业务回滚；需要强交付保证时，可在该端口前增设持久 outbox，而不用修改状态机或 Chroma 适配器。

## 验证

```powershell
python -m ruff check .
python -m mypy src/god_news
python -m pytest --cov=god_news --cov-report=term-missing --cov-fail-under=75
pnpm --filter @god-news/frontend check
pnpm --filter @god-news/video check
```

测试覆盖完整制作路径、软归档/重开终审、两道审核闸门、失败恢复、乐观并发、抓取降级、URL 安全政策、API 和未来视频 manifest。测试不会访问真实网络、DeepSeek、LM Studio 或 GPU。真实 GPT-SoVITS 验收会实际占用 GPU，默认不在自动测试中启动。

## 已核对的上游契约

- [DeepSeek 首次 API 调用与当前模型 ID](https://api-docs.deepseek.com/)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode)
- [DeepSeek 列出模型](https://api-docs.deepseek.com/api/list-models)
- [OpenAI Python SDK 异步客户端](https://github.com/openai/openai-python#async-usage)
- [Chroma PersistentClient](https://docs.trychroma.com/reference/python/client)
- [Chroma collection query/upsert](https://docs.trychroma.com/reference/python/collection)
- [Chroma 默认本地 embedding function](https://docs.trychroma.com/docs/embeddings/embedding-functions)
- [Chroma metadata filtering](https://docs.trychroma.com/docs/querying-collections/metadata-filtering)
- [Jina Reader](https://github.com/jina-ai/reader#usage)
- [DrissionPage 浏览器生命周期](https://www.drissionpage.cn/browser_control/browser_object/)
- [Scrapy asyncio/reactor 约束](https://docs.scrapy.org/en/latest/topics/asyncio.html)
- [Trafilatura Python API](https://trafilatura.readthedocs.io/en/latest/usage-python.html)

## 安全边界

- URL 层只允许 HTTP(S)、指定端口和公网解析地址；每个 Scrapy redirect 重新检查。DNS 预检仍不能彻底消除 rebinding，生产应再加出站防火墙/代理或域名 allowlist。
- DrissionPage 执行不可信 JavaScript；生产浏览器必须运行在网络受限的容器或低权限账号中。
- 日志只记录 `trace_id`/`story_id` 和安全错误码，不记录 API Key、完整正文或 vendor 错误体。
- `.env`、数据库、输出和运行时临时文件均已从 Git 排除。
