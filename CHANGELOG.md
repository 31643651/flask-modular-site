# CHANGELOG

本项目变更日志统一记录于此文件。

## [2026-11-21] 发布包剔除开发期工具与流程文档

### 变更
- `scripts/export_release.py` 排除清单增加 `session.py`（开发会话 CLI）与 `可复用开发流程标准与Python移植.md`（开发流程文档），发布包只保留运行所需源码、文档、测试与运维脚本
- 同步更新 `tests/test_export_release.py` 排除矩阵与 README 导出说明

### 测试
- 全量 `py -3.12 -m pytest tests/ -q` 0 failed；重新导出实测包内不再包含上述文件

## [2026-11-21] 文档优化、许可证与一键发布包导出

### 新增
- **README 重写**：功能矩阵、技术栈、快速开始、三种运行方式（前台/生产/start-quit-reload）、目录结构、数据与配置、测试、导出发布包、文档索引、许可证
- **`docs/README.md` 文档索引**：全部文档与常用脚本（导出/审计/性能/死按钮）一览
- **`scripts/export_release.py` 一键导出**：生成可发布 zip（`dist/`），自动剔除 `.git`/缓存/虚拟环境/数据库与 PID/日志/用户上传/壁纸/运行配置 `Module/json`/内部规划（`docs/superpowers`）/代理文档（`AGENTS.md`、`tasks*`）等；内置必需文件校验与禁入项安全扫描（命中即失败并删除产物）
- **`tests/test_export_release.py`**（31 条）：排除/包含规则矩阵、打包过滤、缺必需文件失败
- **许可证**：确认 `LICENSE` 为 MIT（Copyright (c) 2026 xuh7），README 增加许可证章节；`dist/` 加入 `.gitignore`

### 实测
- 导出：**200 个文件 / 源 1.37 MB → zip 0.46 MB**，禁入项扫描为空（无 config/db/log/cookies/内部文档）
- 全量 `py -3.12 -m pytest tests/ -q` 0 failed

## [2026-11-21] 暗夜模式全站文字适配

### 修复
- **画廊浏览页**：此前完全未应用暗夜类（无 `dark-mode` 初始化）且样式表无暗色规则 → 引入 `/static/common/ui.js` 应用主题类，并在 `gallery.css` 补暗色规则（标题/搜索框/按钮/面包屑/文件夹遮罩/发现区/侧栏及其下拉与输入）
- **收藏页**：有 `dark-mode` 类但 `favorites.css` 无任何暗色规则 → 补齐（标题/计数/搜索/面包屑/空状态/灯箱信息/对话框）
- **首页导航卡片**：深底深字（`#2c3e50` 于 `#565656` 上）→ 导航项文字改为浅色
- **管理员配置页**：路径输入框由 JS 写入内联白底深字 → 暗夜下以 `!important` 覆盖为深底浅字
- 新增 `static/common/dark-mode.css`（共享对话框暗色：面板/正文/取消按钮），9 个引用 `ui.js` 的模板统一引入
- 亮色模式零回归（全部新增规则限定 `body.dark-mode`）

### 测试
- 全量 `py -3.12 -m pytest tests/ -q` **573 passed / 0 failed**（画廊注入行锚点改为指向主脚本 `gallery-page.js`，意图不变）
- 浏览器逐页实测暗夜：`/gallery`、`/gallery/favorites`、首页、`/admin/config`、`/admin/users`（含对话框）、`/user/login`、`/book`、`/book/1`、404 错误页、ipguard 提示页——正文/标题/输入框/表格/对话框文字均随主题变化；切回亮色确认无回归

## [2026-11-21] 模块化重构：服务层落地、横切收敛、模板基座化（M1–M7）

### 变更（行为不变的结构重构，测试全程为锚）
- **books 收敛**：`books.py` 路由改调 `BooksService`（补 `get_chapters/get_chapter_content`），删除路由层重复的加载/搜索/缓存实现；搜索语义统一为 title/author/description
- **userfix 收敛**：`userfix.py` 路由改调 `UserfixService`；白名单 + magic-bytes + 大小校验、落盘复验、过期清理全部集中到服务层（路由只做前置编排）；userfix 管理后台的提交列表/状态更新/删除从 `AdminService` 迁入 `UserfixService`
- **横切设施收敛**：
  - 新增 `common/settings_utils.py`（功能开关/站点设置），5 个模块不再依赖 `AdminService` 读开关；
  - 新增 `common/net_utils.py`（真实 IP 单一实现）、`common/web_paths.py`（认证/CSRF/ipguard 三套路径常量单一来源）；
  - 配置读取统一走 `config_utils`（index/gallery/books 移除自带实现，index 保存前备份）；
  - **消除 `common ↔ core` 循环依赖**（审计脚本确认反向依赖=0、循环=0）
- **拆 AdminService**：认证中间件迁至 `common/auth_utils.register_auth_middleware`（不再由 service 注册 Flask 中间件）；userfix 管理迁出
- **模板基座化**：新增 `static/common/ui.js`（getCookie/getCsrfToken/showDialog/showAlert/showConfirm/confirmDialog/closeDialog + 暗夜引导），8 个模板删除重复实现改为引用；确认框「先捕获后关闭」时序锚点迁移到共享脚本（断言强度不变）
- **index 服务层**：新增 `core/index_service.py`（壁纸 URL/沙箱解析、按名寻址、挂载 MIME、HTML 站根引用改写、目录条目/面包屑），index 路由变薄
- 死代码清理：移除无路由的 `log_bp` 与 `get_log_files/get_log_content`、gallery 未使用缓存残留、未使用导入
- **新增模块化开发文档 `docs/modularity.md`**（分层/依赖规则、横切设施、服务/模板/测试规范、反模式、审计与变更流程）

### 测试
- 全量 `py -3.12 -m pytest tests/ -q` **573 passed / 0 failed**（570 基线 + 3 模板基座化锚定）
- `scripts/module_audit.py` 复跑：`common` 无反向依赖、无模块级循环依赖
- 浏览器回归：首页（入口/壁纸/反馈弹窗）、收藏页灯箱与对话框、`/admin/users` 对话框显示→回调→关闭、暗夜引导切换均正常，console 无报错

## [2026-11-21] 新增 nginx 风格后台运行命令（start / quit / reload）

### 新增
- `py -3.12 app.py start`：守护方式后台启动（生产模式、无 reloader），命令立即返回；PID 写入 `Module/data/app.pid`，stdout/stderr 追加到 `Module/log/server-stdout.log`
- `py -3.12 app.py reload`：停止旧进程并按当前代码重启，立即返回
- `py -3.12 app.py quit`：停止后台服务并清理 PID 文件，立即返回
- 重复 `start` 提示已在运行（退出码 1）；启动失败（如端口占用）打印日志路径并返回非 0；`quit` 在未运行时提示"服务未运行"
- 兼容保留：`py app.py`（前台开发模式）与 `py app.py --production`（前台生产）行为不变；新增 `Module/data/*.pid` gitignore
- 实现：Windows 用 `DETACHED_PROCESS` 脱离控制台 + `tasklist` 判存活 + `taskkill /T /F` 停止（避免 `os.kill(pid,0)` 在 Windows 误杀进程）

### 测试
- 新增 `tests/test_cli_commands.py`（9 条：三条命令分派、前台兼容、PID 文件读写、未运行 quit）
- 端到端实测：`start` → 服务可访问且 PID 文件写入 → 重复 `start` 拒绝 → `reload` 换新 PID 且服务恢复 → `quit` 后端口释放、PID 文件删除
- 全量 `py -3.12 -m pytest tests/ -q` **570 passed / 0 failed**

## [2026-11-21] 修复画廊「发现图片大小」滑块改动不保存

