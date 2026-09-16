# -*- coding: utf-8 -*-
"""
Data provider base classes - Strategy Pattern

- BaseFetcher: abstract base class defining the unified interface
- DataFetchError: exception for data fetch failures
- StockQuote: daily market data record
- ScanConfig: scanner configuration
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


class DataFetchError(Exception):
    """Base exception for data fetch failures."""
    pass


class RateLimitError(DataFetchError):
    """Exception for rate limit / throttling errors."""
    pass


@dataclass
class StockQuote:
    """Single day market quote."""
    date: str          # YYYY-MM-DD
    code: str          # 6-digit stock code
    open: float
    high: float
    low: float
    close: float
    volume: float      # trading volume (lots)
    amount: float      # trading amount (CNY)


@dataclass
class ScanConfig:
    """Scanner configuration from environment variables."""
    continuous_days: int = 5       # minimum consecutive up days
    market: str = "all"            # all / sh / sz
    exclude_st: bool = True        # exclude ST stocks
    exclude_kc_cy: bool = False    # exclude STAR/ChiNext
    request_delay: float = 0.3     # delay between requests (seconds)
    fetch_timeout: int = 15        # single stock fetch timeout (seconds)
    max_retries: int = 3           # max retry attempts
    output_dir: str = "./output"   # output directory
    stock_list_file: str = ""      # path to custom stock list file


class BaseFetcher(ABC):
    """Abstract base class for data providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        ...

    @abstractmethod
    def get_daily_klines(self, code: str, days: int = 120,
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> List[StockQuote]:
        """Fetch daily K-line data for a stock."""
        ...

    @abstractmethod
    def get_stock_list(self, market: Optional[str] = None) -> List[dict]:
        """Fetch stock list."""
        ...
