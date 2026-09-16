# -*- coding: utf-8 -*-
"""
Stock market scanner for consecutive up-trending stocks.

Usage:
    python main.py                          # default: 5 consecutive up days
    python main.py --days 7                 # 7 consecutive up days
    python main.py --market sh              # Shanghai market only
    python main.py --verbose                # debug mode
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
# Output helpers
# ------------------------------------------------------------------

def print_table(results: list[ConsecutiveUpResult]) -> None:
    if not results:
        print("\nNo stocks match the criteria.")
        return

    sep = "=" * 95
    print(f"\n{sep}")
    print(f"  Consecutive Up Stocks ({len(results)} found)")
    print(f"{sep}")
    header = (
        f"  {'Code':<10} {'Name':<12} {'Mkt':<4} "
        f"{'Start Date':<12} {'End Date':<12} "
        f"{'Days':>6} {'Change':>12}"
    )
    print(header)
    print(f"  {'-'*10} {'-'*12} {'-'*4} "
          f"{'-'*12} {'-'*12} "
          f"{'-'*6} {'-'*12}")

    for r in results:
        pct = f"+{r.pct_change_total:.2f}%" if r.pct_change_total >= 0 else f"{r.pct_change_total:.2f}%"
        line = (
            f"  {r.code:<10} {r.name:<12} {r.market:<4} "
            f"{r.streak_start_date:<12} {r.streak_end_date:<12} "
            f"{r.streak_days:>6}  {pct:>12}"
        )
        print(line)

    print(f"{sep}\n")


def save_json(results: list[ConsecutiveUpResult], output_dir: str) -> str:
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

    print(f"JSON saved to: {filepath}")
    return str(filepath)


def save_csv(results: list[ConsecutiveUpResult], output_dir: str) -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = Path(output_dir) / f"continuous_up_{timestamp}.csv"

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Code", "Name", "Market",
            "Streak Start", "Streak End", "Streak Days",
            "Pct Change(%)", "Latest Close", "Latest Date",
        ])
        for r in results:
            writer.writerow([
                r.code, r.name, r.market,
                r.streak_start_date, r.streak_end_date, r.streak_days,
                r.pct_change_total, r.latest_close, r.latest_date,
            ])

    print(f"CSV saved to: {filepath}")
    return str(filepath)


def save_results(results: list[ConsecutiveUpResult], output_dir: str) -> None:
    save_json(results, output_dir)
    save_csv(results, output_dir)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan A-share stocks for consecutive up days",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                     # default 5 consecutive up days
  python main.py --days 7            # 7 consecutive up days
  python main.py --market sh         # Shanghai only
  python main.py --verbose           # debug mode
        """,
    )
    parser.add_argument("--days", type=int, default=None,
                        help="Consecutive up days requirement (default: 5)")
    parser.add_argument("--market", type=str, default=None,
                        choices=["all", "sh", "sz"],
                        help="Market scope: all/sh/sz (default: all)")
    parser.add_argument("--no-exclude-st", action="store_true",
                        help="Do not exclude ST stocks")
    parser.add_argument("--no-exclude-kc-cy", action="store_true",
                        help="Do not exclude STAR/ChiNext stocks")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory (default: ./output)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--stock-list", type=str, default=None,
                        help="Path to stock list file (one code per line)")
    return parser.parse_args()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    logger.info("Scanner started")

    cfg = get_config()

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

    logger.info("Config: days=%d, market=%s, exclude_st=%s, exclude_kc_cy=%s",
                cfg.continuous_days, cfg.market, cfg.exclude_st, cfg.exclude_kc_cy)

    fetcher = AkShareFetcher()

    if cfg.stock_list_file:
        logger.info("Reading stock list from: %s", cfg.stock_list_file)
        with open(cfg.stock_list_file, encoding="utf-8") as f:
            codes = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        stocks = [
            {"code": c, "name": c, "market": "sh" if c.startswith(("6", "5")) else "sz"}
            for c in codes
        ]
    else:
        logger.info("Fetching A-share stock list...")
        stocks = fetcher.get_stock_list(market=cfg.market)
        logger.info("Total stocks: %d", len(stocks))
        if not stocks:
            logger.error("Failed to fetch stock list. Check network connectivity.")
            return 1

    start_time = time.time()
    results = scan_stock_list(stocks, config=cfg)
    elapsed = time.time() - start_time

    print_table(results)

    if results:
        save_results(results, cfg.output_dir)
        print(f"\n[OK] Done in {elapsed:.1f}s, found {len(results)} stocks")
    else:
        print(f"\n[!] Done in {elapsed:.1f}s, no stocks matched")
        print("    Tip: try fewer consecutive days, e.g. --days 3")

    return 0


if __name__ == "__main__":
    sys.exit(main())
