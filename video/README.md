# god-news video

这是与后端解耦的 Remotion 渲染包。它消费审核后的 `ProductionManifest 1.0`，并从同一份语义快照分别生成：

- `douyin_vertical`：1080×1920 / 30fps；
- `bilibili_horizontal`：1920×1080 / 30fps。

宽高由 `output_profiles` 声明，Remotion 的 `calculateMetadata()` 动态选择。两次渲染共享故事、音频、字幕语义与时间顺序，只由布局层适配横竖屏，不能维护两份节目脚本。

## 输入契约

完整 Zod 契约在 `src/schema.ts`：

- `manifest`：审核后音频时间基线，时间轴从 0 开始、连续、ID 唯一；
- `template`：不可变的模板 ID、版本、能力、场景变体、布局和设计令牌快照；
- `episode_plan`：只包含语义场景、已注册变体和类型化素材 ID，不包含 CSS 或像素坐标；
- `visual_assets`：已审核并按大小、哈希冻结的图片、来源截图和其他视觉媒体；
- `output_profiles`：不可变输出配置快照；
- `runtime_assets.output_profile_id`：本次渲染选中的已声明配置；
- `bgm`：可选本地 BGM；
- `visual_reservations`：角色视觉资产引用；生产可绑定按段预渲染、带诊断与哈希的 Live2D VP9 WebM；
- `runtime_assets`：CLI 生成的浏览器可读资产绑定，业务调用方不应手写。

[`example/video-props.json`](./example/video-props.json) 是旧版最小契约示例，仅用于解释历史字段。旧快照可读取和审计，但生产渲染不会静默把它迁移到当前模板。正式可渲染输入应由后端冻结，或在前端 `/template-lab` 导出当前 `world_warmth@1.0.0` 的 validated props。

## 使用

```powershell
pnpm --filter @god-news/video studio
pnpm --filter @god-news/video check
pnpm --filter @god-news/video render -- --input .\video\example\video-props.json --profile douyin_vertical --output .\out\douyin.mp4
pnpm --filter @god-news/video render -- --input .\video\example\video-props.json --profile bilibili_horizontal --output .\out\bilibili.mp4
```

CLI 校验 JSON，把本地音频、视觉素材、主持人视频和 BGM 按内容 SHA-256 复制到一次性 public 目录，覆盖任何传入的运行时绑定，渲染后删除临时 staging。相对路径以输入 JSON 所在目录为基准；HTTP、data URI、UNC 等非本地资产会被拒绝。

后端 `LocalRemotionBatchVideoRenderer` 会先按人工审核时保存的大小和 SHA-256 创建一次可信输入快照，再让两个 profile 只读该快照。它验证分辨率、精确帧率、容器/音频/编译时间轴时长、视频流、音频流和文件哈希，并使用配置的完整 FFmpeg 执行黑屏与长冻结硬门禁。版本化生产快照若含占位文本、测试图案、fixture 路径、未知模板或未知变体会在渲染前失败。布局编译会硬检查媒体、来源、字幕和主持人区域均位于安全区；字幕根据内容长度自适应字号，超过最低可读容量会直接终止渲染。任一 profile 失败会清理整次尝试，避免把部分文件误认成完整批次。

同时运行的批次数由 `GOD_NEWS_VIDEO_RENDER_MAX_PARALLEL_BATCHES` 限制；`GOD_NEWS_VIDEO_RENDER_CONCURRENCY` 只控制单次 Remotion 渲染内部 worker。服务启动时会把断电或强杀遗留的 `RENDERING` 批次原子恢复为可重试 `FAILED`，并仅清理这些批次的孤儿 attempt。

## 当前边界

- `ProductionManifest 1.0` 仍是音频时间基线；`EpisodePlan`、`TemplateDefinition` 和 `CompiledSceneLayout` 分别承担语义场景、版本化视觉策略和输出比例布局。
- `SceneRegistry`、`TemplateRegistry`、`IntroRegistry`、`OutroRegistry`、`TransitionRegistry`、`CaptionPresetRegistry` 与 `SourceBarPresetRegistry` 在启动时验证重复 ID 和悬空引用，不静默退回占位组件。
- `host_evidence` 已有分栏主持人与角落主持人两个明显不同的视觉变体；`evidence_fullscreen` 与 `source_video` 复用公共素材、字幕、来源条和安全区组件。
- Live2D 在隔离进程中以 30 FPS 预渲染，包含 attack/release 口型平滑、确定性眨眼、微弱闲置/头部/视线变化和逐段连续性诊断。Remotion 只消费冻结的透明视频，不耦合本地 SDK。
