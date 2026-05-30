"""
NSE After-Market Reports Module
Downloads daily reports published by NSE after market close (6 PM IST):
  - F&O Bhavcopy → Real futures/options OI for ALL stocks in one file
  - Equity Bhavcopy → Delivery %, volume, turnover
  - Block/Bulk Deals → Institutional activity

These are more reliable than the live API because:
  - Single CSV download covers all 200+ stocks
  - No rate limiting (one HTTP request)
  - Available 24/7 after 6 PM IST
  - Historical data available (can backfill)
"""

import os
import csv
import io
import time
import json
from datetime import datetime, date, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    import pandas as pd
    import numpy as np
except ImportError:
    pass

_REPORT_CACHE = {}
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.nse_cache')


def _ensure_cache():
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _clean_cache(pattern):
    """Remove all cached files matching pattern (keep only latest)."""
    _ensure_cache()
    for f in os.listdir(_CACHE_DIR):
        import fnmatch
        if fnmatch.fnmatch(f, pattern):
            os.remove(os.path.join(_CACHE_DIR, f))


def _date_path(dt=None):
    if dt is None:
        dt = date.today()
    if isinstance(dt, str):
        dt = datetime.strptime(dt, '%Y-%m-%d').date()
    return dt


def _is_weekend(d):
    return d.weekday() >= 5


def _get_last_trading_day(dt=None):
    d = _parse_nse_date(dt)
    while _is_weekend(d):
        d -= timedelta(days=1)
    return d


