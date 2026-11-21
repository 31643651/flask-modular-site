"""
路径常量模块

集中管理所有路径常量，避免各模块重复定义。
所有路径基于项目根目录（Module/ 的上级目录）解析。
"""

from pathlib import Path

# 项目根目录（paths.py → common/ → Module/ → project root）
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 核心目录
MODULE_DIR = BASE_DIR / "Module"
DATA_DIR = MODULE_DIR / "data"
JSON_DIR = MODULE_DIR / "json"
TEMPLATES_DIR = MODULE_DIR / "templates"
STATIC_DIR = MODULE_DIR / "static"

# JSON 配置文件
CONFIG_FILE = JSON_DIR / "config.json"
SERVER_INFO_FILE = JSON_DIR / "server_info.json"
PREFERENCES_FILE = JSON_DIR / "gallery_preferences.json"
USERFIX_LIMITS_FILE = JSON_DIR / "userfix_limits.json"

# 数据文件
DB_FILE = DATA_DIR / "app.db"

# 其他目录
USERFIX_SUBMISSIONS_DIR = MODULE_DIR / "userfix" / "submissions"
BACKUPS_DIR = JSON_DIR / "backups"
