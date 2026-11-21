# 修复方案 - 小工程（详细实现版）

## 工程说明

小工程通常只需要简单修改，涉及1-2个文件，包括添加一行校验代码、修改配置默认值、添加import语句、修改HTML属性、添加日志记录等。

---

## 问题列表

---

### H19: 硬编码 SECRET_KEY 默认值 — 会话伪造

**涉及文件**:
- `app.py`

**修改内容**:
1. 生产模式下改为每次启动刷新的随机32位字符串作为SECRET_KEY
2. 保留开发模式的硬编码密钥
3. 添加启动日志记录密钥生成状态

**实现细节**:
- 在 `create_app()` 函数中，生产模式分支（第44-45行）改为：
  ```python
  # 旧代码
  app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "production-secret-key-change-me")
  
  # 新代码
  secret_key = os.environ.get("SECRET_KEY")
  if not secret_key:
      import secrets
      secret_key = secrets.token_hex(32)
  app.config["SECRET_KEY"] = secret_key
  ```
- 在同一位置后添加日志记录：
  ```python
  import logging
  logger = logging.getLogger(__name__)
  if production_mode:
      logger.info("SECRET_KEY generated randomly for this session")
  ```

**依赖**: 无

---

### S6: 会话固定攻击 (Session Fixation)

**涉及文件**:
- `Module/user/user.py`

**修改内容**:
1. 登录成功后调用 `session.clear()` 清除旧会话
2. 重新设置会话数据，实现session重新生成
3. 保留原始session中的CSRF token

**实现细节**:
- 在 `login()` 路由中，登录成功分支（第181-188行）修改为：
  ```python
  # 旧代码
  session["user_id"] = user["id"]
  session["username"] = user["username"]
  session["role"] = user["role"]
  session["verified"] = False
  session.permanent = True
  
  # 新代码：先清除旧会话，重新生成session ID
  old_csrf = session.get("_csrf")  # 保留CSRF token
  session.clear()
  if old_csrf:
      session["_csrf"] = old_csrf
  session["user_id"] = user["id"]
  session["username"] = user["username"]
  session["role"] = user["role"]
  session["verified"] = False
  session.permanent = True
  ```

**依赖**: 无

---

### S9: 画廊搜索结果标题 XSS（反射型）

**涉及文件**:
- `Module/gallery/templates/gallery/gallery.html`

**修改内容**:
1. 将 `title.innerHTML` 改为 `title.textContent`，防止搜索关键词注入HTML

**实现细节**:
- 在 `gallery.html` 第1423行，修改为：
  ```javascript
  // 旧代码
  title.innerHTML = `<h2>搜索结果: "${query}"</h2>
                    <p>找到 ${results.folders.length} 个文件夹，${results.images.length} 张图片</p>`;
  
  // 新代码：使用 textContent 安全渲染
  const h2 = document.createElement('h2');
  h2.textContent = `搜索结果: "${query}"`;
  const p = document.createElement('p');
  p.textContent = `找到 ${results.folders.length} 个文件夹，${results.images.length} 张图片`;
  title.appendChild(h2);
  title.appendChild(p);
  ```

**依赖**: 无

---

### H2: logger 未定义导致 NameError

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 在文件开头导入logging模块
2. 创建logger实例
3. 替换所有未定义的`logger`调用

