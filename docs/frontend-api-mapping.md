# god-news 前后端接口契约

更新时间：2026-07-13

本文件描述工作台实际调用的后端能力。`frontend/openapi.json` 与
`frontend/src/api/generated.ts` 由 FastAPI 导出，是可生成的唯一事实来源；本文件只补充业务语义和使用边界。

```powershell
pnpm --dir frontend generate:openapi
pnpm --dir frontend check
```

## 故事与审核

| 前端能力 | API | 语义 |
| --- | --- | --- |
| 队列与状态筛选 | `GET /api/v1/stories` | 默认不返回归档故事；`status=ARCHIVED` 显式查看归档。 |
| 工作台 | `GET /api/v1/stories/{story_id}` | 可读取归档故事及其历史证据。 |
| 创建 | `POST /api/v1/stories` | URL 或上传文本进入抓取、翻译和初审管线；创建界面只收集来源与目标语言，播报偏好在初审提交。 |
| 编辑元数据 | `PATCH /api/v1/stories/{story_id}` | 需要 `expected_story_version`；只允许标题、风格与目标时长，不能篡改来源快照。 |
| 归档 | `DELETE /api/v1/stories/{story_id}` | 软归档为 `ARCHIVED`，保留来源、版本、审核和状态迁移证据。 |
| 重开终审 | `POST /api/v1/stories/{story_id}/reopen` | 仅 `DONE → PENDING_SECOND_REVIEW`。 |
| 初审 | `POST /api/v1/stories/{id}/reviews/first` | 可在此提交 `preferences` 覆盖（播报风格、目标时长、默认角色、情绪、语速等）；批准后只生成口播脚本，不启动 TTS。 |
| 口播脚本审核 | `POST /api/v1/stories/{id}/reviews/script` | 仅 `SCRIPT_READY` 可用。批准后进入 `PENDING_TTS`；`request_changes` 可带 `revised_script`，仍停留在脚本审核门。 |
| 手动语音合成 | `POST /api/v1/stories/{id}/synthesize` | 请求体只有 `{expected_story_version}`。仅 `PENDING_TTS` 可用，先持久化为 `PROCESSING_TTS`，成功后进入终审；失败安全回退 `PENDING_TTS` 并写入 `last_failure`。 |
| 终审 | `POST /api/v1/stories/{id}/reviews/second` | 仅 `PENDING_SECOND_REVIEW` 可用。终审携带 `revised_script` 时会清空音频并返回 `SCRIPT_READY`，必须重新审核脚本后手动合成。 |

生产状态路径为 `FETCHED → TRANSLATED → PENDING_FIRST_REVIEW → PROCESSING_SCRIPT → SCRIPT_READY → PENDING_TTS → PROCESSING_TTS → PENDING_SECOND_REVIEW → DONE`。
`ARCHIVED` 是不参与生产进度条的显式终态，可从任一非归档状态进入。

`POST /api/v1/stories/{id}/resume` 只恢复 `FETCHED`、`TRANSLATED`、`PROCESSING_SCRIPT` 和 `PROCESSING_TTS` 的中断工作；不会从 `SCRIPT_READY` 或 `PENDING_TTS` 自动开始高能耗合成。

脚本段 API 保留 `speaker_id`、`emotion`、`speed`、`pitch`、`visual_hint`；其中 `emotion` 为 `happiness`、`sadness`、`anger`、`disgust`、`like`、`surprise`、`fear` 之一，`scene_transition` 为 `black`、`crossfade`、`slide`、`wipe`、`mood_shift` 之一。无效 LLM 输出分别回退为初审偏好情绪和 `black`；`visual_hint`、`pitch` 即使当前 UI 隐藏也保持 API 兼容。

## 角色

| 前端能力 | API | 语义 |
| --- | --- | --- |
| 列表/详情 | `GET /api/v1/roles`、`GET /api/v1/roles/{profile_id}` | 支持 `enabled` 筛选。 |
| 新建 | `POST /api/v1/roles` | 创建旁白或主持人档案。 |
| 替换 | `PUT /api/v1/roles/{profile_id}` | 需要 `expected_version` 乐观锁。 |
| 停用 | `DELETE /api/v1/roles/{profile_id}` | 软停用并返回新版本；历史故事和成片保留引用。 |

启用本地 TTS 的角色须提交 `tts_enabled=true`、成对的 `gpt_weights_path` / `sovits_weights_path`、`tts_model_profile` 和完整七项 `emotion_refs`；可选的 `reference_language` 用于参考文本（DSakiko 日语配置会导入为 `all_ja`）。合成器按脚本段的 `speaker_id` 与 `emotion` 选择参考材料；同一权重相邻段只切参考音频，不重载模型。不同权重会严格顺序切换：先杀净旧 loopback 子进程，再启动下一套，因此任一时刻只驻留一套重型权重。

