import numpy as np
import pandas as pd
import os
import pickle
import time
import json
import threading
from datetime import datetime, timedelta

try:
    import xgboost as xgb
    HAS_XGB = True
except Exception:
    xgb = None
    HAS_XGB = False

try:
    import shap
    HAS_SHAP = True
except Exception:
    shap = None
    HAS_SHAP = False

try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score, precision_recall_curve
    HAS_SKLEARN = True
except Exception:
    RandomForestClassifier = None
    roc_auc_score = None
    precision_recall_curve = None
    HAS_SKLEARN = False

from .config import SECTOR_MAP, SECTOR_MAP, RUNTIME_CONFIG
from .technical_analysis import (
    compute_rsi, compute_stochastic, compute_macd, compute_atr,
    compute_bollinger_bands, compute_relative_strength
)
from .volume_analytics import (
    compute_volume_metrics, detect_pocket_pivot, compute_obv,
    detect_volume_absorption, estimate_delivery_percentage
)
from .oi_analysis import estimate_oi_proxy, estimate_option_metrics

FEATURE_NAMES = [
    'rsi', 'stoch_k', 'macd_hist', 'roc_20d', 'roc_10d',
    'atr_ratio', 'bb_width_percentile', 'atr_expansion_pct',
    'tight_range_pct', 'vwap_dist_pct', 'above_vwap',
    'vol_ratio', 'vol_ratio_50d', 'up_down_ratio',
    'delivery_score', 'oi_change_pct', 'pcr_proxy',
    'composite_rs', 'rs_21d', 'rs_63d',
    'avg_traded_value_cr', 'price_change_pct',
    'sector_phase_score', 'sector_rs_1m', 'sector_breadth',
    'market_regime_num',
]

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.ml_cache')
FEEDBACK_FILE = os.path.join(MODEL_DIR, 'feedback_pool.json')
HISTORY_FILE = os.path.join(MODEL_DIR, 'training_history.json')
MIN_FEEDBACK_FOR_RETRAIN = 200


def _ensure_model_dir():
    os.makedirs(MODEL_DIR, exist_ok=True)


