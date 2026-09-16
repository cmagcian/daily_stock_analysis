# -*- coding: utf-8 -*-
"""
连续上涨股票扫描器 - 主入口

用法：
    python main.py                          # 默认参数运行
    python main.py --days 7                 # 连续7天上涨
    python main.py --days 5 --market sh     # 仅沪市
    python main.py --days 10 --verbose      # 调试模式
    python main.py --help                   # 帮助信息
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from data_provider.akshare_fetcher import AkShareFetcher
from data_provider.base import ScanConfig
from src.config import get_config
from src.scanner import ConsecutiveUpResult, scan_stock_list

logger = logging.getLogger("main")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ------------------------------------------------------------------
# 输出模块
# ------------------------------------------------------------------

def print_table(results: list[ConsecutiveUpResult]) -> None:
    """在控制台以表格形式打印结果"""
    if not results:
        print("\n未找到满足条件的股票。")
        return

    sep_line = "=" * 95
    dash_line = (
        "  "
        + "-" * 10 + " " + "-" * 12 + " " + "-" * 4 + " "
        + "-" * 12 + " " + "-" * 12 + " "
        + "-" * 6 + " " + "-" * 12
    )

    print(f"\n{sep_line}")
    print(f"  连续上涨股票筛选结果  (共 {len(results)} 只)")
    print(f"{sep_line}")
    header = (
        f"  {'代码':<10} {'名称':<12} {'市场':<4} "
        f"{'起始日期':<12} {'结束日期':<12} "
        f"{'连续天数':>6} {'区间涨幅':>12}"
    )
    print(header)
    print(dash_line)

    for r in results:
        pct = f"+{r.pct_change_total:.2f}%" if r.pct_change_total >= 0 else f"{r.pct_change_total:.2f}%"
        line = (
            f"  {r.code:<10} {r.name:<12} {r.market:<4} "
            f"{r.streak_start_date:<12} {r.streak_end_date:<12} "
            f"{r.streak_days:>6}  {pct:>12}"
        )
        print(line)

    print(f"{sep_line}\n")


def save_json(results: list[ConsecutiveUpResult], output_dir: str) -> str:
    """保存为 JSON 文件"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = Path(output_dir) / f"continuous_up_{timestamp}.json"

    data = [
        {
            "code":           r.code,
            "name":           r.name,
            "market":         r.market,
            "streak_start":   r.streak_start_date,
            "streak_end":     r.streak_end_date,
            "streak_days":    r.streak_days,
            "prices":         r.prices,
            "dates":          r.dates,
            "pct_change":     r.pct_change_total,
            "latest_close":   r.latest_close,
            "latest_date":    r.latest_date,
        }
        for r in results
    ]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"JSON 结果已保存至: {filepath}")
    return str(filepath)


def save_csv(results: list[ConsecutiveUpResult], output_dir: str) -> str:
    """保存为 CSV 文件"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = Path(output_dir) / f"continuous_up_{timestamp}.csv"

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "代码", "名称", "市场",
            "连续起始日", "连续结束日", "连续天数",
            "区间涨幅(%)", "最新收盘价", "最新日期",
        ])
        for r in results:
            writer.writerow([
                r.code, r.name, r.market,
                r.streak_start_date, r.streak_end_date, r.streak_days,
                r.pct_change_total, r.latest_close, r.latest_date,
            ])

    print(f"CSV 结果已保存至: {filepath}")
    return str(filepath)


def save_results(results: list[ConsecutiveUpResult], output_dir: str) -> None:
    """同时保存 JSON 和 CSV"""
    save_json(results, output_dir)
    save_csv(results, output_dir)


# ------------------------------------------------------------------
# 参数解析
# ------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="连续上涨股票扫描器 — 筛选近期连续上涨的股票",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                     # 默认连续5天上涨
  python main.py --days 7            # 连续7天上涨
  python main.py --days 5 --market sh   # 仅沪市
  python main.py --days 10 --verbose # 调试模式
        """,
    )
    parser.add_argument("--days", type=int, default=None,
                        help="连续上涨天数要求（默认从 .env 读取，默认 5）")
    parser.add_argument("--market", type=str, default=None,
                        choices=["all", "sh", "sz"],
                        help="扫描市场范围：all/sh/sz（默认 all）")
    parser.add_argument("--no-exclude-st", action="store_true",
                        help="不排除 ST 股票")
    parser.add_argument("--no-exclude-kc-cy", action="store_true",
                        help="不排除科创板/创业板（默认排除）")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="输出目录（默认 ./output）")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="开启调试日志")
    parser.add_argument("--stock-list", type=str, default=None,
                        help="指定股票列表文件（每行一个代码，覆盖全市场扫描）")
    return parser.parse_args()


# ------------------------------------------------------------------
# 主程序
# ------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    logger.info("连续上涨股票扫描器启动")

    cfg = get_config()

    # 命令行参数覆盖环境变量
    config_dict = {
        "continuous_days":  args.days   if args.days   is not None else cfg.continuous_days,
        "output_dir":       args.output_dir if args.output_dir else cfg.output_dir,
        "exclude_st":       not args.no_exclude_st,
        "exclude_kc_cy":    not args.no_exclude_kc_cy,
        "market":           args.market   if args.market   else cfg.market,
        "request_delay":    cfg.request_delay,
        "fetch_timeout":    cfg.fetch_timeout,
        "max_retries":      cfg.max_retries,
        "stock_list_file":  args.stock_list,
    }
    cfg = ScanConfig(**config_dict)

    logger.info("配置: 连续天数=%d, 市场=%s, 排除ST=%s, 排除科创/创业=%s",
                cfg.continuous_days, cfg.market, cfg.exclude_st, cfg.exclude_kc_cy)

    fetcher = AkShareFetcher()

    # 加载股票列表
    if cfg.stock_list_file:
        logger.info("从文件读取股票列表: %s", cfg.stock_list_file)
        with open(cfg.stock_list_file, encoding="utf-8") as f:
            codes = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        stocks = [
            {"code": c, "name": c, "market": "sh" if c.startswith(("6", "5")) else "sz"}
            for c in codes
        ]
    else:
        logger.info("正在获取 A 股市场列表...")
        stocks = fetcher.get_stock_list(market=cfg.market)
        logger.info("共获取 %d 只股票", len(stocks))
        if not stocks:
            logger.error("获取股票列表失败，请检查网络连接")
            return 1

    # 执行扫描
    start_time = time.time()
    results = scan_stock_list(stocks, config=cfg)
    elapsed = time.time() - start_time

    # 输出结果
    print_table(results)

    if results:
        save_results(results, cfg.output_dir)
        print(f"\n[OK] 扫描完成！耗时 {elapsed:.1f} 秒，共找到 {len(results)} 只符合条件的股票")
    else:
        print(f"\n[!] 扫描完成！耗时 {elapsed:.1f} 秒，未找到符合条件的股票")
        print("    提示：可以尝试减少连续上涨天数要求，例如 --days 3")

    return 0


if __name__ == "__main__":
    sys.exit(main())
