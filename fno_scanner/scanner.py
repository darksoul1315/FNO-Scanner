import sys
import os
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import pandas as pd
    import numpy as np
except ImportError as e:
    print("\n" + "!" * 65)
    print(f"  CRITICAL ERROR: Missing dependency: {e.name}")
    print("  Please install all requirements: pip install -r requirements.txt")
    print("!" * 65 + "\n")
    sys.exit(1)

from .config import (
    FNO_STOCKS, SECTOR_MAP, LIQUIDITY_CONFIG, RUNTIME_CONFIG, FOCUS_SECTORS
)
from .data_engine import DataEngine
from .technical_analysis import (
    compute_atr, detect_market_structure,
    detect_equal_highs_lows, detect_imbalance, detect_fair_value_gaps,
    detect_compression_expansion, detect_breakout_setup,
    analyze_vwap, compute_relative_strength,
    compute_volume_profile, compute_momentum_suite
)
from .volume_analytics import (
    compute_smart_money_volume_score
)
from .oi_analysis import (
    estimate_oi_proxy, compute_oi_score,
    estimate_option_metrics, compute_option_score
)
from .sector_rotation import (
    compute_sector_rs, rank_sectors,
    detect_market_regime, get_sector_bonus
)
from .scoring_engine import compute_institutional_score
from .excel_export import export_comprehensive_excel
from .ml_predictor import MLPredictor, extract_features_from_bundle


