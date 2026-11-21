# 修复方案 - 大工程

## 工程说明

大工程需要新建界面、大量代码重构、涉及数据库schema变更或需要添加全局中间件。通常涉及多个文件修改，需要详细的设计和测试。

---

## 问题列表

### H7: 管理员注册端点 — 无角色权限校验

**涉及文件**: 
- `Module/common/user_utils.py` (添加超级管理员判定函数)
- `Module/admin/admin.py` (修改 require_admin 为 require_superadmin，所有管理路由仅超级管理员可访问)
- `Module/admin/templates/admin/users.html` (修改用户管理界面，显示超级管理员标识)
- `Module/admin/templates/admin/config.html` (修改配置管理界面)
- `Module/admin/templates/admin/activity.html` (修改活动日志界面)
- `Module/admin/templates/admin/dashboard.html` (修改仪表盘界面)

**修改内容**: 

1. **超级管理员角色定义**: 角色字符串为 `"superadmin"`，存储在 users 表的 role 字段

2. **超级管理员判定逻辑** (在 `user_utils.py` 中添加):
   - 条件: 同时满足 `uid 0-9` 并且是管理员账户（`role="admin"`）
   - 新增函数 `is_superadmin(user)`: 判断用户是否为超级管理员
   - 新增函数 `require_superadmin()`: 要求超级管理员权限的装饰器

3. **权限划分**:
   - **超级管理员 (`role="admin"` 且 `uid 0-9`)**: 可访问所有管理后台功能
   - **普通管理员 (`role="admin"` 且 `uid >= 10`)**: 权限与普通用户无区别，仅作为普通用户
   - **普通用户 (`role="user"`)**: 仅可访问用户功能

4. **修改管理后台路由** (`admin.py`):
   - 将所有管理后台路由（仪表盘、活动日志、用户管理、配置管理）的权限校验从 `require_admin()` 改为 `require_superadmin()`
   - `require_superadmin()` 内部校验: 用户必须存在、启用、role="admin" 且 uid 0-9

5. **前端界面修改**:
   - 在 users.html 中，为 uid 0-9 的管理员显示"超级管理员"标识
   - 普通管理员不再显示管理权限标识

**依赖**: 无

---

### H21: 管理后台与画廊所有 POST/DELETE 端点均无 CSRF 保护

**涉及文件**: 
- `app.py` (添加CSRF中间件)
- `Module/admin/admin.py` (所有POST/DELETE路由添加CSRF校验)
- `Module/gallery/gallery.py` (所有POST端点添加CSRF校验)
- `Module/userfix/userfix.py` (POST端点添加CSRF校验)
- `Module/admin/templates/admin/users.html` (JavaScript添加CSRF令牌)
- `Module/admin/templates/admin/config.html` (JavaScript添加CSRF令牌)
- `Module/gallery/templates/gallery/gallery.html` (JavaScript添加CSRF令牌)
- `Module/gallery/templates/gallery/favorites.html` (JavaScript添加CSRF令牌)

**修改内容**: 

1. **全局CSRF中间件** (在 `app.py` 中):
   ```python
   @app.before_request
   def csrf_protect():
       """CSRF保护中间件"""
       if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
           token = request.headers.get('X-CSRF-Token')
           expected = request.cookies.get('csrf_token')
           if not token or not expected or token != expected:
               return jsonify({"success": False, "message": "CSRF验证失败"}), 403
   ```

2. **CSRF Token生成** (在 `app.py` 中):
   - 应用启动时生成随机CSRF token
   - 通过cookie传递给前端: `csrf_token=xxx; HttpOnly; SameSite=Strict`

3. **前端JS获取CSRF Token**:
   ```javascript
   function getCsrfToken() {
       const match = document.cookie.match(/csrf_token=([^;]+)/);
       return match ? match[1] : '';
   }
   // 在所有AJAX请求中添加Header
   fetch(url, {
       method: 'POST',
       headers: { 'X-CSRF-Token': getCsrfToken() },
       ...
   });
   ```

4. **修改所有POST/DELETE路由**: 在每个路由开头添加CSRF校验装饰器或手动校验

**依赖**: 无

---

### L8: 活动日志仅保留 200 条

**涉及文件**: 
- `Module/common/user_utils.py` (移除200条限制)
- `Module/admin/admin.py` (添加清理API端点)
- `Module/admin/templates/admin/activity.html` (修改前端显示逻辑)
- `Module/admin/templates/admin/activity_all.html` (新建全量日志界面)

**修改内容**: 

1. **移除200条限制** (`user_utils.py`):
   - 删除 `_ACTIVITY_MAX = 200` 常量
   - 修改 `flush_activity_queue()`: 移除落库后的裁剪逻辑（删除 `DELETE FROM activity_log WHERE id NOT IN...` 语句）
   - 修改 `add_activity()`: 移除队列有界限制（删除 `if len(_activity_queue) > _ACTIVITY_MAX` 块）
   - 修改 `load_activities()`: 返回所有记录，不再截取 `[:_ACTIVITY_MAX]`