### 修复
- **正方形模式的尺寸滑块（`discoverSizeRange`）漏保存**：其 `input` 处理器此前只写 localStorage 与应用样式，未调用 `updateAndSavePreferences`——拖动滑块改尺寸后刷新即回默认值。现与数字输入框一致保存到用户偏好（写入 `users.<username>.discover_size`）
- 端到端验证：滑块改 260 → 偏好文件写入 `{width:260,height:260}` → 刷新后输入框/滑块回显 260、网格项实际 260×260
- 排查确认：登录态下保存/读回链路（POST `/gallery/api/preferences` → `users[username]` → 注入 `serverPreferences`）本身正常；未登录时修改仍只存本浏览器（接口 401）

### 测试
- 新增 `tests/test_gallery_prefs_save.py`（4 条锚定：正方形滑块/数字框、矩形宽/高滑块均必须调用保存）
- 全量 `py -3.12 -m pytest tests/ -q` **561 passed / 0 failed**

## [2026-11-21] 修复画廊发现区加载前后的布局跳动

### 修复
- **发现区在图片渲染完成后才显示**：此前先显示含「加载中…」的空区块、图片返回后再撑开网格，造成页面高度与网格形态变化
- **布局参数提前应用**：列数/尺寸/圆角在插入图片前先在空网格上应用（通过 `discover:images-rendered` 事件在持有设置的闭包内执行），插入后再应用到新条目；改用 `DocumentFragment` 一次性插入，首次绘制即为最终形态
- 修复 `loadRandomImages` 直接调用 `applyDiscoverFormat/Size` 的跨闭包 ReferenceError（此前会被 catch 成「加载失败」）
- 偏好缺少 `discover_enabled` 键时回退 localStorage（此前整块跳过导致区块不出现）；偏好接口失败时仍按本地开关加载

### 测试
- `tests/test_perf_home.py` 新增 3 条布局稳定性锚定（渲染后才显示 / 插入前先应用布局 / 偏好应用不再提前显示）
- 全量 `py -3.12 -m pytest tests/ -q` **557 passed / 0 failed**（554 基线 + 3 新增）
- 浏览器实测：发现区可见时已含 32 项、10 列 150×150、`object-fit: cover`、圆角 8px，无「加载中」残留

## [2026-11-21] 全站加载性能优化：HTTP 缓存 + 首页服务端渲染 + 发现区限量缓存（ADR-0011 / ADR-0012）

### 变更
- **HTTP 缓存策略（ADR-0011）**：HTML 页面 `no-store`；版本化静态资源（`static_url` 附加 `?v=mtime`）`max-age=31536000, immutable`；其它 `/static/` 1 小时；图片 1 天（含画廊/反馈/壁纸）；去掉静态/图片上的 `Vary: Cookie` 以便命中
- **画廊扫描加速**：目录 mtime 校验 2 秒短 TTL（避免每次全树 stat）、子目录计数/封面/递归列表 5 分钟 TTL、服务启动后台预热扫描缓存
- **首页服务端渲染（ADR-0012）**：挂载页面入口与壁纸 URL 随 HTML 输出，页面到达即可见（不再依赖 `/api/mounted-pages`、`/api/wallpaper/config` 前端 fetch）；首屏壁纸优先选取体积最小的文件并 `preload`
- **壁纸缓存化**：`/static/wallpaper` 支持 `?img=<文件名>`（非法名 404），前端不再拼 `?t=Date.now()` 强制下载，同一壁纸命中浏览器缓存
- **发现区限量缓存**：`/gallery/api/random-images` 结果缓存 300 秒 + 最多 8 个文件夹（≤36 张，原 488 张/1426ms）
- 新增开发工具：`scripts/perf_baseline.py`（性能基线探测）、`scripts/clear_ip_ban.py`（清理测试封禁）

### 测试
- 新增 `tests/test_perf_cache.py`（8 用例：缓存头矩阵/版本化 URL/图片缓存）与 `tests/test_perf_home.py`（5 用例：服务端渲染入口与壁纸、按名寻址、发现限量缓存）
- 全量 `py -3.12 -m pytest tests/ -q` **554 passed / 0 failed**（541 基线 + 13 新增）
- 实测：`/gallery` 服务端 155ms → 24-31ms；`random-images` 1426ms → 15.7ms；HTML 页面 15-30ms；壁纸二次加载 0 字节；挂载入口/背景随 HTML 立即出现

### 决策
- ADR-0011：页面与静态资源缓存策略及画廊渲染加速
- ADR-0012：首页服务端渲染与发现区限量缓存

## [2026-11-21] 统一错误页：404/403/500 页面分流（T6, ADR-0010）

### 修复
- **页面导航不再暴露裸 JSON 错误**：挂载目标缺失（如 `/rrr`）、不存在的 URL、无权访问、服务器错误在浏览器整页导航时渲染统一中文错误页（新建 `Module/templates/errors/error.html`：沿用 ipguard 提示页卡片视觉、适配暗夜模式、**纯提示无按钮**、不含任何技术细节）
- **页面/API 分流**：`/api/` 路径、非 GET/HEAD 方法、`Accept` 不含 `text/html` 的请求仍返回 JSON `{"error", "code"}`（404/500 文案与现状逐字一致，新增 403 同形态）——前端 fetch 契约零变化
- **新增 403 全局 handler**：此前无 handler，页面直接暴露 Werkzeug 英文 Forbidden

### 测试
- 新增 `tests/test_error_pages.py`（13 用例：三状态码 × 页面/API 矩阵、纯提示无按钮、暗夜模式适配、无技术泄露、响应式 viewport）
- `tests/test_integration.py` 原 404 JSON 用例拆为「API 仍 JSON」+「页面返回 HTML 错误页」两条（ADR-0010 授权，断言强度不降）
- 全量 `py -3.12 -m pytest tests/ -q` **541 passed / 0 failed**（528 基线 + 13 新增）
- 浏览器实测：`/rrr` 显示错误页；`/api/*` 404 仍为 JSON；暗夜模式切换生效

### 决策
- ADR-0010：统一错误页：404/403/500 页面分流与 API JSON 保持

## [2026-11-21] 修复 Windows 下 127.0.0.1 无法访问（仅 localhost 可用）

### 修复
- **监听地址平台化**：`app.py` 原写死 `host="::"` 并注释"同时支持IPv4"——该假设在 Windows 不成立（`IPV6_V6ONLY` 平台默认为 1，`::` 只收 IPv6）：`localhost` 解析到 `::1` 可访问，`127.0.0.1` 等 IPv4 地址连接被拒。现 **Windows 绑 `0.0.0.0`（IPv4 全接口，`127.0.0.1`/`localhost` 均可访问），Linux/macOS 保持 `::` 双栈监听**（行为不变）
- **诊断/验收脚本** `scripts/check_local_access.py`：双入口 TCP 探测 + 平台 `IPV6_V6ONLY` 证据输出；修复前 FAIL（127 拒绝、localhost 走 ::1），修复后 PASS（localhost 经 IPv4 回退）
- 验证：浏览器实测 `http://127.0.0.1:20999` 与 `http://localhost:20999` 均正常；reloader 重启后监听稳定

### 测试
- 全量 `py -3.12 -m pytest tests/ -q` **528 passed / 0 failed**（本修复只改启动监听地址，不触业务代码）

## [2026-11-21] 画廊模块重写：模板去重与静态资源提取（T5, ADR-0009）

