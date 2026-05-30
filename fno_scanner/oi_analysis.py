import pandas as pd
import numpy as np
from collections import Counter
from .config import OI_CONFIG


def classify_oi_activity(price_change_pct, oi_change_pct):
    if price_change_pct > 0 and oi_change_pct > 0:
        return "Long Buildup"
    elif price_change_pct < 0 and oi_change_pct > 0:
        return "Short Buildup"
    elif price_change_pct > 0 and oi_change_pct < 0:
        return "Short Covering"
    elif price_change_pct < 0 and oi_change_pct < 0:
        return "Long Unwinding"
    else:
        return "Neutral"


def estimate_oi_proxy(df):
    close = df['Close'].values
    volume = df['Volume'].values
    n = len(close)

    if n < 21:
        return _empty_oi_result()

    daily_pct_change = (close[-1] - close[-2]) / close[-2] * 100 if close[-2] > 0 else 0

    avg_vol_20 = np.mean(volume[-21:-1])
    vol_change_pct = (volume[-1] - avg_vol_20) / avg_vol_20 * 100 if avg_vol_20 > 0 else 0

    oi_change_pct_proxy = vol_change_pct * 0.5

    classification = classify_oi_activity(daily_pct_change, oi_change_pct_proxy)

    multi_day_classifications = []
    for i in range(-5, 0):
        if abs(i) >= n:
            continue
        p_chg = (close[i] - close[i-1]) / close[i-1] * 100 if close[i-1] > 0 else 0
        v_chg = (volume[i] - np.mean(volume[max(0,i-20):i])) / np.mean(volume[max(0,i-20):i]) * 100 if np.mean(volume[max(0,i-20):i]) > 0 else 0
        multi_day_classifications.append(classify_oi_activity(p_chg, v_chg * 0.5))

    if multi_day_classifications:
        dominant = Counter(multi_day_classifications).most_common(1)[0][0]
    else:
        dominant = "Neutral"

    oi_expansion_score = 0
    if abs(daily_pct_change) > 1 and vol_change_pct > 20:
        oi_expansion_score = 3
    elif abs(daily_pct_change) > 0.5 and vol_change_pct > 10:
        oi_expansion_score = 2
    elif abs(daily_pct_change) > 0.3 and vol_change_pct > 0:
        oi_expansion_score = 1

    vol_spike = volume[-1] > avg_vol_20 * 2.5
    price_reversal = (
        (close[-1] > close[-2] and close[-2] < close[-3]) or
        (close[-1] < close[-2] and close[-2] > close[-3])
    ) if n >= 3 else False

    sudden_oi_shift = vol_spike and price_reversal

    return {
        'classification': classification,
        'dominant_5d': dominant,
        'price_change_pct': round(daily_pct_change, 2),
        'oi_change_pct_proxy': round(oi_change_pct_proxy, 2),
        'oi_expansion_score': oi_expansion_score,
        'sudden_oi_shift': sudden_oi_shift,
        'vol_change_pct': round(vol_change_pct, 1),
    }


def compute_oi_score(df):
    oi_data = estimate_oi_proxy(df)
    score = 0

    classification = oi_data['classification']
    if classification == "Long Buildup":
        score += 5
    elif classification == "Short Covering":
        score += 4
    elif classification == "Neutral":
        score += 2
    elif classification == "Long Unwinding":
        score += 1
    elif classification == "Short Buildup":
        score += 0

    dominant = oi_data['dominant_5d']
    if dominant == "Long Buildup":
        score += 4
    elif dominant == "Short Covering":
        score += 3
    elif dominant == "Neutral":
        score += 1

    score += oi_data['oi_expansion_score']

    if oi_data['sudden_oi_shift']:
        score += 2

    if oi_data['vol_change_pct'] > 50:
        score += 1

    return min(score, 15)


