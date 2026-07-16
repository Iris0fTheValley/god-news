# 视频模板系统改造审计

审计日期：2026-07-16

## 基线

- 后端：`192 passed`
- 前端：`23 passed`，类型检查和生产构建通过
- Remotion：`19 passed`，类型检查和 bundle 通过
- 当前工作树仅有用户原有的未跟踪文件 `nul` 与
  `scripts/_test_sources.cmd`

这些结果只证明现有契约自洽，不证明视觉质量达标。

## 当前数据流

```text
DONE Story + ProductionManifest
  -> VideoBatchService 创建不可变 VideoBatchStory
  -> ProgramDirectorPlan 选择语义场景
  -> EpisodePlan
  -> RemotionVideoProps
  -> VideoInputAsset 哈希快照
  -> LocalRemotionBatchVideoRenderer staging
  -> video/scripts/render.ts 二次 staging
  -> buildRenderPlan
  -> SceneRegistry
  -> GodNewsShortVideo
```

现有链路已正确保留审核、版本、音频、原视频、Live2D、哈希和双输出
配置，但视觉图片链路在 `VideoBatchStory` 之前中断。

## 可以保留

- Python 领域、应用、基础设施分层。
- `ProgramDirectorPlan -> EpisodePlan -> render-plan` 的语义/时间分层。
- `VideoInputAsset`、渲染输入哈希和原子 staging。
- 同一语义快照生成横竖屏的机制。
- 原视频转写审核、时间段、来源标签和字幕绑定。
- Live2D 预渲染为透明 VP9 文件的进程隔离边界。
- `VisualAssetService` 的上传校验、脚本 revision 绑定、持久化和内容服务。
- Remotion 生产 Composition、ffprobe 验证和输出原子发布。
- 前端 OpenAPI 客户端、TanStack Query 和现有路由外壳。

## 必须修复

### 真实视觉素材

- `VisualAssetService` 已保存编辑上传图片和来源截图，但
  `VideoBatchService._build_batch_stories()` 不读取它们。
- `VideoBatchStory`、`EpisodeScene`、`RemotionVideoProps` 和
  `VideoInputAssetKind` 均没有图片快照。
- Remotion staging 只处理音频、BGM、原视频和主持人视频。
- `HostEvidenceScene` 与 `EvidenceFullscreenScene` 把
  `visual_hint` 当作最终主体，并包含明显占位文案。
- `HostSilhouette` 在生产路径中静默替代缺失的 Live2D 素材。

### 模板和布局

- `VideoTheme` 只有四个颜色字段，不是正式模板。
- 模板 ID、版本、能力、变体、字幕/来源/片头/片尾预设均不存在。
- Python 与 TypeScript 重复定义输出配置、场景模块、场景约束和主题。
  当前没有自动验证两端注册表一致性的生成或契约测试。
- `SceneRegistry` 只有一个对象映射，没有重复 ID、模板引用和能力验证。
- 横竖屏分支散落在每个 React 场景中，没有布局编译层。
- 顶层 Composition 已开始按 track 分流，但片头、片尾和转场仍直接绑定
  单一实现。

### 前端实验室

- 当前没有 `/template-lab`。
- 前端没有 `@remotion/player`，video 包也没有无副作用的浏览器 export。
- 公共批次 DTO 正确隐藏本地路径，因此不能直接作为 Player 输入；
  需要独立、受控的 browser-preview URL 解析边界。
- 当前视频页面只能试听音频和打开最终 MP4，不能播放场景、逐帧、显示
  安全区或诊断。
- 数字导航快捷键在 `BrowserRouter` 下错误写入 hash，且快捷键说明与导航
  顺序已经漂移。

### Live2D

- worker 虽按绝对毫秒推进 `UtSystem`，但口型直接使用逐帧 RMS，没有
  attack/release。
- 参数更新顺序只有 `model.Update -> mouth SetParameterValue -> Draw`；
  没有明确的 motion、idle、blink、look-at、expression、lip-sync 优先级。
- 没有确定性视线、头部微动或动作过渡诊断。
- worker 只返回帧数，不报告连续重复帧、嘴型跳变、眨眼次数或冻结区间。
- 正式默认 FPS 是 30，但旧 E2E 显式使用 15 FPS，造成验收与生产配置不一致。

### 真实验收

- 旧 E2E 用程序生成的网格/光带帧作为“原视频”。
- 旧 E2E 使用 `-stream_loop -1` 将三秒种子循环到 51 秒，违反本轮时长
  真实性要求。