## 采集运行

| 前端能力 | API | 语义 |
| --- | --- | --- |
| 可用采集器 | `GET /api/v1/sources/collectors` | 返回四个源的配置与授权就绪度。 |
| 启动 | `POST /api/v1/source-runs` | 返回 `202` 和持久化 run；前端不暴露采集频率。每个来源的网络采集间隔和全局并发均由后端固定策略控制。 |
| 列表/详情 | `GET /api/v1/source-runs`、`GET /api/v1/source-runs/{run_id}` | 包含降级层尝试、标准化导入结果和错误证据。 |
| 取消 | `POST /api/v1/source-runs/{run_id}/cancel` | 协作式停止；记录 `operator_cancelled`，不删除已完成项目。 |

采集保护是服务端策略，不是可调 UI：同一来源上次网络采集完成后至少等待 30 秒，所有来源合计最多 2 个网络采集同时进行。随仓库启动命令固定为单 worker；多进程部署必须先引入持久化租约协调器，不能依赖内存锁。

服务关闭导致的停止会独立记录为 `service_shutdown`，不能与操作员取消混淆。

## 视频批次与 BGM

| 前端能力 | API | 语义 |
| --- | --- | --- |
| 本地 BGM 目录 | `GET /api/v1/video/bgm` | 仅返回 `track_id`、`display_name`、`relative_path`、`size_bytes`；当前没有媒体流/试听接口。 |
| 新建批次 | `POST /api/v1/video/batches` | 从未占用的 `DONE` 故事快照各自的脚本，再由 LLM 生成一份含过渡句的统一批次口播；可选择本地 BGM。 |
| 列表/详情 | `GET /api/v1/video/batches`、`GET /api/v1/video/batches/{batch_id}` | 返回来源脚本快照、统一口播、审核、输入资产快照和版本。 |
| 审核合并口播 | `POST /api/v1/video/batches/{batch_id}/narration-review` | `APPROVE` / `REJECT` 仅初始 `PENDING_NARRATION_REVIEW` 可用；携带 `revised_script` 的 `REVISE` 也可在 `PENDING_BATCH_TTS` 或 `PENDING_TIMELINE_REVIEW` 提交，会清除派生音频和时间轴并返回口播审核门。 |
| 手动合成合并口播 | `POST /api/v1/video/batches/{batch_id}/narration/synthesize` | 仅 `PENDING_BATCH_TTS` 可用；独立本地 TTS 成功后才进入 `PENDING_TIMELINE_REVIEW`。 |
| 试听统一旁白 | `GET /api/v1/video/batches/{batch_id}/audio/{segment_id}` | 仅返回该批次已持久化的合并旁白段。服务端会校验段归属、输出目录边界与文件存在性；未合成、无效或越界路径均返回 `409`，不会暴露本地文件。 |
| 审阅时间轴 | `POST /api/v1/video/batches/{batch_id}/timeline-review` | 统一口播音频和 Manifest 就绪后才可审；批准后进入 `READY_TO_RENDER`。 |
| 渲染 | `POST /api/v1/video/batches/{batch_id}/render` | 需要 `expected_batch_version`。当前生产渲染器是明确的不可用占位适配器，接口会诚实返回不可用错误，直到替换为 Remotion 进程适配器。 |
| 取消/删除 | `POST /api/v1/video/batches/{batch_id}/cancel`、`DELETE /api/v1/video/batches/{batch_id}` | 未渲染批次可释放故事；渲染中无安全取消契约，已渲染批次是不可变审计证据。 |

批次在创建时记录音频和 BGM 的内容哈希。审阅后发现输入文件变化时不能直接复用旧审批；应取消/删除该批次并创建新批次重新审阅。

## 运维

| 前端能力 | API | 语义 |
| --- | --- | --- |
| 操作历史 | `GET /api/v1/operations/runs` | 返回 `running`、`succeeded` 或 `failed` 的留存清理记录及结果。 |
| 调度状态 | `GET /api/v1/operations/schedules` | 返回启用状态、间隔、下次运行与最近状态。 |
| 手动留存清理 | `POST /api/v1/operations/retention/runs` | 请求为 `{operation: "retention_cleanup", dry_run, requested_by}`。前端的确认操作使用 `dry_run: false`，会物理删除符合保留规则的文件。 |

## 已知边界

- 真实四源采集仍取决于合法授权、凭据和站点条款；离线测试不替代现场运行证据。
- GPT-SoVITS 多角色与七情绪参考音频选择已通过可替换角色解析器接入；真正的 Remotion 批量渲染仍是后续适配器工作。
- 任何前端请求应通过 `frontend/src/api/client.ts`，不得自行拼接未写入 OpenAPI 的接口。
