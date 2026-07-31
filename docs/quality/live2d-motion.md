# Live2D 运动稳定性与验收

本文描述当前生产行为。历史根因分析与 A/B 数据位于
`docs/archive/2026-07/live2d-motion-stability-audit.md`，不作为当前配置说明。

## 当前参数所有权

默认控制模式是 `sdk_native`。SDK 拥有动作、头身姿态与物理；god-news 在最终输出阶段
只接管确定性眨眼、平滑眼神和音频驱动嘴型，避免两个控制器同时写入同一参数。

默认运动策略为 `idle`，SDK 自动呼吸关闭。需要更强表演时必须显式启用
`GOD_NEWS_VIDEO_LIVE2D_MOTION_POLICY=emotion_once` 或
`GOD_NEWS_VIDEO_LIVE2D_SDK_AUTO_BREATH=true`，并重新通过质量门。

## 确定性与隔离

- 角色按段在一次性子进程中预渲染为透明 VP9 WebM。
- 帧时钟由目标 FPS 驱动，不依赖子进程实际运行速度。
- Remotion 只消费冻结后的角色视频，不在逐帧合成时运行 Live2D SDK。
- 角色版本、模型树哈希、音频哈希、轨迹和输出哈希进入审核证据。

## 质量入口

```powershell
python scripts/quality/analyze_live2d_video.py --help
python scripts/quality/run_live2d_ab_experiments.py --help
python scripts/quality/run_e2e_video.py --help
```

发布前同时检查参数轨迹、透明角色视频和最终合成视频。至少验证：

- 帧数、FPS、时长、alpha、音视频流和哈希一致；
- 无长冻结、黑屏、异常重复帧或超阈值图像跳变；
- 嘴型与音频活动相关，停顿时能够释放；
- 眨眼、眼神和动作切换连续；
- 开头、中间、转场和结尾代表帧可读；
- 横竖屏均无角色裁切、字幕越界或来源遮挡。
