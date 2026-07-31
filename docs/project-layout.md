# 项目目录约定

## 正式代码

- `src/god_news/`：Python 领域、应用与基础设施。
- `src/god_news/workers/`：随 Python 包发布、通过 `python -m` 启动的隔离子进程入口。
- `src/god_news/testing/`：确定性测试替身和离线演示应用，与生产适配器隔离。
- `frontend/src/`：React 正式前端代码，不放测试实现。
- `video/src/`：Remotion 渲染器、模板、布局编译器和 Studio fixture。
- `assets/demo-owned/`：项目自有且带 provenance 的演示素材唯一来源。

Template Lab 所需的浏览器静态文件由
`frontend/scripts/build/prepare-template-lab-assets.mjs` 从该唯一来源复制到被忽略的
`frontend/public/template-lab/`，不得重复提交两份相同素材。Live2D 预渲染文件仍由
操作者或视觉测试临时注入。

使用项目 Python 环境、需要作为模块导入或随 wheel 分发的子进程入口属于
`src/god_news/workers/`；使用专用外部 SDK/Python 环境的一次性生产进程属于
`scripts/workers/`。两者都只负责参数解析、协议适配和进程编排，可复用领域逻辑仍属于
`src/god_news/`，不能只存在于 CLI 中。

## 测试

- `tests/`：Python 单元、集成和契约测试，复用夹具放在 `tests/fixtures/`。
- `frontend/tests/unit/`：前端组件与状态单测，目录结构镜像 `frontend/src/`。
- `frontend/tests/support/`：单测夹具、渲染器与全局测试初始化。
- `frontend/tests/e2e/`：浏览器端到端测试。
- `video/tests/`：渲染契约、模板和布局测试。

前端单测通过 `@/` 引用正式代码、通过 `@test/` 引用测试支撑，避免把测试实现重新混入
`frontend/src/`。Python 确定性适配器保留在可导入的 `god_news.testing` 命名空间中，
但生产启动路径不得依赖它。

## 文档与工具

- `docs/architecture/`：当前有效的架构与接口说明。
- `docs/quality/`：当前有效的质量门。
- `docs/design/`：设计规范。
- `docs/archive/YYYY-MM/`：历史记录。
- `scripts/dev/`：本地启动和停止。
- `scripts/maintenance/`：契约生成等维护工具。
- `scripts/quality/`：E2E、A/B 实验和媒体诊断入口。
- `scripts/workers/`：由应用显式启动的隔离生产进程。
- `frontend/scripts/build/`：前端构建前准备脚本。
- `frontend/scripts/quality/`：前端截图和视觉质量工具。

## 本地状态与生成物

- `data/`：数据库、ChromaDB 和本地模型缓存。
- `outputs/`：正式渲染、审核资产和质量输出。
- `logs/`：运行日志。
- `output/`：已废弃的旧单数目录，禁止使用并由 Git 忽略。

这些目录不进入 Git。清理 `outputs/` 前必须确认数据库引用；正式成片归档与生产素材
不能和普通 QA 缓存一起删除。

安全清理可再生缓存、日志、测试报告和 Template Lab 静态暂存文件：

```powershell
.\scripts\maintenance\clean_workspace.ps1
```

该脚本明确不处理 `.venv/`、`node_modules/`、`data/` 和 `outputs/`。开发服务正在写入
的日志在 Windows 上可能被锁定；脚本会明确警告并保留这些活跃文件，其他清理仍正常
完成，服务停止后再次运行即可删除。
