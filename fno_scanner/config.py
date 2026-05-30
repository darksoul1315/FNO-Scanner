import ssl
import warnings

warnings.filterwarnings('ignore')
ssl._create_default_https_context = ssl._create_unverified_context

FNO_STOCKS = [
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENT",
    "ADANIPORTS", "ALKEM", "AMBUJACEM", "ANGELONE", "APLAPOLLO", "APOLLOHOSP",
    "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATUL", "AUBANK",
    "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE",
    "BALKRISIND", "BANDHANBNK", "BANKBARODA", "BANKNIFTY", "BATAINDIA",
    "BEL", "BERGEPAINT", "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON",
    "BOSCHLTD", "BPCL", "BRITANNIA", "BSE", "BSOFT", "CANBK", "CANFINHOME",
    "CHAMBLFERT", "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", "COLPAL",
    "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR",
    "DALBHARAT", "DEEPAKNTR", "DELTACORP", "DIVISLAB", "DIXON", "DLF",
    "DRREDDY", "EICHERMOT", "ESCORTS", "EXIDEIND", "FEDERALBNK",
    "GAIL", "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP",
    "GRANULES", "GRASIM", "GUJGASLTD", "HAL", "HAVELLS", "HCLTECH",
    "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO",
    "HINDCOPPER", "HINDPETRO", "HINDUNILVR", "HUDCO", "ICICIBANK",
    "ICICIGI", "ICICIPRULI", "IDEA", "IDFC", "IDFCFIRSTB", "IEX", "IGL",
    "INDHOTEL", "INDIACEM", "INDIAMART", "INDIGO", "INDUSINDBK",
    "INDUSTOWER", "INFY", "IOC", "IPCALAB", "IRCTC", "ITC", "JINDALSTEL",
    "JIOFIN", "JKCEMENT", "JSL", "JSWENERGY", "JSWSTEEL", "JUBLFOOD",
    "KALYANKJIL", "KOTAKBANK", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN",
    "LT", "LTF", "LTIM", "LTTS", "LUPIN", "M&M", "M&MFIN", "MANAPPURAM",
    "MARICO", "MARUTI", "MAXHEALTH", "MCX", "MFSL", "MGL", "MOTHERSON",
    "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NAVINFLUOR",
    "NESTLEIND", "NHPC", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "OIL",
    "ONGC", "PAGEIND", "PEL", "PERSISTENT", "PETRONET", "PFC", "PIDILITIND",
    "PIIND", "PNB", "POLYCAB", "POONAWALLA", "POWERGRID", "PVRINOX",
    "RAMCOCEM", "RBLBANK", "RECLTD", "RELIANCE", "SAIL", "SBICARD",
    "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SONACOMS",
    "SRF", "SUNPHARMA", "SUNTV", "SUPREMEIND", "SYNGENE", "TATACHEM",
    "TATACOMM", "TATACONSUM", "TATAELXSI", "TATAMOTORS", "TATAPOWER",
    "TATASTEEL", "TCS", "TECHM", "TIINDIA", "TITAN", "TORNTPHARM",
    "TORNTPOWER", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO", "UNITDSPR",
    "UPL", "VBL", "VEDL", "VOLTAS", "WIPRO", "ZOMATO", "ZYDUSLIFE"
]

