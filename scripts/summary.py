# -*- coding: utf-8 -*-
"""连续上涨扫描结果摘要生成脚本 - GitHub Actions 专用"""
import json
import sys

def main():
    json_file = sys.argv[1]
    days = sys.argv[2]
    market = sys.argv[3]
    count = sys.argv[4] if len(sys.argv) > 4 else "?"

    with open(json_file, encoding="utf-8") as f:
        data = json.load(f)

    lines = [f"**[连续上涨扫描 {today}]**", "",
             f"连续 {days} 天上涨 · 市场 {market} · 找到 {len(data)} 只", ""]
    for r in data[:5]:
        lines.append(f"{r['code']} {r.get('name','')} {r['streak_days']}天 +{r['pct_change']}%")
    if len(data) > 5:
        lines.append(f"... 共 {len(data)} 只，详见 Artifact")
    lines.append("")
    lines.append("详情见 GitHub Actions 日志。")

    print("\n".join(lines))

if __name__ == "__main__":
    from datetime import date
    today = date.today().isoformat()
    main()
