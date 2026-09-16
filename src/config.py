# -*- coding: utf-8 -*-
"""
配置管理模块

从 .env 文件加载环境变量，提供类型安全的配置访问接口。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ScannerConfig:
    """扫描器配置，全部来自环境变量，有合理的默认值。"""

    continuous_days: int = 5                # 连续上涨天数要求
    output_dir: str = "./output"            # 输出目录
    exclude_st: bool = True                 # 排除 ST 股票
    exclude_kc_cy: bool = False             # 是否排除科创板/创业板
    market: str = "all"                     # all / sh / sz
    request_delay: float = 0.3              # 请求间隔（秒）
    fetch_timeout: int = 15                 # 单个股票获取超时（秒）
    max_retries: int = 3                    # 最大重试次数
    stock_list_file: Optional[str] = None   # 指定股票列表文件路径


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "off", "")


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None:
        return default
    return int(val.strip())


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key)
    if val is None:
        return default
    return float(val.strip())


# 全局配置实例（延迟初始化，避免循环导入）
_config: Optional[ScannerConfig] = None


def get_config() -> ScannerConfig:
    """获取全局配置单例。"""
    global _config
    if _config is None:
        _config = ScannerConfig(
            continuous_days = _env_int("CONTINUOUS_UP_DAYS", 5),
            output_dir      = os.getenv("OUTPUT_DIR") or "./output",
            exclude_st      = _env_bool("EXCLUDE_ST", True),
            exclude_kc_cy   = _env_bool("EXCLUDE_KC_CY", False),
            market          = (os.getenv("SCAN_MARKET") or "all").strip().lower(),
            request_delay   = _env_float("REQUEST_DELAY", 0.3),
            fetch_timeout   = _env_int("FETCH_TIMEOUT", 15),
            max_retries     = _env_int("MAX_RETRIES", 3),
            stock_list_file = os.getenv("STOCK_LIST_FILE"),
        )
    return _config
