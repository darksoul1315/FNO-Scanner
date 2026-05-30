"""
NSE India API Module — Real Open Interest & Options Chain Data
Fetches live futures OI and option chain directly from NSE India.
"""

import json
import time
import threading
from datetime import datetime, date, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    import pandas as pd
    import numpy as np
except ImportError:
    pass

_NSE_SESSION = {'cookie': None, 'expires': 0}
_SESSION_LOCK = threading.Lock()
_NSE_BASE = "https://www.nseindia.com"


def _get_session():
    with _SESSION_LOCK:
        if time.time() < _NSE_SESSION['expires'] and _NSE_SESSION['cookie']:
            return _NSE_SESSION['cookie']

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }

        req = Request(f"{_NSE_BASE}/", headers=headers)
        try:
            resp = urlopen(req, timeout=15)
            cookie = resp.headers.get('Set-Cookie', '')
            _NSE_SESSION['cookie'] = cookie
            _NSE_SESSION['expires'] = time.time() + 300
            return cookie
        except Exception:
            return None


def _nse_api_call(endpoint, retries=3):
    cookie = _get_session()
    if not cookie:
        return None

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': f'{_NSE_BASE}/',
        'Cookie': cookie,
    }

    for attempt in range(retries):
        try:
            req = Request(f"{_NSE_BASE}{endpoint}", headers=headers)
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode('utf-8'))
            return data
        except HTTPError as e:
            if e.code == 403 and attempt < retries - 1:
                with _SESSION_LOCK:
                    _NSE_SESSION['expires'] = 0
                time.sleep(1)
                continue
            return None
        except (URLError, Exception):
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return None
    return None


