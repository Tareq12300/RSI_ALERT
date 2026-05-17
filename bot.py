import os
import time
import math
import json
import logging
import threading

import requests
import pandas as pd
from flask import Flask

# =========================
# ENV VARIABLES
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ENABLE_WELCOME_MESSAGE = os.getenv("ENABLE_WELCOME_MESSAGE", "true").lower() == "true"

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "180"))
TIMEFRAME = os.getenv("TIMEFRAME", "4h")
CANDLE_LIMIT = int(os.getenv("CANDLE_LIMIT", "120"))

MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "85"))
MIN_VOLUME_24H_USD = float(os.getenv("MIN_VOLUME_24H_USD", "500000"))
MIN_VOLUME_SPIKE_X = float(os.getenv("MIN_VOLUME_SPIKE_X", "2.5"))

MIN_PRICE_CHANGE_24H = float(os.getenv("MIN_PRICE_CHANGE_24H", "-20"))
MAX_PRICE_CHANGE_24H = float(os.getenv("MAX_PRICE_CHANGE_24H", "80"))

MIN_MARKET_CAP_USD = float(os.getenv("MIN_MARKET_CAP_USD", "1000000"))
MAX_MARKET_CAP_USD = float(os.getenv("MAX_MARKET_CAP_USD", "3000000000"))

COOLDOWN_HOURS = float(os.getenv("COOLDOWN_HOURS", "12"))
MAX_SYMBOLS_PER_EXCHANGE = int(os.getenv("MAX_SYMBOLS_PER_EXCHANGE", "350"))

ENABLE_OKX = os.getenv("ENABLE_OKX", "true").lower() == "true"
ENABLE_BYBIT = os.getenv("ENABLE_BYBIT", "true").lower() == "true"
ENABLE_GATE = os.getenv("ENABLE_GATE", "true").lower() == "true"
ENABLE_BITGET = os.getenv("ENABLE_BITGET", "true").lower() == "true"
ENABLE_MEXC = os.getenv("ENABLE_MEXC", "true").lower() == "true"

ENABLE_COINGECKO_FILTERS = os.getenv("ENABLE_COINGECKO_FILTERS", "true").lower() == "true"
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

STATE_FILE = "state.json"

EXCLUDED_SYMBOLS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "USDD", "FRAX", "LUSD", "USD1",
    "DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "BOME", "MEME", "DOGS", "TURBO", "BABYDOGE",
    "CAT", "MOG", "BRETT", "PONKE", "MEW", "POPCAT", "NEIRO", "SUNDOG", "HIPPO", "PNUT",
    "TWT", "SAFE", "GLDX", "XAUT", "PAXG",
    "BNB", "JUP", "SUI"
}

EXCLUDED_KEYWORDS = [
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME", "INU", "CAT", "DOG",
    "BABY", "ELON", "TRUMP", "BIDEN", "MAGA", "PEOPLE", "WOJAK", "PONKE", "POPCAT",
    "USD", "USDT", "USDC", "DAI", "FDUSD", "USDE",
    "XSTOCK", "ETF", "TOKENIZED", "STOCK"
]

# =========================
# LOGGING / FLASK
# =========================

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")

app = Flask(__name__)

@app.route("/")
def home():
    return {
        "ok": True,
        "bot": "Early Pump Scanner",
        "binance": "disabled",
        "timeframe": TIMEFRAME,
        "scan_interval": SCAN_INTERVAL,
        "exchanges": enabled_exchanges()
    }

def enabled_exchanges():
    exchanges = []
    if ENABLE_OKX:
        exchanges.append("OKX")
    if ENABLE_BYBIT:
        exchanges.append("Bybit")
    if ENABLE_GATE:
        exchanges.append("Gate")
    if ENABLE_BITGET:
        exchanges.append("Bitget")
    if ENABLE_MEXC:
        exchanges.append("MEXC")
    return exchanges

# =========================
# HELPERS
# =========================

def request_json(url, params=None, headers=None, timeout=15):
    r = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.warning(f"Could not save state: {e}")