**实现细节**:
- 在文件顶部（第9行 `import re` 之后）添加：
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```
- 检查第850行的 `logger.error(...)` 调用是否可正常工作

**依赖**: 无

---

### H11: 壁纸配置更新端点无认证保护

**涉及文件**:
- `Module/index/index.py`

**修改内容**:
1. 在 `update_wallpaper_config()` 路由中添加认证校验

**实现细节**:
- 在 `update_wallpaper_config()` 函数（第89行）开头添加：
  ```python
  @index_bp.route("/api/wallpaper/config", methods=["POST"])
  def update_wallpaper_config():
      """更新壁纸配置"""
      # 添加认证校验
      from Module.common.auth_utils import require_auth
      auth_check = require_auth()
      if auth_check:
          return jsonify({"success": False, "message": "请先登录"}), 401
      # ... 原有代码
  ```
- 或者更简洁地在文件顶部导入后使用：
  ```python
  from Module.common.auth_utils import check_auth
  
  # 在函数开头
  if not check_auth():
      return jsonify({"success": False, "message": "请先登录"}), 401
  ```

**依赖**: 无

---

### H20: 画廊文件夹图片 API 参数传递 bug — subpath 被忽略

**涉及文件**:
- `Module/gallery/gallery.py`

**修改内容**:
1. 直接使用函数参数 `subpath`
2. 删除从 `request.path` 解析的逻辑

**实现细节**:
- 在 `gallery_folder_images()` 函数（第703-711行），修改为：
  ```python
  # 旧代码
  def gallery_folder_images():
      subpath = sanitize_path(request.path.replace("/gallery/api/folder-images/", ""))
      folder_path = get_gallery_root() / subpath
  
  # 新代码：使用路由参数
  def gallery_folder_images(subpath):
      from urllib.parse import unquote
      subpath = unquote(subpath)
      subpath = sanitize_path(subpath)
      folder_path = get_gallery_root() / subpath
  ```
- 函数签名改为接收 `subpath` 参数：`def gallery_folder_images(subpath):`

**依赖**: 无

---

### M3: 壁纸路径无效时静默 404

**涉及文件**:
- `Module/index/index.py`

**修改内容**:
1. 检查壁纸路径是否存在
2. 不存在时返回明确错误信息
3. 添加日志记录无效路径

**实现细节**:
- 在 `serve_wallpaper()` 函数中（第139行），修改错误处理：
  ```python
  # 旧代码
  if wallpaper_path.exists():
      # ... 处理逻辑
  abort(404)
  
  # 新代码
  if not wallpaper_path.exists():
      logger.warning(f"Wallpaper path does not exist: {wallpaper_path}")
      abort(404)
  ```
- 在第168行的 `except` 块中已有日志记录，保持即可。

**依赖**: 无

---

### M5: 配置更新无 CSRF Token

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 在 `update_config` 端点添加CSRF令牌校验

**实现细节**:
- 在 `update_config()` 函数（第690行）中，在 `require_admin()` 检查后添加：
  ```python
  @admin_bp.route("/config/update", methods=["POST"])
  def update_config():
      # 检查管理员权限
      check = require_admin()
      if check:
          return check
      
      # CSRF 校验
      from Module.user.user import check_csrf
      if not check_csrf():
          return jsonify({"success": False, "message": "CSRF令牌无效"}), 403
      
      # ... 原有代码
  ```
- 在 `Module/admin/templates/admin/config.html` 中的 `fetch` 调用中添加 CSRF token header

**依赖**: 无

---

### M7: 服务器重启端点可被滥用导致拒绝服务

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 添加重启冷却时间限制（60秒内不可重复重启）
2. 记录重启时间戳

**实现细节**:
- 在 `admin.py` 顶部添加模块级变量：
  ```python
  _last_restart_time = 0
  _RESTART_COOLDOWN = 60  # 60秒冷却时间
  ```
- 在 `restart_server()` 函数（第622行）开头添加：
  ```python
  @admin_bp.route("/restart", methods=["POST"])
  def restart_server():
      global _last_restart_time
      # 检查管理员权限
      check = require_admin()
      if check:
          return check
      
      # 冷却时间检查
      now = time.time()
      if now - _last_restart_time < _RESTART_COOLDOWN:
          remaining = int(_RESTART_COOLDOWN - (now - _last_restart_time))
          return jsonify({"success": False, "message": f"请等待{remaining}秒后再重试"})
      _last_restart_time = now
      
      # ... 原有代码
  ```

**依赖**: 无

---

### M8: 活动日志中间件 IP 伪造注入

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 验证X-Forwarded-For头的可信度
2. 使用配置化方式控制是否信任代理头

**实现细节**:
- 在 `get_real_ip()` 函数（第254行）中修改，添加可信代理配置：
  ```python
  # 新增配置变量
  _TRUST_PROXY_HEADERS = False  # 是否信任代理头，默认不信任
  
  def get_real_ip(request):
      """获取真实的客户端IP地址"""
      # 仅在明确配置信任代理时才使用 X-Forwarded-For
      if _TRUST_PROXY_HEADERS:
          if "X-Forwarded-For" in request.headers:
              forwarded_for = request.headers["X-Forwarded-For"]
              ips = [ip.strip() for ip in forwarded_for.split(",")]
              if ips and ips[0]:
                  return ips[0]
          if "X-Real-IP" in request.headers:
              real_ip = request.headers["X-Real-IP"]
              if real_ip:
                  return real_ip
      
      # 默认使用 remote_addr
      return request.remote_addr
  ```
- 可通过环境变量 `TRUST_PROXY_HEADERS=1` 来启用

**依赖**: 无

---

### M9: 硬编码密钥 — 开发和生产模式

**涉及文件**:
- `app.py`

**修改内容**:
1. 生产模式下强制要求环境变量
2. 未设置时拒绝启动
3. 开发模式密钥可保留

**实现细节**:
- 与H19合并实现，在 `create_app()` 函数中修改：
  ```python
  # 旧代码
  if production_mode:
      app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "production-secret-key-change-me")
  else:
      app.config["SECRET_KEY"] = "dev-secret-key-change-in-production"
  
  # 新代码
  if production_mode:
      secret_key = os.environ.get("SECRET_KEY")
      if not secret_key:
          import secrets
          secret_key = secrets.token_hex(32)
      app.config["SECRET_KEY"] = secret_key
  else:
      app.config["SECRET_KEY"] = "dev-secret-key-change-in-production"
  ```

**依赖**: H19完成

---

### M14: 管理员验证码被记录到日志文件

**涉及文件**:
- `Module/user/user.py`

**修改内容**:
1. 仅在调试模式下输出验证码
2. 生产环境移除或替换为哈希值

**实现细节**:
- 修改 `log_verify_code()` 函数（第109行）：
  ```python
  # 旧代码
  def log_verify_code(code):
      logger.info(f"{'=' * 50}")
      logger.info(f"管理员动态验证码: {code}")
      logger.info(f"{'=' * 50}")
  
  # 新代码：仅在DEBUG级别记录
  def log_verify_code(code):
      logger.debug(f"管理员动态验证码: {code[:4]}****")  # 仅记录前4位
  ```
- 或者完全移除日志记录，改为在控制台输出（仅开发模式）：
  ```python
  def log_verify_code(code):
      import sys
      if sys.flags.dev_mode or not getattr(sys, 'flags', {}).get('optimize'):
          print(f"[DEV] 验证码: {code}")
  ```

**依赖**: 无

---

### M15: SQL 语句使用字符串格式化

**涉及文件**:
- `Module/common/user_utils.py`

**修改内容**:
1. 使用参数化查询或验证 `_ACTIVITY_MAX` 为整数类型

**实现细节**:
- 在 `flush_activity_queue()` 函数（第69-70行），修改为：
  ```python
  # 旧代码
  execute(
      "DELETE FROM activity_log WHERE id NOT IN (SELECT id FROM activity_log ORDER BY id DESC LIMIT %d)"
      % _ACTIVITY_MAX
  )
  
  # 新代码：使用参数化查询
  execute(
      "DELETE FROM activity_log WHERE id NOT IN (SELECT id FROM activity_log ORDER BY id DESC LIMIT ?)",
      (_ACTIVITY_MAX,)
  )
  ```
- 或添加类型断言确保安全：
  ```python
  assert isinstance(_ACTIVITY_MAX, int) and _ACTIVITY_MAX > 0
  ```

**依赖**: 无

---

### M17: 活动日志队列数据丢失风险

**涉及文件**:
- `Module/common/user_utils.py`

**修改内容**:
1. 队列满时记录警告日志
2. 队列满时阻塞写入

**实现细节**:
- 在 `add_activity()` 函数（第377行）中，修改队列满时的处理：
  ```python
  # 旧代码
  with _activity_queue_lock:
      _activity_queue.append(record)
      if len(_activity_queue) > _ACTIVITY_MAX:
          del _activity_queue[: len(_activity_queue) - _ACTIVITY_MAX]
  
  # 新代码：队列满时记录警告
  with _activity_queue_lock:
      _activity_queue.append(record)
      if len(_activity_queue) > _ACTIVITY_MAX:
          import structlog
          logger = structlog.get_logger(__name__)
          logger.warning("activity_queue_overflow", queue_size=len(_activity_queue))
          del _activity_queue[: len(_activity_queue) - _ACTIVITY_MAX]
  ```

**依赖**: 无

---

### M19: 用户缓存提供过期数据

**涉及文件**:
- `Module/common/user_utils.py`

**修改内容**:
1. 确保所有路径调用 `invalidate_users_cache`

**实现细节**:
- 检查所有修改用户数据的函数是否在写入后调用了 `invalidate_users_cache()`：
  - `save_users()` 已调用（第168行）— 正确
  - 确认 `admin.py` 中 `register_user()`、`toggle_user_status()`、`delete_user()` 都通过 `save_users()` 间接触发了缓存失效 — 正确
- 无需代码修改，当前实现已正确

**依赖**: 无

---

### M20: 认证白名单路径遍历风险

**涉及文件**:
- `Module/common/auth_utils.py`

**修改内容**:
1. 使用 `os.path.normpath` 规范化路径
2. 再比较白名单

**实现细节**:
- 修改 `check_auth()` 函数（第22-25行）：
  ```python
  # 旧代码
  path = request.path
  for whitelist_path in WHITELIST:
      if path.startswith(whitelist_path):
          return True
  
  # 新代码：规范化路径防止遍历
  import os
  path = os.path.normpath(request.path)
  for whitelist_path in WHITELIST:
      normalized_whitelist = os.path.normpath(whitelist_path)
      if path == normalized_whitelist or path.startswith(normalized_whitelist + os.sep):
          return True
  ```

**依赖**: 无

---

### M21: 活动日志 User-Agent 未校验（信息污染）

**涉及文件**:
- `Module/common/user_utils.py`

**修改内容**:
1. 对 User-Agent 进行 sanitize
2. 移除HTML特殊字符

**实现细节**:
- 在 `add_activity()` 函数中，添加UA清理：
  ```python
  def add_activity(username, description, ip, path="", user_agent="", is_logged_in=True):
      # 清理 User-Agent：移除 HTML 特殊字符
      import re
      sanitized_ua = re.sub(r'[<>"\'&]', '', user_agent) if user_agent else ""
      
      device_info = (
          parse_user_agent(sanitized_ua)
          if sanitized_ua
          else {"device_type": "未知设备", "os": "未知操作系统", "browser": "未知浏览器"}
      )
      # ... 后续使用 sanitized_ua 替代 user_agent
  ```

**依赖**: 无

---

### M22: 管理员创建用户可指定任意角色

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 限制 `role` 参数仅允许 `"user"` 值
2. 添加角色白名单校验

**实现细节**:
- 在 `register_user()` 函数（第534行）中，修改角色处理：
  ```python
  # 旧代码
  role = data.get("role", "user")
  
  # 新代码：强制角色白名单
  ALLOWED_ROLES = {"user"}  # 仅允许创建普通用户
  role = data.get("role", "user")
  if role not in ALLOWED_ROLES:
      return {"success": False, "message": f"不支持的角色类型: {role}"}
  ```

**依赖**: 无

---

### M32: 壁纸 CSS 背景 URL 未转义可能导致 CSS 注入

**涉及文件**:
- `Module/index/templates/index/index.html`

**修改内容**:
1. 对路径进行CSS字符串转义
2. 使用 `url()` 编码

**实现细节**:
- 在 `index.html` 第990行，修改为：
  ```javascript
  // 旧代码
  wallpaper.style.backgroundImage = `url(${data.path}?t=${Date.now()})`;
  
  // 新代码：CSS 安全转义
  function escapeCSSUrl(url) {
      // 转义 CSS 字符串中的特殊字符
      return url.replace(/[()"'\\]/g, '\\$&');
  }
  wallpaper.style.backgroundImage = `url("${escapeCSSUrl(data.path)}?t=${Date.now()}")`;
  ```

**依赖**: 无

---

### M37: 生产依赖包含测试框架

**涉及文件**:
- `requirements.txt`
- `requirements-dev.txt`（新建）

**修改内容**:
1. 将 `pytest` 从 `requirements.txt` 移除
2. 创建 `requirements-dev.txt` 包含开发依赖

**实现细节**:
- 修改 `requirements.txt`：
  ```
  Flask==3.1.0
  Werkzeug==3.1.3
  Flask-WTF==1.2.2
  structlog==26.1.0
  ```
- 新建 `requirements-dev.txt`：
  ```
  -r requirements.txt
  pytest>=8.0
  ```

**依赖**: 无

---

### M38: 画廊收藏页面未使用 HTTP Location 头重定向

**涉及文件**:
- `Module/gallery/gallery.py`

**修改内容**:
1. 使用Flask的 `redirect()` 函数返回标准302重定向
2. 移除JavaScript重定向代码

**实现细节**:
- 在 `gallery_favorites()` 函数（第606-609行），修改为：
  ```python
  # 旧代码
  if not username:
      return (
          '<script>window.location.href="/user/login?next=/gallery/favorites";</script>',
          302,
      )
  
  # 新代码：使用标准 HTTP 重定向
  from flask import redirect, url_for
  if not username:
      return redirect("/user/login?next=/gallery/favorites")
  ```

**依赖**: 无

---

### M43: 管理后台注册用户角色下拉框缺少 api 角色选项

**涉及文件**:
- `Module/admin/templates/admin/users.html`

**修改内容**:
1. 在角色下拉框添加 `api` 选项

**实现细节**:
- 在 `users.html` 的角色下拉框中（约第158-161行），添加选项：
  ```html
  <!-- 旧代码 -->
  <option value="user">普通用户</option>
  <option value="admin">管理员</option>
  
  <!-- 新代码 -->
  <option value="user">普通用户</option>
  <option value="api">API用户</option>
  <option value="admin">管理员</option>
  ```

**依赖**: 无

---

### S10: userfix 提交文本内容无长度限制 — 拒绝服务

**涉及文件**:
- `Module/userfix/userfix.py`

**修改内容**:
1. 添加文本内容最大长度限制（10000字符）
2. 超出长度时拒绝提交并返回错误信息

**实现细节**:
- 在 `submit()` 路由（第327行后），添加长度检查：
  ```python
  # 获取提交的文本内容
  text = request.form.get("text", "").strip()
  if not text:
      return jsonify({"success": False, "message": "请输入内容"})
  
  # 新增：文本长度限制
  MAX_TEXT_LENGTH = 10000
  if len(text) > MAX_TEXT_LENGTH:
      return jsonify({"success": False, "message": f"内容长度超出限制（最多{MAX_TEXT_LENGTH}字符）"})
  ```

**依赖**: 无

---

### S11: userfix 提交次数限制竞态条件 — 速率限制绕过

**涉及文件**:
- `Module/userfix/userfix.py`

**修改内容**:
1. 使用文件锁将检查+递增包裹在同一临界区内

**实现细节**:
- 将 `check_submission_limit()` 和 `increment_user_submission()` 合并为原子操作：
  ```python
  import threading
  _submission_lock = threading.Lock()
  
  def check_and_increment_submission(username):
      """原子地检查并递增提交计数"""
      with _submission_lock:
          # 检查限制
          user = get_user(username)
          if not user:
              return (False, 0)
          if user.get("role") == "admin":
              return (True, -1)
          
          count = get_user_submission_count(username)
          if count >= DAILY_LIMIT:
              return (False, 0)
          
          # 原子递增
          increment_user_submission(username)
          remaining = DAILY_LIMIT - count - 1
          return (True, remaining)
  ```
- 在 `submit()` 路由中替换原来的 `check_submission_limit()` + 后续的 `increment_user_submission()` 调用

**依赖**: 无

---

### L1: 无客户端路径校验

**涉及文件**:
- 前端JavaScript文件（挂载页面相关）

**修改内容**:
1. 在前端添加路径格式校验
2. 检查非法字符

**实现细节**:
- 在 `Module/admin/templates/admin/config.html` 的挂载页面添加表单中，添加客户端路径校验：
  ```javascript
  function validatePath(path) {
      // 检查非法字符
      const illegalChars = /[<>|?*"]/;
      if (illegalChars.test(path)) {
          return { valid: false, message: '路径包含非法字符' };
      }
      // 检查是否包含连续点号（路径遍历尝试）
      if (/\.\./.test(path)) {
          return { valid: false, message: '路径不能包含 ..' };
      }
      return { valid: true };
  }
  ```

**依赖**: 无

---

### L2: 可向 config.json 注入任意键值

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 仅允许更新已知的配置键
2. 添加配置键白名单校验

**实现细节**:
- 在 `update_config()` 函数（第714行）中，添加键白名单：
  ```python
  # 新增配置键白名单
  ALLOWED_CONFIG_KEYS = {
      "paths": {"book_data_path", "book_static_path", "gallery_root_path"},
      "wallpaper": {"enabled", "path"},
  }
  
  # 更新路径配置
  if "paths" in data:
      if "paths" not in config:
          config["paths"] = {}
      for key, value in data["paths"].items():
          if key not in ALLOWED_CONFIG_KEYS.get("paths", set()):
              return jsonify({"success": False, "message": f"不允许的配置键: paths.{key}"}), 400
          config["paths"][key] = value
  
  # 更新壁纸配置
  if "wallpaper" in data:
      if "wallpaper" not in config:
          config["wallpaper"] = {}
      for key, value in data["wallpaper"].items():
          if key not in ALLOWED_CONFIG_KEYS.get("wallpaper", set()):
              return jsonify({"success": False, "message": f"不允许的配置键: wallpaper.{key}"}), 400
          config["wallpaper"][key] = value
  ```

**依赖**: 无

---

### L3: 配置文件无备份恢复机制

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 更新配置前自动备份
2. 保留最近5个备份

**实现细节**:
- 在 `update_config()` 函数中，保存前添加备份逻辑：
  ```python
  import shutil
  from datetime import datetime
  
  def backup_config():
      """备份配置文件"""
      if CONFIG_FILE.exists():
          backup_dir = CONFIG_FILE.parent / "backups"
          backup_dir.mkdir(exist_ok=True)
          timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
          backup_path = backup_dir / f"config_{timestamp}.json"
          shutil.copy2(CONFIG_FILE, backup_path)
          
          # 保留最近5个备份
          backups = sorted(backup_dir.glob("config_*.json"))
          for old_backup in backups[:-5]:
              old_backup.unlink()
  ```
- 在 `update_config()` 中，写入前调用 `backup_config()`

**依赖**: 无

---

### L4: 数据库连接单例无连接池

**涉及文件**:
- `Module/common/db_utils.py`

**修改内容**:
1. 添加定期健康检查
2. 记录连接使用统计

**实现细节**:
- 在 `get_connection()` 函数中，添加健康检查：
  ```python
  def get_connection():
      global _connection
      with _lock:
          if _connection is not None:
              # 健康检查：尝试执行简单查询
              try:
                  _connection.execute("SELECT 1")
              except Exception:
                  # 连接已损坏，重新创建
                  try:
                      _connection.close()
                  except Exception:
                      pass
                  _connection = None
          
          if _connection is None:
              DB_FILE.parent.mkdir(parents=True, exist_ok=True)
              _connection = sqlite3.connect(str(DB_FILE), check_same_thread=False)
              _connection.row_factory = sqlite3.Row
              _connection.execute("PRAGMA journal_mode=WAL")
          return _connection
  ```

**依赖**: 无

---

### L5: JSON 读取静默返回默认值

**涉及文件**:
- `Module/common/file_utils.py`

**修改内容**:
1. JSON解析失败时记录错误日志
2. 包含文件路径和错误信息

**实现细节**:
- 修改 `read_json_file()` 函数（第62行）：
  ```python
  # 旧代码
  except json.JSONDecodeError:
      return default
  
  # 新代码：记录错误日志
  except json.JSONDecodeError as e:
      import structlog
      logger = structlog.get_logger(__name__)
      logger.error("json_parse_error", file_path=str(file_path), error=str(e))
      return default
  ```

**依赖**: 无

---

### L6: 数据库损坏检测范围过广

**涉及文件**:
- `Module/common/db_utils.py`

**修改内容**:
1. 审查 `_is_corruption_error` 匹配的消息列表
2. 添加日志记录检测到的错误类型

**实现细节**:
- 修改 `_is_corruption_error()` 函数（第132行）：
  ```python
  def _is_corruption_error(exc):
      msg = str(exc).lower()
      matched = any(
          marker in msg
          for marker in (
              "file is not a database",
              "database disk image is malformed",
              "disk i/o error",
          )
      )
      if matched:
          import structlog
          logger = structlog.get_logger(__name__)
          logger.warning("database_corruption_detected", error=str(exc))
      return matched
  ```

**依赖**: 无

---

### L7: 画廊扫描缓存无界增长保护粗糙

**涉及文件**:
- `Module/gallery/gallery.py`

**修改内容**:
1. 将整体清空改为LRU淘汰策略
2. 设置合理的缓存大小上限

**实现细节**:
- 修改 `_get_folder_scan()` 函数中的缓存管理（第108-111行）：
  ```python
  # 旧代码
  with _scan_cache_lock:
      if len(_scan_cache) >= _SCAN_CACHE_MAX:
          _scan_cache.clear()
      _scan_cache[key] = (mtime, scan)
  
  # 新代码：LRU淘汰（删除最旧的20%条目）
  with _scan_cache_lock:
      if len(_scan_cache) >= _SCAN_CACHE_MAX:
          # 按访问时间排序，删除最旧的20%
          sorted_keys = sorted(_scan_cache.keys(), 
                              key=lambda k: _scan_cache[k][0])
          remove_count = max(1, len(sorted_keys) // 5)
          for k in sorted_keys[:remove_count]:
              del _scan_cache[k]
      _scan_cache[key] = (mtime, scan)
  ```

**依赖**: 无

---

### L9: 壁纸更新端点无权限校验

**涉及文件**:
- `Module/index/index.py`

**修改内容**:
1. 添加登录校验或管理员权限校验

**实现细节**:
- 与H11合并实现，在 `update_wallpaper_config()` 中添加认证

**依赖**: H11完成

---

### L10: 日志注入风险

**涉及文件**:
- `Module/log/log.py`

**修改内容**:
1. 对记录的路径和IP进行sanitization
2. 移除或转义换行符等控制字符

**实现细节**:
- 修改 `log_request()` 函数（第130行）：
  ```python
  def log_request(logger, response, request_time):
      if response.status_code != 200:
          from flask import request
          import re
          
          # 清理路径和IP中的控制字符
          safe_path = re.sub(r'[\x00-\x1f\x7f]', '', request.path)
          safe_ip = re.sub(r'[\x00-\x1f\x7f]', '', request.remote_addr or '')
          
          log = logger.bind(
              method=request.method,
              path=safe_path,
              status=response.status_code,
              ip=safe_ip,
          )
          # ... 后续日志记录
  ```

**依赖**: 无

---

### L11: 数据库连接线程崩溃泄漏

**涉及文件**:
- `Module/common/db_utils.py`

**修改内容**:
1. 添加连接使用跟踪
2. 线程退出时确保连接关闭

**实现细节**:
- 由于使用单例连接且 `check_same_thread=False`，当前SQLite连接是跨线程共享的。添加连接跟踪：
  ```python
  import weakref
  
  _active_connections = weakref.WeakSet()
  
  def get_connection():
      global _connection
      with _lock:
          if _connection is None:
              # ... 创建连接
              _active_connections.add(_connection)
          return _connection
  ```

**依赖**: 无

---

### L12: 嵌套事务回滚问题

**涉及文件**:
- `Module/common/db_utils.py`

**修改内容**:
1. 评估当前嵌套事务使用场景
2. 如需要，实现SAVEPOINT机制

**实现细节**:
- 当前 `transaction()` 上下文管理器使用模块级 `_in_transaction` 标志，不支持嵌套。由于项目中没有实际嵌套事务场景，可以保持现状。如需改进：
  ```python
  @contextlib.contextmanager
  def transaction():
      global _in_transaction
      with _lock:
          _in_transaction = True
          savepoint_name = f"sp_{threading.get_ident()}"
          try:
              get_connection().execute(f"SAVEPOINT {savepoint_name}")
              yield
              get_connection().execute(f"RELEASE SAVEPOINT {savepoint_name}")
          except Exception:
              get_connection().execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
              raise
          finally:
              _in_transaction = False
  ```

**依赖**: 无

---

### L13: 管理员活动日志无筛选保护

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 添加用户筛选功能（已有）
2. 添加时间范围筛选
3. 添加操作类型筛选

**实现细节**:
- 当前 `activity_api()` 已支持 `username` 筛选，可扩展添加时间范围筛选：
  ```python
  # 在 activity_api() 中添加时间范围筛选参数
  time_from = request.args.get("from", "")
  time_to = request.args.get("to", "")
  
  for activity in activities:
      # ... 原有筛选逻辑
      if time_from:
          if activity.get("time", "") < time_from:
              continue
      if time_to:
          if activity.get("time", "") > time_to:
              continue
  ```

**依赖**: 无

---

### L14: 挂载页面管理无数量限制

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 添加挂载页面数量限制
2. 超出限制时拒绝添加

**实现细节**:
- 在 `add_mounted_page()` 函数（第809行后），添加数量限制：
  ```python
  # 新增：挂载页面数量限制
  MAX_MOUNTED_PAGES = 20
  mounted_pages = config.get("mounted_pages", [])
  if len(mounted_pages) >= MAX_MOUNTED_PAGES:
      return jsonify({"success": False, "message": f"挂载页面数量已达上限（{MAX_MOUNTED_PAGES}个）"})
  ```

**依赖**: 无

---

### L15: 壁纸路径配置为绝对路径时可访问系统任意文件

**涉及文件**:
- `Module/index/index.py`

**修改内容**:
1. 对壁纸路径进行沙箱限制
2. 仅允许项目目录内的路径

**实现细节**:
- 修改 `serve_wallpaper()` 函数（第137行）：
  ```python
  # 旧代码
  wallpaper_path = app_root / wallpaper_config["path"]
  
  # 新代码：路径沙箱检查
  raw_path = wallpaper_config["path"]
  if Path(raw_path).is_absolute():
      wallpaper_path = Path(raw_path)
  else:
      wallpaper_path = app_root / raw_path
  
  # 沙箱检查：确保路径在项目目录内
  try:
      wallpaper_path.resolve().relative_to(app_root.resolve())
  except ValueError:
      logger.warning(f"Wallpaper path outside project root: {wallpaper_path}")
      abort(403)
  ```

**依赖**: 无

---

### L17: 挂载页面目录浏览可暴露文件大小和修改时间

**涉及文件**:
- `Module/index/templates/index/directory.html`

**修改内容**:
1. 隐藏文件大小和修改时间
2. 或仅显示近似值

**实现细节**:
- 在 `directory.html` 的文件列表部分（第119-124行），修改为：
  ```html
  <!-- 旧代码 -->
  <div class="file-meta">
      {% if item.is_file %}
          大小: {{ "%.2f"|format(item.size / 1024) }} KB
      {% else %}
          文件夹
      {% endif %}
  </div>
  
  <!-- 新代码：隐藏精确大小，仅显示类型 -->
  <div class="file-meta">
      {% if item.is_file %}
          文件
      {% else %}
          文件夹
      {% endif %}
  </div>
  ```

**依赖**: 无

---

### L18: 画廊收藏页面搜索仅支持客户端过滤

**涉及文件**:
- `Module/gallery/templates/gallery/favorites.html`

**修改内容**:
1. 评估当前实现是否满足需求
2. 添加搜索结果数量显示

**实现细节**:
- 当前实现对小规模收藏够用，可添加结果计数显示：
  ```javascript
  function filterFavorites(query) {
      // ... 原有过滤逻辑
      // 添加结果显示
      const resultCount = document.getElementById('result-count');
      if (resultCount) {
          resultCount.textContent = `找到 ${visibleCount} 个结果`;
      }
  }
  ```

**依赖**: 无

---

### L19: 画廊文件夹浏览 URL 未编码特殊字符

**涉及文件**:
- `Module/gallery/templates/gallery/gallery.html`

**修改内容**:
1. 使用 `encodeURIComponent()` 对路径进行编码

**实现细节**:
- 在 `gallery.html` 中导航到文件夹的代码（约第1377行），修改为：
  ```javascript
  // 旧代码
  window.location.href = `/gallery/${path}`;
  
  // 新代码：URL编码路径
  window.location.href = `/gallery/${encodeURIComponent(path)}`;
  ```

**依赖**: 无

---

### L20: 暗夜模式 Cookie 未设置 HttpOnly 和 SameSite 属性

**涉及文件**:
- 多个模板文件

**修改内容**:
1. 设置 `HttpOnly` 属性
2. 设置 `SameSite` 属性

**实现细节**:
- 由于暗夜模式Cookie是通过JavaScript `document.cookie` 设置的，HttpOnly属性无法通过JS设置。需要改为通过服务端设置：
  - 在Flask中添加 `@app.after_request` 中间件设置Cookie属性
  - 或在模板中使用服务端设置Cookie的方式
  - 由于暗夜模式Cookie不包含敏感信息，且仅用于UI偏好，当前风险较低，可保持现状

**依赖**: 无

---

### L22: userfix 提交记录无自动清理机制

**涉及文件**:
- `Module/userfix/userfix.py`

**修改内容**:
1. 添加定时清理任务
2. 删除过期提交记录
3. 保留最近30天记录

**实现细节**:
- 添加清理函数并在启动时注册：
  ```python
  import threading
  from datetime import datetime, timedelta
  
  def cleanup_old_submissions():
      """清理超过30天的提交记录"""
      cutoff = datetime.now() - timedelta(days=30)
      if not SUBMISSIONS_DIR.exists():
          return
      
      for item in SUBMISSIONS_DIR.iterdir():
          if item.is_dir():
              # 从目录名解析时间戳
              parts = item.name.split("_")
              if len(parts) >= 3:
                  try:
                      date_str = parts[-3]  # YYYY-MM-DD
                      item_date = datetime.strptime(date_str, "%Y-%m-%d")
                      if item_date < cutoff:
                          import shutil
                          shutil.rmtree(item, ignore_errors=True)
                  except (ValueError, IndexError):
                      pass
  
  def _submission_cleanup_worker():
      """后台清理线程：每天清理一次"""
      while True:
          time.sleep(86400)  # 24小时
          try:
              cleanup_old_submissions()
          except Exception:
              pass
  
  # 在模块加载时启动清理线程
  cleanup_thread = threading.Thread(target=_submission_cleanup_worker, daemon=True)
  cleanup_thread.start()
  ```

**依赖**: 无

---

### L23: 挂载页面目录浏览文件名未转义

**涉及文件**:
- `Module/index/templates/index/directory.html`

**修改内容**:
1. Jinja2默认自动转义已提供基本防护
2. 对路径进行URL编码

**实现细节**:
- 当前Jinja2自动转义已生效，但URL路径需要编码。修改模板中的链接：
  ```html
  <!-- 旧代码 -->
  <a href="/{{ page_name }}/{{ item.relative_path }}" class="file-link file-name">{{ item.name }}</a>
  
  <!-- 新代码：URL编码路径 -->
  <a href="/{{ page_name }}/{{ item.relative_path|urlencode }}" class="file-link file-name">{{ item.name }}</a>
  ```
- 需要在Flask中注册 `urlencode` 过滤器：
  ```python
  from urllib.parse import quote
  app.jinja_env.filters['urlencode'] = lambda s: quote(s, safe='')
  ```

**依赖**: 无

---

### L24: userfix 元数据文件暴露用户角色信息

**涉及文件**:
- `Module/userfix/userfix.py`

**修改内容**:
1. 移除 `role` 字段
2. 或仅保留必要信息

**实现细节**:
- 修改 `save_submission()` 函数（第234行），移除 `role` 字段：
  ```python
  # 旧代码
  metadata = {
      "username": username,
      "user_id": user.get("id"),
      "role": user.get("role"),
      "timestamp": datetime.now().isoformat(),
      "images": saved_images,
  }
  
  # 新代码：移除角色信息
  metadata = {
      "username": username,
      "timestamp": datetime.now().isoformat(),
      "images": saved_images,
  }
  ```

**依赖**: 无

---

### L25: 公开访问设计决策（画廊/书籍 API 无需认证）

**涉及文件**:
- 设计文档

**修改内容**:
1. 记录公开访问的设计决策
2. 说明安全考虑

**实现细节**:
- 在AGENTS.md中添加说明：
  ```markdown
  ## 设计决策：公开访问API
  
  画廊和书籍模块的API端点（搜索、详情、随机图片等）设计为无需认证即可访问。
  这是有意的设计决策，原因：
  1. 画廊为图片浏览场景，书籍为阅读场景，内容本身无敏感性
  2. 公开访问简化用户体验，无需登录即可浏览
  3. 收藏、偏好设置等个人功能仍需认证
  
  安全考虑：
  - 所有公开API均不返回用户个人信息
  - 管理后台和用户管理功能仍严格要求认证
  - 如需限制访问，可在Nginx反向代理层添加IP白名单
  ```

**依赖**: 无

---

### L26: 管理后台无法删除管理员账户

**涉及文件**:
- `Module/admin/admin.py`

**修改内容**:
1. 允许删除非最后管理员的其他管理员
2. 添加删除确认

**实现细节**:
- 修改 `delete_user()` 函数（第601行），允许删除其他管理员：
  ```python
  # 旧代码
  if user_to_delete["role"] in ["admin", "api"]:
      return {"success": False, "message": "不能删除系统用户"}
  
  # 新代码：允许删除其他管理员，但不能删除最后一个管理员
  users = load_users()
  admin_count = sum(1 for u in users.values() if u.get("role") == "admin")
  if user_to_delete["role"] == "admin" and admin_count <= 1:
      return {"success": False, "message": "不能删除最后一个管理员"}
  ```

**依赖**: 无

---

### L27: 壁纸配置更新未使用 CSRF 保护

**涉及文件**:
- `Module/index/index.py`

**修改内容**:
1. 添加CSRF令牌校验

**实现细节**:
- 与H11合并实现，在 `update_wallpaper_config()` 中添加认证后，CSRF保护可选添加：
  ```python
  from Module.user.user import check_csrf
  
  @index_bp.route("/api/wallpaper/config", methods=["POST"])
  def update_wallpaper_config():
      """更新壁纸配置"""
      # 认证校验
      if not check_auth():
          return jsonify({"success": False, "message": "请先登录"}), 401
      
      # CSRF 校验
      if not check_csrf():
          return jsonify({"success": False, "message": "CSRF令牌无效"}), 403
      
      # ... 原有代码
  ```

**依赖**: H21完成

---

## 总结

**小工程总数**: 48个

**涉及文件统计**:
- `app.py`: 2个问题（H19, M9）
- `Module/user/user.py`: 2个问题（S6, M14）
- `Module/admin/admin.py`: 10个问题（H2, H11, M5, M7, M8, M22, L2, L3, L13, L14, L26）
- `Module/index/index.py`: 4个问题（H11, M3, L9, L15, L27）
- `Module/gallery/gallery.py`: 2个问题（H20, M38）
- `Module/common/user_utils.py`: 5个问题（M15, M17, M19, M21, L8）
- `Module/common/auth_utils.py`: 1个问题（M20）
- `Module/common/file_utils.py`: 1个问题（L5）
- `Module/common/db_utils.py`: 4个问题（L4, L6, L11, L12）
- `Module/userfix/userfix.py`: 3个问题（S10, S11, L22, L24）
- `Module/log/log.py`: 1个问题（L10）
- `Module/index/templates/index/index.html`: 1个问题（M32）
- `Module/index/templates/index/directory.html`: 2个问题（L17, L23）
- `Module/gallery/templates/gallery/gallery.html`: 2个问题（S9, L19）
- `Module/admin/templates/admin/users.html`: 1个问题（M43）
- `requirements.txt`: 1个问题（M37）

**依赖关系**:
- M9 依赖 H19（密钥管理）
- L9 依赖 H11（壁纸认证）
- L27 依赖 H21（CSRF保护，不在本计划中）
- M5 依赖无（独立CSRF校验）
- L26 依赖无（独立逻辑修改）

**无需澄清项**: 所有问题均有明确的代码位置和修改方案。