def fetch_futures_oi(symbol, expiry_date=None):
    """
    Fetch futures Open Interest data for a single NSE symbol.

    Args:
        symbol: NSE symbol (e.g., 'RELIANCE', 'TCS') — without .NS suffix
        expiry_date: Specific expiry (YYYY-MM-DD), or None for nearest

    Returns:
        dict with keys: oi, oi_change_pct, prev_oi, volume, price, change_pct
        or None on failure
    """
    data = _nse_api_call(f"/api/derivatives/eq/derivatives?symbol={symbol}")

    if not data:
        return None

    try:
        if isinstance(data, dict) and 'data' in data:
            records = data['data']
        elif isinstance(data, list):
            records = data
        else:
            return None

        if not records:
            return None

        # Find the futures record for the nearest or specified expiry
        today = date.today()
        target_record = None

        for rec in records:
            if rec.get('instrumentType') in ('FUTSTK', 'FUTIDX', 'FUT'):
                exp = rec.get('expiryDate', '')
                if expiry_date and exp == expiry_date:
                    target_record = rec
                    break
                if not target_record:
                    target_record = rec
                elif exp:
                    rec_date = datetime.strptime(exp, '%d-%b-%Y').date() if '-' in exp else None
                    if rec_date and rec_date >= today:
                        target_rec_exp = datetime.strptime(
                            target_record.get('expiryDate', ''), '%d-%b-%Y'
                        ).date() if '-' in target_record.get('expiryDate', '') else None
                        if not target_rec_exp or rec_date < target_rec_exp:
                            target_record = rec

        if not target_record:
            return None

        oi = int(target_record.get('openInterest', 0))
        prev_oi = int(target_record.get('prevOpenInterest', 0))
        volume = int(target_record.get('totalTradedVolume', 0))
        price = float(target_record.get('lastPrice', 0))
        change_pct = float(target_record.get('priceChange', 0))

        oi_change_pct = ((oi - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0

        return {
            'oi': oi,
            'oi_change_pct': round(oi_change_pct, 2),
            'prev_oi': prev_oi,
            'volume_traded': volume,
            'price': price,
            'change_pct': change_pct,
            'symbol': symbol,
            'expiry': target_record.get('expiryDate', ''),
        }

    except (KeyError, TypeError, ValueError, IndexError):
        return None


def fetch_option_chain(symbol, expiry_date=None):
    """
    Fetch full option chain for a given symbol from NSE.

    Args:
        symbol: NSE symbol (e.g., 'RELIANCE', 'NIFTY')
        expiry_date: Expiry in DD-MMM-YYYY format or None for nearest

    Returns:
        dict with 'calls', 'puts', 'expiry', 'underlying_price'
        or None on failure
    """
    endpoint = f"/api/optionChain/eq?symbol={symbol}"
    data = _nse_api_call(endpoint)

    if not data:
        return None

    try:
        records = data.get('records', {})
        option_data = records.get('data', [])
        expiry_dates = records.get('expiryDates', [])
        underlying = records.get('underlyingValue', 0)

        if not option_data:
            return None

        calls, puts = [], []

        for row in option_data:
            strike = row.get('strikePrice', 0)
            expiry = row.get('expiryDate', '')

            if expiry_date and expiry != expiry_date:
                continue

            ce = row.get('CE', {})
            pe = row.get('PE', {})

            if ce:
                calls.append({
                    'strike': strike,
                    'expiry': expiry,
                    'last_price': ce.get('lastPrice', 0),
                    'change': ce.get('change', 0),
                    'oi': ce.get('openInterest', 0),
                    'volume': ce.get('totalTradedVolume', 0),
                    'iv': ce.get('impliedVolatility', 0),
                    'ltp': ce.get('lastPrice', 0),
                })

            if pe:
                puts.append({
                    'strike': strike,
                    'expiry': expiry,
                    'last_price': pe.get('lastPrice', 0),
                    'change': pe.get('change', 0),
                    'oi': pe.get('openInterest', 0),
                    'volume': pe.get('totalTradedVolume', 0),
                    'iv': pe.get('impliedVolatility', 0),
                    'ltp': pe.get('lastPrice', 0),
                })

        total_call_oi = sum(c['oi'] for c in calls)
        total_put_oi = sum(p['oi'] for p in puts)
        pcr_oi = total_put_oi / total_call_oi if total_call_oi > 0 else None

        total_call_vol = sum(c['volume'] for c in calls)
        total_put_vol = sum(p['volume'] for p in puts)
        pcr_vol = total_put_vol / total_call_vol if total_call_vol > 0 else None

        return {
            'calls': calls,
            'puts': puts,
            'expiry': expiry_date or (expiry_dates[0] if expiry_dates else None),
            'underlying_price': underlying,
            'total_call_oi': total_call_oi,
            'total_put_oi': total_put_oi,
            'pcr_oi': round(pcr_oi, 2) if pcr_oi else None,
            'pcr_vol': round(pcr_vol, 2) if pcr_vol else None,
        }

    except (KeyError, TypeError, ValueError):
        return None


def fetch_pcr(symbol):
    """
    Quick PCR fetch for a symbol — returns Put/Call ratio (OI-based).

    Args:
        symbol: NSE symbol

    Returns:
        dict with pcr_oi, pcr_vol, underlying_price or None
    """
    chain = fetch_option_chain(symbol)
    if not chain:
        return None

    return {
        'symbol': symbol,
        'pcr_oi': chain.get('pcr_oi'),
        'pcr_vol': chain.get('pcr_vol'),
        'underlying_price': chain.get('underlying_price'),
        'total_call_oi': chain.get('total_call_oi'),
        'total_put_oi': chain.get('total_put_oi'),
    }


def fetch_max_pain(symbol):
    """
    Estimate max pain from option chain — strike where max loss occurs for option writers.

    Args:
        symbol: NSE symbol

    Returns:
        dict with max_pain_strike, nearest_expiry, or None
    """
    chain = fetch_option_chain(symbol)
    if not chain:
        return None

    calls = chain.get('calls', [])
    puts = chain.get('puts', [])

    if not calls or not puts:
        return None

    strikes = sorted(set(c['strike'] for c in calls + puts))
    max_pain = None
    max_pain_value = float('inf')

    for strike in strikes:
        call_pain = sum(
            abs(strike - c['strike']) * c['oi']
            for c in calls if c['oi'] and c['strike'] > strike
        )
        put_pain = sum(
            abs(p['strike'] - strike) * p['oi']
            for p in puts if p['oi'] and p['strike'] < strike
        )
        total_pain = call_pain + put_pain

        if total_pain < max_pain_value:
            max_pain_value = total_pain
            max_pain = strike

    return {
        'symbol': symbol,
        'max_pain': max_pain,
        'underlying_price': chain.get('underlying_price'),
        'expiry': chain.get('expiry'),
    }


def classify_real_oi(oi_change_pct, price_change_pct):
    """
    Classify OI activity using REAL OI data (not proxy).

    Args:
        oi_change_pct: Real OI % change from NSE API
        price_change_pct: Price % change

    Returns:
        str: Classification
    """
    if oi_change_pct is None or price_change_pct is None:
        return "Neutral"

    if price_change_pct > 0 and oi_change_pct > 0:
        return "Long Buildup"
    elif price_change_pct < 0 and oi_change_pct > 0:
        return "Short Buildup"
    elif price_change_pct > 0 and oi_change_pct < 0:
        return "Short Covering"
    elif price_change_pct < 0 and oi_change_pct < 0:
        return "Long Unwinding"
    return "Neutral"


def enrich_oi_data(scanner_results, symbols, batch_size=5):
    """
    Enrich scanner results with real OI data from NSE API.

    Call this after the scanner runs to replace proxy OI with real data.

    Args:
        scanner_results: DataFrame from scanner.run()
        symbols: List of symbols to fetch (e.g., df['Symbol'].tolist())
        batch_size: NSE API calls per batch (be gentle with rate limits)

    Returns:
        DataFrame with updated OI_Chg%, OI_Class, PCR, IV%ile columns
    """
    df = scanner_results.copy()

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]

        for symbol in batch:
            try:
                # Fetch real futures OI
                oi_data = fetch_futures_oi(symbol)

                if oi_data and 'oi_change_pct' in oi_data:
                    mask = df['Symbol'] == symbol
                    if mask.any():
                        real_oi_chg = oi_data['oi_change_pct']
                        real_price_chg = oi_data.get('change_pct', 0)
                        real_class = classify_real_oi(real_oi_chg, real_price_chg)

                        df.loc[mask, 'OI_Chg%'] = real_oi_chg
                        df.loc[mask, 'OI_Class'] = real_class

                # Fetch real PCR
                pcr_data = fetch_pcr(symbol)
                if pcr_data and pcr_data.get('pcr_oi') is not None:
                    mask = df['Symbol'] == symbol
                    if mask.any():
                        df.loc[mask, 'PCR'] = pcr_data['pcr_oi']

                time.sleep(0.5)

            except Exception:
                continue

        if i + batch_size < len(symbols):
            time.sleep(2)

    return df