def is_excluded_symbol(symbol):
    s = symbol.upper().replace("USDT", "").replace("_", "").replace("-", "").replace("/", "")
    if s in EXCLUDED_SYMBOLS:
        return True

    for keyword in EXCLUDED_KEYWORDS:
        if keyword in s:
            return True

    return False

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram variables missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        requests.post(url, json=payload, timeout=15).raise_for_status()
    except Exception as e:
        logging.error(f"Telegram send failed: {e}")

def send_welcome_message():
    if not ENABLE_WELCOME_MESSAGE:
        return

    msg = f"""🚀 <b>Early Pump Scanner Started</b>

✅ Binance Disabled
✅ Meme Coins Filtered
✅ Stable Coins Filtered
✅ CEX Spot Coins Only
✅ Volume Spike Detection Active
✅ Breakout Scanner Active
✅ Momentum Scanner Active
✅ Repeat Protection Active

📊 <b>Monitoring:</b> 1000+ CEX Coins
🏦 <b>Exchanges:</b> {", ".join(enabled_exchanges())}
⏱ <b>Timeframe:</b> {TIMEFRAME}
🔥 <b>Mode:</b> Early Explosion Detection

📈 <b>Alert Includes:</b>
• Current Volume
• Average 20 Candles Volume
• Volume Spike Ratio
• Spike Increase %
• Market Cap
• 24H Volume
• Confidence Score
• Targets + Stop Loss"""
    send_telegram(msg)

def money(v):
    v = safe_float(v)

    if v >= 1_000_000_000:
        return f"${v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.2f}K"

    return f"${v:.2f}"

def pct(v):
    return f"{v:.2f}%"

# =========================
# EXCHANGE SYMBOLS
# =========================

def get_okx_symbols():
    data = request_json("https://www.okx.com/api/v5/public/instruments", {"instType": "SPOT"})
    rows = data.get("data", [])

    pairs = []
    for x in rows:
        inst = x.get("instId", "")
        if inst.endswith("-USDT"):
            base = inst.replace("-USDT", "")
            if not is_excluded_symbol(base):
                pairs.append({"exchange": "OKX", "symbol": base, "pair": inst})

    return pairs[:MAX_SYMBOLS_PER_EXCHANGE]

def get_bybit_symbols():
    data = request_json("https://api.bybit.com/v5/market/instruments-info", {"category": "spot"})
    rows = data.get("result", {}).get("list", [])

    pairs = []
    for x in rows:
        base = x.get("baseCoin", "")
        quote = x.get("quoteCoin", "")
        status = x.get("status", "")
        sym = x.get("symbol", "")

        if quote == "USDT" and status == "Trading" and not is_excluded_symbol(base):
            pairs.append({"exchange": "Bybit", "symbol": base, "pair": sym})

    return pairs[:MAX_SYMBOLS_PER_EXCHANGE]

def get_gate_symbols():
    data = request_json("https://api.gateio.ws/api/v4/spot/currency_pairs")

    pairs = []
    for x in data:
        pair = x.get("id", "")
        base = x.get("base", "")
        quote = x.get("quote", "")
        trade_status = x.get("trade_status", "")

        if quote == "USDT" and trade_status == "tradable" and not is_excluded_symbol(base):
            pairs.append({"exchange": "Gate", "symbol": base, "pair": pair})

    return pairs[:MAX_SYMBOLS_PER_EXCHANGE]

def get_bitget_symbols():
    data = request_json("https://api.bitget.com/api/v2/spot/public/symbols")
    rows = data.get("data", [])

    pairs = []
    for x in rows:
        base = x.get("baseCoin", "")
        quote = x.get("quoteCoin", "")
        status = x.get("status", "")
        sym = x.get("symbol", "")

        if quote == "USDT" and status == "online" and not is_excluded_symbol(base):
            pairs.append({"exchange": "Bitget", "symbol": base, "pair": sym})

    return pairs[:MAX_SYMBOLS_PER_EXCHANGE]

def get_mexc_symbols():
    data = request_json("https://api.mexc.com/api/v3/exchangeInfo")
    rows = data.get("symbols", [])

    pairs = []
    for x in rows:
        base = x.get("baseAsset", "")
        quote = x.get("quoteAsset", "")
        status = str(x.get("status", ""))
        sym = x.get("symbol", "")

        if quote == "USDT" and status in ("1", "ENABLED", "TRADING") and not is_excluded_symbol(base):
            pairs.append({"exchange": "MEXC", "symbol": base, "pair": sym})

    return pairs[:MAX_SYMBOLS_PER_EXCHANGE]

