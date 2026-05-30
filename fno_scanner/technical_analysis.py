import pandas as pd
import numpy as np
from .config import PRICE_ACTION_CONFIG, LIQUIDITY_CONFIG


def compute_atr(df, period=14):
    high = df['High'].values
    low = df['Low'].values
    close_prev = df['Close'].shift(1).values
    tr1 = high - low
    tr2 = np.abs(high - close_prev)
    tr3 = np.abs(low - close_prev)
    true_range = np.maximum(tr1, np.maximum(tr2, tr3))
    tr_series = pd.Series(true_range, index=df.index)
    return tr_series.rolling(window=period, min_periods=period).mean()


def compute_sma(series, period):
    return series.rolling(window=period, min_periods=period).mean()


def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_bollinger_bands(series, period=20, std_dev=2):
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    bandwidth = (upper - lower) / middle * 100
    return upper, middle, lower, bandwidth


def compute_stochastic(df, k_period=14, d_period=3):
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    stoch_k = 100 * (df['Close'] - low_min) / (high_max - low_min)
    stoch_d = stoch_k.rolling(window=d_period).mean()
    return stoch_k, stoch_d


def compute_macd(series, fast=12, slow=26, signal=9):
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def detect_market_structure(df):
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    n = len(close)

    if n < 20:
        return {'trend': 'unknown', 'last_bos': None, 'swing_highs': [], 'swing_lows': []}

    swing_highs = []
    swing_lows = []
    lookback = 5

    for i in range(lookback, n - lookback):
        if high[i] == max(high[i-lookback:i+lookback+1]):
            swing_highs.append((i, high[i]))
        if low[i] == min(low[i-lookback:i+lookback+1]):
            swing_lows.append((i, low[i]))

    trend = 'ranging'
    last_bos = None

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        recent_highs = [sh[1] for sh in swing_highs[-3:]]
        recent_lows = [sl[1] for sl in swing_lows[-3:]]
        hh = all(recent_highs[i] >= recent_highs[i-1] for i in range(1, len(recent_highs)))
        hl = all(recent_lows[i] >= recent_lows[i-1] for i in range(1, len(recent_lows)))
        lh = all(recent_highs[i] <= recent_highs[i-1] for i in range(1, len(recent_highs)))
        ll = all(recent_lows[i] <= recent_lows[i-1] for i in range(1, len(recent_lows)))
        if hh and hl:
            trend = 'bullish'
            last_bos = 'bullish'
        elif lh and ll:
            trend = 'bearish'
            last_bos = 'bearish'

    return {
        'trend': trend,
        'last_bos': last_bos,
        'swing_highs': swing_highs[-5:] if swing_highs else [],
        'swing_lows': swing_lows[-5:] if swing_lows else [],
    }


def detect_equal_highs_lows(df, tolerance_pct=0.003):
    high = df['High'].values
    low = df['Low'].values
    n = len(high)

    equal_highs = []
    equal_lows = []
    window = min(20, n)

    for i in range(n - window, n):
        for j in range(i + 1, n):
            if abs(high[i] - high[j]) / high[i] < tolerance_pct:
                equal_highs.append(round(float((high[i] + high[j]) / 2), 2))
            if abs(low[i] - low[j]) / low[i] < tolerance_pct:
                equal_lows.append(round(float((low[i] + low[j]) / 2), 2))

    return {
        'equal_highs': list(set(equal_highs))[-3:] if equal_highs else [],
        'equal_lows': list(set(equal_lows))[-3:] if equal_lows else [],
    }


def detect_imbalance(df, atr_series=None):
    if atr_series is None:
        atr_series = compute_atr(df)

    config = PRICE_ACTION_CONFIG
    close = df['Close'].values
    open_p = df['Open'].values
    high = df['High'].values
    low = df['Low'].values
    volume = df['Volume'].values
    n = len(close)

    if n < 2:
        return {'has_imbalance': False}

    last_range = high[-1] - low[-1]
    last_body = abs(close[-1] - open_p[-1])
    last_atr = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else last_range
    body_ratio = last_body / last_range if last_range > 0 else 0
    range_vs_atr = last_range / last_atr if last_atr > 0 else 0
    avg_vol_20 = np.mean(volume[-21:-1]) if n > 21 else np.mean(volume[:-1])
    vol_ratio = volume[-1] / avg_vol_20 if avg_vol_20 > 0 else 1

    is_imbalance = (
        range_vs_atr > config['imbalance_atr_mult'] and
        body_ratio > config['displacement_body_ratio'] and
        vol_ratio > config['volume_spike_mult']
    )

    direction = 'bullish' if close[-1] > open_p[-1] else 'bearish'
    close_near_high = (close[-1] - low[-1]) / last_range > 0.8 if last_range > 0 else False
    close_near_low = (high[-1] - close[-1]) / last_range > 0.8 if last_range > 0 else False

    return {
        'has_imbalance': is_imbalance,
        'direction': direction if is_imbalance else None,
        'range_vs_atr': round(range_vs_atr, 2),
        'body_ratio': round(body_ratio, 2),
        'vol_ratio': round(vol_ratio, 2),
        'close_near_high': close_near_high,
        'close_near_low': close_near_low,
    }


