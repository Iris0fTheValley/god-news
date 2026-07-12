# god-news 前端接口映射表

> 生成时间: 2026-07-12
> 状态: ✅ TypeScript 编译通过 · ✅ 4/4 测试通过
> 用法: 按表去后端对着实现缺失的接口。前端 UI 已就绪。

## 使用说明

- ✅ = 后端已有完整实现，前端可正常调用
- ⚠️ = 后端接口存在，但实现为桩代码（如 Remotion 渲染器）
- ❌ = 后端无此接口，需要新建路由 + FSM 改造

---

## 一、故事管线

| 前端组件 | 调用的 API 函数 | 后端端点 | 方法 | 状态 |
|---------|---------------|---------|------|------|
| StoryListPage | `listStories()` | `/api/v1/stories` | GET | ✅ |
| StoryWorkbenchPage | `getStory(id)` | `/api/v1/stories/{story_id}` | GET | ✅ |
| CreateStoryForm | `createStory(body)` | `/api/v1/stories` | POST | ✅ |
| StoryWorkbenchPage | `resumeStory(id)` | `/api/v1/stories/{story_id}/resume` | POST | ✅ |
| FirstReviewPanel | `submitFirstReview(id, body)` | `/api/v1/stories/{story_id}/reviews/first` | POST | ✅ |
| SecondReviewPanel | `submitSecondReview(id, body)` | `/api/v1/stories/{story_id}/reviews/second` | POST | ✅ |
| StoryWorkbenchPage | `listReviews(id)` | `/api/v1/stories/{story_id}/reviews` | GET | ✅ |
| StoryWorkbenchPage | `listTransitions(id)` | `/api/v1/stories/{story_id}/transitions` | GET | ✅ |
| StoryWorkbenchPage | `getProductionManifest(id)` | `/api/v1/stories/{story_id}/production-manifest` | GET | ✅ |
| AudioPanel | `audioClipUrl(id, segId)` | `/api/v1/stories/{story_id}/audio/{segment_id}` | GET | ✅ |
| StoryListPage | `getClassificationMetrics()` | `/api/v1/metrics/classification` | GET | ✅ |
| **StoryCard 删除按钮** | `deleteStory(id)` | `/api/v1/stories/{story_id}` | DELETE | ✅ 软归档 |
| **工作台「重开审核」按钮** | `reopenStory(id)` | `/api/v1/stories/{story_id}/reopen` | POST | ✅ 仅 DONE 可重开 |
| **工作台「编辑故事」** | `updateStory(id, body)` | `/api/v1/stories/{story_id}` | PATCH | ✅ 需版本号 |

### 已实现的后端契约

```python
# 1. ARCHIVED 是显式的软归档状态；任一非 ARCHIVED 状态均可迁移到它。
# 2. DELETE /api/v1/stories/{story_id}  → status=ARCHIVED，保留证据、版本和状态审计。
# 3. GET /stories 默认隐藏归档；按 ID 仍可读取，GET ?status=ARCHIVED 可显式列出。
# 4. 仅 DONE → PENDING_SECOND_REVIEW 可重开审核；ARCHIVED 不能 resume/reopen。
# 5. PATCH 体为 {expected_story_version, title?, style?, target_duration_seconds?}。
#    title 独立保存，不会修改 source.title 或固定来源 provenance。
```

---

## 二、角色管理

| 前端组件 | 调用的 API 函数 | 后端端点 | 方法 | 状态 |
|---------|---------------|---------|------|------|
| RolesPage 列表 | `listRoles()` | `/api/v1/roles` | GET | ✅ |
| RolesPage 新建表单 | `createRole(body)` | `/api/v1/roles` | POST | ✅ |
| RolesPage 编辑表单 | `updateRole(id, body)` | `/api/v1/roles/{profile_id}` | PUT | ✅ |
| RolesPage 删除按钮 | `deleteRole(id)` | `/api/v1/roles/{profile_id}` | DELETE | ⚠️ **硬删除** |

### 需要后端修改的

```python
# 1. DELETE 改为软删：set enabled=False 而非 DELETE FROM
# 当前是物理删除行，无法恢复
```

### 🔧 多角色独立 TTS 语音（需求规格）

> **状态**: 前端表单已就绪 · 后端未实现 · 见下方改造方案
>
> 前端 RolesPage 已将 `TTS 模型标识` 字段拆为两个输入框：
> - **GPT 权重路径** → `gpt_weights_path`（如 `J:\models\gpt-narrator.pth`）
> - **SoVITS 权重路径** → `sovits_weights_path`（如 `J:\models\sovits-narrator.pth`）
>
> 提交时前端将这两个字段放入请求体。当前后端 `RoleProfileCreate` 使用 `extra="forbid"`，会拒绝未知字段返回 422。

