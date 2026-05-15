import os
import time
import threading
import requests
import pandas as pd
from flask import Flask

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("CMC_API_KEY")

INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "60"))
TOP_LIMIT = int(os.getenv("TOP_LIMIT", "1000"))

STOCH_RSI_PERIOD = int(os.getenv("STOCH_RSI_PERIOD", "14"))
STOCH_K_PERIOD = int(os.getenv("STOCH_K_PERIOD", "3"))
STOCH_D_PERIOD = int(os.getenv("STOCH_D_PERIOD", "3"))

STRONG_ALERT_LEVEL = float(os.getenv("STRONG_ALERT_LEVEL", "10"))
RESET_LEVEL = float(os.getenv("RESET_LEVEL", "50"))

MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", "50000000"))
MIN_VOLUME_24H = float(os.getenv("MIN_VOLUME_24H", "5000000"))
MIN_PRICE_CHANGE_24H_ABS = float(os.getenv("MIN_PRICE_CHANGE_24H_ABS", "1"))
MIN_CONFIDENCE_SCORE = float(os.getenv("MIN_CONFIDENCE_SCORE", "90"))

CMC_BASE = "https://pro-api.coinmarketcap.com"

EXCLUDED_SYMBOLS = [
    "JUP", "BNB", "SUI", "TWT",
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDD", "PYUSD",
    "FRAX", "BUSD", "USDP", "GUSD", "LUSD", "RLUSD",
    "OKB", "GT", "BGB", "HT", "LEO", "CRO"
]

EXCLUDED_KEYWORDS = [
    "meme", "memes", "dog", "cat", "pepe", "shib", "inu",
    "gaming", "gamefi", "games", "play-to-earn", "p2e",
    "gambling", "betting", "casino", "lottery",
    "metaverse", "nft", "fan-token",

    "tokenized", "xstock", "xstocks", "etf",
    "gold tokenized", "gold-backed", "silver-backed",
    "synthetic", "wrapped-stock", "wrapped stock",
    "leveraged", "inverse-etf", "commodity-backed",
    "stock token", "tokenized stock", "tokenized etf",

    "wallet", "wallets", "trust wallet", "web3 wallet", "crypto wallet",
    "wallet token",

    "stablecoin", "stablecoins", "usd stablecoin",
    "usd-pegged", "dollar-pegged", "fiat-backed",

    "exchange token", "exchange coin", "cex token",
    "centralized exchange",

    "launchpad", "launchpool",
    "custody", "payment token"
]

NEGATIVE_NEWS_KEYWORDS = [
    "hack", "hacked", "exploit", "exploited",
    "delisting", "delisted",
    "lawsuit", "sec", "investigation",
    "bankruptcy", "fraud", "scam",
    "rug pull", "security breach"
]

EXCHANGES = {
    "Binance": "https://api.binance.com/api/v3/klines",
    "OKX": "https://www.okx.com/api/v5/market/candles",
    "Bybit": "https://api.bybit.com/v5/market/kline",
    "Gate": "https://api.gateio.ws/api/v4/spot/candlesticks",
    "Bitget": "https://api.bitget.com/api/v2/spot/market/candles",
}

alert_state = {}


@app.route("/")
def home():
    return "Stoch RSI Smart Telegram Bot is running"


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram variables")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }

    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print("Telegram error:", e)


def cmc_headers():
    return {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": CMC_API_KEY
    }


def get_top_cryptos():
    url = f"{CMC_BASE}/v1/cryptocurrency/listings/latest"

    params = {
        "start": 1,
        "limit": TOP_LIMIT,
        "convert": "USD",
        "sort": "market_cap"
    }

    r = requests.get(url, headers=cmc_headers(), params=params, timeout=30)
    r.raise_for_status()

    return r.json().get("data", [])


def get_crypto_info(ids):
    if not ids:
        return {}

    url = f"{CMC_BASE}/v2/cryptocurrency/info"

    params = {
        "id": ",".join(map(str, ids))
    }

    r = requests.get(url, headers=cmc_headers(), params=params, timeout=30)
    r.raise_for_status()

    return r.json().get("data", {})


def collect_coin_text(coin, info):
    parts = [
        str(coin.get("name", "")),
        str(coin.get("symbol", "")),
    ]

    parts.extend(coin.get("tags") or [])

    if info:
        parts.append(str(info.get("name", "")))
        parts.append(str(info.get("symbol", "")))
        parts.append(str(info.get("description", "")))
        parts.extend(info.get("tags") or [])

        if info.get("category"):
            parts.append(str(info.get("category")))

    return " ".join(parts).lower()


def is_excluded_coin(coin, info):
    text = collect_coin_text(coin, info)
    return any(word in text for word in EXCLUDED_KEYWORDS)