def get_all_symbols():
    all_pairs = []
    funcs = []

    if ENABLE_OKX:
        funcs.append(get_okx_symbols)
    if ENABLE_BYBIT:
        funcs.append(get_bybit_symbols)
    if ENABLE_GATE:
        funcs.append(get_gate_symbols)
    if ENABLE_BITGET:
        funcs.append(get_bitget_symbols)
    if ENABLE_MEXC:
        funcs.append(get_mexc_symbols)

    for fn in funcs:
        try:
            pairs = fn()
            if pairs:
                logging.info(f"{pairs[0]['exchange']}: {len(pairs)} pairs")
            all_pairs.extend(pairs)
        except Exception as e:
            logging.warning(f"Failed loading symbols from {fn.__name__}: {e}")

    unique = []
    seen = set()

    for p in all_pairs:
        key = (p["exchange"], p["pair"])
        if key not in seen:
            unique.append(p)
            seen.add(key)

    logging.info(f"Total watchlist pairs: {len(unique)}")
    return unique

# =========================
# CANDLES
# =========================

def map_tf(exchange, tf):
    if exchange in ("OKX", "Gate", "Bitget"):
        return {"15m": "15m", "1h": "1H", "4h": "4H"}.get(tf, "4H")

    if exchange == "Bybit":
        return {"15m": "15", "1h": "60", "4h": "240"}.get(tf, "240")

    if exchange == "MEXC":
        return {"15m": "15m", "1h": "60m", "4h": "4h"}.get(tf, "4h")

    return tf

def fetch_candles(item):
    ex = item["exchange"]
    pair = item["pair"]
    tf = map_tf(ex, TIMEFRAME)

    if ex == "OKX":
        data = request_json(
            "https://www.okx.com/api/v5/market/candles",
            {"instId": pair, "bar": tf, "limit": CANDLE_LIMIT}
        )
        rows = list(reversed(data.get("data", [])))

        return pd.DataFrame([{
            "time": int(r[0]),
            "open": safe_float(r[1]),
            "high": safe_float(r[2]),
            "low": safe_float(r[3]),
            "close": safe_float(r[4]),
            "volume": safe_float(r[7])
        } for r in rows])

    if ex == "Bybit":
        data = request_json(
            "https://api.bybit.com/v5/market/kline",
            {"category": "spot", "symbol": pair, "interval": tf, "limit": CANDLE_LIMIT}
        )
        rows = list(reversed(data.get("result", {}).get("list", [])))

        return pd.DataFrame([{
            "time": int(r[0]),
            "open": safe_float(r[1]),
            "high": safe_float(r[2]),
            "low": safe_float(r[3]),
            "close": safe_float(r[4]),
            "volume": safe_float(r[6])
        } for r in rows])

    if ex == "Gate":
        data = request_json(
            "https://api.gateio.ws/api/v4/spot/candlesticks",
            {"currency_pair": pair, "interval": tf.lower(), "limit": CANDLE_LIMIT}
        )

        return pd.DataFrame([{
            "time": int(r[0]),
            "volume": safe_float(r[1]),
            "close": safe_float(r[2]),
            "high": safe_float(r[3]),
            "low": safe_float(r[4]),
            "open": safe_float(r[5])
        } for r in data])

    if ex == "Bitget":
        data = request_json(
            "https://api.bitget.com/api/v2/spot/market/candles",
            {"symbol": pair, "granularity": tf, "limit": str(CANDLE_LIMIT)}
        )
        rows = data.get("data", [])

        return pd.DataFrame([{
            "time": int(r[0]),
            "open": safe_float(r[1]),
            "high": safe_float(r[2]),
            "low": safe_float(r[3]),
            "close": safe_float(r[4]),
            "volume": safe_float(r[6])
        } for r in rows])

    if ex == "MEXC":
        data = request_json(
            "https://api.mexc.com/api/v3/klines",
            {"symbol": pair, "interval": tf, "limit": CANDLE_LIMIT}
        )

        return pd.DataFrame([{
            "time": int(r[0]),
            "open": safe_float(r[1]),
            "high": safe_float(r[2]),
            "low": safe_float(r[3]),
            "close": safe_float(r[4]),
            "volume": safe_float(r[7])
        } for r in data])

    return pd.DataFrame()

