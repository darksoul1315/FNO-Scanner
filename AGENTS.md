# Project: Institutional F&O Scanner — NSE Derivatives Prop Desk System

## Overview
F&O scanner for NSE derivatives: identifies institutional-grade setups using OI, options, volume, momentum, and sector rotation data.

## Architecture
- `fno_scanner/` — package with modular components
- `run_scanner.py` — entry point with CLI (--enrich flag for real NSE data)
- Scoring: 0-100 based on 8 sub-scores (Liq 10, OI 15, Mom 15, RS 10, Vol 15, Volatility 10, Smart Money 15, Options 10)

## Key Files
- `fno_scanner/scanner.py` — core scanner, analysis pipeline, yfinance data collection with throttling (semaphore=4)
- `fno_scanner/oi_analysis.py` — OI proxy estimation, option chain analysis, PCR, Max Pain
- `fno_scanner/scoring_engine.py` — scoring formula with volatility thresholds, trend gate, RS penalty
- `fno_scanner/ml_predictor.py` — **ML OUTPERFORMANCE PREDICTOR**: XGBoost/RandomForest model that predicts stock outperformance vs NIFTY using 28 features from the analysis pipeline. Trains on historical data, provides calibrated probabilities and SHAP explainability.
- `fno_scanner/volume_analytics.py` — volume profile, VWAP, delivery proxy
- `fno_scanner/sector_rotation.py` — sector classification, RS computation, breadth analysis
- `fno_scanner/option_chain.py` — option chain utilities
- `fno_scanner/after_market.py` — **REAL NSE DATA**: F&O bhavcopy (cumulative OI across expiries), delivery report, block deals
- `fno_scanner/nse_data.py` — live NSE API functions (alternative to after_market)

## Recent Changes (Session: May 24, 2026)

### Real NSE After-Market Data Integration
- `get_futures_oi_from_bhav()` — aggregates futures OI across ALL expiry months per symbol (cumulative OPEN_INT, sum of CHG_IN_OI)
- `fetch_delivery_report()` — real delivery % from NSE `sec_bhavdata_full` report
- `classify_real_oi()` — OI classification (Long Buildup / Short Covering / Long Unwinding / Short Buildup)
- `enrich_from_bhavcopy()` — 3-phase enrichment: (1) cumulative OI, (2) delivery %, (3) score recalculation
  - Replaces OI_Chg%, OI_Class, Del% with real data
  - Adds FUT_OI (total open interest) and FUT_CONTRACTS (active expiry count)
  - Adds REAL_DEL% column
  - Only recalculates scores when real OI data is available
- Weekend detection: auto-falls back to last trading day
- Reduced HTTP timeout: 15s, retries: 2
- Caching: .nse_cache/ directory with 24-hour TTL

### ML Outperformance Predictor (Session: May 24, 2026)
- `ml_predictor.py` — XGBoost (or RandomForest fallback) trained on 28 features from the analysis pipeline
- **Training**: `--train-ml` fetches 400 days of data for all F&O stocks, extracts features per-bar, labels with forward 5-day outperformance vs NIFTY (+1.5% threshold), and trains a classifier
- **Features** (28): RSI, StochK, MACD histogram, MACD cross, ROC(20), ATR ratio, BB width %ile, ATR expansion %, tight range %, NR7, inside day, compression flag, VWAP dist %, above VWAP, volume ratio, up/down ratio, accumulation, delivery score, OI change %, PCR proxy, composite RS, RS 21d, RS 63d, avg traded value, price change %, OBV above MA, sector bonus
- **Score integration**: ML confidence (0-100%) is added as a score boost (-10 to +15 points) to the heuristic score
- **SHAP**: Full explainability support when `shap` is installed — shows top 10 features driving each prediction
- **Persistence**: Trained model saved to `.ml_cache/xgboost_model.pkl`; loads automatically on subsequent runs
- **Fallback**: If XGBoost/OpenMP is unavailable, uses RandomForestClassifier from scikit-learn automatically

### Running
```bash
# Proxy mode (default, no NSE download)
python run_scanner.py --top 20

# Real data mode (downloads F&O bhavcopy + delivery report)
python run_scanner.py --top 20 --enrich

# ML-enhanced scan (requires trained model)
python run_scanner.py --ml --top 20

# Train ML model from historical data + run scan
python run_scanner.py --train-ml --top 20

# ML + real NSE data
python run_scanner.py --train-ml --enrich --top 20 --export

# Other options
python run_scanner.py --min-score 50 --top 10 --enrich --export
```

### Notes
- F&O bhavcopy available ~6 PM IST on trading days; returns None on weekends/holidays
- Delivery report (`sec_bhavdata_full`) available even on weekends (NSE republishes last trading day)
- `--enrich` is opt-in to avoid surprise HTTP delays for users who only want proxy data
