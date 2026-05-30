import numpy as np
from .config import (
    SCORING_WEIGHTS, LIQUIDITY_CONFIG, PRICE_ACTION_CONFIG,
    OI_CONFIG, INSTITUTIONAL_CONFIG
)


SETUP_TYPES = {
    'liquidity_sweep_reversal': "Liquidity Sweep Reversal",
    'vwap_reclaim': "VWAP Reclaim",
    'opening_range_expansion': "Opening Range Expansion",
    'compression_breakout': "Compression Breakout",
    'short_squeeze': "Short Squeeze",
    'gamma_expansion': "Gamma Expansion",
    'trend_continuation': "Trend Continuation",
    'failed_breakdown_reversal': "Failed Breakdown Reversal",
    'failed_breakout_reversal': "Failed Breakout Reversal",
    'institutional_accumulation': "Institutional Accumulation",
    'momentum_ignition': "Momentum Ignition",
}

TREND_GATE = {
    'bullish': 1.0,
    'ranging': 0.85,
    'bearish': 0.60,
    'unknown': 0.80,
}


def compute_liquidity_score(vol_metrics, cmp):
    score = 0
    atv = vol_metrics.get('avg_traded_value_cr', 0)
    if atv > 500:
        score += 4
    elif atv > 200:
        score += 3
    elif atv > 100:
        score += 2
    elif atv > 50:
        score += 1

    vol_ratio = vol_metrics.get('vol_ratio', 0)
    if vol_ratio > 3:
        score += 3
    elif vol_ratio > 2:
        score += 2
    elif vol_ratio > 1:
        score += 1

    if cmp > 1000:
        score += 2
    elif cmp > 500:
        score += 1.5
    elif cmp > 200:
        score += 1

    rvol = vol_metrics.get('rvol_percentile', 50)
    if rvol > 90:
        score += 1

    return min(round(score), SCORING_WEIGHTS['liquidity_score'])


def compute_momentum_score(momentum_data, compression_data, breakout_data):
    score = 0
    rsi = momentum_data.get('rsi', 50)

    if 55 <= rsi <= 70:
        score += 3
    elif 40 <= rsi <= 55:
        score += 2
    elif rsi > 70:
        score += 1

    if momentum_data.get('macd_bullish_cross', False):
        score += 3
    elif momentum_data.get('macd_above_zero', False):
        score += 2

    roc = momentum_data.get('roc_20d', 0)
    if roc > 10:
        score += 3
    elif roc > 5:
        score += 2
    elif roc > 0:
        score += 1

    setup = breakout_data.get('setup')
    if setup == 'range_breakout':
        score += 3
    elif setup == 'near_breakout':
        score += 2
    elif setup in ('pdl_sweep_reclaim', 'failed_breakdown'):
        score += 2

    if compression_data.get('is_compressed', False):
        score += 2

    stoch = momentum_data.get('stoch_k', 50)
    if 20 <= stoch <= 40:
        score += 1

    return min(score, SCORING_WEIGHTS['momentum_score'])


def compute_rs_score(rs_data, sector_bonus=0):
    score = 0
    composite = rs_data.get('composite_rs', 0)

    if composite > 0.08:
        score += 4
    elif composite > 0.05:
        score += 3
    elif composite > 0.02:
        score += 2
    elif composite > 0.01:
        score += 1
    elif composite < -0.03:
        score -= 2
    elif composite < -0.01:
        score -= 1

    rs_1m = rs_data.get('rs_21d', 0)
    rs_3m = rs_data.get('rs_63d', 0)
    rs_6m = rs_data.get('rs_126d', 0)

    above_benchmark_count = sum([rs_1m > 0, rs_3m > 0, rs_6m > 0])
    if above_benchmark_count == 3:
        score += 3
    elif above_benchmark_count == 2:
        score += 2
    elif above_benchmark_count == 1:
        score += 1

    sector_capped = min(sector_bonus, 2)
    score += sector_capped

    return max(min(score, SCORING_WEIGHTS['rs_score']), 0)


def compute_volume_score_component(vol_metrics, pp_data, obv_data, delivery_data):
    score = 0
    vol_ratio = vol_metrics.get('vol_ratio', 1)
    if vol_ratio > 3:
        score += 3
    elif vol_ratio > 2:
        score += 2
    elif vol_ratio > 1.3:
        score += 1

    if vol_metrics.get('accumulation', False):
        score += 3

    ud_ratio = vol_metrics.get('up_down_ratio', 1)
    if ud_ratio > 1.5:
        score += 2
    elif ud_ratio > 1.2:
        score += 1

    if pp_data.get('pocket_pivot', False):
        score += 3

    if obv_data.get('obv_trend') == 'bullish':
        score += 2

    if delivery_data.get('delivery_score', 50) >= 70:
        score += 2

    return min(score, SCORING_WEIGHTS['volume_score'])