def compute_feature_dataframe(stock_df, nifty_df):
    df = stock_df.copy()
    close = df['Close']
    high = df['High']
    low = df['Low']
    open_p = df['Open']
    volume = df['Volume']

    features = pd.DataFrame(index=df.index)

    features['price_change_pct'] = close.pct_change() * 100

    rsi = compute_rsi(close)
    features['rsi'] = rsi
    stoch_k, _ = compute_stochastic(df)
    features['stoch_k'] = stoch_k
    macd_line, signal_line, macd_hist = compute_macd(close)
    features['macd_hist'] = macd_hist
    features['macd_bullish_cross'] = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
    features['macd_above_zero'] = macd_line > 0
    features['roc_20d'] = close.pct_change(20) * 100
    features['roc_10d'] = close.pct_change(10) * 100

    atr14 = compute_atr(df, 14)
    atr50 = compute_atr(df, 50)
    features['atr_ratio'] = atr14 / atr50.replace(0, np.nan)

    _, _, _, bbw = compute_bollinger_bands(close)
    features['bb_width'] = bbw
    features['bb_width_percentile'] = bbw.rank(pct=True) * 100

    daily_range = high - low
    features['nr7'] = daily_range <= daily_range.rolling(7, min_periods=7).min().shift(1)
    features['inside_day'] = (high <= high.shift(1)) & (low >= low.shift(1))

    tp = (high + low + close) / 3
    cum_tp_vol = (tp * volume).cumsum()
    cum_vol = volume.cumsum()
    vwap_series = cum_tp_vol / cum_vol.replace(0, np.nan)
    features['vwap_dist_pct'] = (close / vwap_series - 1) * 100
    features['above_vwap'] = close > vwap_series

    vol_20_ma = volume.rolling(20).mean()
    features['vol_ratio'] = volume / vol_20_ma.replace(0, np.nan)
    vol_50_ma = volume.rolling(50).mean()
    features['vol_ratio_50d'] = vol_20_ma / vol_50_ma.replace(0, np.nan)
    features['avg_traded_value_cr'] = (close * volume).rolling(20).mean() / 1e7

    up_vol = volume.where(close > close.shift(1), 0)
    down_vol = volume.where(close < close.shift(1), 0)
    up_vol_50 = up_vol.rolling(50).sum()
    down_vol_50 = down_vol.rolling(50).sum()
    features['up_down_ratio'] = up_vol_50 / down_vol_50.replace(0, np.nan)
    features['accumulation'] = up_vol_50 > down_vol_50 * 1.1

    signs = np.sign(close.diff())
    obv = (signs.fillna(0) * volume).cumsum()
    obv_20_ma = obv.rolling(20).mean()
    features['obv_above_ma'] = obv > obv_20_ma

    body = (close - open_p).abs()
    candle_range = high - low
    body_ratio = body / candle_range.replace(0, np.nan)
    vol_ratio_s = features['vol_ratio']
    delivery_raw = pd.Series(50, index=df.index)
    delivery_raw += (body_ratio > 0.7).astype(int) * 15
    delivery_raw += ((vol_ratio_s > 1.3) & (body_ratio > 0.6)).astype(int) * 15
    features['delivery_score'] = delivery_raw.clip(0, 100)

    vol_change_pct = ((volume - vol_20_ma) / vol_20_ma.replace(0, np.nan)) * 100
    features['oi_change_pct'] = vol_change_pct * 0.5

    up_vol_20 = up_vol.rolling(20).sum()
    down_vol_20 = down_vol.rolling(20).sum()
    features['pcr_proxy'] = up_vol_20 / down_vol_20.replace(0, np.nan)

    atr14_5d_min = atr14.rolling(10, min_periods=10).min()
    features['atr_expansion_pct'] = ((atr14 - atr14_5d_min) / atr14_5d_min.replace(0, np.nan)) * 100

    recent_5d_high = high.rolling(5).max()
    recent_5d_low = low.rolling(5).min()
    features['tight_range_pct'] = ((recent_5d_high - recent_5d_low) / close) * 100

    features['is_compressed'] = features['atr_ratio'] < 0.75

    if nifty_df is not None and len(nifty_df) > 60:
        aligned = pd.DataFrame({
            'stock_close': close,
            'nifty_close': nifty_df['Close']
        }).dropna()
        if len(aligned) > 60:
            s_close = aligned['stock_close']
            b_close = aligned['nifty_close']
            for p in [21, 63, 126, 252]:
                col = f'rs_{p}d'
                features.loc[aligned.index, col] = np.nan
                if len(s_close) > p and len(b_close) > p:
                    ratio = len(features.loc[:aligned.index[-1]])
                    stock_ret = s_close / s_close.shift(p) - 1
                    bench_ret = b_close / b_close.shift(p) - 1
                    rs_val = (stock_ret - bench_ret) * 100
                    features.loc[aligned.index, col] = rs_val
            weights = {21: 0.4, 63: 0.3, 126: 0.2, 252: 0.1}
            composite = pd.Series(0.0, index=aligned.index)
            valid_rs = []
            for p, w in weights.items():
                col = f'rs_{p}d'
                if col in features.columns:
                    valid_rs.append(features[col] * w)
            if valid_rs:
                composite = sum(valid_rs)
            features['composite_rs'] = np.nan
            features.loc[aligned.index, 'composite_rs'] = composite

    features['sector_bonus'] = 0.0

    return features


def _get_sector_bonus(symbol, sector_metrics):
    sector = SECTOR_MAP.get(symbol, 'Unknown')
    if sector in sector_metrics:
        phase = sector_metrics[sector].get('phase', 'Mixed')
        phase_bonus = {'Leading': 2, 'Improving': 1, 'Weakening': -1, 'Lagging': -2, 'Mixed': 0}
        return phase_bonus.get(phase, 0)
    return 0


