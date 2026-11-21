# ADR-0003: 启动期 admin 账户常驻兜底

## 状态

已接受（2026-11-20）

## 背景

用户要求"始终保持数据库中有一个 admin，我登录用"。三种劣化情形当前均无自愈手段：

1. admin 行被禁用/降级（`enabled=0` 或 `role≠admin` 或 `is_superadmin≠1`）；
2. admin 行被删除但存在其他用户；
3. `users` 表为空。

应用内 `AdminService` 对 admin 行有"不能禁用/删除管理员账户"防护（`admin_service.py:170,211`），但绕过应用直改 SQLite 可绕过该防护；`init_db()` 目前只建表不校验数据。

## 决策

1. `config.json` 已存在（已过首次部署）且 `init_db()` 完成后调用 `ensure_admin_exists()`（实现于 `Module/common/user_utils.py`，经 `db_utils.execute` 单行操作）：
   - **admin 行存在但被降级/禁用** → `UPDATE` 恢复 `role='admin', enabled=1, is_superadmin=1`，**密码保留**（用户可直接用原密码登录）；
   - **admin 行不存在且 users 非空** → 提权 **id 最小的用户**（最老用户）：恢复 `role/is_superadmin/enabled`，**用户名与密码保留**（登录方式不变，即用户本人）；
   - **users 表为空** → `INSERT username='admin'`（`id=COALESCE(MAX(id),0)+1`，`role='admin', enabled=1, is_superadmin=1`），随机密码（`secrets.token_urlsafe`）并以 structlog warning 将用户名与初始随机密码打印到启动日志。
2. `config.json` 不存在（首次部署进行中）时**不执行**——避免与 setup 向导 step 2 的 `INSERT admin`（`setup.py:64-67`）主键冲突；首次部署的 admin 创建仍由 setup 负责。

放弃的备选：

- **仅恢复 admin 行、缺行不提权**：表里没有 admin 时无法登录，不满足"始终保持有一个"；
- **始终新建 admin 用户**：非空表情形会额外造出新账号，与"提权最老用户（用户本人）"的预期不符，且制造重复管理入口。

## 后果

- 正：任何劣化状态下重启即可恢复可登录的超管；被误禁用/降级的 admin 自愈；
- 负：空表情形随机密码仅出现在启动日志，日志文件权限即凭据暴露面（缓解：`Module/log` 本就含敏感运营数据且已 gitignore）；
- 存储语义变化：启动后 `users` 表内容可能被自动修复（用户可观察的数据变化，故立此 ADR）。