# =========================
# COINGECKO MARKET DATA
# =========================

cg_cache = {}
cg_last_load = 0

def load_coingecko_markets():
    global cg_cache, cg_last_load

    now = time.time()

    if cg_cache and now - cg_last_load < 3600:
        return cg_cache

    if not ENABLE_COINGECKO_FILTERS:
        return {}

    headers = {}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

    cache = {}

    try:
        for page in range(1, 6):
            data = request_json(
                "https://api.coingecko.com/api/v3/coins/markets",
                {
                    "vs_currency": "usd",
                    "order": "volume_desc",
                    "per_page": 250,
                    "page": page,
                    "sparkline": "false",
                    "price_change_percentage": "24h"
                },
                headers=headers,
                timeout=20
            )

            for x in data:
                sym = str(x.get("symbol", "")).upper()
                if sym:
                    cache[sym] = {
                        "market_cap": safe_float(x.get("market_cap")),
                        "volume_24h": safe_float(x.get("total_volume")),
                        "price_change_24h": safe_float(x.get("price_change_percentage_24h")),
                        "name": x.get("name", ""),
                        "id": x.get("id", "")
                    }

            time.sleep(1.2)

        cg_cache = cache
        cg_last_load = now
        logging.info(f"CoinGecko markets loaded: {len(cg_cache)} symbols")
        return cg_cache

    except Exception as e:
        logging.warning(f"CoinGecko failed. Continuing without full market data: {e}")
        return cg_cache or {}

def get_market_info(symbol):
    markets = load_coingecko_markets()
    return markets.get(symbol.upper(), {})

# =========================
# INDICATORS
# =========================

def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()

    rs = gain / loss.replace(0, math.nan)
    return 100 - (100 / (1 + rs))

def macd(close):
    fast = ema(close, 12)
    slow = ema(close, 26)
    line = fast - slow
    signal = ema(line, 9)
    hist = line - signal
    return line, signal, hist

# =========================
# ANALYSIS
# =========================

