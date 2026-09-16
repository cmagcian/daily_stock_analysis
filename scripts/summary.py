# -*- coding: utf-8 -*-
"""Summary generator for consecutive up-scan results."""
import json
import sys
from datetime import date


def main():
    json_file = sys.argv[1]
    days = sys.argv[2]
    market = sys.argv[3]

    today = date.today().isoformat()

    with open(json_file, encoding="utf-8") as f:
        data = json.load(f)

    lines = [
        f"**[Consecutive Up Scan {today}]**",
        "",
        f"{days} consecutive up days | Market: {market} | Found: {len(data)} stocks",
        "",
    ]
    for r in data[:5]:
        lines.append(f"{r['code']} {r.get('name','')} {r['streak_days']}days +{r['pct_change']}%")
    if len(data) > 5:
        lines.append(f"... and {len(data) - 5} more, see Artifact")
    lines.extend(["", "See GitHub Actions log for details."])

    print("\n".join(lines))


if __name__ == "__main__":
    main()
