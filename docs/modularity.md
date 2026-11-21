# 模块化开发文档

> 本文档是模块化开发的唯一操作规范。与 `AGENTS.md`（项目总览）和 `docs/architecture.md`（实现细节）配合阅读。
> 审计基线：`scripts/module_audit.py`（量化）+ 2026-11-21 模块化重构（M1–M7）。

## 1. 分层与依赖规则

```
Module/<业务模块>/    路由层：解析请求 → 调用服务 → 渲染/响应。禁止写业务规则、禁止直接读写文件/数据库。
Module/core/          服务层：业务规则、持久化编排、可独立单测。禁止依赖 Flask request/session（中间件除外，见 §4.4）。
Module/common/        共享工具：配置、数据库、文件、认证、设置、网络、路径常量、安全。禁止引用任何业务模块。
Module/static/        全局静态资源（/static/ 前缀，ipguard 白名单内）。
Module/templates/     全局模板（base、错误页等）。
```

**依赖方向（硬约束）**

| 允许 | 禁止 |
|---|---|
| 路由层 → `core` / `common` | `common` → `core` 或业务模块 |
| `core` → `common` | `core` → 业务模块（跨域逻辑应通过参数/注入） |
| 业务模块之间 → `common` 工具 | 业务模块之间直接 import 对方私有函数/服务单例 |
| `app.py` → 所有模块（注册） | 业务模块 → `app.py` |

- 功能开关：统一使用 `Module.common.settings_utils.is_feature_enabled()`，**不要**再通过 `AdminService` 读取（避免反向依赖）。
- 配置：统一 `Module.common.config_utils.load_config/save_config`（含 TTL 缓存与备份）。
- 客户端 IP：统一 `Module.common.net_utils.get_client_ip(request)`。
- 公开路径：统一 `Module.common.web_paths`（认证白名单 / CSRF 豁免 / ipguard 白名单是三种不同语义，不要混用）。
- 自检：`py -3.12 scripts/module_audit.py`，要求"反向依赖告警（无）"且"模块级循环依赖（无）"。

## 2. 目录约定

```
Module/<name>/
├── __init__.py          # 导出蓝图（如 gallery 三个蓝图）
├── <name>.py            # 路由（薄）
├── templates/<name>/    # 模块模板
└── static/              # 仅当确实需要模块专属静态资源（默认走 Module/static）
Module/core/<name>_service.py   # 服务（一个业务域一个 service）
Module/common/<topic>_utils.py  # 共享工具（无业务名）
tests/test_<module>_*.py        # 测试（平铺，模块名前缀）
```

## 3. 新增一个业务模块

1. `Module/<name>/__init__.py` + `<name>.py`：只定义蓝图、路由、参数解析、模板渲染。
2. `Module/core/<name>_service.py`：定义 `class <Name>Service`，构造函数支持依赖注入：
   ```python
   def __init__(self, db_utils=None, file_utils=None, config_utils=None):
       self.db = db_utils or __import__("Module.common.db_utils", fromlist=["query"])
       ...
   ```
3. 路由顶部模块级单例：`_service = <Name>Service()`。
4. 功能开关用 `settings_utils`；配置用 `config_utils`；文件/数据库用 `common` 工具。
5. 在 `app.py` 注册蓝图（顺序见 `docs/architecture.md`）；新增开关时同时更新 `settings_utils.SETTING_DEFAULTS`。
6. 测试：`tests/test_<name>_*.py`；涉及对外响应结构的，补 `tests/contracts/`（golden）。
7. 文档：`docs/specs/<name>.md` + `<name>.history.md`；行为变更先写 ADR（`py session.py new-adr`）。

## 4. 横切设施

| 设施 | 位置 | 规范 |
|---|---|---|
| 设置/开关 | `common/settings_utils.py` | `get_settings/is_feature_enabled/update_setting`；管理后台经 `AdminService` 委托调用，业务代码直接用 |
| 配置 | `common/config_utils.py` | TTL 5 秒；写配置前 `backup_config()`（保留 5 份） |
| 数据库 | `common/db_utils.py` | WAL；`query/execute/executemany/transaction`；连接全局串行 |
| JSON 文件 | `common/file_utils.py` | 线程安全读写；**禁止直接 open() 写 JSON** |
| 认证 | `common/auth_utils.py` | `check_auth/require_auth/register_auth_middleware`；白名单来自 `web_paths` |
| CSRF | `common/security.py` | 全局中间件；豁免路径 `web_paths.CSRF_EXEMPT_PATHS`；3 种取 token 方式以 `ui.js getCsrfToken()` 为准 |
| 限流/封禁 | `Module/ipguard/` | `middleware/rate_limiter/ban_manager` 分层；白名单 `web_paths` |
| 网络 IP | `common/net_utils.py` | 仅 `TRUST_PROXY_HEADERS=1` 读代理头 |
| 分页 | `common/pagination.py` | **当前未使用**（历史工具）；新列表接口优先使用它并在 PR 中说明；既有手写分页不强制迁移 |
| 响应格式 | `common/response.py` | **API 现状以 `{"success": bool, ...}` 为准**；`{code,data,msg}` 仅为历史工具，新接口不要混用，错误处理器沿用 `{"error","code"}` |

