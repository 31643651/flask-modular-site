# Architecture

详细模块说明，包含路由、数据文件和功能特性。

---

## 1. 主程序 (app.py)

**职责**: 
- 提供 create_app 工厂函数创建 Flask 应用实例
- 配置应用基础设置
- 注册所有功能模块的蓝图
- 启动开发/生产服务器

**重要说明**: 
- 不包含任何业务逻辑路由，所有路由定义在各模块中
- `setup` 蓝图必须最先注册，配合 `check_initial_setup` 中间件：config.json 未生成时所有请求重定向到 `/setup`
- `ipguard` 中间件在 create_app 末尾通过 `init_ipguard_middleware(app)` 注册为全局 `before_request`
- SD Inspector 已改为静态站挂载（根目录 `sdinspector/`），不再注册蓝图
- 支持生产模式（`--production` 参数）和开发模式

**蓝图注册顺序**: setup → ipguard → index → books → user → admin（7 个蓝图）→ log → userfix（2 个蓝图）→ gallery（3 个蓝图）

**中间件挂载顺序（均为 before_request）**: 
1. `check_initial_setup` - 初始配置检查（config.json 不存在时重定向 /setup）
2. `ipguard_check` - 两级 IP 限流与封禁检查（`init_ipguard_middleware` 注册）
3. 认证中间件（`AdminService.register_auth_middleware`）与日志中间件（`register_log_middleware`）
4. CSRF 保护（`init_csrf_middleware`）
5. after_request: 安全响应头（`add_security_headers`，生产模式附加 HSTS）

**启动方式**:
- 开发模式: `py -3.12 app.py`
- 生产模式: `py -3.12 app.py --production`

## 2. 初始配置模块 (Module/setup/)

**路由前缀**: `/setup`

**主要功能**:
- 首次部署的初始配置向导，必须在其他模块之前注册
- config.json 未生成时，app.py 的全局中间件将所有请求重定向到 `/setup`
- 分两步完成：
  - 步骤 1: 创建管理员账户（用户名固定 `admin`，两次密码校验），设置管理员二次验证开关，暂存于 session
  - 步骤 2: 设置服务器名称，写入 users 表（id=1、role=admin、is_superadmin=1），生成 `Module/json/config.json` 默认结构（paths、settings、wallpaper、mounted_pages、config.server_name），随后清理 session 并重定向到登录页

**主要路由**:
- `GET /setup/` - 显示步骤 1 表单
- `POST /setup/`（step=1）- 校验并暂存管理员账户信息
- `POST /setup/`（step=2）- 创建管理员用户并生成 config.json

**特殊行为**: config.json 已存在时访问 `/setup` 直接重定向到登录页（`/user/login`）

**数据文件**: 创建 `Module/json/config.json`；管理员账户写入 SQLite（`Module/data/app.db` 的 users 表）

## 3. 访问防护模块 (Module/ipguard/)

**路由前缀**: `/ipguard`

**主要功能**: 两级 IP 访问频率限制与封禁管理

**文件结构**:
- `middleware.py`: 核心检查逻辑 `_handle_request` 与 Flask 中间件包装 `init_ipguard_middleware(app)`（注册到 `app.before_request`，中间件内部异常时放行，避免拖垮正常服务）
- `rate_limiter.py`: 内存滑动窗口计数（RLock 保护，单键最多保留 200 条、1 小时窗口）
- `ban_manager.py`: 封禁内存缓存（启动时 `load_ban_cache()` 从 SQLite 加载）+ `ip_bans` 表持久化（UPSERT 幂等写入）
- `module.py`: 提示页预览路由

**客户端 IP 语义**: 仅当环境变量 `TRUST_PROXY_HEADERS=1`（部署于可信反向代理之后）时才读取 `X-Forwarded-For` / `X-Real-IP`，否则一律回退 `request.remote_addr`，防止伪装代理头绕过限速或伪造封禁记录

**白名单前缀**（不计入统计、不受封禁拦截）: `/static/`、`/favicon.ico`、`/setup`、`/ipguard/banned`、`/ipguard/rate_limited`；超级管理员完全豁免

**第一防线**（针对未登录/匿名流量，递进式封禁 5 分钟 → 1 小时 → 24 小时 → 第 4 次起永久；24 小时窗口重置计数）:
- 未登录高强度访问 `/user/login`: 阈值 5 次/分钟、15 次/小时
- UA 浏览器或 OS 解析为 Other: 阈值 3 次/分钟、9 次/小时

