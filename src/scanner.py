# -*- coding: utf-8 -*-
"""
Consecutive up-stock scanner.

Core logic: fetch recent trading days for each stock, find the longest
sequence where each day's close is strictly greater than the previous day.
Uses sequential scanning for reliability (akshare is slow/unstable).
"""

from __future__ import annotations

import logging
import time
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
    diag: Optional[dict] = None,
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
    Scan a list of stocks sequentially for reliability.
    """
    cfg = config or get_config()
    fetcher = AkShareFetcher()
    results: List[ConsecutiveUpResult] = []
    total = len(stocks)

    # Diagnostic tracking
    diag_seen: List[dict] = []
    skipped_st = 0
    skipped_kc_cy = 0
    failed_fetch = 0
    no_match = 0

    logger.info("Scanning %d stocks sequentially, consecutive up >= %d days",
                total, cfg.continuous_days)

    t_start = time.time()

    for idx, stock in enumerate(stocks):
        code = stock["code"]
        name = stock["name"]
        market = stock.get("market", "sh")

        # Filter
        if cfg.exclude_st and fetcher.is_st_stock(name):
            skipped_st += 1
            continue
        if cfg.exclude_kc_cy and fetcher.is_kc_cy_stock(code):
            skipped_kc_cy += 1
            continue

        # Scan
        t0 = time.time()
        diag_info: dict = {}
        result = find_consecutive_up(code, name, market, config=cfg, diag=diag_info)
        elapsed = time.time() - t0

        # Track first few for diagnostics
        if len(diag_seen) < 5:
            diag_seen.append({"code": code, "elapsed": elapsed, **diag_info})
            if len(diag_seen) == 5:
                logger.info("DIAG first 5 (showing failure reasons): %s", diag_seen)

        if result:
            results.append(result)
            logger.info("[%d] %s %s %d days, +%.2f%% (%.1fs)",
                        len(results), code, name, result.streak_days,
                        result.pct_change_total, elapsed)
        else:
            no_match += 1
            if "error" in diag_info:
                failed_fetch += 1

        # Progress every 500 stocks
        if (idx + 1) % 500 == 0 or idx + 1 == total:
            elapsed_total = time.time() - t_start
            rate = (idx + 1) / elapsed_total if elapsed_total > 0 else 0
            logger.info("Progress: %d/%d, found=%d, no_match=%d, failed=%d, rate=%.2f/sec, elapsed=%.0fs",
                        idx + 1, total, len(results), no_match, failed_fetch, rate, elapsed_total)

        # Rate limiting: 0.3s delay between requests
        time.sleep(cfg.request_delay)

    results.sort(key=lambda r: r.pct_change_total, reverse=True)
    elapsed = time.time() - t_start
    logger.info("Done: %d found out of %d scanned (%.0fs, %.2f/sec)",
                len(results), total, elapsed, total / elapsed if elapsed > 0 else 0)
    logger.info("  skipped_ST=%d, skipped_KC_CY=%d, no_match=%d, failed_fetch=%d",
                skipped_st, skipped_kc_cy, no_match, failed_fetch)
    return results
