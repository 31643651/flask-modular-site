# Development Standards

UI 风格规范和功能实现规范。

---

## UI 风格规范

### 设计原则
- 简洁、实用、无多余装饰
- 参考标准: gallery.html 和 books/detail.html
- 不使用表情符号（功能性符号除外）
- 不使用渐变背景
- 专注于功能实现

### 颜色方案
- 主背景色: `#f5f7fa`
- 卡片背景: `#ffffff`
- 主色调: `#3498db` (蓝色)
- 文字颜色: `#2c3e50` (深灰)
- 边框颜色: `#ddd` / `#eee`
- 成功色: `#27ae60` (绿色)
- 错误色: `#e74c3c` (红色)
- 警告色: `#f39c12` (橙色)
- 次要色: `#95a5a6` (灰色)

### 字体规范
- 字体族: `'Microsoft YaHei', sans-serif`
- 标题字号: 18-24px
- 正文字号: 14px
- 小字字号: 12px
- 行高: 1.6

### 布局规范
- 容器最大宽度: 800-1200px
- 卡片圆角: 8px
- 按钮圆角: 4px
- 内边距: 20-30px
- 间距: 15-20px

### 组件规范
- 按钮：扁平化设计，hover 时背景色加深
- 表单：简单边框，focus 时边框变色
- 表格：简洁线条，hover 时行高亮
- 卡片：白色背景，轻微阴影
- 导航：左侧固定或顶部居中

### 禁止使用
- 表情符号（功能性符号除外）
- 渐变背景
- 复杂的阴影
- 花哨的图标
- 过度装饰

### 必须实现
- 响应式设计（移动端适配）
- 清晰的视觉层次
- 良好的可读性
- 直观的交互反馈
- 统一的间距和对齐

---

## 功能实现规范

### 1. 模块化原则
- 每个功能独立为一个模块，存放在 `/Module` 目录下
- 主程序仅负责启动和模块导入，不包含业务逻辑
- 高频可变数据存于 SQLite（`Module/data/app.db`），config 类配置存于 JSON，禁止在 Python 代码中硬编码可变数据
- 代码结构清晰，注释详细

### 2. 目录结构
- 项目根目录允许的固定内容: `app.py`、`requirements.txt`、`requirements-dev.txt`、`pytest.ini`、`.gitignore`、`LICENSE`、`README.md`、`CHANGELOG.md`、其他 md 文档，以及 `/Module`、`/docs`、`/tests` 目录
- `/Module` 内部结构: 每个模块一个子目录，包含 templates 子目录
- 所有 JSON 配置数据文件统一存放在 `/Module/json` 目录下（备份存于 `/Module/json/backups/`）
- 高频可变数据（users/books/activity_log/active_sessions/favorites/ip_bans）统一存于 `/Module/data/app.db`
- 大体积静态内容（如 SD Inspector 静态站、画廊/书籍数据目录）可经 gitignore 排除，通过页面挂载机制或路径配置接入

### 3. 模块规范
- 每个模块必须定义蓝图对象
- 模板路径应使用模块名前缀以避免冲突
- 模块不得直接存储数据，所有数据读写通过 db_utils（SQLite）或 JSON 文件进行
- 模块间不应相互依赖，通过数据文件或全局配置实现共享
- 蓝图 URL 前缀建议与模块名一致

### 4. 配置文件和数据存储规范
- 高频可变数据（用户/书籍/活动日志/会话/收藏）存于 SQLite（`Module/data/app.db`），config 类配置使用 JSON 文件存储，统一存放在 `/Module/json/` 目录下
- JSON 文件命名清晰，内部结构合理
- 读写 SQLite 使用 `db_utils.py`，读写 JSON 使用 `file_utils.py`，函数应封装在模块内或单独的工具模块中
- 禁止在 Python 代码中以全局变量形式存储可变数据
- 全局配置存储在 config.json 中，读写统一使用 `config_utils.py`（`load_config` / `get_config_value` / `save_config`），保存前可用 `backup_config()` 备份

### 5. 主程序规范 (app.py)
- app.py 位于项目根目录，仅包含: 导入、创建应用实例、配置、注册蓝图、启动服务器
- 不包含任何业务逻辑路由

### 6. 代码注释要求
- 每个 Python 文件开头应有文件功能说明
- 每个函数、方法必须有文档字符串（docstring）
- 关键逻辑代码行应有行内注释
- 注释使用中文

### 7. 安全与接口规范
- 所有 POST/PUT/DELETE/PATCH 请求必须通过 CSRF 验证：表单携带 `csrf_token` 字段，AJAX 携带 `X-CSRF-Token` 请求头（token 由 `security.py` 的 `generate_csrf_token()` 生成并存于 session）；全局中间件统一校验，豁免 `/user/login`、`/user/verify`、`/setup`
- API JSON 响应使用 `response.py` 的统一格式 `{"code": ..., "data": ..., "msg": ...}`，通过 `success_response` / `error_response` / `paginated_response` 构造
- 列表类接口分页使用 `pagination.py`（`get_pagination_params` / `paginate_query` / `format_pagination_meta`），per_page 上限 100
- 所有响应经 `add_security_headers` 附加安全响应头（CSP、nosniff、X-Frame-Options 等，生产模式附加 HSTS）

### 8. 禁止事项
- 禁止在 Python 代码中直接存储可变数据
- 禁止在模块间直接导入其他模块的视图函数或变量
- 禁止将 HTML 模板硬编码在 Python 字符串中
- 禁止在根目录创建上述允许清单之外的新文件夹（当前仅允许 /Module、/docs、/tests）
- 禁止在代码中保留调试打印语句
- 禁止依赖已移除的 Flask-WTF：CSRF 一律使用 `Module/common/security.py` 的自研实现

### 9. 变更管理与安全规范
- 每次更改代码后，必须在更新日志中记录变更
- 收到用户需求时，必须先制定详细的实现规划，获得用户确认后方可实施
- 严禁未经用户明确允许执行任何代码
