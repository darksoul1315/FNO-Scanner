import numpy as np

N_ITERATIONS = 200
STABILITY_THRESHOLDS = {
    'HIGH': 0.10,
    'MED': 0.20,
}


def compute_stability(bundle, sector_bonus=0):
    from .scoring_engine import (
        compute_liquidity_score, compute_momentum_score,
        compute_rs_score, compute_volume_score_component,
        compute_volatility_score, TREND_GATE,
    )

    cmp = bundle.get('cmp', 0)
    vol_metrics = bundle.get('volume', {})
    momentum_data = bundle.get('momentum', {})
    compression_data = bundle.get('compression', {})
    breakout_data = bundle.get('breakout', {})
    rs_data = bundle.get('rs', {})
    pp_data = bundle.get('pocket_pivot', {})
    obv_data = bundle.get('obv', {})
    delivery_data = bundle.get('delivery', {})
    imbalance_data = bundle.get('imbalance', {})

    base_liq = compute_liquidity_score(vol_metrics, cmp)
    base_oi = bundle.get('oi_score', 0)
    base_mom = compute_momentum_score(momentum_data, compression_data, breakout_data)
    base_rs = compute_rs_score(rs_data, sector_bonus)
    base_vol = compute_volume_score_component(vol_metrics, pp_data, obv_data, delivery_data)
    base_vola = compute_volatility_score(compression_data, imbalance_data)
    base_sm = bundle.get('smart_money_score', 0)
    base_opt = bundle.get('option_score', 0)

    structure = bundle.get('structure', {})
    trend = structure.get('trend', 'unknown')
    trend_mult = TREND_GATE.get(trend, 0.80)

    base_total = base_liq + base_oi + base_mom + base_rs + base_vol + base_vola + base_sm + base_opt
    base_total = min(base_total, 100)
    base_score = round(base_total * trend_mult)

    scores = np.zeros(N_ITERATIONS)
    for i in range(N_ITERATIONS):
        liq = min(base_liq + int(np.random.normal(0, 1)), 10)
        oi = min(base_oi + int(np.random.normal(0, 2)), 15)
        mom = min(base_mom + int(np.random.normal(0, 2)), 15)
        rs = min(base_rs + int(np.random.normal(0, 1)), 10)
        vol = min(base_vol + int(np.random.normal(0, 2)), 15)
        vola = min(base_vola + int(np.random.normal(0, 1)), 10)
        sm = min(base_sm + int(np.random.normal(0, 2)), 15)
        opt = min(base_opt + int(np.random.normal(0, 1)), 10)

        total = max(0, min(100, liq + oi + mom + rs + vol + vola + sm + opt))
        scores[i] = round(total * trend_mult)

    mean_score = np.mean(scores)
    std_score = np.std(scores)
    cv = std_score / mean_score if mean_score > 1 else 0

    if cv <= STABILITY_THRESHOLDS['HIGH']:
        stability = 'HIGH'
    elif cv <= STABILITY_THRESHOLDS['MED']:
        stability = 'MED'
    else:
        stability = 'LOW'

    return {
        'stability': stability,
        'mean_score': round(mean_score, 1),
        'std_score': round(std_score, 2),
        'cv': round(cv, 3),
    }
