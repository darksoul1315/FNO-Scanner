import os
import sys as _sys

try:
    import pandas as pd
    import numpy as np
except ImportError as e:
    print("\n" + "!" * 65)
    print(f"  CRITICAL ERROR: Missing dependency: {e.name}")
    print("  Please install all requirements: pip install -r requirements.txt")
    print("!" * 65 + "\n")
    _sys.exit(1)

import yfinance as yf
from datetime import datetime, timedelta
import time
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from .config import (
    FNO_STOCKS, SECTOR_MAP, RUNTIME_CONFIG, LIQUIDITY_CONFIG, TIMEFRAMES
)

_API_SEMAPHORE = threading.Semaphore(4)
_API_CALL_COUNTER = {'count': 0, 'last_reset': time.time()}
_API_LOCK = threading.Lock()
_RATE_LIMIT_BACKOFF = {'factor': 1.0, 'until': 0}
_RATE_LIMIT_LOCK = threading.Lock()


def _check_rate_limit():
    with _RATE_LIMIT_LOCK:
        if time.time() < _RATE_LIMIT_BACKOFF['until']:
            wait = _RATE_LIMIT_BACKOFF['until'] - time.time()
            time.sleep(wait)
            return True
    return False


def _record_rate_limit():
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_BACKOFF['factor'] = min(_RATE_LIMIT_BACKOFF['factor'] * 2, 60)
        _RATE_LIMIT_BACKOFF['until'] = time.time() + 10 * _RATE_LIMIT_BACKOFF['factor']


def _reset_rate_limit():
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_BACKOFF['factor'] = 1.0
        _RATE_LIMIT_BACKOFF['until'] = 0


def _stagger():
    with _API_LOCK:
        _API_CALL_COUNTER['count'] += 1
        count = _API_CALL_COUNTER['count']
        if time.time() - _API_CALL_COUNTER.get('last_reset', time.time()) > 60:
            _API_CALL_COUNTER['count'] = 0
            _API_CALL_COUNTER['last_reset'] = time.time()
        jitter = random.uniform(0.3, 0.8)
        return count, jitter


class DataCache:
    def __init__(self, ttl_seconds=300):
        self.cache = {}
        self.lock = threading.Lock()
        self.ttl = ttl_seconds

    def get(self, key):
        with self.lock:
            if key in self.cache:
                entry = self.cache[key]
                if time.time() - entry['timestamp'] < self.ttl:
                    return entry['data']
                del self.cache[key]
        return None

    def set(self, key, data):
        with self.lock:
            self.cache[key] = {
                'data': data,
                'timestamp': time.time()
            }

    def clear(self):
        with self.lock:
            self.cache.clear()


