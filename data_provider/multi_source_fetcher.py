# -*- coding: utf-8 -*-
"""
Stock data fetcher using multiple sources with fallback.

Primary: akshare stock_zh_a_hist_tx (Tencent) - works in restricted networks
Fallback: Sina Finance API
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta
from typing import List, Optional

import requests

from data_provider.base import BaseFetcher, DataFetchError, StockQuote
from src.config import get_config

logger = logging.getLogger(__name__)

_SINA_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
]


class MultiSourceFetcher(BaseFetcher):
    """Fetcher with multiple data sources and automatic fallback."""

    def __init__(self):
        self._session = requests.Session()
        self._last_request_time = 0
        self._min_delay = 0.5  # seconds between requests

    @property
    def name(self) -> str:
        return "multi_source"

    def get_daily_klines(
        self,
        code: str,
        days: int = 120,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[StockQuote]:
        """Get daily K-line data with automatic fallback."""
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

        # Try Tencent first (via akshare), then Sina
        sources = [
            ("tencent", self._fetch_from_tencent),
            ("sina", self._fetch_from_sina),
        ]

        for source_name, fetch_func in sources:
            try:
                quotes = fetch_func(code, days, start_date, end_date)
                if quotes:
                    logger.debug("Got data from %s for %s", source_name, code)
                    return quotes
            except Exception as e:
                logger.debug("%s failed for %s: %s", source_name, code, str(e)[:50])
                continue

        return []

    def _fetch_from_tencent(self, code: str, days: int, start_date: str, end_date: str) -> List[StockQuote]:
        """Fetch from Tencent via akshare."""
        try:
            import akshare as ak
            import tqdm
            tqdm.tqdm = lambda *args, **kwargs: __import__("tqdm").tqdm(*args, disable=True, **kwargs)
        except ImportError:
            logger.warning("akshare not installed")
            return []

        try:
            df = ak.stock_zh_a_hist_tx(
                symbol=code,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
        except Exception as e:
            raise DataFetchError(f"Tencent API failed: {e}") from e

        if df is None or df.empty:
            return []

        # Normalize column names
        col_map = {}
        for col in df.columns:
            v = str(col).lower()
            if "date" in v:
                col_map["date"] = col
            elif v == "open":
                col_map["open"] = col
            elif v == "high":
                col_map["high"] = col
            elif v == "low":
                col_map["low"] = col
            elif v == "close":
                col_map["close"] = col
            elif v in ("volume", "vol"):
                col_map["volume"] = col
            elif v in ("amount",):
                col_map["amount"] = col

        date_col = col_map.get("date", df.columns[0])
        open_col = col_map.get("open", df.columns[1] if len(df.columns) > 1 else date_col)
        high_col = col_map.get("high", df.columns[2] if len(df.columns) > 2 else open_col)
        low_col = col_map.get("low", df.columns[3] if len(df.columns) > 3 else high_col)
        close_col = col_map.get("close", df.columns[4] if len(df.columns) > 4 else low_col)
        volume_col = col_map.get("volume", df.columns[5] if len(df.columns) > 5 else close_col)
        amount_col = col_map.get("amount", None)

        quotes = []
        for _, row in df.iterrows():
            try:
                # Get date - handle both datetime and string formats
                date_val = str(row[date_col]).strip()
                # Normalize date format (handle both "2026-09-18" and "20260918")
                date_val = date_val.replace("-", "")
                if len(date_val) != 8 or not date_val.isdigit():
                    continue

                # Get price values with fallback
                def safe_float(val, default=0.0):
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return default

                open_val = safe_float(row[open_col])
                high_val = safe_float(row[high_col])
                low_val = safe_float(row[low_col])
                close_val = safe_float(row[close_col])
                volume_val = safe_float(row[volume_col]) if volume_col else 0.0
                amount_val = safe_float(row[amount_col]) if amount_col and amount_col in row.index else 0.0

                # Skip invalid rows (e.g., suspended stocks with NaN prices)
                if close_val <= 0 or open_val <= 0:
                    continue

                quotes.append(StockQuote(
                    date=date_val,
                    code=code,
                    open=open_val,
                    high=high_val,
                    low=low_val,
                    close=close_val,
                    volume=volume_val,
                    amount=amount_val,
                ))
            except (KeyError, ValueError, TypeError, IndexError):
                continue

        # Filter by date range
        quotes = [q for q in quotes if start_date <= q.date <= end_date]
        quotes.sort(key=lambda q: q.date)

        if len(quotes) > days:
            quotes = quotes[-days:]
        return quotes

    def _fetch_from_sina(self, code: str, days: int, start_date: str, end_date: str) -> List[StockQuote]:
        """Fallback: Fetch from Sina Finance API."""
        # Convert code to Sina format
        if code.startswith(("6", "5")):
            sina_code = f"sh{code}"
        else:
            sina_code = f"sz{code}"

        # Rate limiting
        self._wait_if_needed()

        params = {
            "symbol": sina_code,
            "scale": "240",
            "ma": "no",
            "datalen": str(max(days + 10, 100)),
        }
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://finance.sina.com.cn/",
        }

        try:
            resp = self._session.get(
                _SINA_KLINE_URL,
                params=params,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise DataFetchError(f"Sina API failed: {e}") from e

        if not data or not isinstance(data, list):
            return []

        quotes = []
        for item in data:
            try:
                # Sina returns dates with hyphens, normalize them
                date_val = item["day"].replace("-", "")
                quotes.append(StockQuote(
                    date=date_val,
                    code=code,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item["volume"]),
                    amount=float(item.get("amount", 0)),
                ))
            except (KeyError, ValueError, TypeError):
                continue

        # Filter by date range
        quotes = [q for q in quotes if start_date <= q.date <= end_date]
        quotes.sort(key=lambda q: q.date)

        if len(quotes) > days:
            quotes = quotes[-days:]
        return quotes

    def get_stock_list(self, market: Optional[str] = None) -> List[dict]:
        """Generate A-share codes from known ranges."""
        from data.code_ranges import generate_all_codes
        filter_markets = ["sh", "sz"] if market in (None, "all", "") else [market]
        all_codes = generate_all_codes()
        stocks: List[dict] = []
        for code, mkt in all_codes:
            if mkt not in filter_markets:
                continue
            stocks.append({"code": code, "name": code, "market": mkt})
        logger.info("generated %d candidate codes from ranges", len(stocks))
        return stocks

    def _wait_if_needed(self) -> None:
        """Enforce minimum delay between requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_delay:
            time.sleep(self._min_delay - elapsed + random.uniform(0, 0.2))
        self._last_request_time = time.time()

    @staticmethod
    def is_st_stock(name: str) -> bool:
        """Check if stock name indicates ST."""
        return bool(name) and ("ST" in name.upper())

    @staticmethod
    def is_kc_cy_stock(code: str) -> bool:
        """Check if stock is STAR Market (688) or ChiNext (300)."""
        return code.startswith(("688", "300"))
