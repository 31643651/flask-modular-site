# Flask 多功能综合网站服务器

基于 Flask 的模块化个人网站服务器：首页导航与页面挂载、书籍阅读、图片画廊、用户中心、管理后台、访问防护、用户反馈、结构化日志。使用 SQLite 存储高频数据、JSON 存储配置，**无需独立数据库服务**，适合单机部署。

## 功能特性

| 模块 | 路由 | 说明 |
|---|---|---|
| 初始配置 | `/setup` | 首次部署向导：创建管理员、设置服务器名称并生成 `config.json` |
| 首页导航 | `/` | 功能入口、随机壁纸、外部页面挂载（文件/目录，含 HTML 站根引用改写） |
| 书籍管理 | `/book` | 书籍搜索、详情、章节阅读、封面子目录服务 |
| 画廊 | `/gallery` | 目录浏览、搜索、发现流、灯箱、收藏、偏好跨端同步（按用户保存） |
| 用户中心 | `/user` | 登录/登出、注册、超级管理员动态验证码、资料页 |
| 管理后台 | `/admin` | 仪表盘、活动日志、用户管理、配置、挂载页面、系统设置、IP 封禁管理 |
| 访问防护 | `/ipguard` | 两级 IP 限流 + 递进封禁（内存滑窗 + SQLite 持久化） |
| 用户反馈 | `/userfix` | Bug 提交 / 功能建议（图片白名单 + magic-bytes 校验、每日配额） |
| 日志 | — | structlog 结构化日志，按天滚动 |
| 静态站挂载 | `/<名称>` | 外部纯前端站点以目录挂载方式服务（如 `sdinspector/`） |

UI 支持**暗夜模式**与响应式布局；错误页 404/403/500 中文化并对页面/API 分流。

## 技术栈

- Python 3.12、Flask 3.1、Werkzeug 3.1、structlog 26.1
- 数据：SQLite（`Module/data/app.db`）+ JSON 配置（`Module/json/`）
- 测试：pytest + 契约测试（`tests/contracts/`，golden 期望样例）
- 前端：原生 JS/CSS（无构建步骤），共享脚本 `Module/static/common/`

## 快速开始

```bash
py -3.12 -m pip install -r requirements.txt
py -3.12 app.py
```

访问 `http://127.0.0.1:20999`（或 `http://localhost:20999`）。首次访问会自动跳转 `/setup` 完成初始化。

## 运行方式

```bash
py -3.12 app.py                 # 开发模式（前台、debug、自动重载）
py -3.12 app.py --production    # 生产模式（前台、无调试）
py -3.12 app.py start           # 后台启动（生产模式，命令立即返回）
py -3.12 app.py reload          # 停止并按当前代码重启
py -3.12 app.py quit            # 停止后台服务
```

`start` 会写入 `Module/data/app.pid`，输出追加到 `Module/log/server-stdout.log`；重复 `start` 会提示已在运行。

## 目录结构

```
app.py                  # 应用工厂（create_app）+ 进程管理命令
session.py              # 开发会话/任务 CLI
Module/
├── common/             # 共享工具（配置/数据库/文件/认证/设置/网络/路径/安全）
├── core/               # 业务服务层（admin/books/gallery/index/user/userfix）
├── <模块>/             # 路由层（index/books/gallery/user/admin/userfix/ipguard/setup/log）
├── static/             # 全局静态资源（/static/）
├── templates/          # 全局模板（错误页）
├── data/               # SQLite（运行时生成）
├── json/               # JSON 配置（运行时生成）
└── log/                # 日志（运行时生成）
docs/                   # 架构、数据存储、UI、模块化、安全审计、ADR、模块规格
tests/                  # pytest（含 contracts 契约测试）
scripts/                # 开发/运维脚本（审计、性能、导出发布包等）
```

## 数据与配置

- 首次部署由 `/setup` 生成 `Module/json/config.json`；该文件与运行数据**不纳入版本库**。
- 配置读写统一走 `Module.common.config_utils`（TTL 缓存 + 备份，保留最近 5 份）。
- 数据库为 SQLite（WAL），表结构见 `docs/data-storage.md`。

## 测试

```bash
py -3.12 -m pip install -r requirements-dev.txt
py -3.12 -m pytest tests/ -q
```

## 导出发布包

```bash
py -3.12 scripts/export_release.py
```

在 `dist/` 生成可发布的 zip（自动剔除 `.git`、缓存、数据库、配置、日志、用户上传、壁纸、开发期工具与流程文档（如 `session.py`、`AGENTS.md`）、内部规划文档等；内置禁入项安全检查）。可用 `--output` 指定输出路径。

## 文档

| 文件 | 说明 |
|---|---|
| `docs/architecture.md` | 模块与路由、数据文件的详细说明 |
| `docs/modularity.md` | 模块化开发规范（分层与依赖、横切设施、服务/模板/测试规范） |
| `docs/data-storage.md` | 数据存储规范（SQLite 表结构、JSON 文件） |
| `docs/standards.md` | UI 风格与实现规范 |
| `docs/security-audit.md` | 安全审计报告与修复方案索引 |
| `docs/adr/` | 架构决策记录（ADR）索引与判定标准 |
| `docs/specs/` | 各模块意图规格与演变记录 |
| `CHANGELOG.md` | 变更日志 |

## 许可证

本项目采用 [MIT License](LICENSE) 发布。
