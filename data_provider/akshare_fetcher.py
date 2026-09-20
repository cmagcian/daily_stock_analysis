# -*- coding: utf-8 -*-
"""
AkShareFetcher - Primary data source

Data source: Eastmoney push2 API (free, no token required)
Anti-block strategy: random delay + exponential backoff retry + UA rotation
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from data_provider.base import BaseFetcher, DataFetchError, StockQuote
from src.config import get_config

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
]

_EASTMONEY_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def _random_delay(low: float = 0.2, high: float = 0.6):
    time.sleep(random.uniform(low, high))


class AkShareFetcher(BaseFetcher):
    """Data source using Eastmoney push2 API."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://quote.eastmoney.com/",
        })

    @property
    def name(self) -> str:
        return "akshare"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type((DataFetchError, requests.RequestException, Exception)),
        reraise=True,
    )
    def get_daily_klines(
        self,
        code: str,
        days: int = 120,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[StockQuote]:
        """Get daily K-line data via akshare stock_zh_a_hist (qfq adjusted)."""
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

        try:
            import akshare as ak
        except ImportError:
            raise DataFetchError("akshare not installed")

        try:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
        except Exception as e:
            raise DataFetchError(f"ak.stock_zh_a_hist failed: {e}") from e

        if df is None or df.empty:
            return []

        # Detect column names flexibly
        col_map: dict = {}
        for col in df.columns:
            v = str(col).lower()
            if "date" in v:
                col_map.setdefault("date", col)
            elif v == "open":
                col_map.setdefault("open", col)
            elif v == "high":
                col_map.setdefault("high", col)
            elif v == "low":
                col_map.setdefault("low", col)
            elif v == "close":
                col_map.setdefault("close", col)
            elif v in ("volume", "vol"):
                col_map.setdefault("volume", col)
            elif v in ("amount",):
                col_map.setdefault("amount", col)

        # Fallback to positional columns
        date_col  = col_map.get("date",  df.columns[0])
        open_col  = col_map.get("open",  df.columns[1] if len(df.columns) > 1 else date_col)
        high_col  = col_map.get("high",  df.columns[2] if len(df.columns) > 2 else open_col)
        low_col   = col_map.get("low",   df.columns[3] if len(df.columns) > 3 else high_col)
        close_col = col_map.get("close", df.columns[4] if len(df.columns) > 4 else low_col)
        volume_col = col_map.get("volume", df.columns[5] if len(df.columns) > 5 else close_col)
        amount_col = col_map.get("amount", None)

        df = df.sort_values(date_col).reset_index(drop=True)

        quotes: List[StockQuote] = []
        for _, row in df.iterrows():
            try:
                quotes.append(StockQuote(
                    date   = str(row[date_col]).strip(),
                    code   = code,
                    open   = float(row[open_col]),
                    high   = float(row[high_col]),
                    low    = float(row[low_col]),
                    close  = float(row[close_col]),
                    volume = float(row[volume_col]) if volume_col else 0.0,
                    amount = float(row[amount_col]) if amount_col and amount_col in row.index else 0.0,
                ))
            except (ValueError, TypeError, KeyError):
                continue

        # Return last `days` records
        if len(quotes) > days:
            quotes = quotes[-days:]
        return quotes

    def get_stock_list(self, market: Optional[str] = None) -> List[dict]:
        """Generate A-share codes from known ranges. No network needed."""
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

    def _fetch_via_push2(self, market: Optional[str] = None) -> List[dict]:
        """Fetch stock list using Eastmoney push2 API with pagination."""
        stocks: List[dict] = []
        filter_markets = ["sh", "sz"] if market in (None, "all", "") else [market]

        # fs groups: (market_key, fs_value, default_market)
        groups = [
            ("sh_main",  "m:0+t:6",   "sh"),    # Shanghai main board
            ("sh_star",  "m:1+t:23",  "sh"),    # Shanghai STAR market
            ("sz_main",  "m:0+t:80",  "sz"),    # Shenzhen main board
            ("sz_cy",    "m:1+t:2",   "sz"),    # Shenzhen ChiNext
        ]

        for group_key, fs_value, default_mkt in groups:
            if default_mkt not in filter_markets:
                continue

            page = 1
            while True:
                params = {
                    "pn":     str(page),
                    "pz":     "5000",
                    "po":     "1",
                    "np":     "1",
                    "fltt":   "2",
                    "invt":   "2",
                    "fid":    "f3",
                    "fs":     fs_value,
                    "fields": "f12,f14",
                }
                try:
                    resp = self._session.get(
                        _EASTMONEY_LIST_URL,
                        params=params,
                        timeout=10,
                    )
                    resp.raise_for_status()
                    json_data = resp.json()
                    items = (json_data.get("data") or {}).get("diff", [])
                except Exception as e:
                    logger.warning("push2 page %d (%s) failed: %s", page, group_key, e)
                    break

                if not items:
                    break

                for item in items:
                    code = (item.get("f12") or "").strip()
                    name = (item.get("f14") or "").strip()
                    if code and name and len(code) == 6 and code.isdigit():
                        stocks.append({"code": code, "name": name, "market": default_mkt})

                # Check if we got fewer than page size = no more pages
                if len(items) < 5000:
                    break
                page += 1

                # Safety: max 10 pages
                if page > 10:
                    break

                _random_delay(0.1, 0.3)

        logger.info("push2 API returned %d stocks", len(stocks))
        return stocks

    def _fetch_via_akshare(self, market: Optional[str] = None) -> List[dict]:
        """Primary: fetch via akshare stock_zh_a_spot_em()."""
        for attempt in range(3):
            try:
                import akshare as ak
            except ImportError:
                logger.error("akshare not installed")
                return []

            try:
                df = ak.stock_zh_a_spot_em()
            except Exception as e:
                logger.warning("akshare attempt %d failed: %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                logger.error("akshare exhausted retries: %s", e)
                return []

            if df is None or df.empty:
                logger.warning("akshare returned empty, retrying...")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                return []

            break  # success
        else:
            return []

        # Detect code/name columns flexibly
        code_col = None
        name_col = None
        for col in df.columns:
            val = str(col).lower()
            if any(kw in val for kw in ["code", "ticker", "symbol", "secu_code"]):
                if code_col is None:
                    code_col = col
            if any(kw in val for kw in ["name", "secu_name"]):
                if name_col is None:
                    name_col = col
        if code_col is None:
            code_col = df.columns[0]
        if name_col is None:
            name_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

        stocks: List[dict] = []
        filter_markets = ["sh", "sz"] if market in (None, "all", "") else [market]

        for _, row in df.iterrows():
            code = str(row.get(code_col, "")).strip()
            name = str(row.get(name_col, "")).strip()
            if not code or not name:
                continue
            if len(code) != 6 or not code.isdigit():
                continue
            if code.startswith(("6", "5")):
                stock_market = "sh"
            elif code.startswith(("0", "3")):
                stock_market = "sz"
            else:
                continue
            if stock_market not in filter_markets:
                continue
            stocks.append({"code": code, "name": name, "market": stock_market})

        logger.info("akshare returned %d stocks", len(stocks))
        return stocks

    @staticmethod
    def _to_secid(code: str) -> str:
        """Convert 6-digit code to Eastmoney secid format (1.xxx=SH, 0.xxx=SZ)."""
        return f"1.{code}" if code.startswith(("6", "5")) else f"0.{code}"

    @staticmethod
    def is_st_stock(name: str) -> bool:
        """Check if stock name indicates an ST (special treatment) stock."""
        return bool(name) and ("ST" in name.upper())

    @staticmethod
    def is_kc_cy_stock(code: str) -> bool:
        """Check if stock is STAR Market (688) or ChiNext (300)."""
        return code.startswith(("688", "300"))
