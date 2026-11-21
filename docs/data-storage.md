# Data Storage Specification

项目数据分为两层存储：高频可变数据（用户、书籍、活动日志、会话、收藏、IP 封禁）存于 SQLite（`Module/data/app.db`），config 类配置仍以 JSON 文件存放于 `Module/json/` 目录。

---

## 数据文件说明

| 文件名 | 用途 | 数据结构 |
|--------|------|----------|
| config.json | 全局配置 | `{"paths": {"book_data_path": "...", "book_static_path": "...", "gallery_root_path": "..."}, "settings": {"admin_verify_enabled": ..., "wallpaper_enabled": ..., ...}, "wallpaper": {"enabled": true/false, "path": "..."}, "mounted_pages": [...], "config": {"server_name": "..."}}` |
| gallery_preferences.json | 画廊用户偏好设置 | `{"default_preferences": {...}, "device_specific": {...}, "users": {"username": {...}}}` |
| server_info.json | 服务器信息 | `{"server_name": "...", "version": "...", "start_time": "..."}` |
| userfix_limits.json | 用户修复限制 | `{}` |

## 配置备份目录

`Module/json/backups/`（路径常量 `BACKUPS_DIR`，定义于 `Module/common/paths.py`）:

- 由 `config_utils.backup_config()` 在保存配置等场景调用时生成
- 备份文件命名 `config_YYYYMMDD_HHMMSS.json`（`shutil.copy2` 保留元数据）
- 自动清理：仅保留最近 5 份备份，旧备份删除
- 备份失败时通过 structlog 记录 `backup_config_failed` 事件，不影响主流程

---

## SQLite 表结构

高频可变数据存于 `Module/data/app.db`（WAL 模式，运行时生成 `-wal` / `-shm` 伴随文件，均已 gitignore）：

| 表名 | 用途 | 主要字段 |
|------|------|----------|
| users | 用户 | id, username, password, role, enabled, is_superadmin |
| books | 书籍 | id, title, author, description, detail, cover |
| activity_log | 活动日志 | id, username, description, time, ip, path, device_type, os, browser, is_logged_in |
| active_sessions | 活动会话 | username(主键), ip, user_agent, last_activity |
| favorites | 画廊收藏 | id, username, path, added_at |
| ip_bans | IP 封禁记录（ipguard 模块） | id, ip(唯一), ban_count, ban_type, ban_reason, created_at, expires_at, is_permanent |

说明：
- `ip_bans` 由 ipguard 模块读写：内存缓存实时判定，`ban_manager._write_ban` 以 UPSERT（`ON CONFLICT(ip) DO UPDATE`）幂等落库，重启后由 `load_ban_cache()` 重新加载
- 启动时 `init_db()` 建表；`_migrate_superadmin()` 自动将 uid 0-9 且 role="admin" 的用户标记为超级管理员（兼容旧库自动补 `is_superadmin` 列）
- 数据库损坏（"file is not a database" 等）时 `query`/`execute` 自动触发 `_rebuild_db()`：删除库文件及 `-wal`/`-shm`/`-journal` 伴随文件后重建，config 类数据仍可从 JSON 恢复

---

## 迁移说明

> 说明：`users/books/activity_log/active_sessions/favorites` 5 类高频可变数据已迁移到 SQLite（`Module/data/app.db`），后续新增的 `ip_bans`（ipguard 封禁记录）同样存于 SQLite；config 类（config/server_info/userfix_limits/gallery_preferences）仍使用 JSON 存储。

---

## 缓存策略

- 高频读取使用 TTL 缓存（用户 30 秒、config 类 5 秒，config 经 `config_utils.load_config()` 统一读取）
- 活动日志走内存队列异步落盘，读时合并队列与 SQLite
- 画廊目录扫描结果按目录 mtime 缓存，递归聚合由单层缓存组合得出
- ipguard 封禁状态使用内存缓存（启动时全量加载，写入时先更新缓存再落库）
