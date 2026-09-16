# -*- coding: utf-8 -*-
"""
连续上涨筛选器

核心逻辑：对每只股票获取最近 N 个交易日的收盘价，
检测是否存在连续 consecutive_days 天每天收盘价都高于前一天的股票。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from data_provider.akshare_fetcher import AkShareFetcher
from data_provider.base import ScanConfig
from src.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class ConsecutiveUpResult:
    """单只股票的筛选结果"""
    code: str
    name: str
    market: str
    # 连续上涨序列的详细信息
    streak_start_date: str       # 连续上涨起始日期
    streak_end_date: str         # 连续上涨结束日期（通常是最近交易日）
    streak_days: int             # 实际连续上涨天数
    prices: List[float] = field(default_factory=list)   # 连续期间的每日收盘价
    dates: List[str] = field(default_factory=list)      # 对应日期
    pct_change_total: float = 0.0   # 区间总涨幅（%）
    # 最新行情
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
    判断单只股票是否存在符合要求的连续上涨序列。

    策略：
    1. 获取最近 (continuous_days + 缓冲) 个交易日数据
    2. 从最新日期倒序查找最长的连续上涨序列
    3. 若最长序列 >= 要求天数，返回结果

    Returns:
        ConsecutiveUpResult 或 None（不满足条件）
    """
    cfg = config or get_config()
    fetcher = AkShareFetcher()

    # 多取一些缓冲数据，确保能找到完整序列
    lookback = cfg.continuous_days + 10
    try:
        quotes = fetcher.get_daily_klines(code, days=lookback)
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", code, e)
        return None

    if len(quotes) < cfg.continuous_days + 1:
        return None

    # quotes 已按日期升序排列
    closes = [q.close for q in quotes]
    dates  = [q.date  for q in quotes]
    n = len(closes)

    # 从末尾向前扫描，找最长连续上涨序列
    # 关键：streak_end 指向序列最后一个上涨日的索引（即最高点）
    max_streak = 0
    max_streak_end = n - 1  # 初始为最后一个索引

    current_streak = 1
    current_streak_end = n - 1

    for i in range(n - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            # 当前天比前一天高，连续上涨序列延伸
            current_streak += 1
        else:
            # 当前天比前一天低或持平，结束当前序列
            if current_streak > max_streak:
                max_streak = current_streak
                max_streak_end = current_streak_end
            # 新序列从 i 开始（长度为1，即只有 day i 自身）
            current_streak = 1
            current_streak_end = i - 1  # 新区间的结束是 i-1（因为 i 是下跌点）

    # 处理扫描结束时的最后一段
    if current_streak > max_streak:
        max_streak = current_streak
        max_streak_end = current_streak_end

    if max_streak < cfg.continuous_days:
        return None

    # 计算序列的起止索引
    # 序列从 (max_streak_end - max_streak + 1) 到 max_streak_end
    streak_start_idx = max_streak_end - max_streak + 1
    streak_dates  = dates[streak_start_idx: max_streak_end + 1]
    streak_prices = closes[streak_start_idx: max_streak_end + 1]
    total_change  = (streak_prices[-1] / streak_prices[0] - 1) * 100 if streak_prices[0] > 0 else 0.0

    return ConsecutiveUpResult(
        code           = code,
        name           = name,
        market         = market,
        streak_start_date = streak_dates[0],
        streak_end_date   = streak_dates[-1],
        streak_days      = max_streak,
        prices           = streak_prices,
        dates            = streak_dates,
        pct_change_total = round(total_change, 2),
        latest_close     = closes[-1],
        latest_date      = dates[-1],
    )


def scan_stock_list(
    stocks: List[dict],
    *,
    config: Optional[ScanConfig] = None,
) -> List[ConsecutiveUpResult]:
    """
    批量扫描股票列表，返回所有满足条件的结果。

    Args:
        stocks:  [{"code": "...", "name": "...", "market": "..."}]
        config: 扫描配置（默认从环境变量读取）

    Returns:
        满足连续上涨条件的股票列表，按涨幅降序排列
    """
    import time
    import random

    cfg = config or get_config()
    fetcher = AkShareFetcher()
    results: List[ConsecutiveUpResult] = []
    total = len(stocks)
    skipped = 0
    failed = 0

    logger.info("开始扫描 %d 只股票，连续上涨要求 >= %d 天", total, cfg.continuous_days)

    for idx, stock in enumerate(stocks):
        code   = stock["code"]
        name   = stock["name"]
        market = stock.get("market", "sh")

        # 过滤条件
        if cfg.exclude_st and fetcher.is_st_stock(name):
            skipped += 1
            continue
        if cfg.exclude_kc_cy and fetcher.is_kc_cy_stock(code):
            skipped += 1
            continue

        result = find_consecutive_up(code, name, market, config=cfg)
        if result:
            results.append(result)
            pct = f"+{result.pct_change_total:.2f}%" if result.pct_change_total >= 0 else f"{result.pct_change_total:.2f}%"
            logger.info(
                "[%d] ✅ %s %s 连续 %d 天上涨，涨幅 %s",
                len(results),
                code,
                name,
                result.streak_days,
                pct,
            )
        else:
            failed += 1

        # 每100只输出一次进度
        if (idx + 1) % 100 == 0:
            logger.info("进度：%d/%d，找到 %d 只，跳过 %d 只，失败 %d 只",
                        idx + 1, total, len(results), skipped, failed)

        # 随机延迟防封禁
        time.sleep(random.uniform(0.05, cfg.request_delay))

    logger.info(
        "扫描完成：找到 %d 只，跳过 %d 只（过滤），失败 %d 只",
        len(results), skipped, failed
    )
    return sorted(results, key=lambda r: r.pct_change_total, reverse=True)