#### 后端改造方案

**1. `operations/models.py` — RoleProfile 新增字段**

```python
class RoleProfileCreate(OperationsModel):
    # ... 现有字段 ...
    gpt_weights_path: AssetRef | None = None    # 新增
    sovits_weights_path: AssetRef | None = None  # 新增
```

同样在 `RoleProfile` / `RoleProfileReplace` / `_row_values()` 中都加上。

**2. `infrastructure/role_profiles.py` — 数据表加两列**

```python
class RoleProfileRow(Base):
    # ... 现有列 ...
    gpt_weights_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    sovits_weights_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
```

**3. `infrastructure/tts/multi_voice.py` — 新建多路合成器**

```
MultiVoiceSpeechSynthesizer
├── 构造函数接收 RoleProfile 列表
├── synthesize() 按 speaker_id 分组脚本段落
├── 每个 speaker_id 用自己的权重路径起一个 GPT-SoVITS server (不同 loopback 端口)
├── 串行执行: 先跑完 speaker A 的所有段落 → 关闭 server → 再跑 speaker B
└── 合并所有 AudioClip 成一个 AudioBundle 返回
```

关键点：
- 同一时刻只有一个 GPT-SoVITS 进程占用 GPU（串行合成，避免显存溢出）
- 权重切换时每次需重新启动 GPT-SoVITS api_v2 server（有启动耗时）
- 保留现有 `GPTSoVITSSpeechSynthesizer` 不动，新建 `MultiVoiceSpeechSynthesizer` 包装它

**4. `container.py` — 更换 TTS 实例**

```python
# 旧: 单一 synthesizer，固定一套权重
tts = GPTSoVITSSpeechSynthesizer(
    gpt_weights=settings.tts_gpt_weights,
    sovits_weights=settings.tts_sovits_weights,
    ...
)

# 新: 多路合成器，启动时拉取所有启用的角色
tts = MultiVoiceSpeechSynthesizer(
    role_profiles=role_profiles,  # 注入 RoleProfileRepository
    base_config=...,              # 共享的 tts_infer.yaml 和通用参数
)
```

**5. 移除 `_validate_capabilities` 中的 speaker_id 单例校验**

当前硬编码了 `speaker_id must equal default_speaker_id`。改为按 speaker_id 查找对应角色的权重路径，找不到才报错。

---

## 三、采集运行

| 前端组件 | 调用的 API 函数 | 后端端点 | 方法 | 状态 |
|---------|---------------|---------|------|------|
| SourceRunsPage 列表 | `listSourceRuns()` | `/api/v1/source-runs` | GET | ✅ |
| SourceRunsPage 详情 | `getSourceRun(id)` | `/api/v1/source-runs/{run_id}` | GET | ✅ |
| SourceManagementPage | `getSourceCollectors()` | `/api/v1/sources/collectors` | GET | ✅ |
| SourceRunsPage「开始采集」 | `startSourceRun(body)` | `/api/v1/source-runs` | POST | ✅ |
| **SourceRunsPage「取消运行」** | `cancelSourceRun(id)` | `/api/v1/source-runs/{run_id}/cancel` | POST | ❌ **需新建** |

### 需要后端实现的

```python
# POST /api/v1/source-runs/{run_id}/cancel
# 调用 SourceRunService 中已有的 _mark_cancelled() 逻辑
# 目前 CANCELLED 状态只在服务关闭时内部调用，无外部 API
```

---

## 四、视频批次

| 前端组件 | 调用的 API 函数 | 后端端点 | 方法 | 状态 |
|---------|---------------|---------|------|------|
| VideoBatchesPage 列表 | `listVideoBatches()` | `/api/v1/video/batches` | GET | ✅ |
| VideoBatchesPage 详情 | `getVideoBatch(id)` | `/api/v1/video/batches/{batch_id}` | GET | ✅ |
| VideoBatchesPage 新建 | `createVideoBatch(body)` | `/api/v1/video/batches` | POST | ✅ |
| 批次详情「审阅时间轴」 | `submitTimelineReview(id, body)` | `/api/v1/video/batches/{batch_id}/timeline-review` | POST | ⚠️ |
| 批次详情「开始渲染」 | `renderVideoBatch(id, body)` | `/api/v1/video/batches/{batch_id}/render` | POST | ⚠️ **桩** |
| **批次详情「取消渲染」** | `cancelVideoRender(id)` | `/api/v1/video/batches/{batch_id}/cancel` | POST | ❌ **需新建** |
| **批次详情「删除批次」** | `deleteVideoBatch(id)` | `/api/v1/video/batches/{batch_id}` | DELETE | ❌ **需新建** |

### 需要后端实现的

