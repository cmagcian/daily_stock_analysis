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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional

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
    up run ending at the latest day. If length >= requirement, return the result.
    """
    cfg = config or get_config()
    fetcher = AkShareFetcher()

    lookback = cfg.continuous_days + 5
    try:
        quotes = fetcher.get_daily_klines(code, days=lookback)
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", code, e)
        return None

    if not quotes or len(quotes) < cfg.continuous_days + 1:
        return None

    closes = [q.close for q in quotes]
    dates = [q.date for q in quotes]
    n = len(closes)

    # Require: latest day must be an up day (streak ends today)
    if closes[-1] <= closes[-2]:
        return None

    # Count backwards from the last day
    streak = 1
    for i in range(n - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            streak += 1
        else:
            break

    if streak < cfg.continuous_days:
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


def _scan_one(stock: dict, cfg: ScanConfig, fetcher: AkShareFetcher,
              results: List[ConsecutiveUpResult], lock: threading.Lock,
              stats: dict, diag_seen_ref: list) -> None:
    """Scan a single stock and append result if matched."""
    code = stock["code"]
    name = stock["name"]
    market = stock.get("market", "sh")

    if cfg.exclude_st and fetcher.is_st_stock(name):
        stats["skipped_st"] += 1
        return
    if cfg.exclude_kc_cy and fetcher.is_kc_cy_stock(code):
        stats["skipped_kc_cy"] += 1
        return

    t0 = time.time()
    result = find_consecutive_up(code, name, market, config=cfg)
    elapsed = time.time() - t0

    # DIAG: show first 5 stocks to check data
    if len(diag_seen_ref) < 5:
        with diag_lock:
            diag_seen_ref.append({"code": code, "elapsed": elapsed})
            if len(diag_seen_ref) == 5:
                logger.info("DIAG: first 5 stocks scanned (no filter applied yet): %s", diag_seen_ref)

    # DIAG: show why each stock fails (first 10)
    if result is None and len(diag_seen_ref) >= 5 and len(diag_seen_ref) < 15:
        with diag_lock:
            if len([d for d in diag_seen_ref if "fail_reason" in d]) < 10:
                # We can't easily get the failure reason from find_consecutive_up
                # So just log that we're checking
                pass

    if elapsed > 3.0:
        logger.debug("SLOW: %s took %.1fs", code, elapsed)

    if result:
        with lock:
            results.append(result)
            logger.info("[%d] %s %s %d days, +%.2f%% (%.1fs)",
                        len(results), code, name, result.streak_days,
                        result.pct_change_total, elapsed)
    else:
        stats["no_match"] += 1


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

    # Shared stats dict for cross-thread counting
    stats = {"no_match": 0, "skipped_st": 0, "skipped_kc_cy": 0, "no_data": 0}

    # Diagnostic: track the first 5 stocks that have data to verify
    diag_seen: list = []
    diag_lock = threading.Lock()

    # Use 20 concurrent workers for speed
    max_workers = min(20, total)
    logger.info("Scanning %d stocks (workers=%d), consecutive up >= %d days",
                total, max_workers, cfg.continuous_days)

    t_start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scan_one, stock, cfg, fetcher, results, lock, stats, diag_seen): stock
                   for stock in stocks}
        for i, future in enumerate(as_completed(futures), 1):
            if i % 500 == 0 or i == total:
                elapsed = time.time() - t_start
                rate = i / elapsed if elapsed > 0 else 0
                logger.info("Progress: %d/%d, found %d, no_match=%d, rate=%.1f/sec, elapsed=%.0fs",
                            i, total, len(results), stats["no_match"], rate, elapsed)

    results.sort(key=lambda r: r.pct_change_total, reverse=True)
    elapsed = time.time() - t_start
    logger.info("Done: %d found out of %d scanned (%.1fs, %.1f/sec)",
                len(results), total, elapsed, total / elapsed if elapsed > 0 else 0)
    logger.info("  skipped_ST=%d, skipped_KC_CY=%d, no_match=%d",
                stats["skipped_st"], stats["skipped_kc_cy"], stats["no_match"])
    return results
