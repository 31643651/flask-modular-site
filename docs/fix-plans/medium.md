# 修复方案 - 中工程

## 工程说明

中工程需要修改现有代码，改动适中，通常涉及多个文件但每个改动不大。包括修改现有函数逻辑、添加新的校验/验证、修改现有模板的交互等。

---

## 问题列表

### H13: 挂载页面可指向任意文件系统路径

**涉及文件**: 
- `Module/admin/admin.py` (添加路径白名单校验)
- `Module/json/config.json` (添加敏感路径配置)

**修改内容**: 
在 `add_mounted_page` 端点添加路径沙箱校验，禁止挂载系统敏感目录。维护敏感路径列表。

**实现细节**:
1. 在 `admin.py` 中新增模块级常量 `SENSITIVE_PATHS`，包含 Windows 和 Linux 敏感路径前缀：
   ```python
   SENSITIVE_PATHS = [
       "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
       "C:\\Users", "/etc", "/proc", "/sys", "/bin", "/sbin", "/root"
   ]
   ```
2. 在 `add_mounted_page()` 函数（`admin.py:788-792`）中，路径存在性检查之后、判断文件/文件夹之前，添加路径安全校验：
   ```python
   # 路径安全校验：禁止挂载系统敏感路径
   resolved_file = file_path.resolve()
   for sensitive in SENSITIVE_PATHS:
       try:
           resolved_file.relative_to(Path(sensitive).resolve())
           return jsonify({"success": False, "message": f"禁止挂载系统敏感路径: {sensitive}"})
       except ValueError:
           continue
   ```
3. 在 `Module/json/config.json` 中增加 `sensitive_paths` 字段维护敏感路径列表（可选，便于运维修改）

**依赖**: 无

---

### S1: 画廊空路径导致项目根目录暴露

**涉及文件**: 
- `Module/gallery/gallery.py` (修改 `get_gallery_root()` 函数)

**修改内容**: 
在 `get_gallery_root()` 中增加空值/空字符串校验，防止 `Path("")` 解析为项目根目录。

**实现细节**:
1. 修改 `gallery.py:141-142`，在 `config.get()` 获取路径后添加空值校验：
   ```python
   gallery_path = config.get("paths", {}).get("gallery_root_path", "gallery_images")
   if not gallery_path:
       import structlog
       structlog.get_logger(__name__).warning("gallery_root_path_empty")
       gallery_path = "gallery_images"
   ```
2. 当路径为空字符串或 None 时，回退到默认值 `"gallery_images"`，并在日志中记录警告

**依赖**: 无

---

### S2: 空值 (null) 导致画廊路由 TypeError 崩溃

**涉及文件**: 
- `Module/gallery/gallery.py` (修改路径处理逻辑)

**修改内容**: 
在 `get_gallery_root()` 中添加 `None` 类型检查，防止 `Path(None)` 抛出 `TypeError`。

**实现细节**:
1. 修改 `gallery.py:141-142`，在获取 `gallery_path` 后添加类型检查：
   ```python
   gallery_path = config.get("paths", {}).get("gallery_root_path", "gallery_images")
   if gallery_path is None:
       import structlog
       structlog.get_logger(__name__).warning("gallery_root_path_is_null")
       gallery_path = "gallery_images"
   if not isinstance(gallery_path, str):
       import structlog
       structlog.get_logger(__name__).warning("gallery_root_path_wrong_type", type=type(gallery_path).__name__)
       gallery_path = "gallery_images"
   ```
2. 合并到 S1 的修改中，作为同一函数的防御性检查

**依赖**: S1完成

---

### S3: 数值类型路径导致 TypeError 崩溃

**涉及文件**: 
- `Module/gallery/gallery.py` (修改路径处理逻辑)

**修改内容**: 
在 `get_gallery_root()` 中检查 `gallery_path` 是否为字符串类型，数值类型时转换或拒绝。

**实现细节**:
1. 合并到 S2 的修改中，使用 `isinstance(gallery_path, str)` 统一检查类型
2. 非字符串类型（int/float/bool）时回退到默认值并记录警告日志

**依赖**: S1完成

---

### S4: 配置更新接口无路径校验

**涉及文件**: 
- `Module/admin/admin.py` (修改 `update_config` 端点)

**修改内容**: 
在 `update_config` 端点添加路径值的空值、null、类型校验。

**实现细节**:
1. 在 `admin.py:714-718` 的路径更新循环中，添加校验逻辑：
   ```python
   if "paths" in data:
       if "paths" not in config:
           config["paths"] = {}
       for key, value in data["paths"].items():
           # 路径值校验
           if value is None or (isinstance(value, str) and not value.strip()):
               return jsonify({"success": False, "message": f"路径 {key} 不能为空"})
           if not isinstance(value, str):
               return jsonify({"success": False, "message": f"路径 {key} 必须是字符串类型"})
           config["paths"][key] = value
   ```
2. 对 wallpaper 路径同样添加校验
3. 同时合并 M23 的配置键白名单校验（见 M23）

**依赖**: S1、S2、S3完成

---

### H1: 无路径遍历限制，可挂载任意文件系统路径

**涉及文件**: 
- `Module/admin/admin.py` (添加路径遍历限制)

**修改内容**: 
在 `add_mounted_page` 端点添加路径遍历限制，使用 `pathlib` 规范化后验证。