class DataEngine:
    def __init__(self):
        self.cache = DataCache(ttl_seconds=RUNTIME_CONFIG['cache_expiry_seconds'])
        self.nifty_data = None
        self.banknifty_data = None
        self.sector_index_data = {}
        self.lock = threading.Lock()

    def fetch_stock_data(self, symbol, period_days=None):
        if period_days is None:
            period_days = RUNTIME_CONFIG['data_lookback_days']

        cache_key = f"ohlcv_{symbol}_{period_days}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        _check_rate_limit()

        ticker = f"{symbol}.NS"
        end_date = datetime.today()
        start_date = end_date - timedelta(days=period_days)

        last_error = None
        for attempt in range(RUNTIME_CONFIG['retry_count']):
            try:
                with _API_SEMAPHORE:
                    count, jitter = _stagger()
                    if count > 0 and count % 3 == 0:
                        time.sleep(jitter)

                    df = yf.download(
                        ticker,
                        start=start_date,
                        end=end_date,
                        progress=False,
                        auto_adjust=True
                    )

                if df.empty:
                    if attempt < RUNTIME_CONFIG['retry_count'] - 1:
                        time.sleep(RUNTIME_CONFIG['retry_delay_seconds'] * (attempt + 1) * 2)
                    continue

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                df = df.dropna(subset=['Close', 'Volume'])

                if df.empty:
                    continue

                if len(df) < 50:
                    continue

                _reset_rate_limit()
                self.cache.set(cache_key, df)
                return df

            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if 'rate' in err_str or '429' in err_str or 'too many' in err_str:
                    _record_rate_limit()
                if attempt < RUNTIME_CONFIG['retry_count'] - 1:
                    delay = RUNTIME_CONFIG['retry_delay_seconds'] * (attempt + 1) * 3
                    time.sleep(delay)
                continue

        return None

    def fetch_multi_timeframe_data(self, symbol):
        cache_key = f"mtf_{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        ticker = f"{symbol}.NS"
        mtf_data = {}

        daily = self.fetch_stock_data(symbol)
        if daily is not None:
            mtf_data['daily'] = daily

        if daily is not None and len(daily) >= 50:
            weekly = daily.resample('W').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()
            mtf_data['weekly'] = weekly

        try:
            hourly = yf.download(
                ticker, period='60d', interval='60m', progress=False, auto_adjust=True
            )
            if not hourly.empty:
                if isinstance(hourly.columns, pd.MultiIndex):
                    hourly.columns = hourly.columns.get_level_values(0)
                mtf_data['1h'] = hourly
        except Exception:
            pass

        if mtf_data:
            self.cache.set(cache_key, mtf_data)
        return mtf_data

    def fetch_nifty_data(self):
        if self.nifty_data is not None:
            return self.nifty_data
        try:
            end_date = datetime.today()
            start_date = end_date - timedelta(days=RUNTIME_CONFIG['data_lookback_days'])
            df = yf.download('^NSEI', start=start_date, end=end_date, progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if not df.empty:
                self.nifty_data = df
                return df
        except Exception:
            pass
        return None

    def fetch_banknifty_data(self):
        if self.banknifty_data is not None:
            return self.banknifty_data
        try:
            end_date = datetime.today()
            start_date = end_date - timedelta(days=RUNTIME_CONFIG['data_lookback_days'])
            df = yf.download('^NSEBANK', start=start_date, end=end_date, progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if not df.empty:
                self.banknifty_data = df
                return df
        except Exception:
            pass
        return None

    def fetch_all_fno_data(self, symbols=None):
        if symbols is None:
            symbols = FNO_STOCKS

        symbols = [s for s in symbols if s not in ['BANKNIFTY', 'NIFTY']]

        results = {}
        failed = []

        print(f"  [*] Fetching data for {len(symbols)} F&O stocks (throttled)...")

        _API_CALL_COUNTER['count'] = 0
        _API_CALL_COUNTER['last_reset'] = time.time()

        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_symbol = {
                executor.submit(self.fetch_stock_data, symbol): symbol
                for symbol in symbols
            }

            completed = 0
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                completed += 1

                if completed % 30 == 0:
                    ok = len(results)
                    pct = ok / max(completed, 1) * 100
                    print(f"  [*] Progress: {completed}/{len(symbols)} | OK: {ok} ({pct:.0f}%) | Fail: {len(failed)}")

                try:
                    data = future.result()
                    if data is not None and len(data) >= 50:
                        results[symbol] = data
                    else:
                        failed.append(symbol)
                except Exception:
                    failed.append(symbol)

        print(f"  [*] Data fetched: {len(results)} valid, {len(failed)} failed")
        return results

    def compute_vwap(self, df):
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        cum_tp_vol = (typical_price * df['Volume']).cumsum()
        cum_vol = df['Volume'].cumsum()
        vwap = cum_tp_vol / cum_vol
        return vwap

    def compute_anchored_vwap(self, df, anchor_idx):
        sliced = df.iloc[anchor_idx:].copy()
        typical_price = (sliced['High'] + sliced['Low'] + sliced['Close']) / 3
        cum_tp_vol = (typical_price * sliced['Volume']).cumsum()
        cum_vol = sliced['Volume'].cumsum()
        avwap = cum_tp_vol / cum_vol
        return avwap

    def get_sector_for_symbol(self, symbol):
        return SECTOR_MAP.get(symbol, 'Unknown')

    def get_sector_stocks(self, sector):
        return [s for s, sec in SECTOR_MAP.items() if sec == sector and s in FNO_STOCKS]