def detect_fair_value_gaps(df):
    high = df['High'].values
    low = df['Low'].values
    n = len(high)
    fvgs = []
    window = min(20, n - 2)

    for i in range(n - window, n - 1):
        if i < 1:
            continue
        if i + 1 < n and low[i+1] > high[i-1]:
            fvgs.append({
                'type': 'bullish',
                'top': float(low[i+1]),
                'bottom': float(high[i-1]),
                'midpoint': float((low[i+1] + high[i-1]) / 2),
            })
        if i + 1 < n and high[i+1] < low[i-1]:
            fvgs.append({
                'type': 'bearish',
                'top': float(low[i-1]),
                'bottom': float(high[i+1]),
                'midpoint': float((low[i-1] + high[i+1]) / 2),
            })

    return fvgs[-5:] if fvgs else []


def detect_compression_expansion(df):
    atr14 = compute_atr(df, 14)
    atr50 = compute_atr(df, 50)
    config = PRICE_ACTION_CONFIG

    current_atr14 = float(atr14.iloc[-1]) if not np.isnan(atr14.iloc[-1]) else 0
    current_atr50 = float(atr50.iloc[-1]) if not np.isnan(atr50.iloc[-1]) else 0
    atr_ratio = current_atr14 / current_atr50 if current_atr50 > 0 else 1
    is_compressed = atr_ratio < config['compression_ratio']

    atr14_5d_min = float(atr14.tail(10).min()) if len(atr14) >= 10 else current_atr14
    atr_expansion_pct = ((current_atr14 - atr14_5d_min) / atr14_5d_min * 100) if atr14_5d_min > 0 else 0

    _, _, _, bandwidth = compute_bollinger_bands(df['Close'])
    current_bw = float(bandwidth.iloc[-1]) if not np.isnan(bandwidth.iloc[-1]) else 0
    bw_percentile = float(bandwidth.rank(pct=True).iloc[-1] * 100) if not np.isnan(bandwidth.rank(pct=True).iloc[-1]) else 50

    recent_5d_high = float(df['High'].tail(5).max())
    recent_5d_low = float(df['Low'].tail(5).min())
    close = float(df['Close'].iloc[-1])
    tight_range_pct = (recent_5d_high - recent_5d_low) / close if close > 0 else 0

    daily_ranges = (df['High'] - df['Low']).tail(7).values
    nr7 = False
    if len(daily_ranges) == 7:
        nr7 = daily_ranges[-1] <= min(daily_ranges[:-1])

    if len(df) >= 2:
        inside_day = (
            df['High'].iloc[-1] <= df['High'].iloc[-2] and
            df['Low'].iloc[-1] >= df['Low'].iloc[-2]
        )
    else:
        inside_day = False

    return {
        'atr14': round(current_atr14, 2),
        'atr50': round(current_atr50, 2),
        'atr_ratio': round(atr_ratio, 3),
        'is_compressed': is_compressed,
        'atr_expansion_pct': round(atr_expansion_pct, 2),
        'bb_width_percentile': round(bw_percentile, 1),
        'tight_range_pct': round(tight_range_pct * 100, 2),
        'nr7': nr7,
        'inside_day': inside_day,
    }


def detect_breakout_setup(df):
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    n = len(close)

    if n < 21:
        return {'setup': None}

    cmp = float(close[-1])
    pivot_high_20 = float(np.max(high[-21:-1]))
    pivot_low_20 = float(np.min(low[-21:-1]))
    prev_high = float(high[-2])
    prev_low = float(low[-2])
    breakout_dist = (cmp / pivot_high_20) - 1

    setup = None
    if cmp > pivot_high_20:
        setup = 'range_breakout'
    elif breakout_dist > -0.02:
        setup = 'near_breakout'
    elif cmp < pivot_low_20:
        setup = 'range_breakdown'

    swept_prev_high = float(high[-1]) > prev_high and cmp < prev_high
    swept_prev_low = float(low[-1]) < prev_low and cmp > prev_low

    if swept_prev_high:
        setup = 'pdh_sweep_rejection'
    elif swept_prev_low:
        setup = 'pdl_sweep_reclaim'

    if float(high[-1]) > pivot_high_20 and cmp < pivot_high_20:
        setup = 'failed_breakout'

    if float(low[-1]) < pivot_low_20 and cmp > pivot_low_20:
        setup = 'failed_breakdown'

    return {
        'setup': setup,
        'pivot_high_20': round(pivot_high_20, 2),
        'pivot_low_20': round(pivot_low_20, 2),
        'breakout_dist_pct': round(breakout_dist * 100, 2),
        'swept_prev_high': swept_prev_high,
        'swept_prev_low': swept_prev_low,
    }