**实现细节**:
1. 在 `admin.py` 的 `add_mounted_page()` 中，路径存在性检查之后，使用 `resolve()` + `relative_to()` 验证：
   ```python
   # 路径遍历防护：验证规范化后的路径不包含 ..
   raw_path = Path(path)
   file_path = raw_path if raw_path.is_absolute() else app_root / raw_path
   resolved = file_path.resolve()
   # 检查是否在允许的目录内（项目目录或白名单目录）
   try:
       resolved.relative_to(app_root)
   except ValueError:
       # 不在项目目录内，需要额外验证是否在允许的外部目录
       # （此处可根据白名单策略决定是否放行）
       pass
   ```
2. 拒绝包含 `..` 的原始路径（双重保险）：
   ```python
   if ".." in path:
       return jsonify({"success": False, "message": "路径不允许包含 .."})
   ```

**依赖**: H13完成

---

### H3: TOCTOU 竞态条件

**涉及文件**: 
- `Module/admin/admin.py` (修改配置更新逻辑)

**修改内容**: 
在 `update_config` 端点使用 `read_json_file` + `write_json_file` 的文件锁机制，确保读写原子性。

**实现细节**:
1. 当前 `update_config` 已使用 `read_json_file`（有文件锁）和 `write_json_file`（有文件锁），但读写之间没有持有同一把锁
2. 修改为使用 `file_utils.py` 的锁机制，在同一个锁内完成读取-修改-写入：
   ```python
   from Module.common.file_utils import _get_file_lock
   lock = _get_file_lock(CONFIG_FILE)
   with lock:
       config = read_json_file(CONFIG_FILE, default={"paths": {}, "wallpaper": {}})
       # 修改 config...
       write_json_file(CONFIG_FILE, config, ensure_ascii=False, indent=2)
   ```
3. 这确保了读取-修改-写入在同一临界区内完成

**依赖**: 无

---

### H4: 管理员验证码可暴力破解 — 无尝试次数限制

**涉及文件**: 
- `Module/user/user.py` (添加尝试次数限制)

**修改内容**: 
为 `/user/verify` 端点增加尝试次数限制（5次），超限后重新生成验证码或锁定。

**实现细节**:
1. 在 `user.py` 中新增验证码尝试限制数据结构（复用登录失败的模式）：
   ```python
   _verify_failures = {}  # username -> (count, first_ts)
   _VERIFY_FAIL_LIMIT = 5
   _VERIFY_FAIL_WINDOW = 300  # 5分钟
   ```
2. 在 `verify()` 函数的 POST 处理中，验证码错误时记录失败次数：
   ```python
   if code == session.get("verify_code"):
       # 成功，清除失败计数
       _verify_failures.pop(username, None)
       session["verified"] = True
       ...
   else:
       # 失败，累计计数
       now = time.time()
       count, first = _verify_failures.get(username, (0, now))
       if now - first >= _VERIFY_FAIL_WINDOW:
           _verify_failures[username] = (1, now)
           count = 0
       count += 1
       _verify_failures[username] = (count, first)
       if count >= _VERIFY_FAIL_LIMIT:
           # 超限：重新生成验证码
           verify_code = generate_verify_code()
           session["verify_code"] = verify_code
           log_verify_code(verify_code)
           _verify_failures.pop(username, None)
           return render_template("user/verify.html", error="尝试次数过多，验证码已重新生成", csrf_token=generate_csrf_token())
       return render_template("user/verify.html", error=f"验证码错误（剩余 {5 - count} 次机会）", csrf_token=generate_csrf_token())
   ```
3. 添加 IP 级别的速率限制日志记录

**依赖**: 无

---

### H5: 画廊路径清理函数可被绕过 — 目录遍历

**涉及文件**: 
- `Module/gallery/gallery.py` (修改 `sanitize_path()` 函数)

**修改内容**: 
使用循环替换或 `pathlib` 规范化替代单次 `replace`，彻底消除 `..` 遍历绕过。

**实现细节**:
1. 修改 `gallery.py:222-236` 的 `sanitize_path()` 函数：
   ```python
   def sanitize_path(path):
       """清理路径，防止目录遍历攻击"""
       # 循环替换直到稳定，防止 ....// 绕过
       while ".." in path:
           path = path.replace("..", "")
       path = path.replace("~", "")
       # 规范化双斜杠
       while "//" in path:
           path = path.replace("//", "/")
       path = path.strip("/")
       return path
   ```
2. 或者使用更安全的 `pathlib` 方式：
   ```python
   def sanitize_path(path):
       """清理路径，防止目录遍历攻击"""
       import re
       # 移除所有 .. 片段
       parts = [p for p in Path(path).parts if p != ".."]
       path = str(Path(*parts)) if parts else ""
       return path.strip("/")
   ```
3. 添加日志记录路径遍历尝试：
   ```python
   if ".." in path:
       import structlog
       structlog.get_logger(__name__).warning("path_traversal_attempt", path=path)
   ```

**依赖**: 无

---

### H8: X-Forwarded-For 头伪造导致 IP 欺骗

**涉及文件**: 
- `Module/admin/admin.py` (修改 `get_real_ip()` 函数)

**修改内容**: 
仅在可信反向代理后使用时信任 X-Forwarded-For 头，添加配置开关。