def extract_features_from_bundle(analysis_bundle, sector_bonus=0):
    features = {}
    mom = analysis_bundle.get('momentum', {})
    features['rsi'] = mom.get('rsi', 50)
    features['stoch_k'] = mom.get('stoch_k', 50)
    features['macd_hist'] = mom.get('macd_hist', 0.0)
    features['macd_bullish_cross'] = 1 if mom.get('macd_bullish_cross', False) else 0
    features['macd_above_zero'] = 1 if mom.get('macd_above_zero', False) else 0
    features['roc_20d'] = mom.get('roc_20d', 0)

    comp = analysis_bundle.get('compression', {})
    features['atr_ratio'] = comp.get('atr_ratio', 1)
    features['bb_width_percentile'] = comp.get('bb_width_percentile', 50)
    features['atr_expansion_pct'] = comp.get('atr_expansion_pct', 0)
    features['tight_range_pct'] = comp.get('tight_range_pct', 10)

    vwap = analysis_bundle.get('vwap', {})
    features['vwap_dist_pct'] = vwap.get('vwap_dist_pct', 0)
    features['above_vwap'] = 1 if vwap.get('above_vwap', False) else 0

    vol = analysis_bundle.get('volume', {})
    features['vol_ratio'] = vol.get('vol_ratio', 1)
    features['vol_ratio_50d'] = vol.get('vol_ratio_50d', 1)
    features['up_down_ratio'] = vol.get('up_down_ratio', 1)
    features['avg_traded_value_cr'] = vol.get('avg_traded_value_cr', 0)
    features['price_change_pct'] = analysis_bundle.get('price_change_pct', 0)

    deliv = analysis_bundle.get('delivery', {})
    features['delivery_score'] = deliv.get('delivery_score', 50)

    oi = analysis_bundle.get('oi', {})
    features['oi_change_pct'] = oi.get('oi_change_pct_proxy', 0)

    opt = analysis_bundle.get('options', {})
    features['pcr_proxy'] = opt.get('pcr_proxy', 1.0)

    rs = analysis_bundle.get('rs', {})
    features['composite_rs'] = rs.get('composite_rs', 0) * 100
    features['rs_21d'] = rs.get('rs_21d', 0) * 100
    features['rs_63d'] = rs.get('rs_63d', 0) * 100

    features['sector_phase_score'] = analysis_bundle.get('sector_phase_score', 5)
    features['sector_rs_1m'] = analysis_bundle.get('sector_rs_1m', 0)
    features['sector_breadth'] = analysis_bundle.get('sector_breadth', 50)
    features['market_regime_num'] = analysis_bundle.get('market_regime_num', 0)

    return np.array([features.get(name, 0) for name in FEATURE_NAMES], dtype=np.float32)


def build_training_data(stock_data, nifty_df, sector_metrics=None, market_regime=None, forward_days=5, outperform_threshold=0.015, verbose=True):
    X_list = []
    y_list = []
    stock_ids = []
    date_list = []
    min_bars = 250

    if sector_metrics is None:
        sector_metrics = {}

    if verbose:
        print(f"  [ML] Building training data from {len(stock_data)} stocks...")
        start_t = time.time()

    if nifty_df is not None:
        nifty_close = nifty_df['Close']
    else:
        nifty_close = None

    processed = 0
    skipped_bars = 0

    for symbol, df in stock_data.items():
        if len(df) < min_bars:
            continue

        if nifty_close is not None:
            combined = pd.DataFrame({
                'stock_close': df['Close'],
                'nifty_close': nifty_close
            }).dropna()
            if len(combined) < min_bars:
                continue
            aligned_df = df.loc[combined.index].copy()
            aligned_nifty = combined['nifty_close']
        else:
            aligned_df = df.copy()
            aligned_nifty = None

        feat_df = compute_feature_dataframe(aligned_df, nifty_df)

        sector_bonus = _get_sector_bonus(symbol, sector_metrics)
        feat_df['sector_bonus'] = sector_bonus

        sector = SECTOR_MAP.get(symbol, 'Unknown')
        sec_info = sector_metrics.get(sector, {})
        feat_df['sector_phase_score'] = sec_info.get('momentum_score', 5)
        feat_df['sector_rs_1m'] = sec_info.get('rs_1m', 0)
        feat_df['sector_breadth'] = sec_info.get('breadth_pct', 50)
        regime = market_regime.get('regime', 'neutral') if market_regime else 'neutral'
        regime_map = {'risk_on': 1, 'neutral': 0, 'risk_off': -1}
        feat_df['market_regime_num'] = regime_map.get(regime, 0)

        feat_df = feat_df.replace([np.inf, -np.inf], np.nan)

        lookback = 60
        close = aligned_df['Close']

        first_valid_idx = 0
        non_null = feat_df.dropna()
        if len(non_null) > 0:
            first_valid_idx = feat_df.index.get_loc(non_null.index[0]) if non_null.index[0] in feat_df.index else lookback

        valid_start = max(lookback, first_valid_idx)
        valid_end = len(close) - forward_days

        for i in range(valid_start, valid_end):
            row = feat_df.iloc[i]
            if row.isna().any():
                skipped_bars += 1
                continue

            stock_fwd = float(close.iloc[i + forward_days]) / float(close.iloc[i]) - 1
            if aligned_nifty is not None:
                nifty_fwd = float(aligned_nifty.iloc[i + forward_days]) / float(aligned_nifty.iloc[i]) - 1
                outperformance = stock_fwd - nifty_fwd
            else:
                outperformance = stock_fwd

            label = 1 if outperformance >= outperform_threshold else 0

            feature_vec = np.array([row.get(name, 0) for name in FEATURE_NAMES], dtype=np.float32)
            X_list.append(feature_vec)
            y_list.append(label)
            stock_ids.append(symbol)
            date_list.append(df.index[i] if hasattr(df.index, 'iloc') else df.index[i])

        processed += 1
        if verbose and processed % 30 == 0:
            print(f"  [ML] Processing: {processed}/{len(stock_data)} stocks, "
                  f"{len(X_list)} samples collected...")

    if not X_list:
        if verbose:
            print(f"  [ML] No training data collected. Check data availability.")
        return None, None, None, None

    X = np.array(X_list)
    y = np.array(y_list)

    pos_ratio = y.mean() * 100
    if verbose:
        elapsed = time.time() - start_t
        print(f"  [ML] Training data: {len(X)} samples from {processed} stocks "
              f"({skipped_bars} skipped due to NaN)")
        print(f"  [ML] Positive class: {pos_ratio:.1f}% | Features: {len(FEATURE_NAMES)}")
        print(f"  [ML] Build time: {elapsed:.1f}s")

    return X, y, stock_ids, date_list