def analyze(item):
    df = fetch_candles(item)

    if df.empty or len(df) < 50:
        return None

    df = df.dropna().copy()

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    last_close = safe_float(close.iloc[-1])
    prev_close = safe_float(close.iloc[-2])

    if last_close <= 0:
        return None

    current_volume = safe_float(volume.iloc[-1])
    avg20_volume = safe_float(volume.iloc[-21:-1].mean())

    if avg20_volume <= 0:
        return None

    spike_x = current_volume / avg20_volume
    spike_pct = (spike_x - 1) * 100

    last3_avg_volume = safe_float(volume.iloc[-3:].mean())
    prev10_avg_volume = safe_float(volume.iloc[-13:-3].mean())

    acceleration_x = last3_avg_volume / prev10_avg_volume if prev10_avg_volume > 0 else 0
    acceleration_increasing = acceleration_x >= 1.4

    rsi_val = safe_float(rsi(close).iloc[-1])

    ema20 = safe_float(ema(close, 20).iloc[-1])
    ema50 = safe_float(ema(close, 50).iloc[-1])

    _, _, hist = macd(close)

    macd_hist = safe_float(hist.iloc[-1])
    macd_hist_prev = safe_float(hist.iloc[-2])

    resistance = safe_float(high.iloc[-31:-1].max())
    breakout = last_close > resistance and current_volume > avg20_volume * 1.5

    price_change_24h_local = 0
    if len(close) >= 7 and safe_float(close.iloc[-7]) > 0:
        price_change_24h_local = ((last_close - safe_float(close.iloc[-7])) / safe_float(close.iloc[-7])) * 100

    market = get_market_info(item["symbol"])

    market_cap = safe_float(market.get("market_cap", 0))
    volume_24h = safe_float(market.get("volume_24h", 0))
    price_change_24h = safe_float(market.get("price_change_24h", price_change_24h_local))

    # Main filters
    if volume_24h and volume_24h < MIN_VOLUME_24H_USD:
        return None

    if market_cap and (market_cap < MIN_MARKET_CAP_USD or market_cap > MAX_MARKET_CAP_USD):
        return None

    if price_change_24h < MIN_PRICE_CHANGE_24H or price_change_24h > MAX_PRICE_CHANGE_24H:
        return None

    if spike_x < MIN_VOLUME_SPIKE_X:
        return None

    score = 0
    reasons = []

    if spike_x >= 7:
        score += 25
        reasons.append("Extreme Volume Spike")
    elif spike_x >= 4:
        score += 18
        reasons.append("Strong Volume Spike")
    elif spike_x >= 2:
        score += 10
        reasons.append("Good Volume Spike")

    if acceleration_increasing:
        score += 10
        reasons.append("Volume Acceleration Increasing")

    if breakout:
        score += 20
        reasons.append("Breakout Confirmed")

    if ema20 > ema50:
        score += 12
        reasons.append("EMA Trend Positive")

    if 45 <= rsi_val <= 72:
        score += 12
        reasons.append("Healthy Momentum RSI")

    if macd_hist > macd_hist_prev and macd_hist > 0:
        score += 12
        reasons.append("MACD Momentum Rising")

    candle_body = abs(last_close - safe_float(df["open"].iloc[-1]))
    candle_range = max(safe_float(high.iloc[-1]) - safe_float(low.iloc[-1]), 1e-12)

    strong_candle = last_close > prev_close and (candle_body / candle_range >= 0.45)

    if strong_candle:
        score += 9
        reasons.append("Strong Buyer Candle")

    if volume_24h >= MIN_VOLUME_24H_USD:
        score += 5
        reasons.append("Good 24H Volume")

    confidence = min(score, 100)

    if confidence < MIN_CONFIDENCE:
        return None

    if spike_x >= 7:
        spike_status = "Extreme"
    elif spike_x >= 4:
        spike_status = "Strong"
    elif spike_x >= 2:
        spike_status = "Good"
    else:
        spike_status = "Weak"

    return {
        "exchange": item["exchange"],
        "symbol": item["symbol"],
        "pair": item["pair"],
        "price": last_close,
        "market_cap": market_cap,
        "volume_24h": volume_24h,
        "price_change_24h": price_change_24h,
        "current_volume": current_volume,
        "avg20_volume": avg20_volume,
        "spike_x": spike_x,
        "spike_pct": spike_pct,
        "spike_status": spike_status,
        "acceleration_x": acceleration_x,
        "acceleration": "Increasing" if acceleration_increasing else "Normal",
        "rsi": rsi_val,
        "breakout": breakout,
        "confidence": confidence,
        "reasons": reasons
    }

# =========================
# ALERT FORMAT
# =========================

def format_alert(s):
    price = s["price"]

    tp1 = price * 1.08
    tp2 = price * 1.15
    tp3 = price * 1.25
    tp4 = price * 1.40
    tp5 = price * 1.70
    sl = price * 0.92

    reasons = "\n".join([f"✅ {r}" for r in s["reasons"]])

    return f"""🚀 <b>EARLY PUMP / BREAKOUT ALERT</b>

<b>Coin:</b> {s['symbol']}/USDT
<b>Exchange:</b> {s['exchange']}
<b>Price:</b> ${price:.8f}

📊 <b>Market Data</b>
<b>Market Cap:</b> {money(s['market_cap']) if s['market_cap'] else 'N/A'}
<b>24H Volume:</b> {money(s['volume_24h']) if s['volume_24h'] else 'N/A'}
<b>24H Change:</b> {pct(s['price_change_24h'])}

📈 <b>Volume Spike</b>
<b>Current Candle Volume:</b> {money(s['current_volume'])}
<b>Average 20 Candles:</b> {money(s['avg20_volume'])}
<b>Spike Ratio:</b> {s['spike_x']:.2f}X
<b>Spike Increase:</b> +{s['spike_pct']:.0f}%
<b>Status:</b> {s['spike_status']}
<b>Acceleration:</b> {s['acceleration']} ({s['acceleration_x']:.2f}X)

🔥 <b>Signals</b>
{reasons}

🎯 <b>Confidence:</b> {s['confidence']}%

🎯 <b>Targets</b>
TP1: ${tp1:.8f} (+8%)
TP2: ${tp2:.8f} (+15%)
TP3: ${tp3:.8f} (+25%)
TP4: ${tp4:.8f} (+40%)
TP5: ${tp5:.8f} (+70%)

🛑 <b>Stop Loss:</b> ${sl:.8f} (-8%)

⚠️ ليست توصية مالية. استخدم إدارة مخاطر."""



