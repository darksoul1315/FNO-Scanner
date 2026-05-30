import pandas as pd
import numpy as np


def compute_volume_metrics(df):
    close = df['Close'].values
    volume = df['Volume'].values
    high = df['High'].values
    low = df['Low'].values
    open_p = df['Open'].values
    n = len(close)

    if n < 21:
        return _empty_volume_result()

    avg_vol_20 = np.mean(volume[-21:-1])
    avg_vol_50 = np.mean(volume[-51:-1]) if n > 51 else avg_vol_20
    vol_ratio = volume[-1] / avg_vol_20 if avg_vol_20 > 0 else 1.0

    vol_series = pd.Series(volume)
    rvol_percentile = float(vol_series.rank(pct=True).iloc[-1] * 100)

    up_vol = np.where(close[1:] > close[:-1], volume[1:], 0)
    down_vol = np.where(close[1:] < close[:-1], volume[1:], 0)

    up_vol_50 = np.sum(up_vol[-50:]) if len(up_vol) >= 50 else np.sum(up_vol)
    down_vol_50 = np.sum(down_vol[-50:]) if len(down_vol) >= 50 else np.sum(down_vol)

    accumulation = up_vol_50 > down_vol_50 * 1.1
    ud_ratio = up_vol_50 / down_vol_50 if down_vol_50 > 0 else 2.0

    avg_vol_5d = np.mean(volume[-5:])
    vol_dry_up = avg_vol_5d < (avg_vol_50 * 0.65)

    vol_climax = volume[-1] > (avg_vol_20 * 3)

    traded_value = close * volume
    avg_traded_value = np.mean(traded_value[-20:])

    return {
        'vol_ratio': round(vol_ratio, 2),
        'vol_ratio_50d': round(avg_vol_20 / avg_vol_50, 2) if avg_vol_50 > 0 else 1.0,
        'rvol_percentile': round(rvol_percentile, 1),
        'avg_vol_20': int(avg_vol_20),
        'avg_vol_50': int(avg_vol_50),
        'up_down_ratio': round(ud_ratio, 2),
        'accumulation': accumulation,
        'vol_dry_up': vol_dry_up,
        'vol_climax': vol_climax,
        'avg_traded_value_cr': round(avg_traded_value / 1e7, 1),
    }


def detect_pocket_pivot(df):
    close = df['Close'].values
    volume = df['Volume'].values
    n = len(close)

    if n < 12:
        return {'pocket_pivot': False, 'pp_strength': 0}

    today_up = close[-1] > close[-2]
    today_vol = volume[-1]

    down_vols = []
    for i in range(max(n - 11, 1), n - 1):
        if close[i] < close[i - 1]:
            down_vols.append(volume[i])

    max_down_vol = max(down_vols) if down_vols else 0
    pocket_pivot = today_up and today_vol > max_down_vol and max_down_vol > 0
    pp_strength = (today_vol / max_down_vol - 1) * 100 if max_down_vol > 0 else 0

    return {
        'pocket_pivot': pocket_pivot,
        'pp_strength': round(pp_strength, 1),
    }


def compute_obv(df):
    close = df['Close'].values
    volume = df['Volume'].values
    n = len(close)

    if n < 21:
        return {'obv_trend': 'neutral', 'obv_divergence': False}

    signs = np.sign(np.diff(close))
    obv = np.concatenate([[0], np.cumsum(signs * volume[1:])])
    obv_series = pd.Series(obv)
    obv_sma = obv_series.rolling(20).mean()
    obv_trend = 'bullish' if obv[-1] > float(obv_sma.iloc[-1]) else 'bearish'

    price_lower_low = close[-1] < min(close[-10:-1]) if n > 10 else False
    obv_higher_low = obv[-1] > min(obv[-10:-1]) if n > 10 else False
    bullish_divergence = price_lower_low and obv_higher_low

    price_higher_high = close[-1] > max(close[-10:-1]) if n > 10 else False
    obv_lower_high = obv[-1] < max(obv[-10:-1]) if n > 10 else False
    bearish_divergence = price_higher_high and obv_lower_high

    return {
        'obv_trend': obv_trend,
        'obv_bullish_div': bullish_divergence,
        'obv_bearish_div': bearish_divergence,
    }