def compute_volatility_score(compression_data, imbalance_data):
    score = 0

    atr_ratio = compression_data.get('atr_ratio', 1)
    if atr_ratio < 0.55:
        score += 4
    elif atr_ratio < 0.65:
        score += 3
    elif atr_ratio < 0.75:
        score += 2
    elif atr_ratio < 0.85:
        score += 1

    bw_pct = compression_data.get('bb_width_percentile', 50)
    if bw_pct < 15:
        score += 2
    elif bw_pct < 25:
        score += 1

    if compression_data.get('nr7', False):
        score += 1

    if compression_data.get('inside_day', False):
        score += 1

    atr_exp = compression_data.get('atr_expansion_pct', 0)
    if atr_exp > 30:
        score += 2
    elif atr_exp > 15:
        score += 1

    tight_range = compression_data.get('tight_range_pct', 10)
    if tight_range < 2.5:
        score += 1

    return min(score, SCORING_WEIGHTS['volatility_score'])


def identify_setup_type(analysis_bundle):
    breakout = analysis_bundle.get('breakout', {})
    compression = analysis_bundle.get('compression', {})
    oi_data = analysis_bundle.get('oi', {})
    vwap = analysis_bundle.get('vwap', {})
    imbalance = analysis_bundle.get('imbalance', {})
    volume = analysis_bundle.get('volume', {})
    pp_data = analysis_bundle.get('pocket_pivot', {})
    structure = analysis_bundle.get('structure', {})

    setup = breakout.get('setup')

    if setup == 'failed_breakdown':
        return SETUP_TYPES['failed_breakdown_reversal']
    if setup == 'failed_breakout':
        return SETUP_TYPES['failed_breakout_reversal']
    if breakout.get('swept_prev_low', False) or setup == 'pdl_sweep_reclaim':
        return SETUP_TYPES['liquidity_sweep_reversal']
    if vwap.get('vwap_reclaim', False):
        return SETUP_TYPES['vwap_reclaim']

    oi_class = oi_data.get('classification', '')
    if oi_class == "Short Covering" and volume.get('vol_ratio', 0) > 2:
        return SETUP_TYPES['short_squeeze']
    if imbalance.get('has_imbalance', False) and volume.get('vol_ratio', 0) > 2.5:
        return SETUP_TYPES['momentum_ignition']
    if compression.get('is_compressed', False) and setup in ('range_breakout', 'near_breakout'):
        return SETUP_TYPES['compression_breakout']

    option_data = analysis_bundle.get('options', {})
    if option_data.get('in_gamma_zone', False) and volume.get('vol_ratio', 0) > 1.5:
        return SETUP_TYPES['gamma_expansion']
    if (volume.get('accumulation', False) and
        pp_data.get('pocket_pivot', False) and
        volume.get('vol_dry_up', False)):
        return SETUP_TYPES['institutional_accumulation']
    if structure.get('trend') == 'bullish' and oi_class == "Long Buildup":
        return SETUP_TYPES['trend_continuation']
    if compression.get('atr_expansion_pct', 0) > 20 and compression.get('is_compressed', False):
        return SETUP_TYPES['opening_range_expansion']
    if structure.get('trend') == 'bullish':
        return SETUP_TYPES['trend_continuation']
    elif volume.get('accumulation', False):
        return SETUP_TYPES['institutional_accumulation']

    return "Developing"


