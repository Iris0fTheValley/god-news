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
| 创建 | `POST /api/v1/stories` | URL 或上传文本进入抓取、翻译和初审管线。 |
| 编辑元数据 | `PATCH /api/v1/stories/{story_id}` | 需要 `expected_story_version`；只允许标题、风格与目标时长，不能篡改来源快照。 |
| 归档 | `DELETE /api/v1/stories/{story_id}` | 软归档为 `ARCHIVED`，保留来源、版本、审核和状态迁移证据。 |
| 重开终审 | `POST /api/v1/stories/{story_id}/reopen` | 仅 `DONE → PENDING_SECOND_REVIEW`。 |
| 初审/终审 | `POST /api/v1/stories/{id}/reviews/first`、`POST /api/v1/stories/{id}/reviews/second` | 两道人工门禁仍是高能耗脚本与 TTS 的前置条件。 |

生产状态路径为 `FETCHED → TRANSLATED → PENDING_FIRST_REVIEW → PROCESSING_SCRIPT → SCRIPT_READY → PENDING_SECOND_REVIEW → DONE`。
`ARCHIVED` 是不参与生产进度条的显式终态，可从任一非归档状态进入。

## 角色

| 前端能力 | API | 语义 |
| --- | --- | --- |
| 列表/详情 | `GET /api/v1/roles`、`GET /api/v1/roles/{profile_id}` | 支持 `enabled` 筛选。 |
| 新建 | `POST /api/v1/roles` | 创建旁白或主持人档案。 |
| 替换 | `PUT /api/v1/roles/{profile_id}` | 需要 `expected_version` 乐观锁。 |
| 停用 | `DELETE /api/v1/roles/{profile_id}` | 软停用并返回新版本；历史故事和成片保留引用。 |

`gpt_weights_path`、`sovits_weights_path` 和视觉资产只是受校验的角色元数据。当前 GPT-SoVITS 适配器仍为单语音实例；多角色/多权重调度必须通过新的合成器适配器实现，不能把档案字段误认为已生效的推理配置。

## 采集运行

| 前端能力 | API | 语义 |
| --- | --- | --- |
| 可用采集器 | `GET /api/v1/sources/collectors` | 返回四个源的配置与授权就绪度。 |
| 启动 | `POST /api/v1/source-runs` | 返回 `202` 和持久化 run；请求包含 source、limit、语言、风格、语音控制及 requested_by。 |
| 列表/详情 | `GET /api/v1/source-runs`、`GET /api/v1/source-runs/{run_id}` | 包含降级层尝试、标准化导入结果和错误证据。 |
| 取消 | `POST /api/v1/source-runs/{run_id}/cancel` | 协作式停止；记录 `operator_cancelled`，不删除已完成项目。 |

服务关闭导致的停止会独立记录为 `service_shutdown`，不能与操作员取消混淆。

## 视频批次与 BGM

| 前端能力 | API | 语义 |
| --- | --- | --- |
| 本地 BGM 目录 | `GET /api/v1/video/bgm` | 仅返回 `track_id`、`display_name`、`relative_path`、`size_bytes`；当前没有媒体流/试听接口。 |
| 新建批次 | `POST /api/v1/video/batches` | 自动从未占用的 `DONE` 故事中选择，或使用显式 `story_ids`；可选择本地 BGM。 |
| 列表/详情 | `GET /api/v1/video/batches`、`GET /api/v1/video/batches/{batch_id}` | 返回时间轴、审核、输入资产快照和版本。 |
| 审阅时间轴 | `POST /api/v1/video/batches/{batch_id}/timeline-review` | 需要 `expected_batch_version` 与 reviewer；批准后进入 `READY_TO_RENDER`。 |
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
- GPT-SoVITS 多角色、情绪参考音频选择和真正的 Remotion 批量渲染仍是可替换的后续适配器工作。
- 任何前端请求应通过 `frontend/src/api/client.ts`，不得自行拼接未写入 OpenAPI 的接口。
