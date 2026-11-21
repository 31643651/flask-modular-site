"""
站点设置与功能开关（共享设施）

从 AdminService 上提：各业务模块直接使用本模块读取开关，
避免「工具层/业务路由 → 服务层」的反向依赖（原 common<->core 环的来源）。

config 仅经 Module.common.config_utils 读写（统一缓存与备份策略）。
"""

from Module.common.config_utils import load_config, save_config

# 已知开关及其默认值（缺省视为启用）
SETTING_DEFAULTS = {
    "admin_verify_enabled": True,
    "wallpaper_enabled": True,
    "books_enabled": True,
    "gallery_enabled": True,
    "mounted_pages_enabled": True,
}

ALLOWED_SETTING_KEYS = frozenset(SETTING_DEFAULTS)


def get_settings():
    """读取全部开关（缺省值补全）"""
    config = load_config()
    settings = dict(SETTING_DEFAULTS)
    custom = config.get("settings") or {}
    if isinstance(custom, dict):
        settings.update(custom)
    return settings


def is_feature_enabled(feature_key):
    """检查功能是否启用（未知键默认 True）"""
    return bool(get_settings().get(feature_key, True))


def update_setting(key, value):
    """
    更新单个开关

    Returns:
        tuple: (success, message)
    """
    if key not in ALLOWED_SETTING_KEYS:
        return (False, f"无效的设置键: {key}")
    config = load_config()
    if "settings" not in config:
        config["settings"] = {}
    config["settings"][key] = bool(value)
    save_config(config)
    return (True, "设置已更新")