2. **日志存储方式**: 
   - 活动日志存储在 SQLite (`Module/data/app.db`) 的 `activity_log` 表中
   - 使用 structlog 记录应用日志到文件 (`Module/log/app.log`)
   - 活动日志与应用日志是独立的系统

3. **清理API端点** (`admin.py`):
   - 新增路由: `POST /admin/activity/api/cleanup`
   - 参数: `days` (7/30/365/1825 分别代表7天、30天、1年、5年前)
   - 实现: 解析 `time` 字段，删除早于指定天数的记录
   - 返回: `{"success": true, "deleted_count": N}`

4. **前端activity.html修改**:
   - 默认仅显示最近200条日志（前端截取）
   - 在 `class="card-title"` 右侧添加链接到全量日志界面
   - 添加清理按钮（下拉菜单: 7天前、30天前、1年前、5年前）
   - 点击清理按钮调用 `/admin/activity/api/cleanup` 接口

5. **新建activity_all.html**:
   - 显示全量活动日志
   - 支持服务端分页API: `GET /admin/activity/api/all?page=1&per_page=100`
   - 支持筛选: 用户名、登录状态、折叠模式
   - 支持清理功能（与activity.html相同的清理按钮）

**依赖**: 无

---

### M35: userfix 提交无管理审核功能

**涉及文件**: 
- `Module/userfix/userfix.py` (添加管理审核路由)
- `Module/userfix/templates/userfix/admin.html` (新建管理审核界面)
- `Module/admin/admin.py` (添加管理后台入口)

**修改内容**: 

1. **管理后台审核页面路由** (`userfix.py`):
   - 新增路由: `GET /userfix/admin`
   - 功能: 显示所有用户提交的修复请求

2. **审核功能实现**:
   - 查看提交详情（问题描述、截图、用户信息）
   - 删除提交记录
   - 标记为已处理/未处理
   - 分页功能支持大量提交记录

3. **新建管理审核界面** (`admin.html`):
   - 表格显示所有提交: 用户名、问题描述、提交时间、状态
   - 每行显示图片缩略图（如有截图）
   - 操作按钮: 查看详情、标记处理、删除
   - 分页导航

4. **管理后台入口** (`admin.py`):
   - 在仪表盘页面添加userfix审核入口链接

5. **过期清理机制**:
   - 自动清理超过90天的提交记录

**依赖**: 无

---

### M11: 全站无速率限制

**涉及文件**: 
- `requirements.txt` (添加flask-limiter依赖)
- `app.py` (添加全局速率限制中间件)
- `Module/admin/admin.py` (为管理端点添加速率限制)
- `Module/gallery/gallery.py` (为画廊API添加速率限制)
- `Module/user/user.py` (为登录端点添加速率限制)
- `Module/userfix/userfix.py` (为提交端点添加速率限制)

**修改内容**: 

1. **添加依赖** (`requirements.txt`):
   ```
   flask-limiter>=3.0.0
   ```

2. **初始化flask-limiter** (`app.py`):
   ```python
   from flask_limiter import Limiter
   from flask_limiter.util import get_remote_address

   limiter = Limiter(
       key_func=get_remote_address,
       default_limits=["200 per day", "50 per hour"],
       storage_uri="memory://"
   )
   limiter.init_app(app)
   ```

3. **为各端点添加速率限制**:
   - 管理端点: `100 per minute`
   - 画廊API: `60 per minute`
   - 登录端点: `5 per minute`
   - userfix提交: `3 per hour`
   - 注册端点: `3 per hour`

4. **配置存储后端**: 使用flask-limiter默认的内存存储（无需Redis）

**依赖**: 无

---

### S7: 活动日志 JavaScript 渲染存储型 XSS

**涉及文件**: 
- `Module/admin/templates/admin/activity.html` (修改JavaScript渲染逻辑)

**修改内容**: 

1. **添加HTML实体转义函数**:
   ```javascript
   function escapeHtml(str) {
       if (!str) return '';
       return String(str)
           .replace(/&/g, '&amp;')
           .replace(/</g, '&lt;')
           .replace(/>/g, '&gt;')
           .replace(/"/g, '&quot;')
           .replace(/'/g, '&#039;');
   }
   ```

2. **对所有动态数据进行转义**: description、path、username、ip、device_type、os、browser

3. **使用模板字面量**: `${escapeHtml(activity.username)}` 而非直接拼接

4. **验证所有渲染点**: 确保表格中的每个动态字段都经过转义

**依赖**: 无

---

### S8: 画廊模板 JavaScript innerHTML 存储型 XSS

**涉及文件**: 
- `Module/gallery/templates/gallery/gallery.html` (修改JavaScript渲染逻辑)

**修改内容**: 

1. **添加HTML实体转义函数**: 与S7相同的 `escapeHtml` 函数

2. **对动态数据进行转义**: 文件夹名、图片名、封面路径