**第二防线**（针对已登录普通用户的页面频率）:
- 同一 (IP, 路径) 1 分钟内 GET 超过 10 次（非静态资源）触发，10 分钟窗口内递进：
  - 第 1 次: 进入 1 分钟限速期（期间除静态资源外全部返回 429 限速页）
  - 第 2 次: 封禁 2 分钟
  - 第 3 次及以上: 永久封禁，并禁用该用户账户
- 限速状态与滑窗均存于内存，封禁结果持久化到 SQLite（重启不丢失）；过期封禁超过 24 小时后自动清理记录

**主要路由**:
- `GET /ipguard/banned` - 封禁提示页预览
- `GET /ipguard/rate_limited` - 限速提示页预览

**数据文件**: SQLite（`Module/data/app.db` 的 `ip_bans` 表）

## 4. 首页模块 (Module/index/)

**路由前缀**: `/` (根路径)

**主要功能**:
- 首页导航，展示各功能模块入口
- 支持壁纸功能（随机切换）
- 支持挂载外部页面或文件夹（提供目录浏览）

**主要路由**:
- `GET /` - 首页
- `GET /static/wallpaper` - 壁纸服务
- `GET /api/wallpaper/config` - 获取/更新壁纸配置
- `GET /api/mounted-pages` - 获取已挂载页面列表
- `GET /<page_name>` - 服务挂载的页面或文件夹

**数据文件**: `Module/json/config.json`

## 5. 书籍管理模块 (Module/books/)

**路由前缀**: `/book`

**主要功能**:
- 书籍搜索
- 书籍详情查看
- 章节阅读

**主要路由**:
- `GET /book` 或 `GET /book/` - 书籍首页
- `GET /book/search?q=关键词` - 搜索书籍
- `GET /book/<book_id>` - 书籍详情
- `GET /book/<book_id>/chapter/<chapter_num>` - 章节内容
- `GET /book/static/<filename>` - 书籍静态资源

**数据文件**: 书籍数据存于 SQLite（`Module/data/app.db` 的 books 表），路径配置存于 `Module/json/config.json`

## 6. 用户模块 (Module/user/)

**路由前缀**: `/user`

**主要功能**:
- 用户登录
- 用户注册
- 管理员二次验证
- 用户资料管理

**主要路由**:
- `GET /user/login` - 登录页面
- `POST /user/login` - 登录处理
- `GET /user/register` - 注册页面
- `POST /user/register` - 注册处理
- `GET /user/logout` - 登出
- `GET /user/verify` - 管理员验证页面
- `POST /user/verify` - 验证处理
- `GET /user` 或 `GET /user/` - 用户资料页面
- `GET /user/profile` - 用户资料页面（别名）
- `GET /user/api/check-username` - 检查用户名是否存在

**数据文件**: 用户数据存于 SQLite（`Module/data/app.db` 的 users 表）

## 7. 管理后台模块 (Module/admin/)

**路由前缀**: `/admin`（按功能拆分为 7 个蓝图，均使用 `/admin` 前缀）

**蓝图拆分**:
- `routes.py` (`admin_bp`) - 仪表盘与服务器重启
- `routes_activity.py` (`admin_activity_bp`) - 活动日志查看与 API
- `routes_users.py` (`admin_users_bp`) - 用户管理
- `routes_config.py` (`admin_config_bp`) - 配置管理
- `routes_mounted.py` (`admin_mounted_bp`) - 挂载页面管理
- `routes_setting.py` (`admin_setting_bp`) - 设置页（仅超级管理员）
- `routes_ipguard.py` (`admin_ip_bp`) - 封禁 IP 管理（仅超级管理员）

**主要路由**:
- `GET /admin` 或 `GET /admin/` - 仪表盘
- `POST /admin/restart` - 重启服务器
- `GET /admin/activity` - 活动日志
- `GET /admin/activity/all` - 全量活动日志
- `GET /admin/activity/api` - 活动日志 API（支持折叠模式）
- `POST /admin/activity/api/cleanup` - 清理活动日志
- `GET /admin/users` - 用户管理
- `POST /admin/users/<username>/toggle` - 切换用户状态
- `POST /admin/users/register` - 注册用户
- `POST /admin/users/<username>/delete` - 删除用户
- `GET /admin/config` - 配置管理
- `GET /admin/config/api` - 获取配置信息
- `POST /admin/config/update` - 更新配置
- `GET /admin/mounted-pages` - 获取已挂载页面列表
- `POST /admin/mounted-pages` - 添加挂载页面
- `DELETE /admin/mounted-pages/<name>` - 删除挂载页面
- `GET /admin/setting` - 设置页面
- `GET /admin/setting/api` - 获取所有设置
- `POST /admin/setting/update` - 更新单个设置
- `GET /admin/ip` - 封禁 IP 管理页面
- `GET /admin/ip/api/bans` - 活跃封禁列表 API
- `POST /admin/ip/unban` - 解除 IP 封禁