### 变更（行为不变的结构重写）
- **删除零引用死副本**：`gallery/gallery.html`（2442 行，与 index.html 重复率 >99%、无路由/测试引用）移入 `待处理文件/gallery.html` 存档（含工作区滑动原地换图改动），不再参与运行
- **静态资源提取**：`index.html` 的 895 行内联 CSS → `/static/gallery/css/gallery.css`；1300 行内联 JS → `/static/gallery/js/gallery-page.js`（单个 `DOMContentLoaded` 闭包整块搬运，注入三行 `serverPreferences/serverDeviceSpecific/csrfToken` 仍内联且先于 src 脚本）；`favorites.html` CSS → `/static/gallery/css/favorites.css`
- **灯箱 markup 参数化 include**：两页共用 `_lightbox.html`（`lightbox_favorite_title` 区分收藏/取消收藏）
- **路由层去重**：三 blueprint 逐字相同的 `gallery_enabled` before_request → `Module/gallery/guards.py` 单一实现；`sanitize_path`/`_resolve_subdir` 下沉 `Module/core/gallery_service.py`
- **滑动原地换图改动入库**：innerWidth 基准、直接换 `src`、手动推进 `_discoverCurrentIndex`、手动更新文件名、手动 `checkFavoriteStatus`、对侧滑入序列——6 点语义原样保留并由锚定测试锁定
- 资产走全局 `/static/` 前缀（ipguard 白名单内，不改 middleware）；`favorites` JS 保留内联（`confirmDialog` 时序被模板源码测试锚定）

### 测试
- 新增 `tests/test_gallery_rewrite_anchors.py`（14 用例：三蓝图 guard 矩阵、CSS/JS 资产可达、注入行在外部脚本之前、滑动 6 点语义、favorites CSS 外置与灯箱 include）
- 两份 gallery golden 与全部既有画廊测试断言**零改动**；全量 `py -3.12 -m pytest tests/ -q` **528 passed / 0 failed**（514 基线 + 14 新增）
- 浏览器回归：画廊浏览/发现图片加载/灯箱环形导航/收藏页灯箱与收藏增删/静态资产 200/console 零报错

### 决策
- ADR-0009：画廊模块模板去重与静态资源提取

## [2026-11-21] 反馈上传图片安全加固（T4, ADR-0008）

### 修复
- **非白名单扩展被静默改名而非拒绝**：上传扩展不在白名单（`.jpg/.jpeg/.png/.gif/.webp/.bmp`）的文件原先被改名存为 `.jpg` 继续保存；现改为**直接拒绝**，扩展判定不区分大小写，空文件名表单 part 跳过不计数
- **新增 magic-bytes 内容校验**：按扩展断言真实文件头（PNG/GIF/BMP/JPEG/WebP RIFF+WEBP 双段）；SVG/HTML/脚本顶着白名单扩展一律拒绝（探针实测的 479717 字节 SVG→`.jpg` 场景闭环）
- **校验时点**：白名单 + magic + 大小校验全部**前置到配额扣减之前**（userfix 契约 #1：校验失败不扣配额），`save_submission` 建目录写盘前复验，失败无文件系统副作用
- **`serve_image` 显式 MIME + 白名单 404 + 内容复验**：按固定映射显式传 `mimetype` 不再依赖 `mimetypes` 猜；非白名单扩展 404；文件头与扩展名不符（历史被改名的脏文件）404——服务层独立闭环，`nosniff` 纵深保留

### 测试
- 新增 `tests/test_userfix_upload_security.py`（17 用例：白名单拒绝不扣配额、magic 拒绝不扣配额、serve 显式 MIME 六格式参数化、非白名单 404、脏内容 404）
- `tests/test_userfix_submit_quota.py::test_image_at_size_limit_passes` 测试数据由全零改为真实 PNG 头 + 长度断言不变（数据适配新校验，断言强度不降）
- 全量 `py -3.12 -m pytest tests/ -q` **514 passed / 0 failed**（497 基线 + 17 新增）

### 决策
- ADR-0008：反馈上传图片安全加固：非白名单拒绝、magic-bytes 校验与显式 MIME

## [2026-11-21] UID 分区模型、超管启动迁移强化与手动指定 UID（T3, ADR-0007）

### 行为变更
- **超级管理员建模为 UID 分区**：`id 0-9` 即超级管理员（维持 `role='admin'` + id 区间组合判定，不新增 role 值，`is_superadmin` 为启动期同步的派生标记）；`10` 系统保留（禁手动/禁自动）；`11-99` 可放非超管身份（`role='admin'` 仅能落此段）；`100-1000` 仅非管理员身份（可手动、自动分配保留不取）；`1001+` 仅非管理员身份（自动新建起点）
- **启动迁移强化（`_migrate_superadmin`，幂等权威校正）**：`0-9` 一律提权 `role='admin'` + `is_superadmin=1` + `enabled=1`（提权+强制启用）；`id>9 且 is_superadmin=1` 的越界超管一律清退 `enabled=0/is_superadmin=0`（防御带外改库造成的双源角色冲突，根治历史 302 场景源头）
- **兜底对齐（`ensure_admin_exists`）**：保证「始终保留的 admin」永远落在 `0-9` 最小空位——admin 行/被提权的最老用户若 `id>9` 则重定位其行到 0-9 空位，表空创建也落 0-9，与越界清退规则自洽（ADR-0003 + ADR-0007）
- **待遇收窄到仅超管**：登录 16 位动态验证码与反馈提交不限次，判定由 `role=='admin'` 收窄为 `is_superadmin`（uid 0-9）。普通管理员（11-99）自此登录免动态验证、反馈受每日 3 次限制，等同普通用户
- **保护收窄**：「不能禁用/删除管理员」收窄为「不能禁用/删除超级管理员」——超管可管理普通管理员（11-99）与普通用户，仅不可动其他 0-9 超管与自身
- **手动指定 UID + 落段校验**：`register_user(username, password, role, uid=None)`；`0-10` 保留区拒绝、admin 仅 `11-99`、非 admin `≥11`、占用拒绝、新建用户 `is_superadmin` 恒 0；未指定时 admin 从 `11` 起、其余从 `1001` 起自动分配；注册表单新增可选 UID 输入框（后端为权威，前端仅体验预检），角色下拉维持 3 项

### 测试
- 新增 `tests/test_uid_partition.py`（30 用例：启动迁移 R1/R2/幂等、兜底 0-9 重定位、注册落段矩阵与手动 UID、待遇收窄、保护收窄、前端表单）；`tests/test_ensure_admin.py` 提权断言按 ADR-0007 适配（重定位到 0-9，断言强度不降）
- 全量 `py -3.12 -m pytest tests/ -q` **497 passed / 0 failed**（467 基线 + 30 新增）

### 决策
- ADR-0007：UID分区模型与超管启动迁移强化
- 设计规格 `docs/superpowers/specs/2026-11-20-uid-partition-superadmin-design.md`、实施计划 `docs/superpowers/plans/2026-11-20-uid-partition-superadmin.md`
- 只读调查脚本 `scripts/probe_userfix_image_ct.py`、`scripts/dump_users_uid.py` 随规格入库

## [2026-11-20] 确认框死按钮、挂载删除失效与写入侧路径校验恢复（T2）

### 修复
- **全站确认框死按钮（日志清除断链 / 挂载删除失效 / 用户删除、禁用、重启服务器、解除封禁、反馈处理等全部确认类操作无响应的共同根因）**：8 个模板的 `confirmDialog()` 均先调 `closeDialog()`（把 `dialogCallback` 置 null）随后才判断回调，导致点"确定"永不执行；改为先用局部变量捕获回调、再关闭对话框、最后触发（ADR-0006）
- **挂载页面删除失效**：`remove_mounted_page` 恢复"页面不存在"判定，对不存在的名称不再恒返回成功
- **挂载/配置写入侧路径校验恢复（模块化重构 `f79b372` 拆分 `admin.py` 时丢失）**：`add_mounted_page` 恢复名称格式（ASCII 字母/数字/下划线/短横线）、路径存在性、系统敏感路径白名单（`SENSITIVE_PATHS`，a4713d4 H13）、文件必须 HTML、数量上限 20、重名拒绝；`update_config` 恢复顶层键白名单、`paths` 空值/类型/存在性校验（aff91cf S4 + dcdcdc9 M39），并由裸 `current.update()` 改为逐子键合并（未提交的既有键不再被整体覆盖）（ADR-0006）
- **配置保存联动**：`config.html` `saveConfig()` 对被开关禁用的路径输入框改为"不提交该键"（原先提交空串会被恢复后的空值校验整单拒绝），禁用功能后仍可保存配置
- 注：`index.py` 服务端挂载路径白名单（be033be H1）经核查仍在，未丢失

