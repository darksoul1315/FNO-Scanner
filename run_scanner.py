#!/usr/bin/env python3
"""
INSTITUTIONAL F&O SCANNER — ENTRY POINT
Elite Institutional-Grade Stock Scanner for NSE F&O Stocks
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fno_scanner.scanner import InstitutionalFnOScanner
from fno_scanner.after_market import enrich_from_bhavcopy, master_enrich


def parse_args():
    parser = argparse.ArgumentParser(
        description="Institutional F&O Scanner — NSE Derivatives Prop Desk System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_scanner.py                          Full scan (auto: REAL if available, else PROXY)
  python run_scanner.py --force-proxy            Skip NSE download — use proxy data
  python run_scanner.py --min-score 40 --top 20  Filter by score
  python run_scanner.py --bullish                Show only bullish bias
  python run_scanner.py --bearish                Show only bearish bias
  python run_scanner.py --no-ml                  Disable ML confidence scoring
  python run_scanner.py --train-ml               Train ML model from history + scan
        """
    )

    parser.add_argument(
        '--min-score', type=int, default=0,
        help='Minimum Institutional Score to display (0-100, default: 0)'
    )
    parser.add_argument(
        '--top', type=int, default=None,
        help='Show only top N results (default: show all)'
    )
    parser.add_argument(
        '--bullish', action='store_true',
        help='Show only Bullish bias setups'
    )
    parser.add_argument(
        '--bearish', action='store_true',
        help='Show only Bearish bias setups'
    )
    parser.add_argument(
        '--export', action='store_true',
        help='Export results to CSV file'
    )
    parser.add_argument(
        '--force-proxy', action='store_true',
        help='Force proxy mode — skip NSE bhavcopy enrichment'
    )
    parser.add_argument(
        '--no-ml', action='store_true',
        help='Disable ML-powered confidence scoring'
    )
    parser.add_argument(
        '--train-ml', action='store_true',
        help='Train ML model from historical data and save'
    )

    return parser.parse_args()


def main():
    args = parse_args()

    scanner = InstitutionalFnOScanner(use_ml=not args.no_ml or args.train_ml)

    if args.train_ml:
        print("=" * 90)
        print("  ML TRAINING MODE — Building Outperformance Predictor")
        print("=" * 90)

        from fno_scanner.after_market import get_fno_symbols_from_bhav
        bhav_symbols = get_fno_symbols_from_bhav()
        stock_symbols = bhav_symbols if bhav_symbols is not None else None

        if stock_symbols:
            print(f"  Stock list: {len(stock_symbols)} symbols from NSE bhavcopy")
        else:
            print(f"  Stock list: using hardcoded F&O list")

        print("\n  Phase 1: Fetching historical data...")
        stock_data = scanner.data_engine.fetch_all_fno_data(stock_symbols)

        print("\n  Phase 2: Computing sector rotation...")
        nifty_df = scanner.data_engine.fetch_nifty_data()
        if nifty_df is not None:
            from fno_scanner.sector_rotation import compute_sector_rs, detect_market_regime
            scanner.sector_metrics = compute_sector_rs(stock_data, nifty_df)
            scanner.market_regime = detect_market_regime(scanner.sector_metrics, nifty_df)

        print("\n  Phase 3: Training ML model...")
        success = scanner.train_ml(stock_data, nifty_df)
        if success:
            print("\n  \u2713 ML model trained and saved successfully!")
        else:
            print("\n  \u2716 ML training failed. See errors above.")
            sys.exit(1)

        print("\n  Phase 4: Running scan with ML predictions...")
        results = scanner.run(
            min_score=args.min_score,
            top_n=args.top,
            stock_list=stock_symbols
        )

    else:
        # Try getting live F&O stock list from bhavcopy (falls back to hardcoded list)
        from fno_scanner.after_market import get_fno_symbols_from_bhav
        bhav_symbols = get_fno_symbols_from_bhav()
        if bhav_symbols is not None:
            stock_symbols = bhav_symbols
            print(f"  Stock list: {len(stock_symbols)} symbols from NSE bhavcopy")
        else:
            stock_symbols = None
            print(f"  Stock list: using hardcoded F&O list (bhavcopy unavailable)")

        results = scanner.run(
            min_score=args.min_score,
            top_n=args.top,
            stock_list=stock_symbols
        )

    if results.empty:
        print("\n  No stocks matched the scanning criteria.")
        sys.exit(0)

    if not args.force_proxy:
        scanner.results = master_enrich(scanner.results)
        results = scanner.results
        if args.min_score > 0:
            results = results[results['Score'] >= args.min_score]
            results = results.sort_values('Score', ascending=False)
            results.insert(0, '#', range(1, len(results) + 1))
            scanner.results = results
    else:
        scanner.results['Data_Source'] = 'PROXY'
        results = scanner.results

    if args.bullish:
        results = results[results['Bias'] == 'Bullish']
        print(f"\n  Filtered to {len(results)} Bullish setups")
    elif args.bearish:
        results = results[results['Bias'] == 'Bearish']
        print(f"\n  Filtered to {len(results)} Bearish setups")

    scanner.display_results(results)

    scanner.export_excel()

    if args.export:
        scanner.export_csv()

    if not args.no_ml and scanner.ml_predictor and scanner.ml_predictor.is_ready:
        try:
            nifty_df = scanner.data_engine.fetch_nifty_data()
            if args.train_ml and 'stock_data' in dir():
                scanner.ml_predictor.auto_improve(stock_data, nifty_df)
            else:
                stock_data = scanner.data_engine.fetch_all_fno_data()
                scanner.ml_predictor.auto_improve(stock_data, nifty_df)
        except Exception as e:
            print(f"  [ML] Auto-improve skipped: {e}")

    print("\n  \u2713 Scan complete. Use --help for more options.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  [Interrupted] Scanner stopped by user.\n")
        sys.exit(0)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\n" + "!" * 65)
        print(f"  SCANNER ERROR: {e}")
        print("!" * 65)
        sys.exit(1)