def determine_bias(analysis_bundle, total_score):
    bullish_signals = 0
    bearish_signals = 0

    structure = analysis_bundle.get('structure', {})
    if structure.get('trend') == 'bullish':
        bullish_signals += 2
    elif structure.get('trend') == 'bearish':
        bearish_signals += 2

    oi_class = analysis_bundle.get('oi', {}).get('classification', '')
    if oi_class in ("Long Buildup", "Short Covering"):
        bullish_signals += 2
    elif oi_class in ("Short Buildup", "Long Unwinding"):
        bearish_signals += 2

    if analysis_bundle.get('vwap', {}).get('above_vwap', False):
        bullish_signals += 1
    else:
        bearish_signals += 1

    if analysis_bundle.get('volume', {}).get('accumulation', False):
        bullish_signals += 1
    else:
        bearish_signals += 1

    rsi = analysis_bundle.get('momentum', {}).get('rsi', 50)
    if rsi > 55:
        bullish_signals += 1
    elif rsi < 45:
        bearish_signals += 1

    if total_score >= 60:
        bullish_signals += 1
    elif total_score < 30:
        bearish_signals += 1

    imbalance = analysis_bundle.get('imbalance', {})
    if imbalance.get('has_imbalance') and imbalance.get('direction') == 'bullish':
        bullish_signals += 1
    elif imbalance.get('has_imbalance') and imbalance.get('direction') == 'bearish':
        bearish_signals += 1

    if bullish_signals >= bearish_signals + 3:
        return "Bullish"
    elif bearish_signals >= bullish_signals + 3:
        return "Bearish"
    elif bullish_signals > bearish_signals:
        return "Bullish"
    elif bearish_signals > bullish_signals:
        return "Bearish"
    else:
        return "Neutral"


def identify_key_liquidity_zone(analysis_bundle, cmp):
    zones = []

    vwap_price = analysis_bundle.get('vwap', {}).get('vwap', 0)
    if vwap_price > 0:
        zones.append(('VWAP', vwap_price))

    vol_profile = analysis_bundle.get('vol_profile', {})
    poc = vol_profile.get('poc', 0)
    if poc > 0:
        zones.append(('POC', poc))

    breakout = analysis_bundle.get('breakout', {})
    pivot_h = breakout.get('pivot_high_20', 0)
    pivot_l = breakout.get('pivot_low_20', 0)
    if pivot_h > 0:
        zones.append(('R-20D', pivot_h))
    if pivot_l > 0:
        zones.append(('S-20D', pivot_l))

    eq_data = analysis_bundle.get('equal_levels', {})
    for eh in eq_data.get('equal_highs', [])[:1]:
        zones.append(('EQH', eh))
    for el in eq_data.get('equal_lows', [])[:1]:
        zones.append(('EQL', el))

    max_pain = analysis_bundle.get('options', {}).get('max_pain_proxy', 0)
    if max_pain > 0:
        zones.append(('MaxPain', max_pain))

    if not zones:
        return "\u2014"

    nearest = min(zones, key=lambda z: abs(z[1] - cmp))
    return f"{nearest[0]}: \u20b9{nearest[1]:,.0f}"


def compute_institutional_score(analysis_bundle, sector_bonus=0):
    cmp = analysis_bundle.get('cmp', 0)
    vol_metrics = analysis_bundle.get('volume', {})
    pp_data = analysis_bundle.get('pocket_pivot', {})
    obv_data = analysis_bundle.get('obv', {})
    delivery_data = analysis_bundle.get('delivery', {})
    momentum_data = analysis_bundle.get('momentum', {})
    compression_data = analysis_bundle.get('compression', {})
    breakout_data = analysis_bundle.get('breakout', {})
    rs_data = analysis_bundle.get('rs', {})
    imbalance_data = analysis_bundle.get('imbalance', {})

    liquidity = compute_liquidity_score(vol_metrics, cmp)
    oi = analysis_bundle.get('oi_score', 0)
    momentum = compute_momentum_score(momentum_data, compression_data, breakout_data)
    rs = compute_rs_score(rs_data, sector_bonus)
    volume = compute_volume_score_component(vol_metrics, pp_data, obv_data, delivery_data)
    volatility = compute_volatility_score(compression_data, imbalance_data)
    smart_money = analysis_bundle.get('smart_money_score', 0)
    option = analysis_bundle.get('option_score', 0)

    total = liquidity + oi + momentum + rs + volume + volatility + smart_money + option
    total = min(total, 100)

    structure = analysis_bundle.get('structure', {})
    trend = structure.get('trend', 'unknown')
    trend_mult = TREND_GATE.get(trend, 0.80)
    total = round(total * trend_mult)

    setup_type = identify_setup_type(analysis_bundle)
    bias = determine_bias(analysis_bundle, total)
    liquidity_zone = identify_key_liquidity_zone(analysis_bundle, cmp)

    return {
        'total_score': total,
        'sub_scores': {
            'liquidity': liquidity,
            'oi': oi,
            'momentum': momentum,
            'rs': rs,
            'volume': volume,
            'volatility': volatility,
            'smart_money': smart_money,
            'option': option,
        },
        'setup_type': setup_type,
        'bias': bias,
        'liquidity_zone': liquidity_zone,
    }