### 新增
- `scripts/audit_dead_buttons.py`：全站死按钮审计（onclick 引用未定义函数 + confirmDialog 时序），22 个模板通过
- `tests/test_confirm_dialog_templates.py`（8 模板回调时序锚定）、`tests/test_admin_write_validation.py`（写入侧校验 + 路由失败响应口径 + saveConfig 禁用键）

### 决策
- ADR-0006：确认框回调时序修复与挂载/配置路径校验恢复

### 测试
- 全量 467 passed / 0 failed（421 基线 + 46 新增）；既有挂载测试数据由不存在的 `D:/test/page.html` 适配为真实路径 `sdinspector/index.html`（断言强度不变，仅测试数据适配新校验）

## [2026-11-20] 302 循环治理、admin 常驻、登录实时读库（T1）

### 修复
- **302 死亡循环（/user/login ⇄ /user/verify 二元环，3 条入环路径）**：`user.py` verify 页角色判定由登录时写入且永不失效的 `session["role"]` 改为 DB 单一权威源（与 login/`auth_utils`/`require_superadmin` 同源），外部提权会话不再互跳；附带修掉 verify 页对已禁用管理员仍渲染的缺陷（ADR-0004）
- **302 硬限制**：新增 `init_redirect_circuit_breaker` 服务端熔断——同一会话 **2 秒窗口内第 4 个重定向 → 508 Loop Detected**（移除 Location + 结构化告警日志），非重定向响应清零窗口；替代原先"靠 ipguard 滑窗把循环用户永久封禁"的伤害性刹车（ADR-0004）
- **setup 豁免收紧**：`app.py` `startswith("/setup")` → 精确匹配 `/setup` 或 `/setup/`，`/setupfoo` 类挂载路径不再被误豁免
- **登录必须重启才能生效**：`verify_user` 改为登录时直读 SQLite（绕过 30s TTL 缓存），带外手工 `INSERT/UPDATE users` 立即可登录，无需等待过期、无需重启；高频读路径的 30s 缓存保持不变（ADR-0005）
- **始终保持一个 admin**：启动期 `ensure_admin_exists()` 三情形兜底——admin 行被降级/禁用→恢复（密码保留）；缺 admin 行且无可用超管→提权 id 最小用户（登录方式不变）；users 表空→创建 admin（随机密码打启动日志）；首次部署（config 缺失）跳过，交由 setup 向导（ADR-0003）

### 测试
- 新增 `tests/test_auth_redirect_loop.py`（双源环 ×3、508 熔断、窗口复位守卫）、`tests/test_login_realtime.py`（带外插库即时登录）、`tests/test_ensure_admin.py`（常驻四情形）、`test_setup` 补豁免收紧回归；全量 421 passed / 0 failed

## [2026-11-19] 仓库未跟踪文件清零

### 归档
- **入库从未被跟踪的两项内容**：①`可复用开发流程标准与Python移植.md`（`session.py` 第 4 行引用的只读规格，从未入过库）；②`待处理文件/`（`itools-dist` 挂载测试夹具 4 文件 + 5 个历史一次性调试脚本 + 1 个 pytest 结果输出，共约 1.1MB）。此后每次提交保持 `git status --short` 无 `??` 未跟踪项

## [2026-11-16] 挂载纯前端站优化（SPA-ready mounting）

### 修复
- **挂载纯前端构建产物无法加载 css/js**：三个根因逐一修复——①目录挂载根与含 index.html 的子目录在无尾斜杠访问时 302 重定向到带尾斜杠路径（子目录重定向为本计划新增，根级为既有行为锚定）；②静态资源显式 MIME 表（19 后缀，`.js/.mjs→text/javascript` 等），消除 Windows 注册表猜测导致的 module script 拒载；③挂载 HTML 中站根绝对引用（`src="/..."`/`href="/..."`）重写为挂载前缀路径，`base:'/'` 构建产物（it-tools 型）可挂载
- **sdinspector 挂载路径修正**：config.json 中 `Module/sdinspector` → `sdinspector`（数据断裂导致整页 404）；上游构建产物布局脱节已复制补齐（static/ 前缀引用 vs 根目录文件）

### 新增
- `scripts/verify_mounted_spa.py`：真实构建包冒烟验证脚本（抓取 it-tools 部署资产 + 本地 sdinspector 真包，六断言含 MIME 与重写校验）
- `tests/test_mounted_page_serving.py`：挂载服务行为锚定 17 用例（重定向/MIME/重写/穿越拒绝/认证）

### 决策
- ADR-0002：挂载纯前端站优化（尾斜杠重定向 + MIME 表 + 保守 HTML 重写；放弃 `<base>` 注入；运行时动态 fetch 与 history 路由深链接为备案限制）
- 兼容范围：Vite `base:'./'`（相对引用）与 Vite `base:'/'`（绝对引用）构建产物可挂载；excalidraw 型运行时拼绝对路径取资源的站点不在服务端兼容范围

## [2026-11-13] 28 项 bug 修复与流程标准移植

### 修复
按子代理深度排查（28 项发现，逐项审查修复），修复要点：

**阻断级（功能完全失效）**
- **auth 白名单平台无关化**：`check_auth` 移除 `normpath` 依赖（经核实原实现在 Windows 下可正常匹配，本次为加固）
- **activity.html 补全被截断的 script 与文档尾部**：页面 JS 恢复执行（截断自文件创建即存在）
- **users.html 跨 script 块引用修复**：管理员注册新用户功能恢复，暗夜模式恢复
- **统一密码哈希校验**：`verify_user` 支持 pbkdf2/scrypt 哈希 + 存量明文登录时自动迁移；setup 初始管理员改存哈希（此前 admin 注册的用户无法登录）
- **壁纸开关补 X-CSRF-Token 头**：壁纸配置保存不再恒 403

**前后端连接**
- **活动日志恢复分组折叠与用户筛选**：后端实现 grouped/username 参数与分组响应结构（默认最近 200 条），启用 activity_all.html 死模板，修复前后端参数脱节
- **画廊偏好保存结构对齐**：兼容 `{preferences:...}` 包裹形态，服务端渲染带已存偏好（此前保存后永远回到默认值）
- **搜索结果文件夹补 cover/count 字段**：不再显示 "undefined 张图片"
- **书籍搜索翻页 urlencode + 封面子目录路由**：含特殊字符关键词翻页正常、子目录封面可显示
- **挂载页面 API 响应与列表字段对齐**：添加后跳转提示生效、类型列显示正确
- **CSRF 保留键名修正 + 收藏 API 错误状态码统一**（401/400）

**安全**
- **userfix 提交 ID 路径穿越校验**：黑名单 + resolve/relative_to 双保险（rmtree/写文件不再可达任意路径）
- **userfix 配额扣减时序**：校验失败（含图片超限）不再扣减每日 3 次配额
- **画廊 browse/folder_images 目录穿越加固**：绝对路径/盘符/`..` 段三层拒绝 + relative_to 兜底
- **壁纸配置仅超级管理员可改** + enabled 强转；HTTPException 透传（403 不再被吞成 404）