**数据文件**: 用户/活动日志/活动会话/ip_bans 存于 SQLite（`Module/data/app.db`），server_info、config 存于 JSON

**权限要求**: 管理后台仅管理员可访问；设置页（`/admin/setting*`）与封禁 IP 管理（`/admin/ip*`）仅超级管理员可访问

**活动日志功能特性**:
- **折叠模式**: 支持按用户+路径分组，显示访问次数，仅折叠连续多次访问
- **真实 IP 地址**: 仅在 `TRUST_PROXY_HEADERS=1` 时读取代理头（X-Forwarded-For, X-Real-IP），否则回退 remote_addr
- **设备识别**: 自动识别 Android、iOS、Windows、Mac、Linux 等设备类型
- **浏览器识别**: 支持 Chrome、Firefox、Safari、Edge、Opera、Internet Explorer
- **系统识别**: 详细显示 Windows 版本（10/11、7、8、8.1）、macOS、Linux 等
- **未登录访问记录**: 记录所有未登录的访问请求
- **全量日志页**: `/admin/activity/all` 提供不折叠的全量活动日志视图
- **日志清理**: `POST /admin/activity/api/cleanup` 清理历史活动日志

## 8. 日志模块 (Module/log/)

**主要功能**:
- 运营日志记录：structlog 输出 Logfmt 结构化格式，字段化记录 method/path/status/ip
- 日志文件按天滚动存储（`app.log`，保留 7 天），桥接 werkzeug 等第三方库日志
- 在线查看路由已移除，仅保留 `get_log_files()` / `get_log_content()` 辅助函数

**主要路由**:
- 无（日志查看路由已移除，仅注册无路由的蓝图并挂载日志中间件）

**日志存储**: `Module/log/app.log`（按天滚动，Logfmt 格式）

## 9. 画廊模块 (Module/gallery/)

**路由前缀**: `/gallery`（按功能拆分为 3 个蓝图）

**蓝图拆分**:
- `routes.py` (`gallery_bp`) - 图片浏览、搜索、图片服务、收藏页面
- `routes_favorites.py` (`gallery_favorites_bp`) - 收藏 API
- `routes_preferences.py` (`gallery_preferences_bp`) - 用户偏好设置 API

**主要功能**:
- 图片浏览（支持文件夹导航）
- 图片搜索
- 随机图片发现
- 收藏管理
- 全屏灯箱预览
- 用户偏好设置（多端同步）

**主要路由**:
- `GET /gallery` 或 `GET /gallery/` - 画廊首页
- `GET /gallery/<path:subpath>` - 浏览子文件夹
- `GET /gallery/favorites` - 收藏页面
- `GET /gallery/image/<path:image_path>` - 图片服务
- `GET /gallery/api/random-images` - 随机图片
- `GET /gallery/api/folder-images/<path:subpath>` - 文件夹图片列表
- `GET /gallery/api/search` - 搜索
- `GET /gallery/api/favorites` - 收藏列表
- `POST /gallery/api/favorite/add` - 添加收藏
- `POST /gallery/api/favorite/remove` - 取消收藏
- `POST /gallery/api/favorite/check` - 检查收藏状态
- `GET /gallery/api/preferences` - 用户偏好设置
- `POST /gallery/api/preferences` - 更新偏好设置
- `GET /gallery/api/preferences/default` - 默认偏好设置

**数据文件**: 收藏存于 SQLite（`Module/data/app.db` 的 favorites 表），偏好设置与配置存于 JSON

**用户偏好设置功能**:
- **多端同步**: 登录用户设置在所有设备间自动同步
- **设备特定**: 移动端和电脑端显示不同的设置选项
- **实时保存**: 修改设置后立即保存到服务器
- **设置项**:
  - discover_enabled: 是否开启发现功能
  - discover_format: 发现格式（one/two/three，仅移动端）
  - discover_rounded: 发现图片圆角（仅移动端）
  - discover_shape: 发现图片形状（square/rectangle，仅电脑端）
  - discover_size: 发现图片大小（仅电脑端）
  - sidebar_transparency: 侧边栏透明度
  - lightbox_zoom_level: 灯箱默认缩放级别
  - image_quality: 图片质量（high/medium/low）
  - autoplay_lightbox: 是否自动播放灯箱