- 旧 E2E 每个输出只抽取开头、中间、结尾三帧，没有 20 点 contact sheet。
- 当前 ffprobe 检查只覆盖编码、分辨率、FPS 和音轨，不检测黑屏、测试图案、
  重复帧、占位文本、安全区或 Live2D 冻结。

## 需要重构

1. 在后端建立版本化模板快照与注册表，模板完整快照进入渲染哈希。
2. 为场景建立语义模块、视觉变体和类型化素材槽。
3. 把现有故事视觉素材接入批次不可变快照、EpisodePlan、staging 和
   Remotion props。
4. 在 video 包建立模板、场景、变体、片头、片尾、转场、字幕和布局注册表。
5. 建立 `SemanticScene + Template + OutputProfile -> CompiledSceneLayout`。
6. 把共享字幕、来源条、媒体、主持人和安全区逻辑移到公共组件。
7. video 包提供无副作用 Player 入口，前端实验室直接复用生产 Composition。
8. Live2D worker 建立确定性的分阶段参数管线和质量诊断。
9. 建立真实 still/contact-sheet/视觉门禁工具，并使发布失败而非只告警。

## 应删除或限制在测试环境

- 生产场景中的 `HostSilhouette` 和证据占位文案。
- 旧 E2E 的网格帧生成和 `stream_loop` 时长填充。
- `video/src/sample-props.ts` 中不存在的 placeholder 音频引用。
- fixture 只能由 Template Lab、单元测试和开发渲染入口导入；生产批次不得
  引用 fixture 目录。

## 关键架构风险

- 若模板只保存 ID 而不保存版本化完整快照，旧视频会随注册表更新漂移。
- 若浏览器预览暴露宿主路径，会破坏当前正确的媒体安全边界。
- 若图片只在前端显示而不进入 batch hash，审核后替换文件会产生不可复现成片。
- 若每个模板复制字幕、媒体加载和来源条，模板数量增加后会快速失控。
- 若 Live2D 只靠像素单帧检查，仍无法发现动作冻结和高频抖动。
- 若自动视觉门禁只 warning，生产仍可发布占位或损坏成片。

## 本轮明确不做

- 任意图层拖拽、无限轨道和 Premiere 式时间轴。
- 任意 CSS/JSX 编辑。
- 模板市场、协同编辑和完整撤销历史。
- 不受约束的 LLM 像素、帧号或动画参数控制。
- 复制或嵌入 AIRI 未经确认许可的实现；只借鉴其公开的更新阶段和状态思想。

## 实施顺序

1. 建立模板/变体/布局/素材契约和注册表。
2. 选择 `host_evidence`，接通一张真实图片与一张来源截图。
3. 提供同一场景的两个明显不同变体。
4. 用生产组件建立 Template Lab。
5. 迁移其余现有场景并删除生产占位。
6. 修复 Live2D 平滑和诊断。
7. 替换旧 E2E 素材生成方式，加入视觉门禁和 contact sheet。
8. 真实渲染、浏览器/播放器检查和独立审查。

## 已验证的 Live2D 根因与修复证据

旧横屏成片的主持人区域逐帧测量显示：

- 104 个相邻帧对中有 51 对的平均像素差低于 `0.25`；
- 偶数相邻对差异中位数为 `3.9333`；
- 奇数相邻对差异中位数仅为 `0.0579`；
- Host WebM 为 15 FPS，最终 Composition 为 30 FPS。

因此卡顿不是主观印象，也不是 VP9 worker 丢帧，而是 15 FPS 角色素材进入
30 FPS Composition 后产生的稳定隔帧近重复。

本轮修复将角色主时钟统一为 30 FPS，并增加：

- PCM 位宽归一化；
- 口型 attack/release；
- motion 结束后的确定性轮换；
- 显式眨眼状态机；
- 头部、身体与视线的微弱确定性轨道；
- expression 选择；
- `motion -> idle/look -> blink -> mouth` 参数覆盖顺序；
- 帧数、时间步长、眨眼、口型分位数、口型最大跳变、精确重复帧率和最长冻结段诊断；
- 超限时使角色预渲染失败的硬门禁。

使用 DSakiko 实际 `v2cpp` 运行时完成的 3 秒、512×512、30 FPS 探针结果：

```text
rendered_frames=90
fps=30
blink_events=1
exact_duplicate_pair_ratio=0.0
longest_exact_duplicate_run=0
```

该探针同时确认本机运行时的公开参数 API 是
`SetParameterValue` / `AddParameterValue`，不能依赖 Python 包内部对象
`live2DModel`。
