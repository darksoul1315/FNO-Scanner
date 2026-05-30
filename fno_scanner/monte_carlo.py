import numpy as np

N_ITERATIONS = 200
BOUNCE_ITERATIONS = 200
ML_RANGE_ITERATIONS = 100
POSITION_PATHS = 10000
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


def compute_bounce_test(results_bundles, sector_info_map, ml_boost_map=None):
    from .scoring_engine import (
        compute_liquidity_score, compute_momentum_score,
        compute_rs_score, compute_volume_score_component,
        compute_volatility_score, TREND_GATE,
    )

    symbols = list(results_bundles.keys())
    n = len(symbols)

    base_scores = {}
    base_blob = {}
    for sym in symbols:
        bundle = results_bundles[sym]
        sector_bonus = sector_info_map.get(sym, 0)
        cmp = bundle.get('cmp', 0)
        vol_metrics = bundle.get('volume', {})
        md = bundle.get('momentum', {})
        cd = bundle.get('compression', {})
        bd = bundle.get('breakout', {})
        rd = bundle.get('rs', {})
        pp = bundle.get('pocket_pivot', {})
        obv = bundle.get('obv', {})
        dd = bundle.get('delivery', {})
        imb = bundle.get('imbalance', {})

        liq = compute_liquidity_score(vol_metrics, cmp)
        oi = bundle.get('oi_score', 0)
        mom = compute_momentum_score(md, cd, bd)
        rs = compute_rs_score(rd, sector_bonus)
        vol = compute_volume_score_component(vol_metrics, pp, obv, dd)
        vola = compute_volatility_score(cd, imb)
        sm = bundle.get('smart_money_score', 0)
        opt = bundle.get('option_score', 0)

        trend = bundle.get('structure', {}).get('trend', 'unknown')
        trend_mult = TREND_GATE.get(trend, 0.80)
        total = min(100, liq + oi + mom + rs + vol + vola + sm + opt)

        ml_b = ml_boost_map.get(sym, 0) if ml_boost_map else 0
        score = max(0, min(100, round(total * trend_mult) + ml_b))

        base_scores[sym] = score
        base_blob[sym] = {
            'liq': liq, 'oi': oi, 'mom': mom, 'rs': rs,
            'vol': vol, 'vola': vola, 'sm': sm, 'opt': opt,
            'trend_mult': trend_mult,
        }

    sorted_base = sorted(base_scores.items(), key=lambda x: -x[1])
    base_ranks = {sym: idx + 1 for idx, (sym, _) in enumerate(sorted_base)}

    top5_count = {sym: 0 for sym in symbols}
    top10_count = {sym: 0 for sym in symbols}
    top20_count = {sym: 0 for sym in symbols}

    for _ in range(BOUNCE_ITERATIONS):
        perturbed_scores = {}
        for sym in symbols:
            b = base_blob[sym]
            liq = min(b['liq'] + int(np.random.normal(0, 1)), 10)
            oi = min(b['oi'] + int(np.random.normal(0, 2)), 15)
            mom = min(b['mom'] + int(np.random.normal(0, 2)), 15)
            rs = min(b['rs'] + int(np.random.normal(0, 1)), 10)
            vol = min(b['vol'] + int(np.random.normal(0, 2)), 15)
            vola = min(b['vola'] + int(np.random.normal(0, 1)), 10)
            sm = min(b['sm'] + int(np.random.normal(0, 2)), 15)
            opt = min(b['opt'] + int(np.random.normal(0, 1)), 10)
            total = max(0, min(100, liq + oi + mom + rs + vol + vola + sm + opt))
            perturbed_scores[sym] = round(total * b['trend_mult'])

        sorted_pert = sorted(perturbed_scores.items(), key=lambda x: -x[1])
        top5_set = set(sym for sym, _ in sorted_pert[:5])
        top10_set = set(sym for sym, _ in sorted_pert[:10])
        top20_set = set(sym for sym, _ in sorted_pert[:20])

        for sym in top5_set:
            top5_count[sym] += 1
        for sym in top10_set:
            top10_count[sym] += 1
        for sym in top20_set:
            top20_count[sym] += 1

    result = {}
    for sym in symbols:
        base_rank = base_ranks.get(sym, 999)
        result[sym] = {
            'bounce_top5_pct': round(top5_count[sym] / BOUNCE_ITERATIONS * 100, 1),
            'bounce_top10_pct': round(top10_count[sym] / BOUNCE_ITERATIONS * 100, 1),
            'bounce_top20_pct': round(top20_count[sym] / BOUNCE_ITERATIONS * 100, 1),
            'base_rank': base_rank,
        }

    return result


def compute_ml_range(feature_vector, predictor, n_iterations=ML_RANGE_ITERATIONS):
    probs = np.zeros(n_iterations)
    fv = np.array(feature_vector, dtype=float)

    for i in range(n_iterations):
        perturbed = fv + np.random.normal(0, 0.05, size=fv.shape)
        try:
            p = predictor.predict_proba(perturbed.reshape(1, -1))[0][1]
            probs[i] = p
        except Exception:
            probs[i] = 0.0

    p_mean = np.mean(probs) * 100
    p_std = np.std(probs) * 100

    return {
        'ml_range_low': round(max(0, p_mean - p_std), 1),
        'ml_range_high': round(min(100, p_mean + p_std), 1),
        'ml_range': round(p_std * 2, 1),
        'ml_mean': round(p_mean, 1),
    }


def compute_position_sizing(close_prices, n_days=5, n_paths=POSITION_PATHS):
    returns = np.diff(np.log(close_prices[-60:]))
    mu = np.mean(returns)
    sigma = np.std(returns)

    dt = 1.0
    final_prices = np.zeros(n_paths)
    max_drawdowns = np.zeros(n_paths)

    for i in range(n_paths):
        rand = np.random.normal(0, 1, n_days)
        path = np.zeros(n_days)
        price = 1.0
        peak = 1.0
        dd = 0.0
        for d in range(n_days):
            price *= np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rand[d])
            peak = max(peak, price)
            dd = min(dd, (price - peak) / peak)
        final_prices[i] = price
        max_drawdowns[i] = abs(dd)

    prob_positive = np.mean(final_prices > 1.0) * 100
    expected_return = (np.mean(final_prices) - 1.0) * 100
    avg_dd = np.mean(max_drawdowns) * 100
    worst_dd = np.percentile(max_drawdowns, 95) * 100

    return {
        'pos_prob_positive': round(prob_positive, 1),
        'pos_expected_return': round(expected_return, 2),
        'pos_avg_drawdown': round(avg_dd, 1),
        'pos_worst_drawdown': round(worst_dd, 1),
    }