# =========================
# TARGET TRACKING
# =========================

TARGET_LEVELS = {
    "TP1": 0.08,
    "TP2": 0.15,
    "TP3": 0.25,
    "TP4": 0.40,
    "TP5": 0.70,
}

def target_tracking_key(exchange, symbol):
    return f"target_tracking:{exchange}:{symbol}"

def get_latest_price(item):
    df = fetch_candles(item)
    if df.empty or len(df) < 2:
        return 0.0
    return safe_float(df["close"].iloc[-1])

def register_target_tracking(signal, state):
    tracking_key = target_tracking_key(signal["exchange"], signal["symbol"])
    entry_price = safe_float(signal.get("price", 0))

    if entry_price <= 0:
        return

    state[tracking_key] = {
        "entry_price": entry_price,
        "created_at": time.time(),
        "hit": {
            "TP1": False,
            "TP2": False,
            "TP3": False,
            "TP4": False,
            "TP5": False,
        }
    }

def check_active_targets(item, state):
    tracking_key = target_tracking_key(item["exchange"], item["symbol"])
    tracking = state.get(tracking_key)

    if not tracking:
        return

    entry_price = safe_float(tracking.get("entry_price", 0))
    hit = tracking.get("hit", {})

    if entry_price <= 0:
        return

    if all(hit.get(tp, False) for tp in TARGET_LEVELS.keys()):
        return

    current_price = get_latest_price(item)

    if current_price <= 0:
        return

    changed = False

    for tp_name, pct_gain in TARGET_LEVELS.items():
        target_price = entry_price * (1 + pct_gain)

        if current_price >= target_price and not hit.get(tp_name, False):
            gain_percent = pct_gain * 100
            msg = f"""🎯 <b>تم تحقيق الهدف {tp_name}</b>

<b>Coin:</b> {item['symbol']}/USDT
<b>Exchange:</b> {item['exchange']}
<b>Entry Price:</b> ${entry_price:.8f}
<b>Target Price:</b> ${target_price:.8f}
<b>Current Price:</b> ${current_price:.8f}
<b>Profit:</b> +{gain_percent:.0f}%

✅ تم تحقيق الهدف بنجاح"""
            send_telegram(msg)
            hit[tp_name] = True
            changed = True

    if changed:
        tracking["hit"] = hit
        state[tracking_key] = tracking
        save_state(state)


# =========================
# SCANNER LOOP
# =========================

def scanner_loop():
    send_welcome_message()

    state = load_state()

    while True:
        try:
            pairs = get_all_symbols()
            logging.info(f"Scanning {len(pairs)} pairs...")

            sent = 0
            now = time.time()

            for idx, item in enumerate(pairs, 1):
                key = f"{item['exchange']}:{item['symbol']}"

                try:
                    check_active_targets(item, state)
                except Exception as e:
                    logging.warning(f"Target check failed {item}: {e}")

                last_sent = safe_float(state.get(key, 0))

                if now - last_sent < COOLDOWN_HOURS * 3600:
                    time.sleep(0.08)
                    continue

                try:
                    logging.info(f"[{idx}/{len(pairs)}] {item['exchange']} {item['symbol']}")
                    signal = analyze(item)

                    if signal:
                        send_telegram(format_alert(signal))
                        register_target_tracking(signal, state)
                        state[key] = now
                        save_state(state)
                        sent += 1
                        time.sleep(1)

                except Exception as e:
                    logging.warning(f"Analyze failed {item}: {e}")

                time.sleep(0.08)

            logging.info(f"Scan finished. Alerts sent: {sent}. Sleeping {SCAN_INTERVAL}s")
            time.sleep(SCAN_INTERVAL)

        except Exception as e:
            logging.error(f"Scanner loop error: {e}")
            time.sleep(30)

# =========================
# START
# =========================

if __name__ == "__main__":
    t = threading.Thread(target=scanner_loop, daemon=True)
    t.start()

    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