## 10. SD Inspector 静态站（根目录 sdinspector/）

**访问路径**: `/sdinspector`（经页面挂载机制服务）

**主要功能**:
- Stable Diffusion 图片检查工具
- 纯前端应用，由后端提供静态资源服务

**特点**: 无数据存储，纯前端应用；目录已 gitignore

**注意**: SD Inspector 为纯静态网站（位于项目根目录 `sdinspector/`），通过通用静态站点挂载机制服务（见"页面挂载"），不再作为独立蓝图注册。

## 11. 用户修复模块 (Module/userfix/)

**路由前缀**: `/userfix`（拆分为 2 个蓝图）

**蓝图拆分**:
- `userfix.py` (`userfix_bp`) - 用户提交端
- `admin_view.py` (`userfix_admin_bp`) - 管理后台查看端（挂载于 `/admin`）

**主要功能**:
- 用户问题反馈和修复（Bug 提交 / 功能建议）

**主要路由**:
- `GET /userfix/check-limit` - 查询当日剩余提交次数
- `POST /userfix/submit` - 提交修复请求（文本 + 最多 6 张图片，非管理员每日 3 次限制，提交保留 30 天自动清理）
- `GET /userfix/image/<submission_id>/<filename>` - 提交图片服务
- `GET /admin/userfix` - 管理后台反馈列表（仅超级管理员，支持状态筛选与分页）
- `POST /admin/userfix/api/update-status` - 更新反馈状态
- `POST /admin/userfix/api/delete` - 删除反馈

**数据文件**: `Module/json/userfix_limits.json`（每日提交计数）；提交内容存于 `Module/userfix/submissions/`（按用户名与时间戳组织，gitignore）

---

## 共享工具模块 (Module/common/)

### auth_utils.py - 认证工具

**主要函数**:
- `check_auth()` - 检查用户认证状态
- `require_auth()` - 要求认证的装饰器

**白名单路径**: `/user/login`, `/user/verify`, `/static`, `/favicon.ico`

### user_utils.py - 用户工具

**主要函数**:
- `load_users()` - 从 SQLite 加载用户数据（带 30 秒 TTL 缓存）
- `invalidate_users_cache()` - 使缓存立即失效（save_users 写库后自动调用）
- `save_users(users)` - 将用户字典整体写入 SQLite（全量替换）
- `get_user(username)` - 获取用户信息
- `verify_user(username, password)` - 验证用户登录凭据
- `load_activities()` - 从 SQLite 加载活动日志（最新在前）
- `save_activities(activities)` - 保存活动日志到 SQLite（全量替换）
- `add_activity(...)` - 添加活动记录到内存队列，后台线程每 10 秒批量写入 SQLite，仅保留最近 200 条
- `flush_activity_queue()` - 强制将队列写入 SQLite（服务器重启前调用）
- `parse_user_agent(user_agent_string)` - 解析 User-Agent 字符串

**parse_user_agent 功能**:
- 设备类型识别：Android、iOS、Windows、Mac、Linux
- 操作系统识别：Windows 10/11、Windows 7、Windows 8/8.1、macOS、Linux
- 浏览器识别：Chrome、Firefox、Safari、Edge、Opera、Internet Explorer

### db_utils.py - 数据库工具

**主要函数**:
- `get_connection()` - 获取线程安全的 SQLite 连接（单例，WAL 模式）
- `query(sql, params)` - 执行查询，返回 dict 列表
- `execute(sql, params)` - 执行写操作并提交，返回自增 id
- `executemany(sql, seq)` - 批量执行写操作
- `transaction()` - 事务上下文管理器（支持嵌套 SAVEPOINT，退出统一提交或回滚）
- `set_db_path(path)` / `reset_state()` - 测试隔离：切换临时数据库路径并重置单例状态
- `init_db()` - 建表并从 JSON 导入历史数据（仅空表时导入）
- `_rebuild_db()` - 数据库损坏时删除文件（含 -wal/-shm/-journal 伴随文件）并重建，从 JSON 恢复历史数据

**特点**: 高频可变数据（users/books/activity_log/active_sessions/favorites/ip_bans）存于 `Module/data/app.db`；数据库损坏自动重建