class MLPredictor:
    def __init__(self):
        self.model = None
        self.feature_names = FEATURE_NAMES
        self.model_path = os.path.join(MODEL_DIR, 'xgboost_model.pkl')
        self.metadata_path = os.path.join(MODEL_DIR, 'model_metadata.json')
        self.is_trained = False
        self.lock = threading.Lock()
        _ensure_model_dir()

    def _get_classifier(self, X, y):
        pos_weight = (len(y) - y.sum()) / max(y.sum(), 1)
        if HAS_XGB:
            return xgb.XGBClassifier(
                n_estimators=300, max_depth=5, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                scale_pos_weight=pos_weight,
                eval_metric='auc', use_label_encoder=False,
                verbosity=0, random_state=42,
            ), 'XGBoost', None
        elif HAS_SKLEARN:
            try:
                from sklearn.preprocessing import StandardScaler
                clf = GradientBoostingClassifier(
                    n_estimators=400, max_depth=4, learning_rate=0.04,
                    subsample=0.75, min_samples_leaf=8, min_samples_split=15,
                    max_features='sqrt',
                    random_state=42,
                )
                return clf, 'GradientBoosting', None
            except Exception:
                return RandomForestClassifier(
                    n_estimators=500, max_depth=7,
                    min_samples_leaf=8, min_samples_split=15,
                    class_weight='balanced_subsample',
                    n_jobs=-1, random_state=42,
                ), 'RandomForest', None
        else:
            return None, None, None

    def train(self, stock_data, nifty_df, sector_metrics=None, market_regime=None):
        X, y, _, _ = build_training_data(stock_data, nifty_df, sector_metrics, market_regime)
        if X is None or len(X) < 1000:
            print(f"  [ML] Insufficient training data ({len(X) if X is not None else 0} samples). Need >= 1000.")
            return False

        result = self._get_classifier(X, y)
        clf, clf_name = result[0], result[1]
        sample_weight = result[2] if len(result) > 2 else None
        if clf is None:
            print("  [ML] No ML library available. Install: pip install xgboost scikit-learn")
            return False

        print(f"  [ML] Training {clf_name} ({len(X)} samples)...")
        start_t = time.time()

        split_idx = int(len(X) * 0.8)
        indices = np.random.RandomState(42).permutation(len(X))
        train_idx = indices[:split_idx]
        eval_idx = indices[split_idx:]

        if HAS_XGB:
            clf.fit(
                X[train_idx], y[train_idx],
                eval_set=[(X[train_idx], y[train_idx]), (X[eval_idx], y[eval_idx])],
                verbose=False,
            )
        else:
            sw = sample_weight[train_idx] if sample_weight is not None else None
            clf.fit(X[train_idx], y[train_idx], sample_weight=sw)

        self.model = clf
        elapsed = time.time() - start_t

        train_auc = self._compute_auc(self.model, X[train_idx], y[train_idx])
        eval_auc = self._compute_auc(self.model, X[eval_idx], y[eval_idx])

        print(f"  [ML] Training complete in {elapsed:.1f}s")
        print(f"  [ML] Train AUC: {train_auc:.3f} | Eval AUC: {eval_auc:.3f}")

        self._calc_threshold(X[eval_idx], y[eval_idx])
        self._show_top_features(10)

        self.is_trained = True
        self.last_eval_auc = eval_auc
        self.history_best_auc = max(getattr(self, 'history_best_auc', 0), eval_auc)
        self._save_training_history({
            'trained_at': datetime.now().isoformat(),
            'source': f'full_train({len(X)} samples)',
            'train_auc': round(float(train_auc), 4),
            'eval_auc': round(float(eval_auc), 4),
            'n_samples': len(X),
            'clf_name': clf_name,
            'features': FEATURE_NAMES,
        })
        self.save()
        return True

    def _compute_auc(self, model, X, y):
        if roc_auc_score is None:
            return 0.5
        try:
            y_prob = model.predict_proba(X)[:, 1]
            if len(np.unique(y)) < 2:
                return 0.5
            return roc_auc_score(y, y_prob)
        except Exception:
            return 0.5

    def _calc_threshold(self, X_val, y_val):
        if precision_recall_curve is None:
            self.optimal_threshold = 0.5
            self.high_conviction_threshold = 0.65
            return
        try:
            y_prob = self.model.predict_proba(X_val)[:, 1]
            precisions, recalls, thresholds = precision_recall_curve(y_val, y_prob)

            f1_scores = 2 * precisions[:-1] * recalls[:-1] / (precisions[:-1] + recalls[:-1] + 1e-10)
            best_idx = np.argmax(f1_scores)
            self.optimal_threshold = thresholds[best_idx]
            best_f1 = f1_scores[best_idx]
            best_prec = precisions[best_idx]
            best_rec = recalls[best_idx]

            idx_70 = np.where(precisions[:-1] >= 0.70)[0]
            if len(idx_70) > 0:
                self.high_conviction_threshold = thresholds[idx_70[0]]
            else:
                self.high_conviction_threshold = self.optimal_threshold

            print(f"  [ML] Optimal threshold: {self.optimal_threshold:.3f} "
                  f"(Prec: {best_prec:.3f}, Rec: {best_rec:.3f}, F1: {best_f1:.3f})")
            print(f"  [ML] High-conviction threshold: {self.high_conviction_threshold:.3f}")
        except Exception:
            self.optimal_threshold = 0.5
            self.high_conviction_threshold = 0.65

    def _show_top_features(self, n=10):
        if self.model is None:
            return
        try:
            if hasattr(self.model, 'feature_importances_'):
                importance = self.model.feature_importances_
            elif hasattr(self.model, 'base_estimator_') and hasattr(self.model.base_estimator_, 'feature_importances_'):
                importance = self.model.base_estimator_.feature_importances_
            elif hasattr(self.model, 'estimators_') and hasattr(self.model.estimators_[0], 'feature_importances_'):
                importance = np.mean([est.feature_importances_ for est in self.model.estimators_], axis=0)
            else:
                print(f"  [ML] Feature importance not available for {type(self.model).__name__}")
                return
            indices = np.argsort(importance)[::-1][:n]
            print(f"  [ML] Top {n} features:")
            for i, idx in enumerate(indices):
                print(f"        {i+1}. {FEATURE_NAMES[idx]:25s}  {importance[idx]:.4f}")
        except Exception:
            print(f"  [ML] Feature importance not available for {type(self.model).__name__}")

    def predict_proba(self, feature_vector):
        if self.model is None or not self.is_trained:
            return 0.5
        vec = np.array(feature_vector, dtype=np.float32).reshape(1, -1)
        return float(self.model.predict_proba(vec)[0, 1])

    def predict_confidence(self, feature_vector):
        prob = self.predict_proba(feature_vector)
        conf = (prob - 0.5) * 2
        return max(0, min(1, conf))

    def predict_batch(self, feature_vectors):
        if self.model is None or not self.is_trained:
            return np.full(len(feature_vectors), 0.5)
        X = np.array(feature_vectors, dtype=np.float32)
        return self.model.predict_proba(X)[:, 1]

    def log_prediction(self, feature_vector, symbol, date_str, prob):
        try:
            pool = self._load_feedback_pool()
            entry = {
                'symbol': symbol,
                'date': date_str,
                'features': [float(v) for v in feature_vector],
                'predicted_prob': round(float(prob), 4),
                'predicted_label': 1 if prob >= getattr(self, 'optimal_threshold', 0.5) else 0,
                'labeled': False,
                'actual_outperformance': None,
            }
            pool.append(entry)
            with open(FEEDBACK_FILE, 'w') as f:
                json.dump(pool, f, indent=1)
        except Exception as e:
            pass

    def _load_feedback_pool(self):
        try:
            if os.path.exists(FEEDBACK_FILE):
                with open(FEEDBACK_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _label_feedback(self, stock_data, nifty_df):
        if nifty_df is None or 'Close' not in nifty_df.columns:
            return 0
        pool = self._load_feedback_pool()
        nifty_close = nifty_df['Close']
        labeled = 0
        for entry in pool:
            if entry.get('labeled'):
                continue
            symbol = entry['symbol']
            date_str = entry['date']
            try:
                entry_date = pd.Timestamp(date_str)
                if entry_date not in nifty_close.index:
                    continue
                if symbol not in stock_data:
                    continue
                stock = stock_data[symbol]
                if 'Close' not in stock.columns:
                    continue
                nifty_idx = nifty_close.index.get_loc(entry_date)
                stock_idx = stock.index.get_loc(entry_date)
                end_nifty = nifty_idx + 5
                end_stock = stock_idx + 5
                if end_nifty >= len(nifty_close) or end_stock >= len(stock):
                    continue
                stock_fwd = float(stock['Close'].iloc[end_stock]) / float(stock['Close'].iloc[stock_idx]) - 1
                nifty_fwd = float(nifty_close.iloc[end_nifty]) / float(nifty_close.iloc[nifty_idx]) - 1
                outperformance = stock_fwd - nifty_fwd
                entry['actual_outperformance'] = round(float(outperformance), 4)
                entry['labeled'] = True
                labeled += 1
            except Exception:
                continue
        if labeled > 0:
            with open(FEEDBACK_FILE, 'w') as f:
                json.dump(pool, f, indent=1)
        return labeled

    def auto_improve(self, stock_data, nifty_df, min_new_samples=MIN_FEEDBACK_FOR_RETRAIN):
        new_labeled = self._label_feedback(stock_data, nifty_df)
        pool = self._load_feedback_pool()
        labeled_pool = [e for e in pool if e.get('labeled')]
        unlabeled_pool = [e for e in pool if not e.get('labeled')]
        print(f"  [ML] Feedback: {len(labeled_pool)} labeled, {len(unlabeled_pool)} unlabeled "
              f"(+{new_labeled} new this run)")

        if len(labeled_pool) < min_new_samples:
            print(f"  [ML] Need {min_new_samples - len(labeled_pool)} more labeled samples to retrain")
            return False

        prev_train_auc = getattr(self, 'history_best_auc', 0)
        X = np.array([e['features'] for e in labeled_pool], dtype=np.float32)
        y = np.array([e['predicted_label'] for e in labeled_pool], dtype=np.int32)

        if not self._validate_and_improve(X, y, f"feedback ({len(X)} samples)"):
            return False

        return True

    def _validate_and_improve(self, X, y, label, min_size=1000):
        if len(X) < min_size:
            print(f"  [ML] Skipping {label}: only {len(X)} samples, need {min_size}")
            return False

        result = self._get_classifier(X, y)
        new_clf, clf_name = result[0], result[1]
        sample_weight = result[2] if len(result) > 2 else None
        if new_clf is None:
            return False

        split_idx = int(len(X) * 0.8)
        indices = np.random.RandomState(42).permutation(len(X))
        train_idx = indices[:split_idx]
        eval_idx = indices[split_idx:]

        print(f"  [ML] Self-improvement: training {clf_name} on {label}...")
        sw = sample_weight[train_idx] if sample_weight is not None else None
        new_clf.fit(X[train_idx], y[train_idx], sample_weight=sw)

        train_auc = self._compute_auc(new_clf, X[train_idx], y[train_idx])
        eval_auc = self._compute_auc(new_clf, X[eval_idx], y[eval_idx])
        print(f"  [ML] New model — Train AUC: {train_auc:.3f} | Eval AUC: {eval_auc:.3f}")

        prev_eval = getattr(self, 'last_eval_auc', 0)
        if eval_auc >= prev_eval - 0.02:
            self.model = new_clf
            self.is_trained = True
            self.optimal_threshold = getattr(self, 'optimal_threshold', 0.5)
            print(f"  [ML] Model updated (AUC: {prev_eval:.3f} → {eval_auc:.3f})")
        else:
            print(f"  [ML] Keeping current model ({eval_auc:.3f} < {prev_eval:.3f} - 0.02)")

        self._save_training_history({
            'trained_at': datetime.now().isoformat(),
            'source': label,
            'train_auc': round(float(train_auc), 4),
            'eval_auc': round(float(eval_auc), 4),
            'n_samples': len(X),
            'clf_name': clf_name,
            'features': FEATURE_NAMES,
        })
        return True

    def _save_training_history(self, entry):
        try:
            history = self._load_training_history()
            history.append(entry)
            with open(HISTORY_FILE, 'w') as f:
                json.dump(history[-20:], f, indent=1)
            self._print_auc_trend(history)
        except Exception:
            pass

    def _load_training_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _print_auc_trend(self, history):
        if len(history) < 2:
            return
        print(f"  [ML] AUC Trend:")
        best = max(h.get('eval_auc', 0) for h in history)
        for h in history[-5:]:
            src = h.get('source', '?')[:30]
            train = h.get('train_auc', 0)
            eval_a = h.get('eval_auc', 0)
            marker = ' ★ BEST' if eval_a == best else ''
            print(f"        {h['trained_at'][:19]} | {src:30s} | Train: {train:.3f} | Eval: {eval_a:.3f}{marker}")

    def save(self):
        if self.model is None:
            return False
        with self.lock:
            try:
                _ensure_model_dir()
                with open(self.model_path, 'wb') as f:
                    pickle.dump(self.model, f)
                metadata = {
                    'feature_names': FEATURE_NAMES,
                    'n_features': len(FEATURE_NAMES),
                    'trained_at': datetime.now().isoformat(),
                    'optimal_threshold': getattr(self, 'optimal_threshold', 0.5),
                    'high_conviction_threshold': getattr(self, 'high_conviction_threshold', 0.65),
                }
                import json
                with open(self.metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
                return True
            except Exception as e:
                print(f"  [ML] Failed to save model: {e}")
                return False

    def load(self):
        with self.lock:
            try:
                if not os.path.exists(self.model_path):
                    return False
                with open(self.model_path, 'rb') as f:
                    self.model = pickle.load(f)
                import json
                if os.path.exists(self.metadata_path):
                    with open(self.metadata_path) as f:
                        metadata = json.load(f)
                    self.optimal_threshold = metadata.get('optimal_threshold', 0.5)
                    self.high_conviction_threshold = metadata.get('high_conviction_threshold', 0.65)
                else:
                    self.optimal_threshold = 0.5
                    self.high_conviction_threshold = 0.65
                self.is_trained = True
                return True
            except Exception as e:
                print(f"  [ML] Failed to load model: {e}")
                return False

    def get_shap_values(self, feature_vector):
        if not HAS_SHAP or self.model is None:
            return None
        try:
            vec = np.array(feature_vector, dtype=np.float32).reshape(1, -1)
            explainer = shap.TreeExplainer(self.model)
            shap_values = explainer.shap_values(vec)
            feature_shap = list(zip(FEATURE_NAMES, shap_values[0]))
            feature_shap.sort(key=lambda x: abs(x[1]), reverse=True)
            return feature_shap[:10]
        except Exception:
            return None

    @property
    def is_ready(self):
        return self.is_trained and self.model is not None