def analyze_vwap(df):
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    cum_tp_vol = (typical_price * df['Volume']).cumsum()
    cum_vol = df['Volume'].cumsum()
    vwap = cum_tp_vol / cum_vol

    cmp = float(df['Close'].iloc[-1])
    current_vwap = float(vwap.iloc[-1])
    prev_close = float(df['Close'].iloc[-2]) if len(df) > 1 else cmp

    tolerance = PRICE_ACTION_CONFIG['vwap_tolerance_pct']
    above_vwap = cmp > current_vwap
    near_vwap = abs(cmp - current_vwap) / current_vwap < tolerance
    vwap_reclaim = prev_close < float(vwap.iloc[-2]) and cmp > current_vwap if len(vwap) > 1 else False
    vwap_rejection = near_vwap and not above_vwap

    return {
        'vwap': round(current_vwap, 2),
        'above_vwap': above_vwap,
        'near_vwap': near_vwap,
        'vwap_reclaim': vwap_reclaim,
        'vwap_rejection': vwap_rejection,
        'vwap_dist_pct': round((cmp - current_vwap) / current_vwap * 100, 2),
    }


def compute_relative_strength(stock_df, benchmark_df, periods=None):
    if periods is None:
        periods = [21, 63, 126, 252]

    stock_close = stock_df['Close']
    bench_close = benchmark_df['Close']
    rs_scores = {}

    for p in periods:
        if len(stock_close) > p and len(bench_close) > p:
            stock_ret = float(stock_close.iloc[-1] / stock_close.iloc[-p-1] - 1)
            bench_ret = float(bench_close.iloc[-1] / bench_close.iloc[-p-1] - 1)
            rs_scores[f'rs_{p}d'] = round(stock_ret - bench_ret, 4)
        else:
            rs_scores[f'rs_{p}d'] = 0.0

    weights = {21: 0.4, 63: 0.3, 126: 0.2, 252: 0.1}
    composite_rs = sum(
        rs_scores.get(f'rs_{p}d', 0) * w
        for p, w in weights.items()
    )
    rs_scores['composite_rs'] = round(composite_rs, 4)

    return rs_scores


def compute_volume_profile(df, num_bins=20):
    close = df['Close'].values
    volume = df['Volume'].values
    n = len(close)

    if n < 10:
        return {'poc': 0, 'vah': 0, 'val': 0}

    price_min = np.min(close)
    price_max = np.max(close)
    bin_edges = np.linspace(price_min, price_max, num_bins + 1)
    bin_volumes = np.zeros(num_bins)

    for i in range(n):
        bin_idx = np.searchsorted(bin_edges[1:], close[i])
        bin_idx = min(bin_idx, num_bins - 1)
        bin_volumes[bin_idx] += volume[i]

    poc_idx = np.argmax(bin_volumes)
    poc = float((bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2)

    total_vol = np.sum(bin_volumes)
    target_vol = 0.7 * total_vol
    sorted_indices = np.argsort(bin_volumes)[::-1]
    cumulative_vol = 0
    va_bins = []

    for idx in sorted_indices:
        cumulative_vol += bin_volumes[idx]
        va_bins.append(idx)
        if cumulative_vol >= target_vol:
            break

    va_bins_sorted = sorted(va_bins)
    val = float(bin_edges[va_bins_sorted[0]])
    vah = float(bin_edges[va_bins_sorted[-1] + 1])

    return {
        'poc': round(poc, 2),
        'vah': round(vah, 2),
        'val': round(val, 2),
    }


def compute_momentum_suite(df):
    close = df['Close']

    rsi_14 = compute_rsi(close, 14)
    current_rsi = float(rsi_14.iloc[-1]) if not np.isnan(rsi_14.iloc[-1]) else 50

    macd_line, signal_line, histogram = compute_macd(close)
    macd_cross_bullish = (
        float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]) and
        float(macd_line.iloc[-2]) <= float(signal_line.iloc[-2])
    ) if len(macd_line) > 1 else False

    macd_cross_bearish = (
        float(macd_line.iloc[-1]) < float(signal_line.iloc[-1]) and
        float(macd_line.iloc[-2]) >= float(signal_line.iloc[-2])
    ) if len(macd_line) > 1 else False

    macd_above_zero = float(macd_line.iloc[-1]) > 0 if not np.isnan(macd_line.iloc[-1]) else False

    stoch_k, _ = compute_stochastic(df)
    current_stoch_k = float(stoch_k.iloc[-1]) if not np.isnan(stoch_k.iloc[-1]) else 50

    roc_20 = ((close.iloc[-1] / close.iloc[-21]) - 1) * 100 if len(close) > 21 else 0
    roc_10 = ((close.iloc[-1] / close.iloc[-11]) - 1) * 100 if len(close) > 11 else 0

    return {
        'rsi': round(current_rsi, 1),
        'macd_bullish_cross': macd_cross_bullish,
        'macd_bearish_cross': macd_cross_bearish,
        'macd_above_zero': macd_above_zero,
        'macd_hist': round(float(histogram.iloc[-1]), 4) if len(histogram) > 0 else 0.0,
        'stoch_k': round(current_stoch_k, 1),
        'roc_20d': round(float(roc_20), 2),
        'roc_10d': round(float(roc_10), 2),
    }
