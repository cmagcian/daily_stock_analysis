# -*- coding: utf-8 -*-
"""
Consecutive up-stock scanner.

Core logic: fetch recent trading days for each stock, find the longest
sequence where each day's close is strictly greater than the previous day.
Uses ThreadPoolExecutor for parallel scanning.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from data_provider.akshare_fetcher import AkShareFetcher
from data_provider.base import ScanConfig
from src.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class ConsecutiveUpResult:
    """Result for a single stock that matches the criteria."""
    code: str
    name: str
    market: str
    streak_start_date: str
    streak_end_date: str
    streak_days: int
    prices: List[float] = field(default_factory=list)
    dates: List[str] = field(default_factory=list)
    pct_change_total: float = 0.0
    latest_close: float = 0.0
    latest_date: str = ""


def find_consecutive_up(
    code: str,
    name: str,
    market: str,
    *,
    config: Optional[ScanConfig] = None,
) -> Optional[ConsecutiveUpResult]:
    """
    Check if a stock has a consecutive up sequence >= continuous_days.

    Algorithm: scan from the last day backwards, find the longest consecutive
    up run. If length >= requirement, return the result.
    """
    cfg = config or get_config()
    fetcher = AkShareFetcher()

    lookback = cfg.continuous_days + 10
    try:
        quotes = fetcher.get_daily_klines(code, days=lookback)
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", code, e)
        return None

    if len(quotes) < cfg.continuous_days + 1:
        return None

    closes = [q.close for q in quotes]
    dates = [q.date for q in quotes]
    n = len(closes)

    max_streak = 0
    max_streak_end = n - 1

    cur = 1
    cur_end = n - 1

    for i in range(n - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            cur += 1
        else:
            if cur > max_streak:
                max_streak = cur
                max_streak_end = cur_end
            cur = 1
            cur_end = i - 1

    if cur > max_streak:
        max_streak = cur
        max_streak_end = cur_end

    if max_streak < cfg.continuous_days:
        return None

    start_idx = max_streak_end - max_streak + 1
    streak_dates = dates[start_idx: max_streak_end + 1]
    streak_prices = closes[start_idx: max_streak_end + 1]
    total_change = (streak_prices[-1] / streak_prices[0] - 1) * 100 if streak_prices[0] > 0 else 0.0

    return ConsecutiveUpResult(
        code=code,
        name=name,
        market=market,
        streak_start_date=streak_dates[0],
        streak_end_date=streak_dates[-1],
        streak_days=max_streak,
        prices=streak_prices,
        dates=streak_dates,
        pct_change_total=round(total_change, 2),
        latest_close=closes[-1],
        latest_date=dates[-1],
    )


def _scan_one(stock: dict, cfg: ScanConfig, fetcher: AkShareFetcher,
              results: List[ConsecutiveUpResult], lock: threading.Lock) -> None:
    """Scan a single stock and append result if matched."""
    code = stock["code"]
    name = stock["name"]
    market = stock.get("market", "sh")

    if cfg.exclude_st and fetcher.is_st_stock(name):
        return
    if cfg.exclude_kc_cy and fetcher.is_kc_cy_stock(code):
        return

    result = find_consecutive_up(code, name, market, config=cfg)
    if result:
        with lock:
            results.append(result)
            logger.info("[%d] %s %s %d days, +%.2f%%",
                        len(results), code, name, result.streak_days, result.pct_change_total)


def scan_stock_list(
    stocks: List[dict],
    *,
    config: Optional[ScanConfig] = None,
) -> List[ConsecutiveUpResult]:
    """
    Scan a list of stocks concurrently and return all matching results.
    """
    cfg = config or get_config()
    fetcher = AkShareFetcher()
    results: List[ConsecutiveUpResult] = []
    lock = threading.Lock()
    total = len(stocks)

    # Use 10 concurrent workers for speed
    max_workers = min(10, total)
    logger.info("Scanning %d stocks concurrently (workers=%d), consecutive up >= %d days",
                total, max_workers, cfg.continuous_days)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scan_one, stock, cfg, fetcher, results, lock): stock
                   for stock in stocks}
        for i, future in enumerate(as_completed(futures), 1):
            if i % 100 == 0 or i == total:
                logger.info("Progress: %d/%d, found %d so far", i, total, len(results))

    # Sort by pct_change descending
    results.sort(key=lambda r: r.pct_change_total, reverse=True)
    logger.info("Done: %d found out of %d scanned", len(results), total)
    return results
