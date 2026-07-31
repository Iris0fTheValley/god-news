# 项目目录约定

## 正式代码

- `src/god_news/`：Python 领域、应用与基础设施。
- `frontend/src/`：React 前端；组件单测与组件共置。
- `video/src/`：Remotion 渲染器、模板、布局编译器和 Studio fixture。
- `assets/demo-owned/`：项目自有且带 provenance 的演示素材唯一来源。

Template Lab 所需的浏览器静态文件由
`frontend/scripts/prepare-template-lab-assets.mjs` 从该唯一来源复制到被忽略的
`frontend/public/template-lab/`，不得重复提交两份相同素材。Live2D 预渲染文件仍由
操作者或视觉测试临时注入。

使用专用 SDK/Python 环境的一次性生产进程属于 `scripts/workers/`，与开发、维护和质量
脚本分开；可复用领域逻辑仍属于 `src/god_news/`。CLI 只负责参数解析和编排，不应成为
领域逻辑的唯一存放位置。

## 测试

- `tests/`：Python 单元、集成和契约测试，复用夹具放在 `tests/fixtures/`。
- `frontend/src/**/*.test.*`：前端组件与状态单测。
- `frontend/e2e/`：浏览器端到端测试。
- `video/tests/`：渲染契约、模板和布局测试。

不为追求目录外观而拆散高内聚的共置测试。

## 文档与工具

- `docs/architecture/`：当前有效的架构与接口说明。
- `docs/quality/`：当前有效的质量门。
- `docs/design/`：设计规范。
- `docs/archive/YYYY-MM/`：历史记录。
- `scripts/dev/`：本地启动和停止。
- `scripts/maintenance/`：契约生成等维护工具。
- `scripts/quality/`：E2E、A/B 实验和媒体诊断入口。
- `scripts/workers/`：由应用显式启动的隔离生产进程。

## 本地状态与生成物

- `data/`：数据库、ChromaDB 和本地模型缓存。
- `outputs/`：正式渲染、审核资产和质量输出。
- `logs/`：运行日志。
- `output/`：已废弃的旧单数目录，禁止使用并由 Git 忽略。

这些目录不进入 Git。清理 `outputs/` 前必须确认数据库引用；正式成片归档与生产素材
不能和普通 QA 缓存一起删除。