3. **使用DOM API替代innerHTML**:
   ```javascript
   const img = document.createElement('img');
   img.src = escapeHtml(imagePath);
   img.alt = escapeHtml(imageName);
   container.appendChild(img);
   ```

4. **验证所有渲染点**: 确保图片和文件夹的每个属性都经过转义

**依赖**: 无

---

### H15: 管理后台用户管理 JS 注入（用户名/角色注入 onclick 处理器）

**涉及文件**: 
- `Module/admin/templates/admin/users.html` (修改JavaScript事件绑定)

**修改内容**: 

1. **使用data属性传递参数**:
   ```html
   <button data-username="xxx" class="toggle-btn">切换状态</button>
   <button data-username="xxx" class="delete-btn">删除</button>
   ```

2. **使用addEventListener绑定事件**:
   ```javascript
   document.querySelectorAll('.toggle-btn').forEach(btn => {
       btn.addEventListener('click', function() {
           const username = this.dataset.username;
           // 处理逻辑
       });
   });
   ```

3. **对用户名进行JS字符串转义**: 使用 `escapeHtml` 函数

4. **验证所有onclick处理器安全性**: 移除所有内联 `onclick` 属性

**依赖**: 无

---

### H16: 首页挂载页面名称 XSS

**涉及文件**: 
- `Module/index/templates/index/index.html` (修改挂载页面渲染)

**修改内容**: 

1. **使用textContent设置链接文本**:
   ```javascript
   const link = document.createElement('a');
   link.textContent = page.name;  // 安全，自动转义
   link.href = '/' + page.name;
   ```

2. **或对page.name进行HTML转义**: 使用 `escapeHtml` 函数

3. **验证首页挂载页面渲染安全性**: 确保所有动态名称都经过转义

**依赖**: 无

---

### H17: 管理后台挂载页面 JS 注入（删除按钮 onclick 注入）

**涉及文件**: 
- `Module/admin/templates/admin/config.html` (修改JavaScript事件绑定)

**修改内容**: 

1. **使用data属性传递页面名称**:
   ```html
   <button data-page-name="xxx" class="delete-page-btn">删除</button>
   ```

2. **使用addEventListener绑定事件**:
   ```javascript
   document.querySelectorAll('.delete-page-btn').forEach(btn => {
       btn.addEventListener('click', function() {
           const pageName = this.dataset.pageName;
           // 处理删除逻辑
       });
   });
   ```

3. **对page.name进行JS字符串转义**: 使用 `escapeHtml` 函数

4. **验证所有挂载页面操作安全性**: 移除所有内联 `onclick` 属性

**依赖**: 无

---

### M25: 活动日志折叠模式 JavaScript XSS

**涉及文件**: 
- `Module/admin/templates/admin/activity.html` (修改折叠模式渲染)

**修改内容**: 

1. **对折叠模式中的动态数据进行转义**: group.description、group.path、group.username

2. **使用与S7相同的转义函数**: `escapeHtml`

3. **在模板字面量中使用转义函数**:
   ```javascript
   html += `<td>${escapeHtml(group.description)}</td>`;
   ```

4. **验证折叠模式下的XSS安全性**: 确保所有折叠/展开的内容都经过转义

**依赖**: S7完成

---

### M28: 画廊 API 数据通过 innerHTML 渲染导致信息污染

**涉及文件**: 
- `Module/gallery/templates/gallery/gallery.html` (修改img标签渲染)

**修改内容**: 

1. **使用DOM API设置img属性**:
   ```javascript
   const img = document.createElement('img');
   img.src = escapeHtml(image.url);
   img.alt = escapeHtml(image.name);
   img.loading = 'lazy';
   gallery.appendChild(img);
   ```

2. **对封面路径进行HTML属性转义**: 使用 `escapeHtml` 函数

3. **验证画廊API数据渲染安全性**: 确保所有图片URL和名称都经过转义

**依赖**: S8完成

---

### M34: 用户名包含特殊字符导致 HTML 属性注入

**涉及文件**: 
- `Module/admin/templates/admin/users.html` (修改HTML属性渲染)

**修改内容**: 

1. **使用DOM API创建元素并设置属性**:
   ```javascript
   const span = document.createElement('span');
   span.textContent = username;  // 自动转义
   span.className = 'username-highlight';
   ```

2. **对用户名进行HTML属性值转义**: 使用 `escapeHtml` 函数

3. **验证用户管理页面所有属性渲染安全性**: 确保所有用户名、角色等属性都经过转义

**依赖**: H15完成

---

## 总结

**大工程总数**: 13个

**实现优先级**:
1. H7 (超级管理员权限) - 基础权限体系
2. H21 (CSRF保护) - 安全基础
3. L8 (活动日志无限保存) - 功能增强
4. M11 (速率限制) - 安全增强
5. S7/S8/H15/H16/H17/M25/M28/M34 (XSS修复) - 安全修复
6. M35 (userfix管理) - 功能增强