**实现细节**:
1. 在 `admin.py:254-282` 修改 `get_real_ip()` 函数：
   ```python
   def get_real_ip(request):
       """获取真实的客户端 IP 地址"""
       # 从配置中读取是否信任代理头（默认不信任）
       from Module.common.file_utils import read_json_file_cached
       config = read_json_file_cached(CONFIG_FILE, default={}, ttl=5)
       trust_proxy = config.get("server", {}).get("trust_proxy", False)
       
       if trust_proxy:
           if "X-Forwarded-For" in request.headers:
               forwarded_for = request.headers["X-Forwarded-For"]
               ips = [ip.strip() for ip in forwarded_for.split(",")]
               if ips and ips[0]:
                   return ips[0]
           if "X-Real-IP" in request.headers:
               real_ip = request.headers["X-Real-IP"]
               if real_ip:
                   return real_ip
       
       return request.remote_addr
   ```
2. 在 `config.json` 中添加 `server.trust_proxy` 配置项（默认 false）
3. 记录 IP 伪造尝试日志（当非信任模式下收到代理头时）

**依赖**: 无

---

### H9: 数据库事务标志线程安全问题

**涉及文件**: 
- `Module/common/db_utils.py` (修改事务标志存储)

**修改内容**: 
使用 `threading.local()` 存储线程本地事务状态，替代模块级变量。

**实现细节**:
1. 修改 `db_utils.py:27`，将 `_in_transaction` 改为线程本地存储：
   ```python
   # 线程本地事务状态
   _thread_local = threading.local()
   
   def _get_in_transaction():
       return getattr(_thread_local, '_in_transaction', False)
   
   def _set_in_transaction(value):
       _thread_local._in_transaction = value
   ```
2. 修改 `transaction()` 上下文管理器（`db_utils.py:226-243`）：
   ```python
   @contextlib.contextmanager
   def transaction():
       with _lock:
           _set_in_transaction(True)
           try:
               yield
               get_connection().commit()
           except Exception:
               get_connection().rollback()
               raise
           finally:
               _set_in_transaction(False)
   ```
3. 修改 `execute()` 和 `executemany()` 中的 `if not _in_transaction` 为 `if not _get_in_transaction()`
4. 修改 `reset_state()` 中的 `_in_transaction = False` 为 `_set_in_transaction(False)`

**依赖**: 无

---

### H10: 文件工具 symlink 竞态条件

**涉及文件**: 
- `Module/common/file_utils.py` (添加符号链接检查)

**修改内容**: 
在写入前检查目标路径是否为符号链接，防止 TOCTOU 攻击。

**实现细节**:
1. 在 `file_utils.py:66-104` 的 `write_json_file()` 中，创建临时文件前检查目标路径：
   ```python
   def write_json_file(file_path, data, ensure_ascii=False, indent=2):
       file_path = Path(file_path)
       lock = _get_file_lock(file_path)
       with lock:
           try:
               file_path.parent.mkdir(parents=True, exist_ok=True)
               
               # 符号链接检查：防止通过 symlink 写入任意文件
               if file_path.exists() and file_path.is_symlink():
                   import structlog
                   structlog.get_logger(__name__).warning("symlink_detected", path=str(file_path))
                   return False
               
               temp_path = file_path.with_suffix('.tmp')
               with open(temp_path, 'w', encoding='utf-8') as f:
                   json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
               temp_path.replace(file_path)
               invalidate_json_cache(file_path)
               return True
           except Exception as e:
               if temp_path.exists():
                   try:
                       temp_path.unlink()
                   except:
                       pass
               return False
   ```

**依赖**: 无

---

### H12: 管理员用户列表 API 泄露密码哈希

**涉及文件**: 
- `Module/common/user_utils.py` (修改 `load_users()` 函数)
- `Module/admin/admin.py` (修改调用点)

**修改内容**: 
`load_users()` 默认不返回密码字段，创建专门的 `load_users_safe()` 函数用于非认证场景。

**实现细节**:
1. 在 `user_utils.py` 中新增 `load_users_safe()` 函数：
   ```python
   def load_users_safe():
       """加载用户数据（不含密码字段，用于管理后台展示等）"""
       users = load_users()
       return {
           username: {k: v for k, v in user.items() if k != "password"}
           for username, user in users.items()
       }
   ```
2. 修改 `admin.py` 中所有不需要密码的调用点（如 `users()` 页面）使用 `load_users_safe()`：
   - `admin.py:428` (`users()` 路由)：`users = load_users_safe()`
   - `admin.py:368` (`dashboard()` 路由)：`users = load_users_safe()`
3. 保持 `load_users()` 原样用于需要密码的场景（如 `verify_user()`、`require_admin()`）

**依赖**: 无

---

### M1: 空白字符导致静默失败

**涉及文件**: 
- `Module/gallery/gallery.py` (修改空白字符处理)

**修改内容**: 
在 `get_gallery_root()` 中检查空白字符，返回明确错误或转换为默认值。

**实现细节**:
1. 合并到 S1/S2/S3 的修改中，在 `get_gallery_root()` 中添加：
   ```python
   if isinstance(gallery_path, str) and not gallery_path.strip():
       # 纯空白字符，回退到默认值
       import structlog
       structlog.get_logger(__name__).warning("gallery_root_path_whitespace")
       gallery_path = "gallery_images"
   ```

**依赖**: S1完成

---

### M2: 缺失配置键使用不存在的默认值

