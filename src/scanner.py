# -*- coding: utf-8 -*-
"""
Consecutive up-stock scanner.

Core logic: fetch recent trading days for each stock, find the longest
sequence where each day's close is strictly greater than the previous day.
Uses sequential scanning for reliability (akshare is slow/unstable).
"""

from __future__ import annotations
tqdm = lambda *args, **kwargs: __import__("tqdm").tqdm(*args, disable=True, **kwargs)


import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional

from data_provider.multi_source_fetcher import MultiSourceFetcher
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
    diag: Optional[dict] = None,
) -> Optional[ConsecutiveUpResult]:
    """
    Check if a stock has a consecutive up sequence >= continuous_days.

    Algorithm: scan from the last day backwards, find the longest consecutive
    up run ending at the latest day. If length >= requirement, return the result.
    """
    cfg = config or get_config()
    fetcher = MultiSourceFetcher()

    lookback = cfg.continuous_days + 5
    try:
        quotes = fetcher.get_daily_klines(code, days=lookback)
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", code, str(e)[:80])
        if diag:
            diag["error"] = str(e)[:100]
        return None

    if not quotes or len(quotes) < cfg.continuous_days + 1:
        if diag:
            diag["reason"] = f"no_data ({len(quotes) if quotes else 0} quotes)"
        return None

    closes = [q.close for q in quotes]
    dates = [q.date for q in quotes]
    n = len(closes)

    # Require: latest day must be an up day (streak ends today)
    if closes[-1] <= closes[-2]:
        if diag:
            diag["reason"] = f"last_day_down ({dates[-2]} {closes[-2]:.2f} -> {dates[-1]} {closes[-1]:.2f})"
        return None

    # Count backwards from the last day
    streak = 1
    for i in range(n - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            streak += 1
        else:
            break

    if streak < cfg.continuous_days:
        if diag:
            diag["reason"] = f"streak={streak} < {cfg.continuous_days}"
        return None

    start_idx = n - streak
    streak_dates = dates[start_idx:n]
    streak_prices = closes[start_idx:n]
    total_change = (streak_prices[-1] / streak_prices[0] - 1) * 100 if streak_prices[0] > 0 else 0.0

    return ConsecutiveUpResult(
        code=code,
        name=name,
        market=market,
        streak_start_date=streak_dates[0],
        streak_end_date=streak_dates[-1],
        streak_days=streak,
        prices=streak_prices,
        dates=streak_dates,
        pct_change_total=round(total_change, 2),
        latest_close=closes[-1],
        latest_date=dates[-1],
    )


def scan_stock_list(
    stocks: List[dict],
    *,
    config: Optional[ScanConfig] = None,
) -> List[ConsecutiveUpResult]:
    """
    Scan stocks concurrently for speed.
    """
    cfg = config or get_config()
    fetcher = MultiSourceFetcher()
    results: List[ConsecutiveUpResult] = []
    total = len(stocks)
    lock = threading.Lock()

    # Diagnostic tracking
    diag_seen: List[dict] = []
    diag_lock = threading.Lock()
    skipped_st = 0
    skipped_kc_cy = 0
    failed_fetch = 0
    no_match = 0
    stats_lock = threading.Lock()

    logger.info("Scanning %d stocks concurrently (workers=10), consecutive up >= %d days",
                total, cfg.continuous_days)

    def scan_one(stock: dict) -> Optional[ConsecutiveUpResult]:
        nonlocal skipped_st, skipped_kc_cy, failed_fetch, no_match
        code = stock["code"]
        name = stock["name"]
        market = stock.get("market", "sh")

        # Filter
        if cfg.exclude_st and fetcher.is_st_stock(name):
            with stats_lock:
                skipped_st += 1
            return None
        if cfg.exclude_kc_cy and fetcher.is_kc_cy_stock(code):
            with stats_lock:
                skipped_kc_cy += 1
            return None

        # Scan
        diag_info: dict = {}
        result = find_consecutive_up(code, name, market, config=cfg, diag=diag_info)

        # Track diagnostics
        if len(diag_seen) < 5:
            with diag_lock:
                if len(diag_seen) < 5:
                    diag_seen.append({"code": code, **diag_info})
                    if len(diag_seen) == 5:
                        logger.info("DIAG first 5: %s", diag_seen)

        if result:
            return result
        else:
            with stats_lock:
                no_match += 1
                if "error" in diag_info:
                    failed_fetch += 1
            return None

    # Concurrent execution
    max_workers = 10
    t_start = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scan_one, stock): stock for stock in stocks}
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            if result:
                with lock:
                    results.append(result)
                    logger.info("[%d] %s %s %d days, +%.2f%%",
                                len(results), result.code, result.name,
                                result.streak_days, result.pct_change_total)

            # Progress every 500 stocks
            if completed % 500 == 0 or completed == total:
                elapsed = time.time() - t_start
                rate = completed / elapsed if elapsed > 0 else 0
                with stats_lock:
                    logger.info("Progress: %d/%d, found=%d, no_match=%d, failed=%d, rate=%.1f/sec",
                                completed, total, len(results), no_match, failed_fetch, rate)

    results.sort(key=lambda r: r.pct_change_total, reverse=True)
    elapsed = time.time() - t_start
    logger.info("Done: %d found out of %d scanned (%.0fs, %.1f/sec)",
                len(results), total, elapsed, total / elapsed if elapsed > 0 else 0)
    logger.info("  skipped_ST=%d, skipped_KC_CY=%d, no_match=%d, failed_fetch=%d",
                skipped_st, skipped_kc_cy, no_match, failed_fetch)
    return results
