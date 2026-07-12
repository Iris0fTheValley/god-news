# god-news video

这是一个与后端解耦的 Remotion 渲染包。它直接消费后端现有的
`ProductionManifest 1.0`，再叠加只属于展示层的标题、片头、转场、BGM 和未来视觉资产配置。

当前实现固定为 1080×1920、30fps 的 9:16 短视频：片头和段间转场使用纯黑占位画面；正文画面展示字幕、`speaker_id`、`emotion` 与 `visual_hint`。Live2D 和差分立绘字段只做类型化预留，不会加载或执行模型。所有字体和画面均由本地代码生成，不依赖网络素材。

## 输入契约

完整契约在 `src/schema.ts`。最小边界如下：

- `manifest`：后端 `/production-manifest` 原样响应；时间轴必须从 0 开始、连续、ID 唯一，且末尾必须等于 `total_duration_ms`。
- `bgm.local_path`：可选本地 BGM；音量和循环明确配置。
- `visual_reservations.live2d` / `differential_art`：仅预留资产描述；当前 `renderer` 只能是 `placeholder`。
- `runtime_assets`：渲染器内部生成的浏览器可读绑定。业务调用方不应手写它。

[`example/video-props.json`](./example/video-props.json) 展示完整结构。示例音频是故意不存在的占位路径，避免仓库携带二进制素材。

## 使用

从仓库根目录安装 workspace 依赖后：

```powershell
pnpm --filter @god-news/video studio
pnpm --filter @god-news/video check
pnpm --filter @god-news/video render -- --input .\video\example\video-props.json --output .\out\story.mp4
```

渲染 CLI 会校验 JSON，把每个本地音频按内容 SHA-256 复制到一次性 Remotion public 目录，覆盖任何传入的 `runtime_assets`，渲染后再删除临时目录。相对路径以输入 JSON 所在目录为基准；为保证确定性，HTTP、data URI 等远程或内联资源会被拒绝。

升级视觉实现时新增 renderer adapter/composition，不要改变 `ProductionManifest 1.0`。升级 Remotion 前也应重新确认其当前许可证是否符合实际团队规模和自动化渲染量。
