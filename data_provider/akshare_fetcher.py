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

    # ------------------------------------------------------------------
    # 公共接口实现
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "akshare"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((DataFetchError, requests.RequestException)),
        reraise=True,
    )
    def get_daily_klines(
        self,
        code: str,
        days: int = 120,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[StockQuote]:
        """Get daily K-line data for a single stock."""
        secid = self._to_secid(code)

        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

        params = {
            "secid":   secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt":     "101",       # daily
            "fqt":     "1",         # adjusted close
            "beg":     start_date,
            "end":     end_date,
            "lmt":     str(days),
        }

        resp = self._session.get(
            _EASTMONEY_KLINE_URL,
            params=params,
            timeout=get_config().fetch_timeout,
        )
        resp.raise_for_status()
        payload = resp.json()

        klines = (payload.get("data") or {}).get("klines") or []
        if not klines:
            return []

        quotes: List[StockQuote] = []
        for kline in klines:
            parts = kline.split(",")
            if len(parts) < 6:
                continue
            quotes.append(StockQuote(
                date  = parts[0],
                code  = code,
                open  = float(parts[1]),
                high  = float(parts[2]),
                low   = float(parts[3]),
                close = float(parts[4]),
                volume=float(parts[5]),
                amount=float(parts[6]) if len(parts) > 6 else 0.0,
            ))
        return quotes

    def get_stock_list(self, market: Optional[str] = None) -> List[dict]:
        """Get A-share stock list from Eastmoney."""
        stocks: List[dict] = []
        filter_markets = ["sh", "sz"] if market in (None, "all", "") else [market]

        for mkt in filter_markets:
            secid_prefix = "1" if mkt == "sh" else "0"
            params = {
                "pn":     "1",
                "pz":     "6000",
                "po":     "1",
                "np":     "1",
                "fltt":   "2",
                "invt":   "2",
                "fid":    "f3",
                "fs":     f"{secid_prefix}60::{mkt}",
                "fields": "f12,f14",   # code, name
            }
            try:
                resp = self._session.get(
                    _EASTMONEY_LIST_URL,
                    params=params,
                    timeout=30,
                )
                resp.raise_for_status()
                items = (resp.json().get("data") or {}).get("diff", [])
                for item in items:
                    code = (item.get("f12") or "").strip()
                    name = (item.get("f14") or "").strip()
                    if code and name:
                        stocks.append({"code": code, "name": name, "market": mkt})
            except Exception as e:
                logger.warning("Failed to fetch %s stock list: %s", mkt, e)

            _random_delay()

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