def _nse_download_bytes(url, retries=2, timeout=15):
    """Download raw bytes from NSE (for ZIP files)."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=timeout)
            raw = resp.read()
            try:
                import gzip
                return gzip.decompress(raw)
            except Exception:
                return raw
        except HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
                continue
    return None


def _nse_archive_request(url, retries=2, timeout=15):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }

    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=timeout)
            raw = resp.read()
            try:
                import gzip
                return gzip.decompress(raw).decode('latin-1')
            except Exception:
                return raw.decode('latin-1')
        except HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
                continue
    return None


def _parse_nse_date(dt):
    if dt is None:
        return date.today()
    if isinstance(dt, date):
        return dt
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d%m%Y', '%d-%b-%Y', '%d-%b-%y'):
        try:
            return datetime.strptime(dt, fmt).date()
        except ValueError:
            continue
    return date.today()


# =========================================================================
# 1. F&O BHAVCOPY — REAL OPEN INTEREST
# =========================================================================

def _normalize_fo_columns(df):
    """Normalize F&O bhavcopy column names to standard format."""
    col_map = {
        'TckrSymb': 'SYMBOL', 'OptnTp': 'OPTION_TYP', 'OpnIntrst': 'OPEN_INT',
        'ChngInOpnIntrst': 'CHG_IN_OI', 'TtlTradgVol': 'CONTRACTS',
        'TtlTrfVal': 'VALUE_IN_LAKHS', 'XpryDt': 'EXPIRY_DT',
        'StrkPric': 'STRIKE_PRICE', 'ClsPric': 'CLOSE',
        'UndrlygPric': 'UNDERLYING', 'FinInstrmTp': 'INSTRM_TP',
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if 'INSTRM_TP' in df.columns:
        df['INSTRM_TP'] = df['INSTRM_TP'].astype(str)
    return df


def fetch_fo_bhavcopy(dt=None):
    """
    Download NSE F&O Bhavcopy for a given date.
    Contains real futures/options OI for EVERY F&O stock.

    URL format (current): BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
    Example for 22-May-2026: BhavCopy_NSE_FO_0_0_0_20260522_F_0000.csv.zip

    Args:
        dt: Date (default: today). Accepts YYYY-MM-DD string or date object.

    Returns:
        pd.DataFrame with standardized columns:
        SYMBOL, EXPIRY_DT, OPTION_TYP, STRIKE_PRICE, OPEN, HIGH, LOW, CLOSE,
        CONTRACTS, VALUE_IN_LAKHS, OPEN_INT, CHG_IN_OI, INSTRM_TP, UNDERLYING

        Stock futures: INSTRM_TP='STF' (formerly OPTION_TYP='XX')
        Index futures: INSTRM_TP='IDF'
        Options:       INSTRM_TP='STO'/'IDO', OPTION_TYP='CE'/'PE'
    """
    dt = _parse_nse_date(dt)
    date_str = dt.strftime('%Y%m%d')
    filename_zip = f"BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip"
    # The CSV inside the zip
    csv_name = f"BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv"

    cache_csv = os.path.join(_CACHE_DIR, csv_name)
    _ensure_cache()
    _clean_cache('BhavCopy_NSE_FO_*.csv')

    url = f"https://nsearchives.nseindia.com/content/fo/{filename_zip}"
    zip_bytes = _nse_download_bytes(url)

    if zip_bytes is None:
        alt_url = f"https://archives.nseindia.com/content/fo/{filename_zip}"
        zip_bytes = _nse_download_bytes(alt_url)

    if zip_bytes is None:
        print(f"  [!] F&O Bhavcopy not available for {dt}")
        return None

    import zipfile as _zipfile
    import io as _io

    try:
        with _zipfile.ZipFile(_io.BytesIO(zip_bytes)) as zf:
            csv_raw = zf.read(csv_name).decode('latin-1')
    except Exception:
        print(f"  [!] Failed to unzip bhavcopy for {dt}")
        return None

    df = _normalize_fo_columns(pd.read_csv(_io.StringIO(csv_raw)))
    df.to_csv(cache_csv, index=False)

    for col in ['OPEN_INT', 'CHG_IN_OI', 'CONTRACTS', 'VALUE_IN_LAKHS']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

    return df


def get_futures_oi_from_bhav(dt=None):
    """
    Get cumulative futures OI for all F&O stocks from a single bhavcopy.
    Aggregates across ALL expiry months for each symbol.

    NSE has 3 monthly futures contracts trading simultaneously:
      - Current month (near expiry)
      - Next month (middle)
      - Far month (distant)

    The cumulative OI across all 3 represents total market positioning.

    Args:
        dt: Date string YYYY-MM-DD or date object

    Returns:
        pd.DataFrame with columns:
            SYMBOL | OPEN_INT | CHG_IN_OI | OI_CHG_PCT | CONTRACTS | CONTRACT_COUNT
        - OPEN_INT: Sum of all expiry OI for the symbol
        - CHG_IN_OI: Sum of all expiry OI change
        - OI_CHG_PCT: Weighted OI change %
        - CONTRACT_COUNT: Number of active expiry months (1-3)
    """
    df = fetch_fo_bhavcopy(dt)
    if df is None:
        return None

    # Support both new format (INSTRM_TP='STF'/'IDF') and legacy (OPTION_TYP='XX')
    if 'INSTRM_TP' in df.columns:
        futures = df[df['INSTRM_TP'].isin(['STF', 'IDF'])].copy()
    else:
        futures = df[df['OPTION_TYP'] == 'XX'].copy()

    if futures.empty:
        return None

    grouped = futures.groupby('SYMBOL', sort=False).agg({
        'OPEN_INT': 'sum',
        'CHG_IN_OI': 'sum',
        'CONTRACTS': 'sum',
        'EXPIRY_DT': 'nunique',
    }).reset_index()

    grouped.rename(columns={'EXPIRY_DT': 'CONTRACT_COUNT'}, inplace=True)

    prev_oi = (grouped['OPEN_INT'] - grouped['CHG_IN_OI']).clip(lower=1)
    grouped['OI_CHG_PCT'] = round((grouped['CHG_IN_OI'] / prev_oi) * 100, 2)

    return grouped


# =========================================================================
# 2. EQUITY BHAVCOPY — DELIVERY PERCENTAGE
# =========================================================================

def fetch_equity_bhavcopy(dt=None):
    """
    Download NSE Equity Bhavcopy.
    Contains: SYMBOL, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE,
              TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN

    URL: cm<DDMMMYYYY>bhav.csv

    Args:
        dt: Date string YYYY-MM-DD or date object

    Returns:
        pd.DataFrame
    """
    dt = _parse_nse_date(dt)
    day = dt.strftime('%d').upper()
    mon = dt.strftime('%b').upper()
    year = dt.strftime('%Y')
    filename = f"cm{day}{mon}{year}bhav.csv"

    cache_path = os.path.join(_CACHE_DIR, filename)
    _ensure_cache()
    _clean_cache('cm*bhav.csv')

    base_url = "https://nsearchives.nseindia.com/content/historical/EQUITIES"
    url = f"{base_url}/{year}/{mon}/{filename}"
    raw = _nse_archive_request(url)

    if raw is None:
        alt_url = f"https://archives.nseindia.com/content/historical/EQUITIES/{year}/{mon}/{filename}"
        raw = _nse_archive_request(alt_url)

    if raw is None:
        print(f"  [!] Equity Bhavcopy not available for {dt}")
        return None

    df = pd.read_csv(io.StringIO(raw))
    df.to_csv(cache_path, index=False)

    float_cols = ['OPEN', 'HIGH', 'LOW', 'CLOSE', 'LAST', 'PREVCLOSE']
    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    int_cols = ['TOTTRDQTY', 'TOTTRDVAL', 'TOTALTRADES']
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

    return df


def fetch_delivery_report(dt=None):
    """
    Fetch NSE Delivery Report (securities delivered vs traded).
    This gives REAL delivery % — replaces the proxy in volume_analytics.py.

    Returns columns:
        SYMBOL, DELIVERABLE_QTY, DELIVERABLE_PCT, TRADED_QTY

    Args:
        dt: Date string YYYY-MM-DD or date object

    Returns:
        pd.DataFrame
    """
    dt = _parse_nse_date(dt)
    date_str = dt.strftime('%d%m%Y')

    cache_path = os.path.join(_CACHE_DIR, f"delivery_{date_str}.csv")
    _ensure_cache()
    _clean_cache('delivery_*.csv')

    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    raw = _nse_archive_request(url)

    if raw is None:
        url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
        raw = _nse_archive_request(url)

    if raw is None:
        print(f"  [!] Delivery report not available for {dt}")
        return None

    lines = raw.strip().split('\n')
    if len(lines) < 2:
        return None

    reader = csv.reader(io.StringIO(raw))
    header = next(reader)
    header = [h.strip().strip('"') for h in header]

    rows = []
    for row in reader:
        if len(row) == len(header):
            rows.append([v.strip().strip('"') for v in row])

    df = pd.DataFrame(rows, columns=header)

    key_cols = {
        'SYMBOL': 'SYMBOL',
        ' SERIES ': None,
        ' Date ': None,
        ' TOTTREDQTY ': None,
        ' DELIV_QTY ': None,
        ' DELIV_PER ': None,
    }

    found_cols = {}
    for c in df.columns:
        clean = c.strip()
        if 'SYMBOL' in clean.upper():
            found_cols['SYMBOL'] = c
        elif 'DELIV' in clean.upper() and 'PER' in clean.upper():
            found_cols['DELIV_PER'] = c
        elif 'DELIV' in clean.upper() and ('QTY' in clean.upper() or 'QUANT' in clean.upper()):
            found_cols['DELIV_QTY'] = c
        elif 'TRAD' in clean.upper() and ('QTY' in clean.upper() or 'QUANT' in clean.upper()):
            found_cols['TRADED_QTY'] = c

    if 'SYMBOL' not in found_cols or 'DELIV_PER' not in found_cols:
        print(f"  [!] Unknown delivery report format. Columns: {list(df.columns)}")
        return None

    result = pd.DataFrame()
    result['SYMBOL'] = df[found_cols['SYMBOL']]
    result['DELIVERABLE_PCT'] = pd.to_numeric(df[found_cols['DELIV_PER']], errors='coerce')
    if 'DELIV_QTY' in found_cols:
        result['DELIVERABLE_QTY'] = pd.to_numeric(df[found_cols['DELIV_QTY']], errors='coerce').fillna(0).astype(int)
    if 'TRADED_QTY' in found_cols:
        result['TRADED_QTY'] = pd.to_numeric(df[found_cols['TRADED_QTY']], errors='coerce').fillna(0).astype(int)

    result = result.dropna(subset=['DELIVERABLE_PCT'])
    result.to_csv(cache_path, index=False)

    return result


# =========================================================================
# 3. BLOCK / BULK DEALS
# =========================================================================

def fetch_block_deals(dt=None):
    """
    Fetch NSE Block/Bulk Deals for a given date.
    Institutional trades of ₹5 Cr+ are reported here.

    Returns:
        pd.DataFrame with: SYMBOL, BUY_QTY, BUY_VALUE, SELL_QTY, SELL_VALUE, NET
    """
    dt = _parse_nse_date(dt)
    date_str = dt.strftime('%d-%m-%Y')

    url = f"https://nsearchives.nseindia.com/products/content/eq_bulkdeals_{date_str}.csv"
    raw = _nse_archive_request(url)

    if raw is None:
        return None

    df = pd.read_csv(io.StringIO(raw))
    return df


# =========================================================================
# 4. PCR (PUT/CALL RATIO) FROM BHAVCOPY
# =========================================================================

def get_pcr_from_bhav(dt=None):
    """
    Compute real Put/Call Ratio from option chain data in the F&O bhavcopy.

    PCR = Total Put OI / Total Call OI (aggregated across all expiries/strikes)

    Args:
        dt: Date string YYYY-MM-DD or date object

    Returns:
        pd.DataFrame: SYMBOL | PCR | CALL_OI | PUT_OI
    """
    df = fetch_fo_bhavcopy(dt)
    if df is None:
        return None

    if 'INSTRM_TP' in df.columns:
        opts = df[df['INSTRM_TP'].isin(['STO', 'IDO'])].copy()
    else:
        opts = df[df['OPTION_TYP'].isin(['CE', 'PE'])].copy()

    if opts.empty:
        return None

    calls = opts[opts['OPTION_TYP'] == 'CE'].groupby('SYMBOL', sort=False)['OPEN_INT'].sum()
    puts = opts[opts['OPTION_TYP'] == 'PE'].groupby('SYMBOL', sort=False)['OPEN_INT'].sum()

    result = pd.DataFrame({'CALL_OI': calls, 'PUT_OI': puts}).reset_index()
    result['PCR'] = round(result['PUT_OI'] / result['CALL_OI'].clip(lower=1), 2)

    return result


# =========================================================================
# 5. F&O STOCK LIST FROM BHAVCOPY
# =========================================================================

def get_fno_symbols_from_bhav(dt=None):
    """
    Get the live F&O stock list from NSE bhavcopy.
    Returns stock futures only (excludes index futures like NIFTY/BANKNIFTY).

    Falls back to None if bhavcopy unavailable (caller uses hardcoded list).

    Args:
        dt: Date string YYYY-MM-DD or date object

    Returns:
        list[str] of symbols (e.g. ['RELIANCE', 'TCS', 'HDFCBANK', ...])
        or None if bhavcopy unavailable
    """
    dt = _get_last_trading_day(dt)
    df = fetch_fo_bhavcopy(dt)
    if df is None:
        return None

    if 'INSTRM_TP' in df.columns:
        stf = df[df['INSTRM_TP'] == 'STF']
    else:
        stf = df[df['OPTION_TYP'] == 'XX']

    if stf.empty:
        return None

    return sorted(stf['SYMBOL'].dropna().unique().tolist())


# =========================================================================
# 6. ENRICH SCANNER WITH AFTER-MARKET DATA
# =========================================================================

def classify_real_oi(oi_change_pct, price_change_pct):
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


def enrich_from_bhavcopy(scanner_results, dt=None, price_col='CMP', chg_col='Chg%'):
    """
    Replace proxy OI/delivery data with REAL after-market data.

    Replaces:
      - OI_Chg%  → cumulative futures OI change % (all expiries summed)
      - OI_Class → real OI+price classification
      - Del%     → real delivery % from NSE

    Adds:
      - FUT_OI       → Total cumulative open interest across all expiries
      - FUT_CONTRACTS → Number of active future contracts (1-3 expiries)

    Call this AFTER scanner.run() to upgrade proxy data to real data.

    Args:
        scanner_results: pd.DataFrame from scanner.run()
        dt: Trade date (default: today)
        price_col: Column name for price (default: 'CMP')
        chg_col: Column name for daily change (default: 'Chg%')

    Returns:
        pd.DataFrame with enriched columns
    """
    df = scanner_results.copy()
    total = len(df)

    # Auto-adjust to last trading day if weekend/public holiday
    fo_dt = _get_last_trading_day(dt)
    if fo_dt != _parse_nse_date(dt):
        print(f"  \u2502  [*] Weekend detected, using {fo_dt} (last trading day)")

    # =========================================================================
    # PHASE 1: REAL FUTURES OI (cumulative across all expiries)
    # =========================================================================
    print(f"  \u2502  [1/3] Fetching F&O Bhavcopy (cumulative futures OI)...")
    fo = get_futures_oi_from_bhav(fo_dt)

    oi_updated = 0
    if fo is not None:
        oi_map = {}
        for _, r in fo.iterrows():
            oi_map[r['SYMBOL']] = {
                'open_int': int(r['OPEN_INT']),
                'chg_in_oi': int(r['CHG_IN_OI']),
                'oi_chg_pct': float(r['OI_CHG_PCT']),
                'contracts': int(r['CONTRACTS']),
                'contract_count': int(r['CONTRACT_COUNT']),
            }

        df['FUT_OI'] = 0
        df['FUT_CONTRACTS'] = 0

        for i, row in df.iterrows():
            sym = row['Symbol']
            if sym in oi_map:
                o = oi_map[sym]
                price_chg = row.get(chg_col, 0) or 0
                real_class = classify_real_oi(o['oi_chg_pct'], price_chg)

                df.at[i, 'OI_Chg%'] = o['oi_chg_pct']
                df.at[i, 'OI_Class'] = real_class
                df.at[i, 'FUT_OI'] = o['open_int']
                df.at[i, 'FUT_CONTRACTS'] = o['contract_count']
                oi_updated += 1

        print(f"  \u2502     OI enriched: {oi_updated}/{total} stocks")

    # =========================================================================
    # PHASE 1b: REAL PCR (Put/Call Ratio) from bhavcopy
    # =========================================================================
    pcr_updated = 0
    print(f"  \u2502  [2/3] Computing PCR from bhavcopy option chain...")
    pcr_data = get_pcr_from_bhav(fo_dt)
    if pcr_data is not None:
        pcr_map = pcr_data.set_index('SYMBOL')['PCR'].to_dict()
        for i, row in df.iterrows():
            sym = row['Symbol']
            if sym in pcr_map:
                df.at[i, 'PCR'] = pcr_map[sym]
                pcr_updated += 1
        print(f"  \u2502     PCR enriched: {pcr_updated}/{total} stocks")
    else:
        print(f"  \u2502     PCR skipped (no option data)")

    # =========================================================================
    # PHASE 3: REAL DELIVERY %
    # =========================================================================
    print(f"  \u2502  [3/4] Fetching Delivery Report (real Del%)...")
    delivery = fetch_delivery_report(fo_dt)

    del_updated = 0
    if delivery is not None:
        del_map = delivery.set_index('SYMBOL')['DELIVERABLE_PCT'].to_dict()

        df['REAL_DEL%'] = None

        for i, row in df.iterrows():
            sym = row['Symbol']
            if sym in del_map:
                real_del = float(del_map[sym])
                df.at[i, 'Del%'] = round(real_del, 1)
                df.at[i, 'REAL_DEL%'] = round(real_del, 1)
                del_updated += 1

        print(f"  \u2502     Delivery enriched: {del_updated}/{total} stocks")

    # =========================================================================
    # PHASE 3: Recalculate OI Score (only if OI was actually enriched)
    # =========================================================================
    score_updated = 0
    if oi_updated > 0:
        print(f"  \u2502  [3/3] Recalculating OI Score with real data...")
        for i, row in df.iterrows():
            real_oi_chg = row.get('OI_Chg%', 0) or 0
            real_class = row.get('OI_Class', 'Neutral')
            old_sub_oi = row.get('_sub_oi', 0) or 0

            new_sub_oi = min(max(int(abs(real_oi_chg) / 5), 0), 15)
            if real_oi_chg > 5 and real_class in ("Long Buildup", "Short Covering"):
                new_sub_oi = min(15, new_sub_oi + 5)
            if real_oi_chg < -5 and real_class in ("Long Unwinding", "Short Buildup"):
                new_sub_oi = max(0, new_sub_oi - 3)

            if old_sub_oi != new_sub_oi:
                score_diff = new_sub_oi - old_sub_oi
                old_total = row.get('Score', 0) or 0
                new_total = max(0, min(100, old_total + score_diff))
                df.at[i, 'Score'] = new_total
                df.at[i, '_sub_oi'] = new_sub_oi
                score_updated += 1

        print(f"  \u2502     Scores recalculated: {score_updated}/{total} stocks")
    else:
        print(f"  \u2502  [4/4] Skipping score recalc (no OI data to enrich with)")

    enriched = oi_updated + del_updated
    print(f"  \u2502  \u2713 Enrichment complete: OI({oi_updated}) + PCR({pcr_updated}) + Delivery({del_updated})")
    print(f"  \u2514" + "\u2500" * 60 + "\u2518")

    return df


def master_enrich(scanner_results, dt=None, price_col='CMP', chg_col='Chg%'):
    """
    Try real NSE enrichment first; fall back to proxy data if unavailable.
    Adds a 'Data_Source' column: 'REAL' if enrichment succeeded, 'PROXY' otherwise.
    Works even on weekends/holidays — falls back gracefully.
    """
    df = scanner_results.copy()
    try:
        fo_dt = _get_last_trading_day(dt)
        fo = get_futures_oi_from_bhav(fo_dt)
        if fo is not None and len(fo) > 0:
            enriched = enrich_from_bhavcopy(df, dt=dt, price_col=price_col, chg_col=chg_col)
            enriched['Data_Source'] = 'REAL'
            return enriched
    except Exception as e:
        pass

    df['Data_Source'] = 'PROXY'
    return df
# =========================================================================

def backfill_oi_history(symbol, start_date, end_date=None):
    """
    Build historical OI data for a single symbol from archived bhavcopies.

    Args:
        symbol: NSE symbol (e.g., 'RELIANCE')
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD (default: today)

    Returns:
        pd.DataFrame with DATE, OPEN_INT, CHG_IN_OI, OI_CHG_PCT
    """
    if end_date is None:
        end_date = date.today()
    else:
        end_date = _parse_nse_date(end_date)

    start_date = _parse_nse_date(start_date)

    records = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            fo = fetch_fo_bhavcopy(current)
            if fo is not None:
                row = fo[(fo['SYMBOL'] == symbol) & (fo['OPTION_TYP'] == 'XX')]
                if not row.empty:
                    records.append({
                        'DATE': current,
                        'OPEN_INT': int(row.iloc[0]['OPEN_INT']),
                        'CHG_IN_OI': int(row.iloc[0]['CHG_IN_OI']),
                        'settle_price': float(row.iloc[0]['SETTLE_PRICE']),
                    })
        current += timedelta(days=1)

    if not records:
        return None

    result = pd.DataFrame(records)
    result['OI_CHG_PCT'] = (result['CHG_IN_OI'] / (result['OPEN_INT'] - result['CHG_IN_OI']).clip(lower=1)) * 100
    return result


def list_available_bhavcopies(since_date=None):
    """
    Check which bhavcopy dates are available in the local cache.
    """
    _ensure_cache()
    files = [f for f in os.listdir(_CACHE_DIR) if f.endswith('.csv')]
    dates = set()
    for f in files:
        if f.startswith('fo') and 'bhav' in f:
            try:
                day = f[2:4]
                mon = f[4:7]
                year = f[7:11]
                dt = datetime.strptime(f"{day}{mon}{year}", '%d%b%Y').date()
                dates.add(dt)
            except ValueError:
                continue
    return sorted(dates)