**涉及文件**: 
- `Module/gallery/gallery.py` (修改默认值处理)

**修改内容**: 
当缺失 `gallery_root_path` 键时，检查默认目录 `"gallery_images"` 是否存在，不存在时创建。

**实现细节**:
1. 在 `gallery.py` 的 `get_gallery_root()` 中，解析路径后检查目录存在性：
   ```python
   def get_gallery_root():
       config = load_config()
       gallery_path = config.get("paths", {}).get("gallery_root_path", "gallery_images")
       # ... 类型检查 ...
       path = Path(gallery_path)
       if not path.is_absolute():
           path = BASE_DIR / path
       resolved = path.resolve()
       
       # 默认目录不存在时自动创建
       if not resolved.exists():
           import structlog
           structlog.get_logger(__name__).warning("gallery_root_not_exist", path=str(resolved))
           resolved.mkdir(parents=True, exist_ok=True)
       
       return resolved
   ```

**依赖**: 无

---

### M4: 壁纸绝对路径可绕过应用根目录

**涉及文件**: 
- `Module/index/index.py` (添加路径沙箱限制)

**修改内容**: 
对壁纸路径进行沙箱限制，仅允许项目目录内的路径。

**实现细节**:
1. 在 `index.py:137` 修改 `serve_wallpaper()` 中的路径解析：
   ```python
   wallpaper_path = app_root / wallpaper_config["path"]
   # 沙箱检查：确保最终路径在项目目录内
   try:
       resolved_wallpaper = wallpaper_path.resolve()
       resolved_wallpaper.relative_to(app_root.resolve())
   except ValueError:
       # 绝对路径在项目目录外，拒绝访问
       abort(403)
   ```
2. 添加日志记录路径绕过尝试

**依赖**: 无

---

### M10: 会话 Cookie 缺少安全属性

**涉及文件**: 
- `app.py` (添加 Cookie 安全配置)

**修改内容**: 
添加 `SESSION_COOKIE_HTTPONLY`、`SESSION_COOKIE_SECURE`（生产模式）、`SESSION_COOKIE_SAMESITE`。

**实现细节**:
1. 在 `app.py:50` 之后添加 Cookie 安全配置：
   ```python
   app.config["SESSION_COOKIE_HTTPONLY"] = True
   app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
   if production_mode:
       app.config["SESSION_COOKIE_SECURE"] = True
   ```
2. 验证暗夜模式 Cookie 不受影响（JavaScript 操作的 Cookie 不能设置 HttpOnly）

**依赖**: 无

---

### M13: 画廊随机图片与搜索 API 存在拒绝服务风险

**涉及文件**: 
- `Module/gallery/gallery.py` (添加递归限制)

**修改内容**: 
对递归函数添加深度限制和超时机制。

**实现细节**:
1. 修改 `get_all_subfolders_recursive()` 和 `get_all_images_recursive()`，添加深度参数：
   ```python
   _MAX_RECURSION_DEPTH = 10  # 最大递归深度
   
   def get_all_subfolders_recursive(folder_path, _depth=0):
       """递归获取所有子文件夹（带深度限制）"""
       if _depth >= _MAX_RECURSION_DEPTH:
           return []
       scan = _get_folder_scan(folder_path)
       if scan is None:
           return []
       _, subfolders = scan
       result = list(subfolders)
       for sub in subfolders:
           result.extend(get_all_subfolders_recursive(sub, _depth + 1))
       return result
   
   def get_all_images_recursive(folder_path, _depth=0):
       """递归获取所有图片（带深度限制）"""
       if _depth >= _MAX_RECURSION_DEPTH:
           return []
       scan = _get_folder_scan(folder_path)
       if scan is None:
           return []
       images, subfolders = scan
       result = list(images)
       for sub in subfolders:
           result.extend(get_all_images_recursive(sub, _depth + 1))
       return result
   ```
2. 在 `gallery_random_images()` 和 `gallery_search()` 中添加超时机制：
   ```python
   import signal
   
   def timeout_handler(signum, frame):
       raise TimeoutError("Gallery scan timeout")
   
   # 在递归扫描前设置超时
   signal.signal(signal.SIGALRM, timeout_handler)
   signal.alarm(5)  # 5秒超时
   try:
       all_subfolders = get_all_subfolders_recursive(gallery_root)
   except TimeoutError:
       return jsonify({"error": "扫描超时"}), 500
   finally:
       signal.alarm(0)
   ```
3. 注意：`signal.SIGALRM` 在 Windows 下不可用，需要使用 `threading.Timer` 作为替代

**依赖**: M11完成

---

### M16: 文件锁字典内存泄漏

**涉及文件**: 
- `Module/common/file_utils.py` (添加锁清理机制)

**修改内容**: 
实现 LRU 淘汰策略，定期清理未使用的锁。

**实现细节**:
1. 修改 `file_utils.py`，为锁字典添加 LRU 淘汰：
   ```python
   import collections
   
   # 使用 OrderedDict 实现 LRU
   _file_locks = collections.OrderedDict()
   _locks_lock = threading.Lock()
   _LOCKS_MAX = 1000  # 最大锁数量
   
   def _get_file_lock(file_path):
       abs_path = str(file_path.absolute())
       with _locks_lock:
           if abs_path in _file_locks:
               # 移到末尾（最近使用）
               _file_locks.move_to_end(abs_path)
               return _file_locks[abs_path]
           # 超过上限时移除最旧的锁
           if len(_file_locks) >= _LOCKS_MAX:
               _file_locks.popitem(last=False)
           lock = threading.Lock()
           _file_locks[abs_path] = lock
           return lock
   ```