def has_negative_news_risk(coin, info):
    text = collect_coin_text(coin, info)
    return any(word in text for word in NEGATIVE_NEWS_KEYWORDS)


def is_strong_project(coin):
    quote = coin.get("quote", {}).get("USD", {})

    market_cap = quote.get("market_cap") or 0
    volume_24h = quote.get("volume_24h") or 0

    return market_cap >= MIN_MARKET_CAP and volume_24h >= MIN_VOLUME_24H


def is_dead_coin(coin, closes):
    quote = coin.get("quote", {}).get("USD", {})

    market_cap = quote.get("market_cap") or 0
    volume_24h = quote.get("volume_24h") or 0
    change_24h = abs(quote.get("percent_change_24h") or 0)

    if market_cap < MIN_MARKET_CAP:
        return True

    if volume_24h < MIN_VOLUME_24H:
        return True

    if change_24h < MIN_PRICE_CHANGE_24H_ABS:
        return True

    if len(closes) >= 20:
        recent = closes[-20:]
        price_range = max(recent) - min(recent)
        avg_price = sum(recent) / len(recent)

        if avg_price > 0:
            range_pct = (price_range / avg_price) * 100

            if range_pct < 2:
                return True

    return False


def calculate_stoch_rsi(closes):
    series = pd.Series(closes, dtype="float64")

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / STOCH_RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / STOCH_RSI_PERIOD, adjust=False).mean()

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    lowest_rsi = rsi.rolling(STOCH_RSI_PERIOD).min()
    highest_rsi = rsi.rolling(STOCH_RSI_PERIOD).max()

    stoch_rsi = ((rsi - lowest_rsi) / (highest_rsi - lowest_rsi)) * 100

    k = stoch_rsi.rolling(STOCH_K_PERIOD).mean()
    d = k.rolling(STOCH_D_PERIOD).mean()

    k = k.dropna()
    d = d.dropna()

    if len(k) < 2 or len(d) < 2:
        return None

    return {
        "k": float(k.iloc[-1]),
        "d": float(d.iloc[-1]),
        "prev_k": float(k.iloc[-2]),
        "prev_d": float(d.iloc[-2]),
    }


def bullish_cross(stoch):
    return stoch["prev_k"] <= stoch["prev_d"] and stoch["k"] > stoch["d"]


def fetch_binance(symbol):
    params = {
        "symbol": f"{symbol}USDT",
        "interval": "4h",
        "limit": 120
    }

    r = requests.get(EXCHANGES["Binance"], params=params, timeout=15)

    if r.status_code != 200:
        return None

    return [float(x[4]) for x in r.json()]


def fetch_okx(symbol):
    params = {
        "instId": f"{symbol}-USDT",
        "bar": "4H",
        "limit": 120
    }

    r = requests.get(EXCHANGES["OKX"], params=params, timeout=15)

    if r.status_code != 200:
        return None

    data = r.json().get("data", [])

    if not data:
        return None

    data.reverse()

    return [float(x[4]) for x in data]


def fetch_bybit(symbol):
    params = {
        "category": "spot",
        "symbol": f"{symbol}USDT",
        "interval": "240",
        "limit": 120
    }

    r = requests.get(EXCHANGES["Bybit"], params=params, timeout=15)

    if r.status_code != 200:
        return None

    data = r.json().get("result", {}).get("list", [])

    if not data:
        return None

    data.reverse()

    return [float(x[4]) for x in data]


def fetch_gate(symbol):
    params = {
        "currency_pair": f"{symbol}_USDT",
        "interval": "4h",
        "limit": 120
    }

    r = requests.get(EXCHANGES["Gate"], params=params, timeout=15)

    if r.status_code != 200:
        return None

    data = r.json()

    if not data:
        return None

    return [float(x[2]) for x in data]


def fetch_bitget(symbol):
    params = {
        "symbol": f"{symbol}USDT",
        "granularity": "4H",
        "limit": 120
    }

    r = requests.get(EXCHANGES["Bitget"], params=params, timeout=15)

    if r.status_code != 200:
        return None

    data = r.json().get("data", [])

    if not data:
        return None

    return [float(x[4]) for x in data]


def get_centralized_exchange_data(symbol):
    fetchers = {
        "Binance": fetch_binance,
        "OKX": fetch_okx,
        "Bybit": fetch_bybit,
        "Gate": fetch_gate,
        "Bitget": fetch_bitget,
    }

    for exchange, func in fetchers.items():
        try:
            closes = func(symbol)

            if closes and len(closes) >= 50:
                return exchange, closes

        except Exception as e:
            print(f"{exchange} failed for {symbol}: {e}")

    return None, None