def detect_volume_absorption(df):
    close = df['Close'].values
    volume = df['Volume'].values
    high = df['High'].values
    low = df['Low'].values
    n = len(close)

    if n < 21:
        return {'absorption_detected': False}

    last_range = high[-1] - low[-1]
    avg_vol_20 = np.mean(volume[-21:-1])
    vol_ratio = volume[-1] / avg_vol_20 if avg_vol_20 > 0 else 1
    avg_range = np.mean(high[-21:-1] - low[-21:-1])
    range_ratio = last_range / avg_range if avg_range > 0 else 1

    absorption_detected = vol_ratio > 1.5 and range_ratio < 0.5

    direction = None
    if absorption_detected:
        direction = 'bullish_absorption' if close[-1] > close[-2] else 'bearish_absorption'

    return {
        'absorption_detected': absorption_detected,
        'absorption_direction': direction,
        'vol_ratio': round(vol_ratio, 2),
        'range_ratio': round(range_ratio, 2),
    }


def estimate_delivery_percentage(df):
    close = df['Close'].values
    volume = df['Volume'].values
    n = len(close)

    if n < 21:
        return {'delivery_proxy': 'unknown', 'delivery_score': 50}

    pct_change = abs(close[-1] - close[-2]) / close[-2] if close[-2] > 0 else 0
    avg_vol = np.mean(volume[-21:-1])
    vol_ratio = volume[-1] / avg_vol if avg_vol > 0 else 1
    high = float(df['High'].iloc[-1])
    low = float(df['Low'].iloc[-1])
    open_p = float(df['Open'].iloc[-1])

    candle_range = high - low
    body = abs(float(close[-1]) - open_p)
    body_ratio = body / candle_range if candle_range > 0 else 0

    delivery_score = 50
    if body_ratio > 0.7:
        delivery_score += 15
    if vol_ratio > 1.3 and body_ratio > 0.6:
        delivery_score += 15
    if pct_change > 0.02 and vol_ratio > 1.5:
        delivery_score += 10
    if vol_ratio < 0.5:
        delivery_score -= 20

    delivery_score = max(0, min(100, delivery_score))
    delivery_proxy = 'high' if delivery_score >= 70 else ('moderate' if delivery_score >= 50 else 'low')

    return {
        'delivery_proxy': delivery_proxy,
        'delivery_score': delivery_score,
    }


def compute_smart_money_volume_score(df):
    vol_metrics = compute_volume_metrics(df)
    pp_data = detect_pocket_pivot(df)
    obv_data = compute_obv(df)
    absorption_data = detect_volume_absorption(df)
    delivery_data = estimate_delivery_percentage(df)

    score = 0
    if vol_metrics['accumulation']:
        score += 3
    if pp_data['pocket_pivot']:
        score += 3
    if obv_data['obv_trend'] == 'bullish':
        score += 2
    if obv_data.get('obv_bullish_div', False):
        score += 2
    if absorption_data['absorption_detected'] and absorption_data.get('absorption_direction') == 'bullish_absorption':
        score += 2
    if vol_metrics['vol_dry_up']:
        score += 1
    if delivery_data['delivery_score'] >= 70:
        score += 2

    return {
        'smart_money_score': min(score, 15),
        'vol_metrics': vol_metrics,
        'pocket_pivot': pp_data,
        'obv': obv_data,
        'absorption': absorption_data,
        'delivery': delivery_data,
    }


def _empty_volume_result():
    return {
        'vol_ratio': 0,
        'vol_ratio_50d': 1.0,
        'rvol_percentile': 0,
        'avg_vol_20': 0,
        'avg_vol_50': 0,
        'up_down_ratio': 1.0,
        'accumulation': False,
        'vol_dry_up': False,
        'vol_climax': False,
        'avg_traded_value_cr': 0,
    }