**依赖**: 无

---

### M18: User-Agent 解析可被绕过

**涉及文件**: 
- `Module/common/user_utils.py` (改进 UA 解析)

**修改内容**: 
使用正则表达式替代简单字符串匹配，提高解析准确性。

**实现细节**:
1. 修改 `user_utils.py:277-338` 的 `parse_user_agent()` 函数，使用正则表达式：
   ```python
   import re
   
   def parse_user_agent(user_agent_string):
       ua = user_agent_string
       
       # 设备类型检测（使用正则，忽略大小写）
       device_type = "未知设备"
       if re.search(r'(?i)android', ua):
           device_type = "Android"
       elif re.search(r'(?i)(iphone|ipad|ipod)', ua):
           device_type = "iOS"
       elif re.search(r'(?i)windows', ua):
           device_type = "Windows"
       elif re.search(r'(?i)(macintosh|mac os x)', ua):
           device_type = "Mac"
       elif re.search(r'(?i)linux', ua):
           device_type = "Linux"
       
       # 操作系统检测
       os_name = "未知操作系统"
       if re.search(r'(?i)android', ua):
           os_name = "Android"
       elif re.search(r'(?i)(iphone|ipad)', ua):
           os_name = "iOS"
       elif re.search(r'(?i)windows nt 10\.0', ua):
           os_name = "Windows 10/11"
       elif re.search(r'(?i)windows nt 6\.1', ua):
           os_name = "Windows 7"
       elif re.search(r'(?i)windows nt 6\.[23]', ua):
           os_name = "Windows 8/8.1"
       elif re.search(r'(?i)windows', ua):
           os_name = "Windows"
       elif re.search(r'(?i)mac os x', ua):
           os_name = "macOS"
       elif re.search(r'(?i)linux', ua):
           os_name = "Linux"
       
       # 浏览器检测（注意顺序：Edge 必须在 Chrome 之前检测）
       browser = "未知浏览器"
       if re.search(r'(?i)edg/', ua):
           browser = "Edge"
       elif re.search(r'(?i)chrome/', ua) and not re.search(r'(?i)chromium', ua):
           browser = "Chrome"
       elif re.search(r'(?i)firefox/', ua):
           browser = "Firefox"
       elif re.search(r'(?i)safari/', ua) and not re.search(r'(?i)chrome/', ua):
           browser = "Safari"
       elif re.search(r'(?i)(opera|opr)/', ua):
           browser = "Opera"
       elif re.search(r'(?i)(msie|trident/)', ua):
           browser = "Internet Explorer"
       
       return {"device_type": device_type, "os": os_name, "browser": browser}
   ```

**依赖**: 无

---

### M23: 配置更新接口可注入任意 JSON 键值

**涉及文件**: 
- `Module/admin/admin.py` (添加配置键白名单)

**修改内容**: 
仅允许更新已知的配置键（`paths`、`wallpaper`、`mounted_pages`），拒绝未知键。

**实现细节**:
1. 在 `admin.py:703-728` 的 `update_config()` 中添加配置键白名单校验：
   ```python
   # 允许更新的顶级配置键
   ALLOWED_CONFIG_KEYS = {"paths", "wallpaper", "mounted_pages"}
   
   def update_config():
       # ...
       data = request.get_json() or {}
       if "config" in data and isinstance(data.get("config"), dict):
           data = data["config"]
       
       # 配置键白名单校验
       unknown_keys = set(data.keys()) - ALLOWED_CONFIG_KEYS
       if unknown_keys:
           return jsonify({"success": False, "message": f"不允许更新以下配置项: {', '.join(unknown_keys)}"})
       
       # 允许更新的 paths 子键
       ALLOWED_PATH_KEYS = {"book_data_path", "book_static_path", "gallery_root_path"}
       if "paths" in data:
           unknown_path_keys = set(data["paths"].keys()) - ALLOWED_PATH_KEYS
           if unknown_path_keys:
               return jsonify({"success": False, "message": f"不允许更新以下路径项: {', '.join(unknown_path_keys)}"})
       
       # 允许更新的 wallpaper 子键
       ALLOWED_WALLPAPER_KEYS = {"enabled", "path"}
       if "wallpaper" in data:
           unknown_wp_keys = set(data["wallpaper"].keys()) - ALLOWED_WALLPAPER_KEYS
           if unknown_wp_keys:
               return jsonify({"success": False, "message": f"不允许更新以下壁纸项: {', '.join(unknown_wp_keys)}"})
       
       # 继续原有逻辑...
   ```

**依赖**: 无

---

### M26: 错误响应泄露内部异常信息和路径

**涉及文件**: 
- `Module/admin/admin.py` (修改错误处理)

**修改内容**: 
生产环境仅返回通用错误信息，详细错误记录到日志。

**实现细节**:
1. 在 `admin.py` 中修改所有 `return {"success": False, "message": str(e)}` 为：
   ```python
   import logging
   _admin_logger = logging.getLogger(__name__)
   
   # 通用错误响应（不泄露内部信息）
   def _error_response(message="操作失败", log_error=None):
       if log_error:
           _admin_logger.error(f"{message}: {log_error}")
       return jsonify({"success": False, "message": message})
   ```
