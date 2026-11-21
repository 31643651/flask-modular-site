"""
配置工具模块

提供集中化的配置加载与缓存功能，避免各模块重复实现配置读取逻辑。
"""

from .paths import CONFIG_FILE, BACKUPS_DIR
from .file_utils import read_json_file_cached, write_json_file


def load_config(ttl=5):
    """
    从 config.json 加载配置（TTL 缓存）

    Args:
        ttl: 缓存有效期（秒），默认 5 秒

    Returns:
        dict: 配置字典
    """
    return read_json_file_cached(CONFIG_FILE, default={}, ttl=ttl)


def get_config_value(key, default=None):
    """
    获取单个配置值

    Args:
        key: 配置键名（支持点号分隔的嵌套键，如 'paths.gallery_root_path'）
        default: 默认值

    Returns:
        配置值或默认值
    """
    config = load_config()
    keys = key.split(".")
    value = config
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            return default
        if value is None:
            return default
    return value


def save_config(config):
    """
    保存配置到 config.json

    Args:
        config: 要保存的配置字典

    Returns:
        bool: 是否成功
    """
    return write_json_file(CONFIG_FILE, config, ensure_ascii=False, indent=2)


def backup_config():
    """备份配置文件，保留最近5个备份

    Returns:
        bool: 是否成功
    """
    import shutil
    from datetime import datetime

    if not CONFIG_FILE.exists():
        return False
    try:
        BACKUPS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUPS_DIR / f"config_{timestamp}.json"
        shutil.copy2(CONFIG_FILE, backup_path)

        # 保留最近5个备份
        backups = sorted(BACKUPS_DIR.glob("config_*.json"))
        for old_backup in backups[:-5]:
            old_backup.unlink()
        return True
    except (OSError, PermissionError) as e:
        import structlog

        structlog.get_logger(__name__).error(
            "backup_config_failed",
            error=str(e),
            config_file=str(CONFIG_FILE),
        )
        return False