**基础设施**
- file_utils 写文件异常路径 NameError 消除、裸 except 收窄
- Windows 服务器重启改 Popen + os._exit 硬终止（原 os.execv 与 sys.exit 方案在 threaded 服务器下不可靠）
- 活动日志清理不再误删异常时间记录（parse_time 失败保留）
- db_utils 损坏重建递归短路（query/execute/executemany 全覆盖）
- userfix metadata 迁移 file_utils 线程安全读写；画廊偏好/收藏读改写加互斥锁

### 新增
- **流程标准移植（6 件套）**：`session.py` 会话与任务生命周期 CLI（start/step/finish/verify/new-adr，串行 pytest 门禁）、`tasks.json` 任务账本、`docs/adr/` 决策档案、`docs/specs/` 8 模块意图规格 + history、`tests/contracts/` 前后端契约测试 + 5 个 goldens、AGENTS.md 增补必读映射表与测试红线六条
- ipguard 未知 UA 限流策略经评审确认保持现状（防护取向决策）

### 收尾审查修复
- **setup 向导不再在 session 存明文密码**：步骤 1 即存 werkzeug 哈希，步骤 2 以哈希直接入库；补"密码不能为空"校验
- **挂载页面列表对旧格式记录回退推断类型**：缺 `type` 键的旧记录按 `is_file` 推断（缺省 file），仅作用于返回值不落盘，前端类型列不再误判
- **壁纸 GET 接口不回显原始路径**：壁纸开关关闭时 path 置空；三处异常分支改通用错误文案（详情进日志）；决策记录见 ADR-0001
- **admin spec 活动日志分组结构描述勘误**：改为与实现/golden 一致的顶层 `activities[]` 分组形态（含聚合键说明）

## [2026-11-11] 文档标准化与依赖清理

### 新增
- **新增 MIT LICENSE**：项目添加 MIT 许可证文件

### 变更
- **requirements.txt 移除未使用的 Flask-WTF 依赖**：表单/CSRF 处理实际由自研 `security.py` 承担，文档技术栈同步移除该依赖
- **cookies.txt 移出版本跟踪并加入 .gitignore**：登录态 Cookie 等敏感文件不再纳入版本控制

### 文档
- **AGENTS.md / README.md / docs/architecture.md / docs/data-storage.md / docs/standards.md 全量对齐当前代码**：
  - 补充 `Module/setup`（初始配置向导 `/setup`，首个注册蓝图）与 `Module/ipguard`（两级 IP 限流与封禁管理）模块说明
  - 管理后台更新为 7 蓝图拆分结构，补充 `/admin/ip` 封禁 IP 管理与 `/admin/setting` 设置页；画廊、用户修复模块的多蓝图拆分同步列出
  - SD Inspector 描述修正为根目录静态站挂载（gitignore，经页面挂载机制服务），不再注册蓝图
  - 共享工具章节补全 config_utils / pagination / response / security（自研 CSRF）说明
  - 数据存储规范补充 `Module/json/backups` 备份目录、SQLite `ip_bans` 表与 WAL 伴随文件说明
  - 项目结构树补充 tests/、docs/、pytest.ini、requirements-dev.txt、LICENSE 等条目

## [2026-08-22] 画廊灯箱和收藏修复

### 修复
- **修复画廊收藏功能**：前端参数名与后端API不匹配（image_path → path），解决收藏按钮点击后无反应的问题
- **修复画廊CSRF验证失败**：Gallery路由未传递CSRF token给模板，导致收藏操作返回403错误；现在通过模板变量传递CSRF token
- **修复画廊收藏路径提取**：简化路径提取逻辑，统一使用extractImagePath函数处理URL，解决路径为空导致收藏失败的问题
- **修复画廊模板不一致**：实际使用的模板是index.html而非gallery.html，将所有修复同步到正确的模板文件
- **修复收藏页面空白**：favorites_page路由未传递收藏数据给模板；现在从数据库加载收藏列表，将绝对路径转为相对路径，构建正确的图片URL
- **修复手机端灯箱图片显示**：移除灯箱图片容器的内边距，让图片最大化显示，消除左右空余
- **隐藏手机端灯箱导航按钮**：在手机端隐藏过大的左右导航按钮，改为滑动操作
- **添加手机端灯箱滑动切换**：新增单指左右滑动切换图片功能，预加载下一张图片后滑动切换，无闪烁
- **修复收藏后页面强制刷新**：移除toggleFavorite中强制刷新页面的逻辑，收藏状态通过心形按钮的active类即时更新
- **优化取消收藏交互**：移除收藏页面取消收藏时的确认弹窗，点击后直接取消并显示角落淡入淡出提示，不退出灯箱
- **修复收藏/取消收藏路径匹配**：统一使用 `_service.db` 操作数据库，路径规范化为正斜杠；移除所有强制刷新和不必要的DOM操作；收藏页面支持收藏/取消收藏切换

## [2026-08-15] Bug修复 - 安全和功能修复

### 修复
- **恢复画廊发现功能原始设计**：从每个子文件夹中随机选择4张图片，确保发现页面的图片来自不同文件夹，提供更加多样化的浏览体验
- **优化画廊图片预加载**：增大IntersectionObserver预加载范围从2500px到5000px，发现功能前8张图片使用eager loading，解决快速滑动时图片来不及渲染的问题
- **修复初始化302重定向循环**：在 `auth_utils.py` 白名单中添加 `/setup` 路径，解决首次访问时 setup 和 login 之间无限重定向的问题
- **修复CSRF验证绕过**：移除 `security.py` 中从 cookie 读取 CSRF token 的回退，仅从 session 读取，防止 cookie 投毒绕过
- **统一CSRF实现**：将 `user.py` 中的CSRF实现统一为使用 `security.py` 的全局实现，消除两套独立CSRF系统互相干扰
- **修复register_user缺少id字段**：为新用户分配递增id，解决管理后台创建用户时的KeyError崩溃
- **修复画廊搜索功能**：修改搜索API返回正确的数据结构 `{results: {folders, images}}`，匹配前端期望格式
- **修复画廊子文件夹图片数量统计**：使用递归计数替换非递归计数，正确显示嵌套文件夹中的图片数量
- **修复管理后台配置保存**：前端去掉多余的 `{ config: config }` 包装，解决配置保存后刷新仍为原值的问题
- **清理config.json中的嵌套config键**：移除已污染的嵌套config键，恢复正确的配置结构
- **统一登录限速实现**：删除 `user.py` 中的重复限速代码，统一使用 `UserService`
- **修复挂载页面路径校验**：添加URL编码的 `..` 检查，防止路径遍历攻击
- **修复画廊路径清理**：使用 `urllib.parse.unquote` 解码URL编码路径，移除不安全的字符串替换
- **修复收藏操作并发问题**：使用SQLite事务的INSERT/DELETE替代全量替换，防止并发操作丢失数据
- **修复活动日志时间比较**：使用 `datetime.strptime` 进行日期比较，替代字符串比较
- **统一路径常量**：`books.py` 使用 `Module/common/paths.py` 中的常量，消除路径定义分散
- **修复CSP策略**：移除 `unsafe-eval`，保留 `unsafe-inline`（因项目大量使用内联事件处理器）
- **修复管理后台重启路由CSRF保护**：添加显式的 `@csrf_protect` 装饰器

## [2026-08-10] ipguard 访问控制模块

### 新增
- 新增 `Module/ipguard` 模块：两级 IP 访问频率限制
  - 第一防线：未登录高强度访问 /user/login，或 UA 为 Other 时，按 IP 封禁（递进：5分钟/1小时/24小时/永久）
  - 第二防线：普通用户同一页面 1 分钟超 10 次触发，三重机制：1 分钟限速提示 / 2 分钟封禁 / 永久封禁并禁用账户
  - 超级管理员不受任何限制