2. 替换所有错误处理：
   - `toggle_user_status` (L513-514): `return _error_response("切换状态失败", str(e))`
   - `register_user` (L572-573): `return _error_response("注册用户失败", str(e))`
   - `delete_user` (L618-619): `return _error_response("删除用户失败", str(e))`
   - `restart_server` (L666-667): `return _error_response("重启服务器失败", str(e))`
   - `update_config` (L734-735): `return _error_response("更新配置失败", str(e))`
   - `add_mounted_page` (L847-851): `return _error_response("挂载页面失败", str(e))`
   - `delete_mounted_page` (L893-894): `return _error_response("删除页面失败", str(e))`
   - `get_config` (L686-687): `return jsonify({"success": False, "message": "获取配置失败"})`

**依赖**: 无

---

### M27: 用户登出未使其他会话失效

**涉及文件**: 
- `Module/user/user.py` (修改登出逻辑)
- `Module/admin/admin.py` (会话管理)

**修改内容**: 
登出时在数据库中删除该用户的活动会话记录。

**实现细节**:
1. 在 `user.py:270-293` 的 `logout()` 中，`session.clear()` 之前删除活动会话：
   ```python
   def logout():
       if not check_csrf():
           return render_template("user/login.html", error="请求已过期", csrf_token=generate_csrf_token()), 400
       
       username = session.get("username")
       
       # 记录登出活动
       add_activity(username, "用户退出登录", request.remote_addr)
       
       # 删除活动会话记录，使其他设备的会话失效
       if username:
           from Module.common.db_utils import execute
           execute("DELETE FROM active_sessions WHERE username = ?", (username,))
       
       session.clear()
       return redirect(url_for("user.login"))
   ```

**依赖**: 无

---

### M29: 画廊 SVG 文件服务可执行嵌入式 JavaScript

**涉及文件**: 
- `Module/gallery/gallery.py` (修改 SVG 处理)

**修改内容**: 
对 SVG 文件添加 `Content-Security-Policy` 头禁止内联脚本，或使用 `Content-Disposition: attachment` 强制下载。

**实现细节**:
1. 在 `gallery.py:877-878` 的 SVG MIME 类型处理中，添加安全头：
   ```python
   elif full_path.suffix == ".svg":
       content_type = "image/svg+xml"
       # SVG 安全：添加 CSP 头禁止内联脚本
       response = send_file(full_path, mimetype=content_type)
       response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
       response.headers["X-Content-Type-Options"] = "nosniff"
       return response
   ```
2. 或者使用强制下载方式（更安全）：
   ```python
   elif full_path.suffix == ".svg":
       return send_file(full_path, mimetype="image/svg+xml", as_attachment=True)
   ```

**依赖**: M31完成

---

### M30: 书籍模板 SVG 文件同样存在 XSS 风险

**涉及文件**: 
- `Module/books/books.py` (修改 SVG 处理)

**修改内容**: 
同 M29 的修复方案，添加 SVG 安全检查。

**实现细节**:
1. 在 `books.py:274-275` 添加与 M29 相同的安全处理：
   ```python
   elif resolved.suffix == ".svg":
       content_type = "image/svg+xml"
   # ... 之后添加安全头
   if resolved.suffix == ".svg":
       response = send_file(resolved, mimetype=content_type)
       response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
       response.headers["X-Content-Type-Options"] = "nosniff"
       return response
   ```

**依赖**: M31完成

---

### M31: 全站缺失 Content Security Policy (CSP) 安全头

**涉及文件**: 
- `app.py` (添加 CSP 响应头)

**修改内容**: 
在 Flask 应用中添加 CSP 响应头，限制脚本、样式、图片来源。

**实现细节**:
1. 在 `app.py` 的 `create_app()` 中添加 `after_request` 中间件：
   ```python
   @app.after_request
   def add_csp_header(response):
       """添加 Content Security Policy 响应头"""
       csp = (
           "default-src 'self'; "
           "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
           "style-src 'self' 'unsafe-inline'; "
           "img-src 'self' data: blob:; "
           "font-src 'self'; "
           "connect-src 'self'; "
           "frame-ancestors 'self'"
       )
       response.headers["Content-Security-Policy"] = csp
       return response
   ```
2. CSP 策略说明：
   - `script-src 'self' 'unsafe-inline' 'unsafe-eval'`：允许同源脚本、内联脚本（模板需要）和 eval（某些库需要）
   - `style-src 'self' 'unsafe-inline'`：允许同源样式和内联样式（暗夜模式需要）
   - `img-src 'self' data: blob:`：允许同源图片、data URI 和 blob URL

**依赖**: 无

---

### M33: 管理员活动日志 API 无分页加载全部记录

**涉及文件**: 
- `Module/admin/admin.py` (添加分页逻辑)
- `Module/admin/templates/admin/activity.html` (修改前端分页)

**修改内容**: 
实现分页加载，添加分页 API 参数（page、per_page），前端支持分页显示。