SECTOR_MAP = {
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
    "KOTAKBANK": "Banking", "AXISBANK": "Banking", "INDUSINDBK": "Banking",
    "BANKBARODA": "Banking", "PNB": "Banking", "FEDERALBNK": "Banking",
    "IDFCFIRSTB": "Banking", "AUBANK": "Banking", "BANDHANBNK": "Banking",
    "CANBK": "Banking", "CUB": "Banking", "RBLBANK": "Banking", "IDFC": "Banking",
    "BAJFINANCE": "Financials", "BAJAJFINSV": "Financials", "CHOLAFIN": "Financials",
    "SHRIRAMFIN": "Financials", "M&MFIN": "Financials", "MUTHOOTFIN": "Financials",
    "MANAPPURAM": "Financials", "LICHSGFIN": "Financials", "CANFINHOME": "Financials",
    "HDFCAMC": "Financials", "SBICARD": "Financials", "SBILIFE": "Financials",
    "HDFCLIFE": "Financials", "ICICIPRULI": "Financials", "ICICIGI": "Financials",
    "MFSL": "Financials", "ANGELONE": "Financials", "BSE": "Financials",
    "MCX": "Financials", "JIOFIN": "Financials", "LTF": "Financials",
    "PFC": "Financials", "RECLTD": "Financials", "POONAWALLA": "Financials",
    "ABCAPITAL": "Financials", "KALYANKJIL": "Financials",

    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT",
    "TECHM": "IT", "LTIM": "IT", "LTTS": "IT", "MPHASIS": "IT",
    "COFORGE": "IT", "PERSISTENT": "IT", "BSOFT": "IT", "TATAELXSI": "IT",
    "OFSS": "IT", "NAUKRI": "IT", "INDIAMART": "IT",

    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma",
    "DIVISLAB": "Pharma", "LUPIN": "Pharma", "AUROPHARMA": "Pharma",
    "BIOCON": "Pharma", "ALKEM": "Pharma", "TORNTPHARM": "Pharma",
    "IPCALAB": "Pharma", "LALPATHLAB": "Pharma", "GRANULES": "Pharma",
    "LAURUSLABS": "Pharma", "GLENMARK": "Pharma", "SYNGENE": "Pharma",
    "ABBOTINDIA": "Pharma", "MAXHEALTH": "Pharma", "APOLLOHOSP": "Pharma",
    "ZYDUSLIFE": "Pharma", "DEEPAKNTR": "Pharma", "NAVINFLUOR": "Pharma",

    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy",
    "IOC": "Energy", "HINDPETRO": "Energy", "GAIL": "Energy",
    "OIL": "Energy", "PETRONET": "Energy", "IGL": "Energy",
    "MGL": "Energy", "GUJGASLTD": "Energy", "NTPC": "Energy",
    "POWERGRID": "Energy", "TATAPOWER": "Energy", "NHPC": "Energy",
    "JSWENERGY": "Energy", "TORNTPOWER": "Energy", "ADANIENT": "Energy",
    "ADANIPORTS": "Energy",

    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals",
    "VEDL": "Metals", "SAIL": "Metals", "JINDALSTEL": "Metals",
    "NMDC": "Metals", "NATIONALUM": "Metals", "HINDCOPPER": "Metals",
    "COALINDIA": "Metals", "JSL": "Metals",

    "TATAMOTORS": "Auto", "MARUTI": "Auto", "M&M": "Auto",
    "BAJAJ-AUTO": "Auto", "HEROMOTOCO": "Auto", "EICHERMOT": "Auto",
    "TVSMOTOR": "Auto", "ASHOKLEY": "Auto", "ESCORTS": "Auto",
    "MOTHERSON": "Auto", "APOLLOTYRE": "Auto", "BALKRISIND": "Auto",
    "BHARATFORG": "Auto", "EXIDEIND": "Auto", "SONACOMS": "Auto",
    "MRF": "Auto",

    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG", "DABUR": "FMCG", "MARICO": "FMCG",
    "GODREJCP": "FMCG", "COLPAL": "FMCG", "TATACONSUM": "FMCG",
    "VBL": "FMCG", "UBL": "FMCG", "UNITDSPR": "FMCG",
    "JUBLFOOD": "FMCG", "ZOMATO": "FMCG", "PVRINOX": "FMCG",
    "PAGEIND": "FMCG", "TRENT": "FMCG", "BATAINDIA": "FMCG",

    "LT": "CapGoods", "SIEMENS": "CapGoods", "ABB": "CapGoods",
    "HAL": "CapGoods", "BEL": "CapGoods", "BHEL": "CapGoods",
    "CUMMINSIND": "CapGoods", "CROMPTON": "CapGoods", "HAVELLS": "CapGoods",
    "POLYCAB": "CapGoods", "VOLTAS": "CapGoods", "TIINDIA": "CapGoods",
    "APLAPOLLO": "CapGoods", "INDUSTOWER": "CapGoods", "DIXON": "CapGoods",
    "IRCTC": "CapGoods", "CONCOR": "CapGoods",

    "ULTRACEMCO": "Cement", "SHREECEM": "Cement", "ACC": "Cement",
    "AMBUJACEM": "Cement", "DALBHARAT": "Cement", "RAMCOCEM": "Cement",
    "JKCEMENT": "Cement", "INDIACEM": "Cement",
    "DLF": "Realty", "OBEROIRLTY": "Realty", "GODREJPROP": "Realty",
    "GMRINFRA": "Realty", "HUDCO": "Realty",

    "SRF": "Chemicals", "PIIND": "Chemicals", "AARTIIND": "Chemicals",
    "CHAMBLFERT": "Chemicals", "GNFC": "Chemicals", "COROMANDEL": "Chemicals",
    "ASTRAL": "Chemicals", "SUPREMEIND": "Chemicals", "PIDILITIND": "Chemicals",
    "ATUL": "Chemicals", "TATACHEM": "Chemicals",

    "BHARTIARTL": "Telecom", "IDEA": "Telecom", "TATACOMM": "Telecom",
    "SUNTV": "Media", "INDIGO": "Aviation",

    "BERGEPAINT": "Paints", "ASIANPAINT": "Paints",
    "TITAN": "Consumer", "GRASIM": "Diversified",
    "IEX": "Exchange", "BOSCHLTD": "Auto",
    "PEL": "Diversified", "ABFRL": "Retail",
    "DELTACORP": "Leisure", "INDHOTEL": "Hotels",
}