- 新增 SQLite `ip_bans` 表存储封禁信息（重启不丢失）
- 新增封禁提示页 `banned.html` 与限速提示页 `rate_limited.html`
- 新增管理后台 `/admin/ip` 封禁 IP 列表与解除封禁接口
- 管理后台仪表盘新增「封禁 IP」卡片，最近活动卡片改为半宽

### 说明
- 频率统计基于内存滑动窗口，不依赖外部服务
- 客户端 IP 优先读取 X-Forwarded-For，回退 remote_addr

### 修复
- 修复管理后台封禁 IP 页面的存储型 XSS：`b.ip` 来自可伪造的代理头，不再拼入 `onclick` JS 字符串，改为 `data-ip` 属性 + `this.dataset.ip` 读取（`ip.html`、`dashboard.html`）
- 修复 `get_client_ip` 无条件信任 `X-Forwarded-For`：仅当 `TRUST_PROXY_HEADERS=1`（可信反向代理部署）时才读取代理头，语义对齐 `AdminService.get_real_ip`，默认回退 `request.remote_addr`
- 修复仪表盘「重启服务器」fetch 缺失 CSRF token 被全局中间件 403 拒绝，管理员看到的重启实际未生效
- 修复 `_write_ban` 检查后写入的 TOCTOU 竞态：改用单条 UPSERT（`ON CONFLICT(ip) DO UPDATE`），并发首触同一 IP 不再因双 INSERT 抛 `IntegrityError` 导致封禁不落库
- 补第二防线升级路径（第2次触发封禁 2 分钟、第3次触发永久封禁并禁用账户）集成测试，以及 XFF 信任门控、UPSERT 幂等与并发竞态测试

## 2026-08-10

### 移除所有速率限制

- 移除 `app.py` 中的全局速率限制器（120 req/min）
- 移除 `Module/user/user.py` 中的登录限流（5/min）
- 移除 `Module/userfix/userfix.py` 中的提交限流（3/hour）
- 从 `requirements.txt` 中移除 `flask-limiter` 依赖
- 所有路由现为无限制状态

### 修复 gallery 429 TOO MANY REQUESTS 问题

- 为 gallery 模块添加限流豁免，避免加载多张图片时触发 429 错误
- 修改 `app.py`，为 `gallery_bp` 添加 `limiter.exempt()`
- **注意：此修复已随速率限制的完全移除而变得无关紧要**

### 修复 admin/config 功能关闭显示问题

- 修改 `config.html` 中的 `togglePathInput` 函数，移除"功能已关闭"占位符
- 功能关闭时现在只是单纯变灰，与"挂载静态页面"部分保持一致

### 修复 admin/setting 保存失败问题

- 修改 `setting.html` 中的 `getCsrfToken` 函数，使用 `{{ csrf_token }}` 从模板变量中获取 token
- 修复 CSRF token 验证失败导致保存设置时出现"未知错误"的问题

### 修复浏览器对话窗口问题

- 在所有 admin 页面（userfix.html、config.html、activity.html、activity_all.html、users.html、dashboard.html）中添加自定义对话框
- 替换浏览器原生的 `alert()` 和 `confirm()` 对话窗口为符合 UI 风格的自定义对话框
- 在首页 `index.html` 和画廊收藏页 `favorites.html` 中也添加自定义对话框
- 清理 `users.html`、`activity.html`、`activity_all.html` 中的重复函数定义（死代码）

### 修复 admin/userfix UI 规范问题

- 更新 `userfix.html` 的 CSS 样式，使其与其他 admin 页面保持一致
- 统一卡片、筛选按钮、分页等组件的样式

### 修复活动日志清理功能

- 在 `routes_activity.py` 中添加 `POST /admin/activity/api/cleanup` 路由
- 修复前端调用清理接口时返回 404 的问题
- 在 `activity.html` 和 `activity_all.html` 中添加 CSRF token 请求头

## 2026-08-09

### 初始配置界面

- 新增初始配置模块 (`Module/setup/`)，引导用户完成首次配置
- 当 `config.json` 不存在时，自动跳转到初始配置页面
- 支持两步配置流程：
  - 步骤1：创建管理员账户（密码 + 管理员二次验证开关）
  - 步骤2：设置服务器名称
- 初始配置完成后自动创建管理员用户并生成配置文件
- 在 `app.py` 中添加 `check_initial_setup` 中间件，确保未完成配置时强制跳转

## 2026-08-08

### M38: 模块化重构完成

- 完成三层架构重构：路由层 → 核心服务层 → 共享工具层
- 新增 `Module/core/` 目录，包含各模块的业务逻辑服务
- 扩展 `Module/common/` 工具模块，新增分页、路径、响应、安全等工具
- 从 websever 文件夹合并模块化重构代码
- 重构后架构更清晰，便于测试和维护

### M39: config.json 迁移到 settings 结构，AdminService 新增 settings 方法

- 将 config.json 迁移到 settings 结构，支持更灵活的配置管理
- AdminService 新增 settings 方法，提供统一的配置访问接口

### feat: add admin setting page route and blueprint registration

- 新增 admin setting 页面路由和蓝图注册

### feat: add admin setting page template with toggle switches

- 新增 admin setting 页面模板，支持 toggle switches

### feat: config page path inputs respect settings toggle state, add settings nav link to admin sidebar

- config page path inputs respect settings toggle state, add settings nav link to admin sidebar

### feat: skip admin verify when admin_verify_enabled is false

- 当 admin_verify_enabled 关闭时，管理员自动跳过二次验证流程

### feat: books module before_request guard and path-empty placeholder

- books 模块新增 before_request 守卫，功能禁用时自动跳转首页
- book_search 路由增加路径空检查，路径未配置时显示占位提示

### feat: gallery module before_request guards and path-empty handling

- gallery 模块新增 before_request 守卫，功能禁用时自动跳转首页
- API 路由增加 root 为 None 时的防护处理，避免空路径异常

### feat: index page respects wallpaper/mounted/books/gallery settings

- 首页根据 config 设置动态展示壁纸、挂载页面、书籍、画廊等功能模块

### feat: config API returns settings state for input disabling

- config API returns settings state for input disabling

## 2026-08-07

### M37: 新增统一响应格式模块 response.py

- 新增 `Module/common/response.py`，提供标准化的 JSON 响应格式
- `ErrorCode` 枚举：定义统一错误码（SUCCESS、BAD_REQUEST、UNAUTHORIZED、FORBIDDEN、NOT_FOUND、INTERNAL_ERROR 及模块特定错误码）
- `success_response(data, message, code)`: 返回成功 JSON 响应，格式 `{code, data, msg}`
- `error_response(message, code, status_code)`: 返回错误 JSON 响应
- `paginated_response(data, page, per_page, total)`: 返回分页 JSON 响应，包含分页元数据
- 更新 `Module/common/__init__.py` 导出新函数

### M36: 新增配置工具模块 config_utils.py

- 新增 `Module/common/config_utils.py`，提供集中化的配置加载与缓存功能
- `load_config(ttl=5)`: 从 config.json 加载配置，支持 TTL 缓存
- `get_config_value(key, default=None)`: 获取单个配置值，支持点号分隔的嵌套键
- `save_config(config)`: 保存配置到 config.json
- `backup_config()`: 备份配置文件，保留最近5个备份，含错误处理

### M35: 实现 userfix 管理界面

- 新增 `/admin/userfix` 路由，支持分页浏览用户修复提交
- 新增 `userfix.html` 管理界面，支持卡片式布局、图片预览、状态筛选
- 新增 `/admin/userfix/api/update-status` POST 端点，支持标记已处理/未处理
- 新增 `/admin/userfix/api/delete` POST 端点，支持删除提交记录
- 新增 `/userfix/image/<submission_id>/<filename>` 路由，支持图片预览
- metadata.json 添加 status 字段（默认 unprocessed）
- 所有管理后台模板添加用户反馈导航链接