**实现细节**:
1. 在 `admin.py:897-993` 的 `activity_api()` 中添加分页参数：
   ```python
   @admin_bp.route("/activity/api")
   def activity_api():
       # ... 现有筛选逻辑 ...
       
       # 分页参数
       try:
           page = int(request.args.get("page", 1))
           per_page = int(request.args.get("per_page", 50))
       except ValueError:
           page, per_page = 1, 50
       page = max(page, 1)
       per_page = min(max(per_page, 1), 200)
       
       total = len(filtered_activities)
       start = (page - 1) * per_page
       end = start + per_page
       paginated = filtered_activities[start:end]
       
       # 折叠模式下的分页
       if grouped:
           # ... 现有折叠逻辑使用 paginated 替代 filtered_activities ...
       
       return jsonify({
           "success": True,
           "activities": result,
           "grouped": grouped,
           "pagination": {
               "page": page,
               "per_page": per_page,
               "total": total,
               "total_pages": (total + per_page - 1) // per_page,
           }
       })
   ```
2. 在 `activity.html` 的 `loadActivities()` 中添加分页控件：
   ```javascript
   function loadActivities(page = 1) {
       const url = `/admin/activity/api?grouped=${isGrouped}&username=${encodeURIComponent(currentFilter)}&page=${page}&per_page=50`;
       fetch(url)
           .then(response => response.json())
           .then(data => {
               if (data.success) {
                   currentActivities = data.activities;
                   renderActivities(data.activities, data.grouped);
                   renderPagination(data.pagination);
               }
           });
   }
   
   function renderPagination(pagination) {
       const container = document.getElementById('pagination') || createPaginationContainer();
       if (pagination.total_pages <= 1) {
           container.innerHTML = '';
           return;
       }
       let html = '';
       for (let i = 1; i <= pagination.total_pages; i++) {
           html += `<button class="filter-btn ${i === pagination.page ? 'active' : ''}" onclick="loadActivities(${i})">${i}</button>`;
       }
       container.innerHTML = html;
   }
   ```

**依赖**: L8完成

---

### M36: 全站缺失安全响应头

**涉及文件**: 
- `app.py` (添加安全响应头)

**修改内容**: 
添加 `X-Content-Type-Options`、`X-Frame-Options`、`X-XSS-Protection`、`Strict-Transport-Security`。

**实现细节**:
1. 在 `app.py` 的 `create_app()` 中，合并到 M31 的 CSP 头中间件：
   ```python
   @app.after_request
   def add_security_headers(response):
       """添加安全响应头"""
       # CSP（M31）
       response.headers["Content-Security-Policy"] = (
           "default-src 'self'; "
           "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
           "style-src 'self' 'unsafe-inline'; "
           "img-src 'self' data: blob:; "
           "font-src 'self'; "
           "connect-src 'self'; "
           "frame-ancestors 'self'"
       )
       # 防止 MIME 类型嗅探
       response.headers["X-Content-Type-Options"] = "nosniff"
       # 防止点击劫持
       response.headers["X-Frame-Options"] = "SAMEORIGIN"
       # XSS 防护（旧浏览器）
       response.headers["X-XSS-Protection"] = "1; mode=block"
       # 生产模式添加 HSTS
       if production_mode:
           response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
       return response
   ```
2. 合并 M31 和 M36 为同一个 `after_request` 中间件

**依赖**: 无

---

### M39: 管理后台配置更新不验证路径值是否存在

**涉及文件**: 
- `Module/admin/admin.py` (添加路径存在性验证)

**修改内容**: 
在保存前验证路径是否存在，至少对 `gallery_root_path` 和 `book_data_path` 做目录存在性检查。

**实现细节**:
1. 在 `admin.py` 的 `update_config()` 中，保存前验证路径：
   ```python
   # 路径存在性验证
   if "paths" in data:
       for key, value in data["paths"].items():
           if isinstance(value, str) and value.strip():
               path = Path(value)
               if not path.is_absolute():
                   path = BASE_DIR / path
               if not path.exists():
                   return jsonify({"success": False, "message": f"路径不存在: {value}（{key}）"})
   ```

**依赖**: 无

---

### M40: 管理后台重启服务器在 Windows 下可能失败

**涉及文件**: 
- `Module/admin/admin.py` (修改重启逻辑)

**修改内容**: 
使用 `subprocess.Popen` 启动新进程后调用 `sys.exit()` 终止当前进程。

**实现细节**:
1. 修改 `admin.py:650-664` 的重启逻辑：
   ```python
   import sys
   import os
   import subprocess
   import platform
   
   # 获取当前 Python 解释器路径和脚本路径
   python = sys.executable
   script = sys.argv[0] if sys.argv else "app.py"
   
   # 等待响应发送完成
   time.sleep(0.5)
   
   if platform.system() == "Windows":
       # Windows: 使用 subprocess.Popen 启动新进程后退出
       subprocess.Popen([python, script] + sys.argv[1:], 
                       creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
   else:
       # Unix: 使用 os.execl 替换当前进程
       os.execl(python, python, script)
   
   # 无论哪种方式，终止当前进程
   sys.exit(0)
   ```

**依赖**: 无

---

### M41: 书籍搜索和加载无缓存机制

**涉及文件**: 
- `Module/books/books.py` (添加缓存机制)

**修改内容**: 
添加 TTL 缓存（类似 `load_users` 的实现）。

