# god-news

一个配置驱动的异步内容生产实验系统：从互联网抓取正面新闻 → AI 翻译/摘要/分类 → 两阶段人工审核 → 本地 TTS 语音合成 → 短视频渲染。

## 愿景

每天自动从全球四个固定来源抓取温暖新闻，AI 做翻译和脚本起草，人类只负责两道审核门——不写文案、不调音频、不剪视频。审核通过后全自动产出带字幕和 BGM 的 9:16 短视频。

## 管线

```
抓取 → 翻译 + AI 分类 → 人工初审 → 脚本生成 → 本地 TTS → 人工终审 → DONE
                                  ↑ 批准后才消耗本地 GPU
任一状态 → ARCHIVED（软归档，保留证据和审计）
DONE → PENDING_SECOND_REVIEW（重开终审）
```

## 技术栈

- **后端**：Python FastAPI + Pydantic v2 + SQLAlchemy 异步 + SQLite
- **LLM**：DeepSeek V4 Flash（可切换 LM Studio 本地模型）
- **TTS**：GPT-SoVITS v2Pro，每个 story 启动一次 loopback 子进程
- **记忆**：ChromaDB 本地持久化，write-through 语义召回
- **前端**：React + Vite + TanStack Query，类型由 OpenAPI 自动生成
- **视频**：Remotion 9:16 渲染包
- **数据源**：大众新闻、Reddit r/HumansBeingBros、Guardian Kindness of Strangers、Pikabu Доброта

## 关键设计决策

- **AI 做重活，人类只审**：LLM 负责翻译、分类、脚本；TTS 自动合成；人只在两道审核门点批准或退回。
- **审核前不消耗 GPU**：只有初审批准后才启动 GPT-SoVITS。一个 story 内复用模型加载，多 story TTS 串行。
- **架构围绕强类型领域模型**：每个管线步骤都有明确的数据契约，状态机只走合法路径，失败通过 `resume` 从检查点恢复而非静默跳过。
- **前端壳策略**：所有后端 API 都有对应 UI 页面，未实现的功能返回 501 而非报错。

## 启动

```powershell
Copy-Item .env.example .env  # 编辑填入 API Key
.\start.cmd                   # 或 .\scripts\start.ps1
```

无 GPU / 离线演示模式：

```powershell
.\scripts\start.ps1 -OfflineDemo
```

## 前端接口映射

`docs/frontend-api-mapping.md` 列出了全部 33 个 API 端点与前端组件的对应关系，以及待后端实现的桩接口和多角色 TTS 改造方向。
