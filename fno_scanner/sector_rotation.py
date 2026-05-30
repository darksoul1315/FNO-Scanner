import pandas as pd
import numpy as np
from .config import FNO_STOCKS, SECTOR_MAP, FOCUS_SECTORS


def compute_sector_rs(stock_data_dict, nifty_df, periods=None):
    if periods is None:
        periods = [21, 63]
    if nifty_df is None or nifty_df.empty:
        return {}

    nifty_close = nifty_df['Close']
    sector_metrics = {}

    for sector in FOCUS_SECTORS:
        sector_symbols = [s for s, sec in SECTOR_MAP.items() if sec == sector]
        sector_symbols = [s for s in sector_symbols if s in stock_data_dict]

        if not sector_symbols:
            continue

        sector_returns = {}
        for period in periods:
            returns = []
            for sym in sector_symbols:
                df = stock_data_dict[sym]
                if len(df) > period:
                    ret = float(df['Close'].iloc[-1] / df['Close'].iloc[-period-1] - 1)
                    returns.append(ret)

            if returns:
                avg_return = np.mean(returns)
                if len(nifty_close) > period:
                    nifty_ret = float(nifty_close.iloc[-1] / nifty_close.iloc[-period-1] - 1)
                else:
                    nifty_ret = 0
                sector_returns[f'rs_{period}d'] = round(avg_return - nifty_ret, 4)
                sector_returns[f'return_{period}d'] = round(avg_return * 100, 2)
            else:
                sector_returns[f'rs_{period}d'] = 0
                sector_returns[f'return_{period}d'] = 0

        rs_1m = sector_returns.get('rs_21d', 0)
        rs_3m = sector_returns.get('rs_63d', 0)

        if rs_1m > 0 and rs_3m > 0:
            phase = "Leading"
        elif rs_1m > 0 and rs_3m <= 0:
            phase = "Improving"
        elif rs_1m <= 0 and rs_3m > 0:
            phase = "Weakening"
        else:
            phase = "Lagging"

        above_sma50 = 0
        total_count = len(sector_symbols)

        for sym in sector_symbols:
            df = stock_data_dict[sym]
            if len(df) >= 50:
                sma50 = float(df['Close'].rolling(50).mean().iloc[-1])
                if float(df['Close'].iloc[-1]) > sma50:
                    above_sma50 += 1

        breadth_pct = (above_sma50 / total_count * 100) if total_count > 0 else 0

        momentum_score = 0
        if phase == "Leading":
            momentum_score += 4
        elif phase == "Improving":
            momentum_score += 3
        elif phase == "Weakening":
            momentum_score += 1

        if breadth_pct > 70:
            momentum_score += 3
        elif breadth_pct > 50:
            momentum_score += 2
        elif breadth_pct > 30:
            momentum_score += 1

        if rs_1m > 0.03:
            momentum_score += 2
        elif rs_1m > 0.01:
            momentum_score += 1

        if sector_returns.get('return_21d', 0) > 3:
            momentum_score += 1

        sector_metrics[sector] = {
            'phase': phase,
            'rs_1m': rs_1m,
            'rs_3m': rs_3m,
            'return_1m': sector_returns.get('return_21d', 0),
            'return_3m': sector_returns.get('return_63d', 0),
            'breadth_pct': round(breadth_pct, 1),
            'momentum_score': min(momentum_score, 10),
            'stock_count': total_count,
        }

    return sector_metrics


def rank_sectors(sector_metrics):
    if not sector_metrics:
        return []
    ranked = sorted(
        sector_metrics.items(),
        key=lambda x: (x[1]['momentum_score'], x[1]['rs_1m']),
        reverse=True
    )
    return ranked


def get_leading_sectors(sector_metrics, top_n=3):
    ranked = rank_sectors(sector_metrics)
    return [s[0] for s in ranked[:top_n]]


def get_lagging_sectors(sector_metrics, bottom_n=3):
    ranked = rank_sectors(sector_metrics)
    return [s[0] for s in ranked[-bottom_n:]]


def detect_market_regime(sector_metrics, nifty_df):
    regime = 'neutral'
    confidence = 50

    if not sector_metrics:
        return {'regime': regime, 'confidence': confidence}

    cyclical_sectors = ['Banking', 'Financials', 'IT', 'Auto', 'Metals', 'CapGoods', 'Realty']
    defensive_sectors = ['FMCG', 'Pharma']

    cyclical_score = 0
    defensive_score = 0

    for sector, metrics in sector_metrics.items():
        if sector in cyclical_sectors:
            cyclical_score += metrics['momentum_score']
        elif sector in defensive_sectors:
            defensive_score += metrics['momentum_score']

    cyclical_count = sum(1 for s in sector_metrics if s in cyclical_sectors)
    defensive_count = sum(1 for s in sector_metrics if s in defensive_sectors)

    cyclical_avg = cyclical_score / cyclical_count if cyclical_count > 0 else 0
    defensive_avg = defensive_score / defensive_count if defensive_count > 0 else 0

    nifty_bullish = False
    if nifty_df is not None and len(nifty_df) >= 50:
        nifty_close = float(nifty_df['Close'].iloc[-1])
        nifty_sma50 = float(nifty_df['Close'].rolling(50).mean().iloc[-1])
        nifty_sma200 = float(nifty_df['Close'].rolling(200).mean().iloc[-1]) if len(nifty_df) >= 200 else nifty_sma50
        nifty_bullish = nifty_close > nifty_sma50 > nifty_sma200

    if cyclical_avg > defensive_avg and nifty_bullish:
        regime = 'risk_on'
        confidence = min(80, 50 + int((cyclical_avg - defensive_avg) * 10))
    elif defensive_avg > cyclical_avg and not nifty_bullish:
        regime = 'risk_off'
        confidence = min(80, 50 + int((defensive_avg - cyclical_avg) * 10))
    elif nifty_bullish:
        regime = 'risk_on'
        confidence = 55
    else:
        regime = 'neutral'
        confidence = 50

    return {
        'regime': regime,
        'confidence': confidence,
        'cyclical_avg_score': round(cyclical_avg, 1),
        'defensive_avg_score': round(defensive_avg, 1),
        'nifty_bullish': nifty_bullish,
    }


def get_sector_bonus(symbol, sector_metrics):
    sector = SECTOR_MAP.get(symbol, 'Unknown')
    if sector not in sector_metrics:
        return 0
    metrics = sector_metrics[sector]
    if metrics['phase'] == 'Leading':
        return 3
    elif metrics['phase'] == 'Improving':
        return 2
    elif metrics['phase'] == 'Weakening':
        return 1
    else:
        return 0