**中间件**：全局 before/after_request 一律在 `app.py` 或 `common/*_utils.py` 注册，不得放在 `core` service（`AdminService.register_auth_middleware` 已于 M4 迁出）。

## 5. 服务层规范

- 一个 service 只负责一个业务域；`AdminService` 现保留：服务器信息、活动会话、用户管理、配置/挂载页、活动日志查询、IP 工具。
- userfix 提交记录管理归 `UserfixService`；书籍归 `BooksService`；画廊归 `GalleryService`；反馈提交/配额/清理归 `UserfixService`。
- service 方法返回**简单数据或 `(success, message)`**，不要返回 Flask Response；HTTP 语义（abort/redirect/jsonify）留在路由层。
- 可注入依赖，便于单测；避免在 service 内 import Flask `request`。
- 缓存：模块级 TTL 缓存必须加锁（参考 `gallery_service._scan_cache_lock`），写清 TTL 与失效条件。

## 6. 前端与模板规范

- **共享脚本**：`Module/static/common/ui.js` —— `getCookie/getCsrfToken/showDialog/showAlert/showConfirm/confirmDialog/closeDialog` 与暗夜模式引导；模板通过 `<script src="/static/common/ui.js"></script>` 引用，**禁止**再复制这些函数。
- **确认框时序（ADR-0006）**：`confirmDialog()` 必须先 `var cb = dialogCallback;` → `closeDialog()` → `cb(true)`；`tests/test_confirm_dialog_templates.py` 锚定该时序，改共享脚本时不得破坏。
- **静态资源**：优先外置到 `Module/static/...`；模板引用使用 `static_url('path')`（附加 `?v=mtime`，配合 ADR-0011 长缓存）。
- **页面请求/API 分流**：错误处理按 `app.py::_prefers_json_error` 规则（`/api/`、非 GET、Accept 不含 html → JSON）。
- **CSS**：admin 共享样式放 `Module/static/admin/admin-base.css`；页面只保留页面专属样式。
- **服务端渲染优先**：首屏必需内容（导航入口、壁纸 URL、列表数据）在 HTML 中直出，不要依赖页面加载后的 fetch。
- **布局稳定**：异步渲染区块先应用最终布局参数再插入内容，渲染完成后才显示（参考画廊发现区）。
- **暗夜模式**：仅通过 `ui.js` 的 cookie 引导，不在各模板重复实现。

## 7. 测试规范

- 位置：`tests/test_<module>_*.py`；契约：`tests/contracts/`（golden JSON + 断言）。
- 每个模块至少覆盖：路由状态码/权限、服务层业务规则、边界与安全（路径穿越/上传/角色）。
- 重构必须保持既有断言强度；只允许"测试数据适配"与"锚点位置迁移"（如函数迁到共享脚本），并在 CHANGELOG 说明。
- 禁止：放宽断言、跳过测试、`--no-verify`、删功能消错。
- 命令：`py -3.12 -m pytest tests/ -q`（当前基线 570+）。

## 8. 常见反模式（本项目真实踩过）

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 路由层重复实现 service（books/userfix 旧状） | 两份逻辑各自演化、安全修复漏一份 | 路由只解析参数，逻辑入 service |
| 上帝 service（`AdminService` 9 域 + 中间件） | 难测、跨域耦合 | 按域拆分；中间件放 `common`/`app.py` |
| `common` 反向 import `core` | 循环依赖、层次倒置 | 共享能力上提到 `common/settings_utils` 等 |
| 模板复制粘贴（8 份 confirmDialog、16 份 getCookie） | 一处 bug 改 8 次 | 共享 `ui.js`/base 模板 |
| 配置各自实现 | TTL/备份/格式不一致 | 统一 `config_utils` |
| 页面入口/背景靠前端 fetch | 慢、失败即缺失 | 服务端渲染 + 预加载 + 缓存 |
| 异步渲染先显示空容器 | 布局跳动 | 先定布局、片段插入、渲染后显示 |

## 9. 审计与验收

```bash
py -3.12 scripts/module_audit.py       # 规模/依赖矩阵/反向与循环依赖/重复窗口/模板内联/测试覆盖
py -3.12 scripts/perf_baseline.py      # 页面/接口/静态资源 P50 与缓存头
py -3.12 scripts/export_release.py     # 导出可发布 zip（剔除运行数据/缓存/内部文档，内置安全扫描）
py -3.12 session.py finish             # 收工门禁：全量测试 + 账本校验
```

验收标准（重构类任务）：`module_audit` 无反向依赖/无模块级循环；`pytest` 0 failed；关键页面浏览器回归；CHANGELOG 与 tasks 账本同步。

## 10. 变更流程

1. 改行为 → 先写 ADR（`py session.py new-adr <标题>`）。
2. 多步骤任务 → `docs/superpowers/plans/` 写计划；`tasks.json` 登记；每任务 TDD + 全绿 + 单独提交。
3. 纯内部重构 → 必须保持契约（specs + goldens + 既有测试）不变；如改测试锚点，只允许迁移位置、不得放宽断言。
4. 收尾：`CHANGELOG.md` + `docs/specs/<模块>.history.md` + `tasks.json` + `py session.py finish`。
