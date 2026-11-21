# SPEC：admin（管理后台模块）

> 本文件只锚定意图与对外承诺，不写实现细节。实现细节见 docs/architecture.md。

## 这个模块存在是为了什么

站点运营控制台：仪表盘、用户管理、配置管理、活动日志审计、挂载页面管理、站点设置与封禁管理。

## 对外承诺的行为契约（用户视角可观察）

1. **权限分层**：`/admin` 全部要求管理员；设置页（`/admin/setting*`）与封禁 IP 管理（`/admin/ip*`）仅超级管理员可访问；普通管理员/未登录被拒绝或重定向。
2. **活动日志 API（B1 锚定）**：`GET /admin/activity/api`
   - `grouped=true`：响应为顶层 `activities[]`，每个元素是一条分组记录：`is_group`（count>1 的折叠组为 true，count=1 的普通行为 false）、`count`、`latest_time`（组内最新时间）、`activities[]`（组内完整记录列表）；分组聚合键为 `(username, description, path)`；无 `groups`/`date` 顶层键；
   - `grouped=false`：平铺结构（顶层 `activities[]` 含原始记录字段），与历史响应向后兼容；
   - 支持 `username` 筛选（含"未登录"筛选）、默认 `per_page=200`（"最近 200 条"口径）、显式 page/per_page 分页、`show_all` 全量。
3. **挂载页面管理（B5 锚定）**：添加成功响应含 `{success, message, name, page_type, redirect_url}`；列表 API 返回 `{name, path, type}` 结构（不再用 is_file 表达类型）。
4. **配置管理**：读改 config.json；改动落盘且可读回。
5. **用户管理**：注册/启停/删除用户；用户状态切换立即生效（被禁用者下一请求即被拦截）。

## 边界与豁免

- 服务器重启接口仅限管理员使用。
- 活动日志记录未登录访问；真实 IP 仅在 `TRUST_PROXY_HEADERS=1` 时读代理头。
- 日志清理接口可清理历史活动日志。
