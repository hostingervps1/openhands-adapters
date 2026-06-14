"""配置适配层 — config adapter layer.

把 vast-core 的 `AppConfig`（来源：`07-config/core.py`）适配进 openhands
建站框架的配置中心。

设计原则（见 README「核心原则」与「标注规范」）：
- 入口格式千变万化、出口格式不变 —— 本层负责把 vast-core 的配置对象
  归一化成 openhands 框架消费的统一字典。
- AI 不能覆盖事实数据 —— 配置以 `os.environ` 为准（[ENV]），代码内只放默认值。

注册点（README「注册点」表）：
    AppConfig | 07-config/core.py | openhands 配置中心
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

__all__ = ["load_config", "register_config"]


# [ENV] 配置项默认值。生产环境一律由 os.environ 覆盖，这里只保证本地/测试可跑。
_DEFAULTS: Dict[str, Any] = {
    "APP_NAME": "openhands",
    "APP_ENV": "production",
    "DEBUG": False,
    "DATABASE_URL": "",
    # OpenRouter 三角色 key 体系（README「基础设施」）
    "OPENROUTER_ANALYZE_KEY": "",
    "OPENROUTER_EXECUTE_KEY": "",
    "OPENROUTER_VERIFY_KEY": "",
}

# 需要按布尔语义解析的 [ENV] 变量。
_BOOL_KEYS = frozenset({"DEBUG"})

# 视为「真」的环境变量取值。
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _coerce(key: str, raw: str) -> Any:
    """把环境变量字符串按 key 的预期类型转换。"""
    if key in _BOOL_KEYS:
        return raw.strip().lower() in _TRUTHY
    return raw


def load_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构建 openhands 框架消费的统一配置字典。

    优先级（由低到高）：
        _DEFAULTS  <  vast-core AppConfig  <  os.environ  <  overrides

    Args:
        overrides: 显式覆盖项，主要用于测试与调试。

    Returns:
        归一化后的配置字典，出口格式稳定不变。
    """
    config: Dict[str, Any] = dict(_DEFAULTS)

    # 叠加 vast-core 的 AppConfig（若可用）。
    config.update(_load_vast_core_config())

    # [ENV] os.environ 覆盖默认值。
    for key in config:
        if key in os.environ:
            config[key] = _coerce(key, os.environ[key])

    # 显式覆盖（最高优先级）。
    if overrides:
        config.update(overrides)

    return config


def _load_vast_core_config() -> Dict[str, Any]:
    """读取 vast-core 的 AppConfig 并归一化成普通字典。

    vast-core 是拆迁产物（README「相关仓库」），在本接入层中可能尚未安装。
    缺失时静默降级到默认值，绝不让导入失败拖垮整个框架启动。
    """
    try:
        # [CIRCULAR_IMPORT] / [IMPORT_CHANGE] 延迟导入：vast-core 为可选依赖，
        # 仅在调用时尝试加载，避免模块导入期硬依赖。
        from vast_core.config.core import AppConfig  # type: ignore
    except Exception:
        return {}

    try:
        app_config = AppConfig()
    except Exception:
        return {}

    # AppConfig 可能是 pydantic 模型 / dataclass / 普通对象，统一取其字典视图。
    for attr in ("model_dump", "dict"):
        method = getattr(app_config, attr, None)
        if callable(method):
            try:
                return dict(method())
            except Exception:
                break

    return {
        key: value
        for key, value in vars(app_config).items()
        if not key.startswith("_")
    }


def register_config(framework: Any, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把归一化后的配置注册进 openhands 配置中心。

    openhands 框架可能通过不同接口接收配置，这里按常见约定逐一尝试，
    保证适配层对消费方框架的实现细节不敏感。

    Args:
        framework: openhands 建站框架实例（或其配置中心）。
        overrides: 透传给 load_config 的显式覆盖项。

    Returns:
        实际注册的配置字典。
    """
    config = load_config(overrides)

    # [ADDED] 兼容多种注册接口：方法 > 属性 > 字典式赋值。
    register = getattr(framework, "register_config", None)
    if callable(register):
        register(config)
        return config

    configure = getattr(framework, "configure", None)
    if callable(configure):
        configure(**config)
        return config

    if hasattr(framework, "config"):
        try:
            framework.config = config  # type: ignore[attr-defined]
            return config
        except Exception:
            pass

    raise TypeError(
        "openhands framework 不支持已知的配置注册接口："
        "需要 register_config(dict) / configure(**kwargs) / .config 属性之一"
    )