LIQUIDITY_CONFIG = {
    "min_avg_traded_value_cr": 200,
    "min_avg_volume_ratio": 1.0,
    "min_price": 50,
    "min_volume_20d": 500_000,
    "min_data_days": 200,
}

PRICE_ACTION_CONFIG = {
    "atr_period": 14,
    "atr_long_period": 50,
    "imbalance_atr_mult": 1.8,
    "volume_spike_mult": 2.0,
    "compression_ratio": 0.75,
    "tight_range_pct": 0.04,
    "elite_tight_range_pct": 0.025,
    "vwap_tolerance_pct": 0.005,
    "displacement_body_ratio": 0.7,
    "fvg_overlap_threshold": 0.5,
}

OI_CONFIG = {
    "oi_change_significant_pct": 5.0,
    "oi_spike_mult": 1.5,
    "pcr_bullish_threshold": 1.2,
    "pcr_bearish_threshold": 0.6,
    "iv_expansion_pct": 20,
    "iv_percentile_high": 75,
    "iv_percentile_low": 25,
}

INSTITUTIONAL_CONFIG = {
    "delivery_pct_spike": 60,
    "delivery_pct_high": 70,
    "block_trade_threshold_cr": 5,
    "rs_outperform_threshold": 0.0,
    "rs_strong_threshold": 0.05,
}

SCORING_WEIGHTS = {
    "liquidity_score": 10,
    "oi_score": 15,
    "momentum_score": 15,
    "rs_score": 10,
    "volume_score": 15,
    "volatility_score": 10,
    "smart_money_score": 15,
    "option_score": 10,
}

RUNTIME_CONFIG = {
    "max_workers": 12,
    "data_lookback_days": 400,
    "cache_expiry_seconds": 300,
    "retry_count": 3,
    "retry_delay_seconds": 2,
}

FOCUS_SECTORS = [
    "Banking", "Financials", "IT", "Energy", "Metals", "CapGoods",
    "Auto", "Pharma", "FMCG", "Cement", "Realty", "Chemicals"
]

TIMEFRAMES = {
    "intraday": "5m",
    "15m": "15m",
    "1h": "60m",
    "daily": "1d",
    "weekly": "1wk",
}