### 中工程修复方案详细实现

- 完成 33 个中工程问题的详细实现方案编写，覆盖 12 个源文件和 3 个模板文件
- 为每个问题提供具体的代码改动、函数修改和新增函数说明
- 明确问题间依赖关系，识别 21 个可并行实施的无依赖问题
- 更新 `修复方案_中工程.md`，替换原有简略描述为完整实现步骤

## 2026-08-06

### 单元测试与工厂重构

- 重构 app.py 为 create_app(config=None, db_path=None) 工厂，import 不再产生数据库/服务器副作用，便于测试注入临时数据库与配置
- 新增 db_utils.set_db_path / reset_state，支持测试切换临时 SQLite，隔离生产数据
- 引入 pytest 单元测试框架（pytest>=8.0），新增 tests/ 目录，覆盖 common 工具层（file_utils/db_utils/user_utils/auth_utils）与关键路由冒烟测试，运行命令：py -3.12 -m pytest tests/
- 删除损坏的 WSGI 启动脚本 start_wsgi_production.bat / start_wsgi_production_silent.vbs；启动方式改为直接 `py -3.12 app.py`

### 安全与健壮性修复（子系统 G）

#### userfix 上传安全
- 增加图片扩展名白名单与单文件 5MB 大小上限，防止任意文件上传与磁盘填充
- 提交目录名对用户名进行清洗，防止路径穿越
- 时间戳加入微秒位，避免同一秒内两次提交覆盖目录
- 保存失败自动清理半成品目录；错误信息不再回显内部路径

#### admin 权限与 JSON 防护
- require_admin 改为实时读取数据库校验角色/启用状态，不再信任过期会话
- 禁止管理员禁用其他管理员账户，与删除保护对称
- request.get_json() 增加 None 防护，防止伪装错误信息
- 挂载页面名称改为仅允许 ASCII 字母/数字/下划线/短横线
- EXCLUDED_PATHS 补全 /admin/activity；仪表盘活跃会话改用代理感知真实 IP

#### user 登录防爆破与 CSRF
- 登录失败按 IP 节流（5 分钟内 8 次上限），成功自动清零
- 登录与登出增加轻量 CSRF 校验（Flask-WTF generate_csrf，带安全回退）
- 登录/验证模板补隐藏 csrf_token 字段；移除废弃 WHITELIST

#### books 404 语义与静态加固
- 不存在的书籍返回 404 而非 200 占位页
- 静态资源增加 resolve + relative_to 路径包含校验与 is_file 检查，防目录遍历与 500
- 配置为空时默认定位书籍路径；补充 webp/svg/ico MIME 类型

#### gallery 收藏路径与参数校验
- 收藏路径统一做画廊根包含校验并改为相对路径存储，移除响应中的绝对路径泄漏
- 收藏读取兼容旧的绝对/相对存储值；面包屑改用 posix 分隔符
- 偏好设置值做类型/枚举校验；分页参数防非法 int 并限制边界

#### index 模板提取
- 目录浏览由硬编码 render_template_string 迁移为独立模板文件
- 目录模板移除 emoji 图标，改用文本字形标记
- 壁纸配置 POST 使用 get_json(silent=True)，非法 JSON 不再 500

## 2026-08-05

### 前端修复（子系统 D）
- 修复 favorites.html 致命 JS 语法错误（多余 `});` 使整段脚本不执行），灯箱/取消收藏/缩放恢复
- 收藏字段 `absolute` → `absolute_path`；修复 isMobile 遮蔽，设备类型随窗口更新
- 清理 gallery.html 重复函数/死代码/console.log；修复发现设置桌面端禁用态
- index.html 面板宽度计算收敛到 `setPanelWidth`；壁纸开关规避 5s TTL 缓存竞态
- 移除无效 X-CSRFToken 头与死分支；config.html 画廊键名改为 `gallery_root_path`
- activity.html 折叠/未登录过滤高亮修复；dashboard 移除多余闭合标签
- 前端路径与后端路由一一对应，13 个模板 JS 全部通过语法校验

### 收藏页对齐主画廊
- 电脑端收藏缩略图改为正方形裁切（aspect-ratio:1/1），隐藏文件名
- 移除收藏卡片右上角「取消收藏」按钮，改为灯箱内心形按钮取消
- 收藏灯箱重构为主画廊同款：新增上一张/下一张切换、心形收藏按钮（active 态）、信息栏 200px
- 收藏灯箱图片改为整图显示（去掉 width/height:100% 与容器 overflow:hidden）
- 移动端灯箱心形按钮与信息左对齐适配；清理重复样式与无用 data-absolute

### 快速滚动白屏/空白优化（调大绘制与加载面积）
- 顶部栏 sticky 隐藏/显示补 will-change:transform + backface-visibility:hidden，保持 GPU 独立图层，快速滚回不再重绘掉帧白屏
- 新增 setupNearPreload()：用 IntersectionObserver（rootMargin 2500px）将视口较远的图片提前从 lazy 提升为 eager，快速滚动时图片已就绪，消除大片空白
- 网页主画廊与收藏页同步应用，并在每次渲染后重新注册新图片

### 画廊发现区修复
- 修复刷新时发现图片被裁成正方形：随机图片异步加载完成后再重新应用格式/圆角/尺寸设置（`discover:images-rendered` 事件），消除 applyDiscoverSize 在图片渲染前执行的时序问题
- 修复发现区底部"已经到底啦/重新加载"提示过早显示：仅在全部发现图片（含懒加载）加载完成后且滚到底部时才显示

### 管理后台配置保存修复
- 修复 /admin/config 保存后不生效：前端提交 `{config:{...}}` 包裹格式，后端却读取顶层 `paths/wallpaper` 键，导致写入未变化的配置。后端现兼容 `config` 包裹格式（也支持直接格式）
- 图库路径支持相对路径：`get_gallery_root()` 相对路径基于项目根目录解析（不再依赖启动时 CWD），`gallery_root_path` 改为相对路径 `imagetest`（相对项目根目录）

### 挂载页面修复（子系统 F）
- 修复 SD Inspector 404：目录挂载的 index.html 在无尾斜杠路径下重定向到带尾斜杠路径（`/sdinspector` → `/sdinspector/`），相对资源路径正确解析
- index 首页：移除硬编码 SD Inspector 入口（由挂载动态渲染，消除重复）；#mountedPagesNav 用 display:contents 使挂载入口与导航项并排；设置栏首次定位前禁用过渡，消除刷新横移
- gallery 画廊：收藏不再整页刷新（仅存在收藏入口时刷新）；发现灯箱支持左右切换（方向键 + 按钮）；发现区滑到底显示"重新加载"提示
- gallery 画廊：收藏入口（"我的收藏"按钮与收藏卡片）仅在根目录显示；favorites 缩略图样式对齐画廊网格（去粉色渐变、绝对路径隐藏、移动端改 cover）
- 发现随机图结果增加目录树签名缓存（10 秒 TTL），避免每次请求整树递归扫描加速随机发现
- 管理"重启服务器"不再依赖 fetch 回执（os.execl 替换进程后请求无响应），点击即提示并定时刷新页面；登录会话持久化（session.permanent，7 天），浏览器关闭后 cookie 有效

### 日志修复（debug 重载器文件占用）
- 修复调试模式启动时 `PermissionError: WinError 32`：Werkzeug 重载器父进程同时打开 app.log，导致按天滚动重命名失败
- 日志中间件增加 `enable_file_logging` 参数，仅重载器子进程（实际服务进程）或生产模式创建文件处理器，父进程仅保留控制台日志