def estimate_option_metrics(df):
    close = df['Close'].values
    volume = df['Volume'].values
    high = df['High'].values
    low = df['Low'].values
    n = len(close)

    if n < 60:
        return _empty_option_result()

    up_days = 0
    down_days = 0
    up_vol = 0
    down_vol = 0

    for i in range(max(n-20, 1), n):
        if close[i] > close[i-1]:
            up_days += 1
            up_vol += volume[i]
        else:
            down_days += 1
            down_vol += volume[i]

    pcr_proxy = up_vol / down_vol if down_vol > 0 else 1.0

    log_returns = np.log(close[1:] / close[:-1])
    rv_20 = np.std(log_returns[-20:]) * np.sqrt(252) * 100 if len(log_returns) >= 20 else 0

    rolling_vols = []
    for i in range(20, len(log_returns)):
        rv = np.std(log_returns[i-20:i]) * np.sqrt(252) * 100
        rolling_vols.append(rv)

    if rolling_vols:
        rv_array = np.array(rolling_vols)
        iv_percentile = float(np.sum(rv_array <= rv_20) / len(rv_array) * 100)
    else:
        iv_percentile = 50.0

    if len(rolling_vols) >= 5:
        recent_rv = np.mean(rolling_vols[-5:])
        prev_rv = np.mean(rolling_vols[-10:-5]) if len(rolling_vols) >= 10 else recent_rv
        iv_expanding = recent_rv > prev_rv * 1.2
    else:
        iv_expanding = False

    cmp = close[-1]
    strike_interval = _get_strike_interval(cmp)
    nearest_strike = round(cmp / strike_interval) * strike_interval
    gamma_zone_lower = nearest_strike - strike_interval
    gamma_zone_upper = nearest_strike + strike_interval
    in_gamma_zone = gamma_zone_lower <= cmp <= gamma_zone_upper

    max_pain_proxy = float(np.median(close[-20:]))

    last_range_pct = (high[-1] - low[-1]) / close[-1] if close[-1] > 0 else 0
    avg_range_pct = np.mean((high[-20:] - low[-20:]) / close[-20:]) if n >= 20 else last_range_pct

    unusual_activity = (
        volume[-1] > np.mean(volume[-21:-1]) * 2 and
        last_range_pct < avg_range_pct * 0.5
    )

    return {
        'pcr_proxy': round(pcr_proxy, 2),
        'iv_proxy': round(rv_20, 1),
        'iv_percentile': round(iv_percentile, 1),
        'iv_expanding': iv_expanding,
        'nearest_strike': nearest_strike,
        'gamma_zone': (gamma_zone_lower, gamma_zone_upper),
        'in_gamma_zone': in_gamma_zone,
        'max_pain_proxy': round(max_pain_proxy, 2),
        'unusual_activity': unusual_activity,
    }


def compute_option_score(df):
    metrics = estimate_option_metrics(df)
    score = 0

    udr = metrics['pcr_proxy']
    if 1.0 < udr <= 1.5:
        score += 3
    elif 1.5 < udr <= 2.0:
        score += 2
    elif 0.7 < udr <= 1.0:
        score += 1
    elif udr > 3.0:
        score -= 2
    elif udr > 2.5:
        score -= 1

    iv = metrics['iv_percentile']
    if 20 <= iv <= 40:
        score += 3
    elif iv < 15:
        score += 2
    elif 40 < iv <= 55:
        score += 1
    elif iv > 85:
        score += 2

    if metrics['iv_expanding']:
        score += 2

    if metrics['unusual_activity']:
        score += 1

    if metrics['in_gamma_zone']:
        score += 1

    return max(0, min(score, 10))


def _get_strike_interval(price):
    if price > 5000:
        return 100
    elif price > 2000:
        return 50
    elif price > 500:
        return 20
    elif price > 100:
        return 5
    else:
        return 2.5


def _empty_oi_result():
    return {
        'classification': 'Neutral',
        'dominant_5d': 'Neutral',
        'price_change_pct': 0,
        'oi_change_pct_proxy': 0,
        'oi_expansion_score': 0,
        'sudden_oi_shift': False,
        'vol_change_pct': 0,
    }


def _empty_option_result():
    return {
        'pcr_proxy': 1.0,
        'iv_proxy': 0,
        'iv_percentile': 50,
        'iv_expanding': False,
        'nearest_strike': 0,
        'gamma_zone': (0, 0),
        'in_gamma_zone': False,
        'max_pain_proxy': 0,
        'unusual_activity': False,
    }