class InstitutionalFnOScanner:
    def __init__(self, use_ml=False):
        self.data_engine = DataEngine()
        self.results = []
        self.full_universe = pd.DataFrame()
        self.failed_stocks = []
        self.sector_metrics = {}
        self.market_regime = {}
        self.lock = threading.Lock()
        self.stats = {
            'total': 0,
            'data_ok': 0,
            'liquidity_pass': 0,
            'analyzed': 0,
            'failed': 0,
        }
        self.use_ml = use_ml
        self.ml_predictor = MLPredictor() if use_ml else None
        if use_ml:
            loaded = self.ml_predictor.load()
            if loaded:
                print(f"  [ML] Model loaded ({len(self.ml_predictor.feature_names)} features)")
            else:
                print(f"  [ML] No trained model found. Run with --train-ml first.")

    def analyze_stock(self, symbol, df, nifty_df):
        try:
            close = df['Close'].values
            volume = df['Volume'].values
            n = len(close)

            if n < LIQUIDITY_CONFIG['min_data_days']:
                with self.lock:
                    self.failed_stocks.append({'symbol': symbol, 'reason': f'Insufficient data days: {n} < {LIQUIDITY_CONFIG["min_data_days"]}'})
                return None

            cmp = float(close[-1])

            if cmp < LIQUIDITY_CONFIG['min_price']:
                with self.lock:
                    self.failed_stocks.append({'symbol': symbol, 'reason': f'Price too low: ₹{cmp:.2f} < ₹{LIQUIDITY_CONFIG["min_price"]}'})
                return None

            avg_vol_20 = np.mean(volume[-20:])
            if avg_vol_20 < LIQUIDITY_CONFIG['min_volume_20d']:
                with self.lock:
                    self.failed_stocks.append({'symbol': symbol, 'reason': f'Low 20d avg volume: {avg_vol_20:.0f} < {LIQUIDITY_CONFIG["min_volume_20d"]}'})
                return None

            avg_traded_value = np.mean(close[-20:] * volume[-20:])
            min_traded_value = LIQUIDITY_CONFIG['min_avg_traded_value_cr'] * 1e7
            if avg_traded_value < min_traded_value:
                with self.lock:
                    self.failed_stocks.append({'symbol': symbol, 'reason': f'Low traded value: ₹{avg_traded_value/1e7:.1f}cr < ₹{LIQUIDITY_CONFIG["min_avg_traded_value_cr"]}cr'})
                return None

            with self.lock:
                self.stats['liquidity_pass'] += 1

            structure = detect_market_structure(df)
            equal_levels = detect_equal_highs_lows(df)
            atr_series = compute_atr(df, 14)
            imbalance = detect_imbalance(df, atr_series)
            fvgs = detect_fair_value_gaps(df)
            compression = detect_compression_expansion(df)
            breakout = detect_breakout_setup(df)
            vwap = analyze_vwap(df)
            vol_profile = compute_volume_profile(df.tail(60))
            momentum = compute_momentum_suite(df)

            smart_money_result = compute_smart_money_volume_score(df)
            vol_metrics = smart_money_result['vol_metrics']
            pp_data = smart_money_result['pocket_pivot']
            obv_data = smart_money_result['obv']
            absorption_data = smart_money_result['absorption']
            delivery_data = smart_money_result['delivery']

            oi_data = estimate_oi_proxy(df)
            oi_score = compute_oi_score(df)

            option_data = estimate_option_metrics(df)
            option_score = compute_option_score(df)

            rs_data = {}
            if nifty_df is not None and len(nifty_df) > 60:
                rs_data = compute_relative_strength(df, nifty_df)

            prev_close = float(close[-2]) if n >= 2 else cmp
            daily_change_pct = round((cmp - prev_close) / prev_close * 100, 2)

            sector = SECTOR_MAP.get(symbol, 'Unknown')
            sector_bonus = get_sector_bonus(symbol, self.sector_metrics)
            sector_info = self.sector_metrics.get(sector, {})
            regime = self.market_regime.get('regime', 'neutral')
            regime_num = {'risk_on': 1, 'neutral': 0, 'risk_off': -1}.get(regime, 0)

            analysis_bundle = {
                'cmp': cmp,
                'price_change_pct': daily_change_pct,
                'structure': structure,
                'equal_levels': equal_levels,
                'imbalance': imbalance,
                'fvgs': fvgs,
                'compression': compression,
                'breakout': breakout,
                'vwap': vwap,
                'vol_profile': vol_profile,
                'momentum': momentum,
                'volume': vol_metrics,
                'pocket_pivot': pp_data,
                'obv': obv_data,
                'absorption': absorption_data,
                'delivery': delivery_data,
                'oi': oi_data,
                'oi_score': oi_score,
                'options': option_data,
                'option_score': option_score,
                'rs': rs_data,
                'smart_money_score': smart_money_result['smart_money_score'],
                'sector_phase_score': sector_info.get('momentum_score', 5),
                'sector_rs_1m': sector_info.get('rs_1m', 0),
                'sector_breadth': sector_info.get('breadth_pct', 50),
                'market_regime_num': regime_num,
            }

            scoring = compute_institutional_score(analysis_bundle, sector_bonus)

            ml_conf = 0.0
            ml_boost = 0
            if self.use_ml and self.ml_predictor and self.ml_predictor.is_ready:
                try:
                    fv = extract_features_from_bundle(analysis_bundle, sector_bonus)
                    ml_conf = self.ml_predictor.predict_proba(fv)
                    ml_boost = int(ml_conf * 30) - 10
                    ml_boost = max(-10, min(15, ml_boost))
                    self.ml_predictor.log_prediction(
                        fv, symbol,
                        datetime.now().strftime('%Y-%m-%d'),
                        ml_conf,
                    )
                except Exception as e:
                    print(f"  [ML] Prediction error for {symbol}: {e}")
                    ml_conf = 0.0
                    ml_boost = 0

            sector = self.data_engine.get_sector_for_symbol(symbol)
            sector_info = self.sector_metrics.get(sector, {})

            result = {
                'Symbol': symbol,
                'Sector': sector,
                'sector_phase': sector_info.get('phase', 'Mixed'),
                'market_bias': self.market_regime.get('regime', 'Neutral'),
                'CMP': round(cmp, 2),
                'Chg%': daily_change_pct,
                'volume': vol_metrics.get('avg_vol_20', 0),
                'avg_volume_20d': vol_metrics.get('avg_vol_20', 0),
                'atr_20d': atr_series.iloc[-1] if not atr_series.empty else 0,
                'vwap_20d': vwap.get('vwap', cmp),
                'support': vwap.get('support', cmp * 0.98),
                'resistance': vwap.get('resistance', cmp * 1.02),
                'VolRatio': vol_metrics.get('vol_ratio', 0),
                'Del%': delivery_data.get('delivery_score', 50),
                'ATR_Exp%': compression.get('atr_expansion_pct', 0),
                'OI_Chg%': oi_data.get('oi_change_pct_proxy', 0),
                'OI_Class': oi_data.get('classification', 'Neutral'),
                'PCR': option_data.get('pcr_proxy', 1.0),
                'IV%ile': option_data.get('iv_percentile', 50),
                'RS_Rank': round(rs_data.get('composite_rs', 0) * 100, 1),
                'Score': max(0, min(100, scoring['total_score'] + ml_boost)),
                'Setup': scoring['setup_type'],
                'Liq_Zone': scoring['liquidity_zone'],
                'Bias': scoring['bias'],
                'ML_Conf': round(ml_conf * 100, 1),
                '_sub_liq': scoring['sub_scores']['liquidity'],
                '_sub_oi': scoring['sub_scores']['oi'],
                '_sub_mom': scoring['sub_scores']['momentum'],
                '_sub_rs': scoring['sub_scores']['rs'],
                '_sub_vol': scoring['sub_scores']['volume'],
                '_sub_vola': scoring['sub_scores']['volatility'],
                '_sub_sm': scoring['sub_scores']['smart_money'],
                '_sub_opt': scoring['sub_scores']['option'],
                '_compressed': compression.get('is_compressed', False),
                '_pocket_pivot': pp_data.get('pocket_pivot', False),
                '_accumulation': vol_metrics.get('accumulation', False),
                '_nr7': compression.get('nr7', False),
                '_above_vwap': vwap.get('above_vwap', False),
                '_trend': structure.get('trend', 'unknown'),
            }

            with self.lock:
                self.stats['analyzed'] += 1

            return result

        except Exception as e:
            with self.lock:
                self.stats['failed'] += 1
                self.failed_stocks.append({'symbol': symbol, 'reason': f'Analysis error: {str(e)[:60]}'})
            return None

    def run(self, min_score=0, top_n=None, stock_list=None):
        start_time = time.time()

        if stock_list is None:
            stock_list = FNO_STOCKS
        else:
            stock_list = [s for s in stock_list if s not in ['BANKNIFTY', 'NIFTY']]

        print("=" * 90)
        print("  \u2554" + "\u2550" * 72 + "\u2557")
        print("  \u2551     INSTITUTIONAL F&O SCANNER — NSE DERIVATIVES PROP DESK SYSTEM        \u2551")
        print("  \u2551     Smart Money \u2022 Liquidity Sweeps \u2022 OI Analysis \u2022 Gamma Zones           \u2551")
        print("  \u255a" + "\u2550" * 72 + "\u255d")
        print("=" * 90)
        print(f"  Scan Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Universe: {len(stock_list)} F&O Stocks | Min Score: {min_score}")
        print("-" * 90)

        # PHASE 1: DATA COLLECTION
        print("\n  \u250c\u2500 PHASE 1: Data Collection \u2500" + "\u2500" * 40 + "\u2510")

        nifty_df = self.data_engine.fetch_nifty_data()
        if nifty_df is not None:
            print(f"  \u2502  \u2713 NIFTY 50 benchmark loaded ({len(nifty_df)} days)")
        else:
            print(f"  \u2502  \u26a0 NIFTY 50 data unavailable")

        banknifty_df = self.data_engine.fetch_banknifty_data()
        if banknifty_df is not None:
            print(f"  \u2502  \u2713 BANK NIFTY loaded ({len(banknifty_df)} days)")

        stock_data = self.data_engine.fetch_all_fno_data(stock_list)
        self.stats['total'] = len(stock_list)
        self.stats['data_ok'] = len(stock_data)

        print(f"  \u2502  \u2713 Stock data: {len(stock_data)} valid / {self.stats['total']} total")
        print("  \u2514" + "\u2500" * 64 + "\u2518")

        # PHASE 2: SECTOR ROTATION
        print("\n  \u250c\u2500 PHASE 2: Sector Rotation Analysis \u2500" + "\u2500" * 33 + "\u2510")

        self.sector_metrics = compute_sector_rs(stock_data, nifty_df)
        self.market_regime = detect_market_regime(self.sector_metrics, nifty_df)

        ranked_sectors = rank_sectors(self.sector_metrics)
        for i, (sector, metrics) in enumerate(ranked_sectors):
            phase_indicators = {'Leading': '\U0001f7e2', 'Improving': '\U0001f535', 'Weakening': '\U0001f7e1', 'Lagging': '\U0001f534'}
            indicator = phase_indicators.get(metrics['phase'], '\u26aa')
            print(f"  \u2502  {indicator} {sector:12s} | Phase: {metrics['phase']:10s} | RS(1M): {metrics['rs_1m']:+.3f} | "
                  f"Breadth: {metrics['breadth_pct']:5.1f}% | Score: {metrics['momentum_score']}/10")

        regime = self.market_regime
        regime_indicators = {'risk_on': '\U0001f7e2', 'risk_off': '\U0001f534', 'neutral': '\U0001f7e1'}
        indicator = regime_indicators.get(regime.get('regime', 'neutral'), '\u26aa')
        print(f"  \u2502")
        print(f"  \u2502  {indicator} Market Regime: {regime.get('regime', 'neutral').upper()} "
              f"(Confidence: {regime.get('confidence', 50)}%)")
        print("  \u2514" + "\u2500" * 64 + "\u2518")

        # PHASE 3: STOCK ANALYSIS
        print("\n  \u250c\u2500 PHASE 3: Stock Analysis Pipeline \u2500" + "\u2500" * 32 + "\u2510")
        print(f"  \u2502  Analyzing {len(stock_data)} stocks across {RUNTIME_CONFIG['max_workers']} threads...")

        results = []

        with ThreadPoolExecutor(max_workers=RUNTIME_CONFIG['max_workers']) as executor:
            future_to_symbol = {
                executor.submit(self.analyze_stock, symbol, df, nifty_df): symbol
                for symbol, df in stock_data.items()
            }

            completed = 0
            for future in as_completed(future_to_symbol):
                completed += 1
                if completed % 50 == 0:
                    print(f"  \u2502  Progress: {completed}/{len(stock_data)} analyzed...")

                result = future.result()
                if result is not None:
                    results.append(result)

        print(f"  \u2502  \u2713 Analysis complete!")
        print(f"  \u2502    Passed liquidity: {self.stats['liquidity_pass']}")
        print(f"  \u2502    Fully analyzed: {self.stats['analyzed']}")
        print(f"  \u2502    Errors: {self.stats['failed']}")
        print("  \u2514" + "\u2500" * 64 + "\u2518")

        # Build full universe (passed + failed stocks)
        fail_map = {f['symbol']: f['reason'] for f in self.failed_stocks}
        result_map = {r['Symbol']: r for r in results}
        universe_rows = []
        for symbol, df in stock_data.items():
            close = df['Close'].values
            volume = df['Volume'].values
            cmp = float(close[-1])
            avg_vol = np.mean(volume[-20:])
            sector = SECTOR_MAP.get(symbol, 'Unknown')
            reason = fail_map.get(symbol, '')
            is_pass = symbol in result_map
            row = {
                'Symbol': symbol,
                'Sector': sector,
                'CMP': round(cmp, 2),
                'Avg_Vol_20d': int(avg_vol),
                'Status': 'PASS' if is_pass else f'FAIL: {reason}',
            }
            if is_pass:
                r = result_map[symbol]
                row['Score'] = r.get('Score', 0)
                row['OI_Chg%'] = r.get('OI_Chg%', 0)
                row['OI_Class'] = r.get('OI_Class', '')
                row['PCR'] = r.get('PCR', 0)
                row['Del%'] = r.get('Del%', 0)
                row['Bias'] = r.get('Bias', '')
                row['Setup'] = r.get('Setup', '')
                row['VolRatio'] = r.get('VolRatio', 0)
            universe_rows.append(row)
        self.full_universe = pd.DataFrame(universe_rows)
        if not self.full_universe.empty:
            self.full_universe = self.full_universe.sort_values(
                'Status', ascending=False
            ).reset_index(drop=True)

        if not results:
            print("\n  [!] No stocks passed all filters.")
            return pd.DataFrame()

        # PHASE 4: RANKING
        print("\n  \u250c\u2500 PHASE 4: Scoring & Ranking \u2500" + "\u2500" * 37 + "\u2510")

        df_results = pd.DataFrame(results)
        df_results = df_results[df_results['Score'] >= min_score]
        df_results = df_results.sort_values('Score', ascending=False)

        df_results.insert(0, '#', range(1, len(df_results) + 1))
        self.results = df_results

        print(f"  \u2502  \u2713 {len(df_results)} stocks ranked (min score: {min_score})")
        print("  \u2514" + "\u2500" * 64 + "\u2518")

        elapsed = time.time() - start_time
        print(f"\n  \u23f1  Total scan time: {elapsed:.1f} seconds")

        return df_results

    def display_results(self, df=None):
        if df is None:
            df = self.results

        if df.empty:
            print("\n  No results to display.")
            return

        drop_cols = {'_sub_liq', '_sub_oi', '_sub_mom', '_sub_rs', '_sub_vol',
                     '_sub_vola', '_sub_sm', '_sub_opt', '_compressed',
                     '_pocket_pivot', '_accumulation', '_nr7', '_above_vwap',
                     '_trend', 'REAL_DEL%'}
        display_cols = [c for c in df.columns if c not in drop_cols]

        pd.set_option('display.max_rows', 200)
        pd.set_option('display.max_columns', 30)
        pd.set_option('display.width', 300)
        pd.set_option('display.float_format', lambda x: f'{x:.2f}')
        pd.set_option('display.colheader_justify', 'center')

        print("\n" + "=" * 180)
        print(" " * 50 + "\U0001f3db  INSTITUTIONAL F&O SCANNER — TOP SETUPS  \U0001f3db")
        data_source = df['Data_Source'].iloc[0] if 'Data_Source' in df.columns else 'PROXY'
        badge = '\U0001f7e2 REAL NSE' if data_source == 'REAL' else '\U0001f7e1 PROXY (estimated)'
        print(f" " * 55 + f"[{badge}]")
        print("=" * 180)
        print(df[display_cols].to_string(index=False))

        print("\n" + "=" * 180)
        print(" " * 65 + "CATEGORY BREAKDOWNS")
        print("=" * 180)

        bullish = df[df['Bias'] == 'Bullish']
        if not bullish.empty:
            print(f"\n  \U0001f7e2 BULLISH SETUPS ({len(bullish)} stocks):")
            print("  " + "-" * 80)
            for _, row in bullish.head(10).iterrows():
                print(f"     {row['Symbol']:15s} | Score: {row['Score']:3d} | {row['Setup']:30s} | {row['OI_Class']}")

        bearish = df[df['Bias'] == 'Bearish']
        if not bearish.empty:
            print(f"\n  \U0001f534 BEARISH SETUPS ({len(bearish)} stocks):")
            print("  " + "-" * 80)
            for _, row in bearish.head(10).iterrows():
                print(f"     {row['Symbol']:15s} | Score: {row['Score']:3d} | {row['Setup']:30s} | {row['OI_Class']}")

        squeeze = df[df['Setup'].str.contains('Short Squeeze|Short Covering', na=False, case=False)]
        if not squeeze.empty:
            print(f"\n  \u26a1 SHORT SQUEEZE CANDIDATES ({len(squeeze)} stocks):")
            print("  " + "-" * 80)
            for _, row in squeeze.head(5).iterrows():
                print(f"     {row['Symbol']:15s} | Score: {row['Score']:3d} | OI: {row['OI_Class']}")

        compressed = df[df['_compressed'] == True]
        if not compressed.empty:
            print(f"\n  \U0001f504 COMPRESSION BREAKOUT READY ({len(compressed)} stocks):")
            print("  " + "-" * 80)
            for _, row in compressed.head(5).iterrows():
                print(f"     {row['Symbol']:15s} | Score: {row['Score']:3d} | ATR Exp: {row['ATR_Exp%']:.1f}%")

        pp = df[df['_pocket_pivot'] == True]
        if not pp.empty:
            print(f"\n  \U0001f4b0 POCKET PIVOTS — Institutional Buying ({len(pp)} stocks):")
            print("  " + "-" * 80)
            for _, row in pp.head(5).iterrows():
                print(f"     {row['Symbol']:15s} | Score: {row['Score']:3d} | Vol Ratio: {row['VolRatio']:.2f}")

        print("\n" + "=" * 180)
        print("  SCORING SYSTEM (0-100 Institutional Opportunity Score):")
        print("  " + "-" * 100)
        print("  Liquidity (10) | OI (15) | Momentum (15) | RS (10) | Volume (15) | Volatility (10) | Smart Money (15) | Options (10)")
        print("  " + "-" * 100)
        print("  Score \u226555: HIGH CONVICTION  |  Score 40-54: MODERATE  |  Score 25-39: DEVELOPING  |  Score <25: WEAK")
        print("  " + "-" * 100)
        print("  OI Classes: Long Buildup (Bullish) | Short Covering (Mildly Bullish) | Short Buildup (Bearish) | Long Unwinding (Mildly Bearish)")
        print("=" * 180)

    def export_csv(self, filename=None):
        if self.results.empty:
            print("  No results to export.")
            return

        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"fno_scan_{timestamp}.csv"

        display_cols = [c for c in self.results.columns if not c.startswith('_')]
        export_df = self.results[display_cols]
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', filename)
        export_df.to_csv(filepath, index=False)
        print(f"\n  \u2713 Results exported to {filename}")
        return filepath

    def export_excel(self, filename=None):
        return export_comprehensive_excel(self, filename)

    def train_ml(self, stock_data=None, nifty_df=None):
        if not self.use_ml or self.ml_predictor is None:
            print("  [ML] Scanner not initialized with ML. Use scanner = InstitutionalFnOScanner(use_ml=True)")
            return False

        if stock_data is None:
            stock_data = self.data_engine.fetch_all_fno_data(None)
        if nifty_df is None:
            nifty_df = self.data_engine.fetch_nifty_data()

        return self.ml_predictor.train(stock_data, nifty_df, self.sector_metrics, self.market_regime)

    def get_top_setups(self, n=10, bias=None, setup_type=None):
        df = self.results.copy()
        if bias:
            df = df[df['Bias'] == bias]
        if setup_type:
            df = df[df['Setup'].str.contains(setup_type, na=False, case=False)]
        return df.head(n)
