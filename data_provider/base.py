# -*- coding: utf-8 -*-
"""
数据源基类 - 策略模式

设计模式：Strategy Pattern
- BaseFetcher: 抽象基类，定义统一接口
- 子类实现具体数据源（AkShare、YFinance 等）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


class DataFetchError(Exception):
    """数据获取异常基类"""
    pass


class RateLimitError(DataFetchError):
    """请求频率限制异常"""
    pass


@dataclass
class StockQuote:
    """单日行情数据"""
    date: str          # YYYY-MM-DD
    code: str          # 股票代码（6位纯数字）
    open: float
    high: float
    low: float
    close: float
    volume: float      # 成交量（手）
    amount: float      # 成交额（元）


@dataclass
class ScanConfig:
    """扫描配置"""
    continuous_days: int = 5           # 连续上涨天数要求
    market: str = "all"                # all / sh / sz
    exclude_st: bool = True            # 是否排除 ST
    exclude_kc_cy: bool = False        # 是否排除科创板/创业板
    request_delay: float = 0.3         # 请求间隔（秒）
    fetch_timeout: int = 15            # 单个股票获取超时
    max_retries: int = 3               # 最大重试次数
    output_dir: str = "./output"       # 输出目录


class BaseFetcher(ABC):
    """数据源抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源名称"""
        ...

    @abstractmethod
    def get_daily_klines(self, code: str, days: int = 120,
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> List[StockQuote]:
        """获取单只股票的日线数据"""
        ...

    @abstractmethod
    def get_stock_list(self, market: Optional[str] = None) -> List[dict]:
        """获取股票列表"""
        ...
