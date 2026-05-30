# FNO Scanner

Real-time F&O stock scanner for Indian markets — automatically fetches NSE data, computes technical/sector/volume scores, and ranks stocks with ML confidence.

## Features

- **Real NSE Data** — Futures OI (cumulative across expiries), PCR from option chain, delivery % from NSE reports
- **Live F&O Stock List** — Bhavcopy-based, no stale symbols
- **Heuristic Scoring** — Momentum, sector rotation, volume, OI analysis, delivery quality
- **ML Confidence** — GradientBoosting model (26 features) predicts 5-day outperformance vs NIFTY; auto-retrains via feedback loop
- **Sector Rotation** — Sector phase, RS, breadth, market regime integrated into scoring & ML
- **Excel Export** — Full universe (all F&O stocks) with color-coded status, ML confidence, data source indicator
- **Automatic Scheduling** — macOS launchd plist for daily 9 PM runs

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Full scan with ML (default)
python run_scanner.py --top 20

# Without ML
python run_scanner.py --no-ml

# Proxy data only (skip NSE real data)
python run_scanner.py --force-proxy

# Retrain ML model
python run_scanner.py --train-ml

# All flags
python run_scanner.py --help
```

## Output

- **Terminal** — Categorized stock table with scores, ML confidence, data source badge (🟢 REAL / 🟡 PROXY)
- **Excel** — `fno_scanner_report.xlsx` with Scanner Results + Full Universe sheet

## Scheduling (macOS)

```bash
# Load auto-run at 9 PM daily
launchctl load ~/Library/LaunchAgents/com.user.fnoscanner.plist

# View logs
tail -f ~/Library/Logs/fnoscanner.log
```

## Project Structure

```
fno_scanner/
├── scanner.py           # Main scan pipeline
├── after_market.py      # NSE bhavcopy/delivery enrichment
├── ml_predictor.py      # GradientBoosting model + feedback loop
├── scoring_engine.py    # Heuristic scoring logic
├── sector_rotation.py   # Sector phase/RS/breadth
├── technical_analysis.py # RSI, MACD, Bollinger, VWAP
├── volume_analytics.py  # Volume profile
├── oi_analysis.py       # OI trend analysis
├── nse_data.py          # NSE data fetching
├── config.py            # Constants, sector map
└── excel_export.py      # Excel report generation
run_scanner.py           # CLI entry point
```
