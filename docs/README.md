# 文档索引

| 文档 | 内容 |
|---|---|
| [architecture.md](architecture.md) | 模块划分、路由清单、数据文件与运行时行为 |
| [modularity.md](modularity.md) | 模块化开发规范：分层与依赖规则、横切设施、服务/模板/测试规范、反模式、审计与变更流程 |
| [data-storage.md](data-storage.md) | SQLite 表结构、JSON 配置/数据文件、备份与迁移约定 |
| [standards.md](standards.md) | UI 风格、配色/排版/响应式/暗夜模式约定 |
| [security-audit.md](security-audit.md) | 安全审计发现与修复状态 |
| [adr/README.md](adr/README.md) | ADR 索引与"何时必须写 ADR"判定标准 |
| [specs/](specs/) | 各模块意图规格（`<模块>.md`）与演变记录（`<模块>.history.md`） |
| [fix-plans/overview.md](fix-plans/overview.md) | 历史安全审计修复方案概览 |

## 常用脚本

| 脚本 | 用途 |
|---|---|
| `scripts/export_release.py` | 生成可发布的 zip 包（自动剔除运行数据与内部文档） |
| `scripts/module_audit.py` | 模块化量化审计（依赖矩阵/循环依赖/重复代码/模板内联/测试覆盖） |
| `scripts/perf_baseline.py` | 性能基线（页面/接口/静态资源 P50 与缓存头） |
| `scripts/audit_dead_buttons.py` | 全站死按钮审计（onclick 引用 + 确认框时序） |
