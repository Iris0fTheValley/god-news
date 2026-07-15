# god-news video

这是与后端解耦的 Remotion 渲染包。它消费审核后的 `ProductionManifest 1.0`，并从同一份语义快照分别生成：

- `douyin_vertical`：1080×1920 / 30fps；
- `bilibili_horizontal`：1920×1080 / 30fps。

宽高由 `output_profiles` 声明，Remotion 的 `calculateMetadata()` 动态选择。两次渲染共享故事、音频、字幕语义与时间顺序，只由布局层适配横竖屏，不能维护两份节目脚本。

## 输入契约

完整 Zod 契约在 `src/schema.ts`：

- `manifest`：审核后音频时间基线，时间轴从 0 开始、连续、ID 唯一；
- `output_profiles`：不可变输出配置快照；
- `runtime_assets.output_profile_id`：本次渲染选中的已声明配置；
- `bgm`：可选本地 BGM；
- `visual_reservations`：角色视觉资产引用，当前仍只完成宿主槽位，尚未执行 Live2D；
- `runtime_assets`：CLI 生成的浏览器可读资产绑定，业务调用方不应手写。

[`example/video-props.json`](./example/video-props.json) 展示完整结构。示例音频路径故意不存在，避免仓库携带来源不明的二进制素材。

## 使用

```powershell
pnpm --filter @god-news/video studio
pnpm --filter @god-news/video check
pnpm --filter @god-news/video render -- --input .\video\example\video-props.json --profile douyin_vertical --output .\out\douyin.mp4
pnpm --filter @god-news/video render -- --input .\video\example\video-props.json --profile bilibili_horizontal --output .\out\bilibili.mp4
```

CLI 校验 JSON，把本地音频和 BGM 按内容 SHA-256 复制到一次性 public 目录，覆盖任何传入的运行时绑定，渲染后删除临时 staging。相对路径以输入 JSON 所在目录为基准；HTTP、data URI、UNC 等非本地资产会被拒绝。

后端 `LocalRemotionBatchVideoRenderer` 会先按人工审核时保存的大小和 SHA-256 创建一次可信输入快照，再让两个 profile 只读该快照。它使用 Remotion 自带的 FFmpeg/ffprobe 验证分辨率、精确帧率、视频流和音频流，并为每个输出保存文件哈希。任一 profile 失败会清理整次尝试，避免把部分文件误认成完整批次。

同时运行的批次数由 `GOD_NEWS_VIDEO_RENDER_MAX_PARALLEL_BATCHES` 限制；`GOD_NEWS_VIDEO_RENDER_CONCURRENCY` 只控制单次 Remotion 渲染内部 worker。服务启动时会把断电或强杀遗留的 `RENDERING` 批次原子恢复为可重试 `FAILED`，并仅清理这些批次的孤儿 attempt。

## 当前边界

- `ProductionManifest 1.0` 仍是音频时间基线；场景、证据素材和字幕策略将进入独立、版本化的 EpisodePlan，不应塞入低层渲染坐标。
- 响应式 `TitleCard`、`HostEvidenceScene`、`TransitionScene` 已替换黑屏/固定竖屏画面。
- 主持人当前是可替换视觉槽位，不是假装完成的 Live2D。接入 Live2D 时应新增角色渲染适配器，不改节目审核与音频清单。