```python
# 1. POST /api/v1/video/batches/{batch_id}/cancel — 取消渲染中批次
# 2. DELETE /api/v1/video/batches/{batch_id} — 删除批次（释放故事占用）
# 3. renderVideoBatch 实现 Remotion 桥接（当前是 UnavailableBatchVideoRenderer 桩）
```

---

## 五、BGM 管理

| 前端组件 | 调用的 API 函数 | 后端端点 | 方法 | 状态 |
|---------|---------------|---------|------|------|
| BgmPage 列表 + 试听 | `listBgmTracks()` | `/api/v1/video/bgm` | GET | ✅ |

### 需确认

```python
# LocalBgmCatalog 已完整实现（扫描本地文件夹 + 格式校验）
# 确认 bgm/ 目录路径在 .env 中正确配置
```

---

## 六、运维操作

| 前端组件 | 调用的 API 函数 | 后端端点 | 方法 | 状态 |
|---------|---------------|---------|------|------|
| OpsPage 操作历史 | `listOperationRuns()` | `/api/v1/operations/runs` | GET | ✅ |
| OpsPage 调度状态 | `listSchedules()` | `/api/v1/operations/schedules` | GET | ✅ |
| OpsPage 手动清理 | `triggerRetention(body)` | `/api/v1/operations/retention/runs` | POST | ✅ |

### 需确认

```python
# RetentionCleanupHandler 已完整实现
# 在 .env 中配置 retention_media_days / retention_uploaded_mp4_days
# 确认 operations_scheduler_enabled=true 使定时清理运行
```

---

## 七、前端新增组件清单

| 组件 | 文件 | 作用 |
|------|------|------|
| ToastProvider + useToast | `components/Toast.tsx` | 操作反馈通知（支持撤销按钮） |
| ConfirmDialog | `components/ConfirmDialog.tsx` | 不可逆操作前的二次确认 |
| KeyboardShortcuts | `components/KeyboardShortcuts.tsx` | `?` 键打开快捷键参考面板 |
| EmptyState | `components/EmptyState.tsx` | 统一空状态占位组件 |

---

## 八、修改过的已有文件（功能代码未动）

| 文件 | 改了什么 | 功能代码 |
|------|---------|---------|
| `ScriptEditor.tsx` | 包了 undo history stack + Ctrl+Z/Y 快捷键 | `resequence()`/`updateSegment()`/`move()`/`remove()`/`add()` 全部原样保留 |
| `FirstReviewPanel.tsx` | 按钮 onClick 从直接调用改为先开 ConfirmDialog | `retryReviewId`/`mutation.mutate`/`onSuccess` 全部原样保留 |
| `SecondReviewPanel.tsx` | 同上 | 同上 |
| `StoryCard.tsx` | 加了 `onDeleteRequest` prop 和删除按钮 | 原有渲染逻辑原样保留 |
| `StoryListPage.tsx` | 加了搜索框 + 删除确认 | 原有 `useQuery`/`refetchInterval` 全部原样保留 |
| `StoryWorkbenchPage.tsx` | 加了重开/删除按钮 + ConfirmDialog | 原有 `scriptEdit`/`recoverable`/所有状态机逻辑原样保留 |
| `RolesPage.tsx` | `ttsModel` 字段拆为 `gptWeightsPath` + `sovitsWeightsPath` | 原有 `createMutation`/`updateMutation`/`deleteMutation` 全部原样保留 |
| `App.tsx` | 加了 6 条路由 + 7 项导航 | 原有 3 条路由原样保留 |
| `render.tsx` | 包了 `ToastProvider` | 原有 render 逻辑原样保留 |
| `queryKeys.ts` | 加了 8 组新的 query key | 原有 7 组原样保留 |
| `client.ts` | 加了 19 个 API 函数（14 真实 + 5 桩） | 原有 12 个函数签名原样保留 |

---

## 九、备份

原始前端文件已备份到：
```
.backups/frontend-20260712-114524/
```

---

## 十、音频合成管线重构方向

> 参考项目：`J:\\AI friend\\DSakiko3.10`
> 核心思路：同一套 GPT/SoVITS 权重，按脚本段落的情绪切换参考音频，实现多情绪语音合成。
>
> 关键文件参考：`emotion_enum.py`（7 情绪枚举）、`character.py:get_reference_materials_for_emotion()`（按情绪选参考音频）、`reference_audio_and_text.json`（每情绪一条 `{audio_path, text}`）。
>
> 当前 god-news 的 `gpt_sovits.py` 里 `_validate_capabilities` 把 `emotion != "neutral"` 直接拒了，`openai_compatible.py` 第 230 行把 LLM 输出的 emotion 覆盖成了 `preferences.emotion`——这是情绪管线断掉的根因。