def confidence_score(stoch, coin, is_cross):
    quote = coin.get("quote", {}).get("USD", {})

    market_cap = quote.get("market_cap") or 0
    volume_24h = quote.get("volume_24h") or 0

    score = 50

    if stoch["k"] <= 5:
        score += 25
    elif stoch["k"] <= 10:
        score += 20
    elif stoch["k"] <= 20:
        score += 10

    if stoch["d"] <= 5:
        score += 10
    elif stoch["d"] <= 10:
        score += 5

    if is_cross:
        score += 25

    if volume_24h >= 100_000_000:
        score += 15
    elif volume_24h >= 20_000_000:
        score += 10
    elif volume_24h >= 5_000_000:
        score += 5

    if market_cap >= 1_000_000_000:
        score += 15
    elif market_cap >= 500_000_000:
        score += 10
    elif market_cap >= 50_000_000:
        score += 5

    return min(score, 100)


def can_send_alert(symbol, stoch):
    if symbol not in alert_state:
        alert_state[symbol] = {
            "armed": True
        }

    state = alert_state[symbol]

    if stoch["k"] >= RESET_LEVEL:
        state["armed"] = True
        return False

    if not state["armed"]:
        return False

    state["armed"] = False

    return True


def short_description(info):
    desc = info.get("description", "") if info else ""

    if not desc:
        return "No description available from CoinMarketCap."

    desc = desc.replace("\n", " ").strip()
    words = desc.split()

    return " ".join(words[:25]) + ("..." if len(words) > 25 else "")


def format_alert(coin, info, exchange, stoch, score):
    quote = coin.get("quote", {}).get("USD", {})

    price = quote.get("price") or 0
    market_cap = quote.get("market_cap") or 0
    volume_24h = quote.get("volume_24h") or 0
    change_24h = quote.get("percent_change_24h") or 0

    return f"""
🚨 Strong Oversold Reversal

Coin: {coin.get('name')} ({coin.get('symbol')})
Rank: #{coin.get('cmc_rank')}
Exchange: {exchange}
Timeframe: 4H

Stoch RSI K: {stoch['k']:.2f}
Stoch RSI D: {stoch['d']:.2f}
Bullish Cross: Yes

Confidence Score: {score}/100

Price: ${price:,.6f}
Market Cap: ${market_cap:,.0f}
Volume 24H: ${volume_24h:,.0f}
24H Change: {change_24h:.2f}%

About:
{short_description(info)}

Not financial advice. Technical alert only.
""".strip()


def run_scan():
    print("Starting scan...")

    try:
        coins = get_top_cryptos()
        ids = [coin["id"] for coin in coins]
        info_map = get_crypto_info(ids)

        print(f"Loaded {len(coins)} coins from CMC")

        for coin in coins:
            symbol = coin.get("symbol", "").upper()

            if not symbol:
                continue

            if symbol in EXCLUDED_SYMBOLS:
                print(f"Excluded manual symbol: {symbol}")
                continue

            coin_id = str(coin.get("id"))
            info = info_map.get(coin_id, {})

            if is_excluded_coin(coin, info):
                print(f"Excluded category: {symbol}")
                continue

            if has_negative_news_risk(coin, info):
                print(f"Excluded negative risk: {symbol}")
                continue

            if not is_strong_project(coin):
                print(f"Weak project: {symbol}")
                continue

            exchange, closes = get_centralized_exchange_data(symbol)

            if not exchange:
                continue

            if is_dead_coin(coin, closes):
                print(f"Dead coin filter: {symbol}")
                continue

            stoch = calculate_stoch_rsi(closes)

            if not stoch:
                continue

            is_cross = bullish_cross(stoch)

            if not is_cross:
                continue

            if stoch["k"] > STRONG_ALERT_LEVEL or stoch["d"] > STRONG_ALERT_LEVEL:
                continue

            score = confidence_score(stoch, coin, is_cross)

            if score < MIN_CONFIDENCE_SCORE:
                print(f"Low confidence skipped: {symbol} Score={score}")
                continue

            if not can_send_alert(symbol, stoch):
                continue

            msg = format_alert(coin, info, exchange, stoch, score)
            send_telegram(msg)

            print(
                f"ALERT SENT: {symbol} | "
                f"Exchange={exchange} | "
                f"K={stoch['k']:.2f} | "
                f"D={stoch['d']:.2f} | "
                f"Score={score}"
            )

            time.sleep(0.25)

    except Exception as e:
        print("Scan error:", e)
        send_telegram(f"Bot Error: {e}")


def bot_loop():
    send_telegram("🚀 Stoch RSI Smart Scanner Started - 4H")

    while True:
        run_scan()
        time.sleep(INTERVAL_MINUTES * 60)


threading.Thread(target=bot_loop, daemon=True).start()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))

    app.run(
        host="0.0.0.0",
        port=port
    )