### gallery/favorites 桌面端风格统一
- 电脑端收藏页图片改为正方形缩略图：`.image-container` 由固定 `height:200px` 改为 `aspect-ratio:1/1`，配合 `object-fit:cover` 裁剪
- 隐藏收藏页图片下方的文件名（`.image-info`），与主画廊一致（主画廊图片下方不显示文件名）
- 移动端保持 gallery 一致的整图 `contain` 显示（`aspect-ratio:auto`），不受桌面正方形改动影响

### gallery/favorites 图片样式统一
- 修复 favorites 页与其他界面图片 CSS 不一致：移动端 favorites 原为固定 200px 高 + `object-fit:cover` 裁剪缩略图，与 gallery 的整图 `contain` 显示不同
- favorites 移动端 `.image-container` 改为 `height:auto; min-height:300px; background:#000`、`.gallery-image` 改为 `height:auto; object-fit:contain`，与 gallery 一致；移除桌面端 `.image-container` 的 `#f5f7fa` 背景，与 gallery 统一
- 保留 favorites 特有的取消收藏按钮与图片路径信息

### 画廊缩略图加载闪白/拉伸修复
- 修复刷新后 0.几秒内所有缩略图（主图库/文件夹封面/发现区/收藏页）被压成方形或拉伸：根因是 `<img>` 在容器内被强制 `width:100%; height:100%`，图片固有比例尚未解析时 `object-fit: cover` 会先以拉伸状态绘制
- 采用加载前 `opacity:0`、加载完成（或出错）后淡入的方案：缩略图直到固有尺寸可知才显示，直接以 cover 裁剪渲染，消除闪变；`bindThumbnailFade()` 覆盖静态渲染、发现区动态渲染与搜索结果
- 保留 `loading="lazy"`，懒加载图片滚动到视口才加载并淡入

## 2026-08-04

### 项目工程化
- 初始化 git 仓库并添加 .gitignore
- 新增 README.md 与 CHANGELOG.md
- requirements.txt 对齐 Python 3.12.10（Flask 3.1.0 / Werkzeug 3.1.3 / Flask-WTF 1.2.2）

### 静态网站挂载
- 挂载目录支持完整静态站点：.css/.js/图片按正确 MIME 内联渲染（不再强制下载）
- 目录自动服务 index.html，无则回退目录浏览
- 增加路径遍历防护（resolve + relative_to）
- SD Inspector 改为静态站挂载，移除蓝图注册
- 挂载路径支持相对应用根目录

### SQLite 存储迁移
- 新增 db_utils SQLite 封装（WAL、JSON 导入、损坏重建）
- 用户/书籍/活动日志/会话/收藏 5 类数据迁移到 SQLite
- 启动自动建表并从 JSON 导入历史数据

### 运营日志 structlog 化
- 新增依赖 structlog==26.1.0
- 运营日志改为 Logfmt 结构化输出，按天滚动存储（app.log.<日期>）
- 桥接 werkzeug 等第三方库日志

### 性能优化
- 活动日志改为内存队列异步批量写入 SQLite（后台线程每 10 秒落盘，重启前强制落盘）
- 用户数据增加 30 秒 TTL 缓存，写库自动失效
- 配置读取增加 5 秒 TTL 缓存，写入自动失效
- 画廊扫描改为单层目录 mtime 缓存 + 递归组合，避免整树重复扫描
- 清理 index.html 重复 CSS 与调试 console.log

## 2026-03-12

### 活动日志功能全面升级

#### 新增功能
- **增强活动日志记录功能**
  - 添加 `parse_user_agent()` 函数：解析 User-Agent 字符串，提取设备类型、操作系统和浏览器信息
  - 修改 `add_activity()` 函数：增加 `path`、`user_agent`、`is_logged_in` 参数
  - 升级日志数据结构，包含：时间、账号、操作、IP地址、设备类型、操作系统、浏览器、访问路径、登录状态
  - 日志记录数量从 100 条增加到 200 条

- **优化认证中间件**
  - 修改 `register_auth_middleware()` 函数：记录所有访问（包括未登录访问）
  - 自动记录每个请求的详细信息：页面路径、User-Agent、登录状态
  - 添加排除路径列表，避免记录日志文件和API请求本身

- **新增 API 路由**
  - `GET /admin/activity/api`：提供日志数据 API，支持按用户名和登录状态筛选
  - `GET /admin/activity/<username>`：按用户筛选的活动日志页面

- **重构活动日志页面**
  - 使用表格布局替代列表布局，便于展示更多信息
  - 添加筛选功能：全部、未登录访问、按用户筛选
  - 动态加载用户列表，自动生成用户筛选按钮
  - 显示详细的日志信息：时间、账号、操作、IP地址、设备、系统、浏览器、访问路径、状态
  - 添加登录状态标签：已登录（绿色）、未登录（红色）
  - 支持响应式设计，移动端自动调整表格显示

#### 折叠模式迭代优化

- **折叠功能迭代**（6 次迭代完成）
  1. 新增日志折叠功能：按用户名+路径分组，显示访问次数
  2. 修改折叠逻辑，只折叠连续多次访问（非连续不折叠）
  3. 优化折叠功能，只有重复访问才可折叠（is_group 标记）
  4. 折叠符号样式改进：叠加在时间单元格中显示，支持旋转动画
  5. 修复折叠符号重复显示问题（删除 CSS 伪元素）
  6. 修复按用户过滤跳转新页面问题（改为 AJAX 过滤）

#### 功能改进
- **真实IP地址**：记录 `request.remote_addr` 显示访客真实IP
- **设备识别**：自动识别 Android、iOS、Windows、Mac、Linux 等设备类型
- **浏览器识别**：支持识别 Chrome、Firefox、Safari、Edge、Opera、Internet Explorer
- **系统识别**：详细显示 Windows 版本（10/11、7、8、8.1）、macOS、Linux 等
- **未登录访问**：记录所有未登录的访问请求，归类为"未登录访问"
- **按账号筛选**：点击用户按钮只显示该用户的日志记录
- **访问路径**：记录每次访问的具体页面路径

#### 修改的文件
- 修改：`Module/common/user_utils.py`（添加 parse_user_agent 函数，修改 add_activity 函数）
- 修改：`Module/admin/admin.py`（更新认证中间件，添加 API 路由）
- 修改：`Module/admin/templates/admin/activity.html`（重构页面布局和功能）

## 2026-02-27

### SD Inspector 模块集成

- 将 SD Inspector 从独立应用改造为蓝图模块
- 创建 `Module/sdinspector/templates/sdinspector/` 目录结构
- 新增 `GET /sdinspector` 和 `GET /sdinspector/<path:filename>` 路由

### 新增画廊模块

- 创建完整的画廊模块，包含图片浏览、搜索、发现、收藏、用户偏好设置
- 支持响应式设计，电脑端和移动端体验优异
- 多端同步的用户偏好设置
- 独立的收藏管理页面
- 全屏灯箱预览，支持缩放

### 画廊收藏功能迭代

- 收藏数据存储格式调整（相对路径/绝对路径切换）
- 收藏页面导航优化
- 用户偏好设置功能实现（多端同步）

## 2026-02-26

### 代码重构优化

- 创建共享工具模块 `Module/common/`（user_utils.py, auth_utils.py, file_utils.py）
- 修复循环导入问题，统一共享功能实现位置
- 添加线程安全的文件操作（文件锁机制）
- 移除硬编码路径，统一使用 config.json 配置
- 统一日志配置，避免模块间冲突
- 简化 app.py 启动方式，改用 Flask 原生 app.run()
- 实现真正的服务器重启（os.execl）
- 检查并确认所有页面响应式设计

### 代码规范合规性修复

- 统一使用 file_utils 进行文件操作
- 移除重复的导入语句
