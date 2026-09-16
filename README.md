# 📈 连续上涨股票扫描器

每日自动扫描 A 股全市场，筛选近期**连续 N 天上涨**的股票。

无需 AI API Key，完全免费运行。

---

## 功能特性

| 能力 | 说明 |
|------|------|
| 连续上涨筛选 | 精确匹配 `收盘价[i] > 收盘价[i-1]` 的连续序列 |
| A 股全市场扫描 | 覆盖沪深两市约 5000+ 只股票 |
| 防封禁机制 | 随机延迟 + 指数退避重试 + User-Agent 轮换 |
| ST/科创/创业板过滤 | 可选排除，默认排除 ST |
| 多格式输出 | 控制台表格 + JSON + CSV |
| GitHub Actions 自动化 | 工作日定时扫描，结果自动上传 Artifact |

## 核心算法

对每只股票获取最近交易日数据，从末尾向前扫描最长连续上涨序列：

```
[100, 101, 102, 103, 104, 105]  →  连续 6 天上涨 ✅
[99, 100, 101, 100, 101, 102]   →  最长连续 3 天，不满足 ❌
[100, 100, 100, 100, 100]       →  无连续上涨，不满足 ❌
```

## 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 复制配置
cp .env.example .env

# 3. 运行扫描（默认连续5天）
python main.py

# 更多选项
python main.py --days 7              # 连续7天上涨
python main.py --days 5 --market sh  # 仅沪市
python main.py --no-exclude-st       # 不排除 ST
python main.py --stock-list stocks.txt  # 指定股票列表
python main.py --verbose             # 调试模式
```

### GitHub Actions 部署（推荐）

1. **Fork** 本仓库
2. 进入 **Settings → Secrets and variables → Actions**
3. （可选）添加通知渠道 Secrets：

| Secret | 说明 |
|--------|------|
| `WECHAT_WEBHOOK_URL` | 企业微信机器人 Webhook |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID |
| `DISCORD_WEBHOOK_URL` | Discord Webhook |
| `PUSHPLUS_TOKEN` | PushPlus Token |

4. 进入 **Actions → 每日连续上涨扫描**，可手动触发

扫描结果自动保存为 GitHub Actions Artifact，保留 30 天。

## 项目结构

```
continuous_up_scanner/
├── .github/workflows/
│   └── daily-scan.yml          # GitHub Actions 工作流
├── data_provider/
│   ├── base.py                 # 抽象基类 BaseFetcher + ScanConfig
│   └── akshare_fetcher.py      # AkShare 数据源（东方财富 API）
├── src/
│   ├── config.py               # 配置管理（读取 .env）
│   └── scanner.py              # 核心筛选逻辑
├── main.py                     # 主入口
├── requirements.txt
└── .env.example
```

## 数据源

- **主要**：东方财富 push2 API（通过 requests 直连，无需 akshare 包，但依赖它的接口稳定性）
- **替代**：可替换为 Tushare、YFinance 等（实现 `BaseFetcher` 接口即可）

## 输出示例

```
================================================================ ==============================
  连续上涨股票筛选结果  (共 12 只)
================================================================ ==============================
  代码        名称          市场  起始日期      结束日期       连续天数     区间涨幅
  ---------- ------------ ---- ------------ ------------ ---------- ------------
  600519     贵州茅台     sh   2026-09-07   2026-09-14        5     +8.32%
  000858     五粮液       sz   2026-09-05   2026-09-14        6     +12.45%
  ...
================================================================ ==============================

JSON 结果已保存至: output/continuous_up_20260914_173000.json
CSV 结果已保存至: output/continuous_up_20260914_173000.csv
```

## 与原版 daily_stock_analysis 对比

| 维度 | daily_stock_analysis（原版） | continuous_up_scanner（本项目） |
|------|---------------------------|-------------------------------|
| 定位 | 单只股票深度 AI 分析 | 全市场快速筛选 |
| 是否需要 AI Key | 是（Gemini/Claude/OpenAI等） | **否** |
| 数据源 | AkShare/YFinance/TickFlow等 | 东方财富 API（免费） |
| GitHub Actions | 需要大量 Secrets 配置 | 只需 Fork，开箱即用 |
| 扫描速度 | 逐只深度分析（分钟级） | 批量快扫（约 10-20 分钟） |
| 输出内容 | AI 决策报告 + 评分 | 连续上涨序列 + 涨幅 |
| 推送渠道 | 6+ 种 | 5 种（可扩展） |

## License

MIT
