# -*- coding: utf-8 -*-
"""
Configuration management.

Reads settings from environment variables (loaded from .env file).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ScannerConfig:
    """Scanner configuration loaded from environment variables."""

    continuous_days: int = 5
    output_dir: str = "./output"
    exclude_st: bool = True
    exclude_kc_cy: bool = False
    market: str = "all"
    request_delay: float = 0.3
    fetch_timeout: int = 15
    max_retries: int = 3
    stock_list_file: Optional[str] = None


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


_config: Optional[ScannerConfig] = None


def get_config() -> ScannerConfig:
    """Get global config singleton."""
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