**实现细节**:
1. 在 `books.py` 中添加缓存机制：
   ```python
   import threading
   import time
   
   # 书籍缓存（TTL 30 秒）
   _books_cache = None
   _books_cache_ts = 0.0
   _books_cache_lock = threading.Lock()
   _BOOKS_CACHE_TTL = 30
   
   def load_books():
       """从 SQLite 加载书籍数据（带 TTL 缓存）"""
       global _books_cache, _books_cache_ts
       now = time.time()
       with _books_cache_lock:
           if _books_cache is not None and now - _books_cache_ts < _BOOKS_CACHE_TTL:
               return _books_cache
       
       from Module.common.db_utils import query
       books = [
           dict(r)
           for r in query("SELECT id, title, author, description, detail, cover FROM books ORDER BY id")
       ]
       
       with _books_cache_lock:
           _books_cache = books
           _books_cache_ts = time.time()
       return books
   ```

**依赖**: 无

---

### M42: 书籍搜索结果无分页

**涉及文件**: 
- `Module/books/books.py` (添加分页逻辑)
- `Module/books/templates/books/search.html` (修改前端分页)

**修改内容**: 
实现分页功能，限制每页返回数量。

**实现细节**:
1. 在 `books.py` 的 `book_search()` 路由中添加分页：
   ```python
   @books_bp.route("/search")
   def book_search():
       search_term = request.args.get("q", "")
       page = int(request.args.get("page", 1))
       per_page = 20
       
       all_books = search_books(search_term)
       total = len(all_books)
       start = (page - 1) * per_page
       end = start + per_page
       paginated_books = all_books[start:end]
       
       total_pages = (total + per_page - 1) // per_page
       
       return render_template("books/search.html", 
           books=paginated_books, 
           search_term=search_term,
           page=page,
           total_pages=total_pages,
           total=total
       )
   ```
2. 在 `search.html` 中添加分页导航控件

**依赖**: 无

---

### M44: 管理后台用户管理页面用户列表无搜索/筛选功能

**涉及文件**: 
- `Module/admin/templates/admin/users.html` (添加搜索筛选)

**修改内容**: 
添加用户搜索功能、角色筛选、状态筛选。

**实现细节**:
1. 在 `users.html` 的用户列表区域添加搜索/筛选控件：
   ```html
   <div class="filter-section" style="margin-bottom: 16px;">
       <input type="text" id="userSearch" placeholder="搜索用户名..." 
              style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px;"
              oninput="filterUsers()">
       <div style="display: flex; gap: 8px; margin-top: 8px;">
           <button class="filter-btn active" onclick="filterByRole('')">全部</button>
           <button class="filter-btn" onclick="filterByRole('user')">普通用户</button>
           <button class="filter-btn" onclick="filterByRole('admin')">管理员</button>
       </div>
   </div>
   ```
2. 添加 JavaScript 筛选逻辑：
   ```javascript
   let currentRoleFilter = '';
   
   function filterUsers() {
       const search = document.getElementById('userSearch').value.toLowerCase();
       const cards = document.querySelectorAll('.user-card');
       cards.forEach(card => {
           const name = card.querySelector('.user-name').textContent.toLowerCase();
           const role = card.dataset.role || '';
           const nameMatch = name.includes(search);
           const roleMatch = !currentRoleFilter || role === currentRoleFilter;
           card.style.display = (nameMatch && roleMatch) ? '' : 'none';
       });
   }
   
   function filterByRole(role) {
       currentRoleFilter = role;
       document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
       event.target.classList.add('active');
       filterUsers();
   }
   ```
3. 在用户卡片上添加 `data-role` 属性：
   ```html
   <div class="user-card" data-role="{{ user.role }}">
   ```

**依赖**: 无

---

## 总结

**中工程总数**: 33个

### 涉及文件汇总

| 文件 | 涉及问题 |
|------|----------|
| `Module/admin/admin.py` | H13, S4, H1, H3, H8, H12, M23, M26, M27, M33, M39, M40 |
| `Module/gallery/gallery.py` | S1, S2, S3, H5, M1, M2, M13, M29 |
| `Module/common/file_utils.py` | H10, M16 |
| `Module/common/db_utils.py` | H9 |
| `Module/common/user_utils.py` | H12, M18 |
| `Module/user/user.py` | H4, M27 |
| `Module/index/index.py` | M4 |
| `Module/books/books.py` | M30, M41, M42 |
| `app.py` | M10, M31, M36 |
| `Module/admin/templates/admin/activity.html` | M33 |
| `Module/admin/templates/admin/users.html` | M44 |
| `Module/index/templates/index/index.html` | (M10 Cookie 相关) |

### 依赖关系

- S1 → S2, S3, M1（S1 是基础，S2/S3/M1 合并到同一函数）
- S1/S2/S3 → S4（配置校验依赖路径校验逻辑）
- H13 → H1（路径限制依赖路径白名单）
- M31 → M29, M30（CSP 头是 SVG 安全的前提）
- M11 → M13（速率限制是 DoS 防护的前提）
- L8 → M33（活动日志保留数量是分页的前提）

### 无依赖问题（可并行实施）

H3, H4, H5, H8, H9, H10, M2, M4, M10, M16, M18, M23, M26, M31, M36, M39, M40, M41, M42, M44

### 需要澄清的问题

1. **M13 信号超时**: `signal.SIGALRM` 在 Windows 下不可用，需要使用 `threading.Timer` 替代方案
2. **H8 代理信任**: 需要确认是否支持反向代理部署场景
3. **M33 活动日志保留**: 当前硬编码 200 条上限是否需要调整
4. **M42 书籍分页**: 分页应在前端还是后端实现