### file_utils.py - 文件工具

**主要函数**:
- `read_json_file(file_path, default=None)` - 线程安全地读取 JSON 文件
- `read_json_file_cached(file_path, default=None, ttl=5)` - 带 TTL 缓存的读取
- `write_json_file(file_path, data, ensure_ascii=False, indent=2)` - 线程安全地写入 JSON 文件（使用原子写入）

**特点**: 使用文件锁机制，防止并发读写冲突

### config_utils.py - 配置工具

**主要函数**:
- `load_config(ttl=5)` - 从 config.json 加载完整配置（基于 `read_json_file_cached`，TTL 缓存默认 5 秒）
- `get_config_value(key, default=None)` - 按点号分隔路径读取嵌套配置键（如 `paths.gallery_root_path`）
- `save_config(config)` - 保存配置到 config.json（ensure_ascii=False、indent=2）
- `backup_config()` - 备份 config.json 到 `Module/json/backups/`（文件名 `config_YYYYMMDD_HHMMSS.json`），自动清理仅保留最近 5 份，失败时通过 structlog 记录 `backup_config_failed`

### pagination.py - 分页工具

**主要函数**:
- `get_pagination_params(req=None)` - 从请求查询参数提取 `(page, per_page)`；非法值回退默认（page=1，per_page=20），per_page 上限 100
- `paginate_query(query_func, page, per_page, **kwargs)` - 通用分页包装器：计算 offset/limit 调用查询函数（约定返回 `(items, total)`），并组装分页元数据
- `format_pagination_meta(page, per_page, total)` - 返回 `{"page", "per_page", "total", "pages"}` 分页元数据字典

### response.py - 统一响应格式

**约定格式**: 所有 API JSON 响应遵循 `{"code": 0, "data": {...}, "msg": "..."}`

**主要成员**:
- `ErrorCode(IntEnum)` - 错误码枚举：SUCCESS=0、BAD_REQUEST=400、UNAUTHORIZED=401、FORBIDDEN=403、NOT_FOUND=404、INTERNAL_ERROR=500，以及模块特定码（ADMIN_CONFIG_ERROR=1001、GALLERY_SCAN_ERROR=2001、BOOK_NOT_FOUND=3001）
- `success_response(data=None, message, code)` - 成功响应（HTTP 200）
- `error_response(message, code, status_code=400)` - 错误响应
- `paginated_response(data, page, per_page, total)` - 分页响应（data 内含 items 与 pagination 元数据）

### security.py - 安全工具

**CSRF 保护（自研，不依赖 Flask-WTF）**:
- `generate_csrf_token()` - 生成或返回当前会话的 CSRF 令牌（`secrets.token_hex(32)`，存于 session）
- `validate_csrf_token()` - 校验请求中的令牌（读取 `X-CSRF-Token` 请求头或表单 `csrf_token` 字段，与 session 内令牌比对；仅从 session 读取，防止 cookie 投毒）
- `csrf_protect(f)` - 装饰器：对单个路由的 POST/PUT/DELETE/PATCH 启用 CSRF 验证
- `init_csrf_middleware(app)` - 全局 CSRF 中间件：对所有非安全方法的请求校验令牌，豁免路径 `/user/login`、`/user/verify`、`/setup`，验证失败返回 403

**安全响应头 `add_security_headers(response, production_mode=False)`**:
- Content-Security-Policy（default-src 'self'，允许内联 script/style，img 支持 data:/blob:，frame-ancestors 'self'）
- X-Content-Type-Options: nosniff
- X-Frame-Options: SAMEORIGIN
- X-XSS-Protection: 1; mode=block
- 生产模式附加 Strict-Transport-Security（max-age=31536000; includeSubDomains）

### paths.py - 路径常量

**常量**:
- `BASE_DIR` / `MODULE_DIR` / `DATA_DIR` / `JSON_DIR` / `TEMPLATES_DIR` / `STATIC_DIR` - 核心目录
- `CONFIG_FILE` / `SERVER_INFO_FILE` / `PREFERENCES_FILE` / `USERFIX_LIMITS_FILE` - JSON 配置文件
- `DB_FILE` - SQLite 数据库（`Module/data/app.db`）
- `USERFIX_SUBMISSIONS_DIR` - 用户提交内容目录（`Module/userfix/submissions/`）
- `BACKUPS_DIR` - 配置备份目录（`Module/json/backups/`）
