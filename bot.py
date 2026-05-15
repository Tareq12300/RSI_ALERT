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
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_MAX = float(os.getenv("RSI_MAX", "20"))
TOP_LIMIT = int(os.getenv("TOP_LIMIT", "1000"))

CMC_BASE = "https://pro-api.coinmarketcap.com"

EXCLUDED_KEYWORDS = [
    "meme", "memes", "dog", "cat",
    "gaming", "gamefi", "games", "play-to-earn", "p2e",
    "gambling", "betting", "casino", "lottery",
    "metaverse", "nft", "fan-token",

    "tokenized", "xstock", "xstocks", "etf",
    "gold tokenized", "gold-backed", "silver-backed",
    "synthetic", "wrapped-stock", "wrapped stock",
    "leveraged", "inverse-etf", "commodity-backed",
    "stock token", "tokenized stock", "tokenized etf"
]

EXCHANGES = {
    "Binance": "https://api.binance.com/api/v3/klines",
    "OKX": "https://www.okx.com/api/v5/market/candles",
    "Bybit": "https://api.bybit.com/v5/market/kline",
    "Gate": "https://api.gateio.ws/api/v4/spot/candlesticks",
    "Bitget": "https://api.bitget.com/api/v2/spot/market/candles",
}

sent_alerts = set()


@app.route("/")
def home():
    return "RSI Oversold CMC Telegram Bot is running"


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
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
    params = {"id": ",".join(map(str, ids))}

    r = requests.get(url, headers=cmc_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("data", {})


def is_excluded_coin(coin, info):
    text_parts = []

    text_parts.append(str(coin.get("name", "")))
    text_parts.append(str(coin.get("symbol", "")))

    tags = coin.get("tags") or []
    text_parts.extend(tags)

    if info:
        text_parts.append(str(info.get("name", "")))
        text_parts.append(str(info.get("symbol", "")))
        text_parts.append(str(info.get("description", "")))
        text_parts.extend(info.get("tags") or [])

        category = info.get("category")
        if category:
            text_parts.append(str(category))

    text = " ".join(text_parts).lower()

    return any(word in text for word in EXCLUDED_KEYWORDS)


def calculate_rsi(closes, period=14):
    series = pd.Series(closes, dtype="float64")

    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return float(rsi.iloc[-1])


def fetch_binance(symbol):
    params = {
        "symbol": f"{symbol}USDT",
        "interval": "4h",
        "limit": 120
    }
    r = requests.get(EXCHANGES["Binance"], params=params, timeout=15)
    if r.status_code != 200:
        return None
    data = r.json()
    return [float(x[4]) for x in data]


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
            if closes and len(closes) >= RSI_PERIOD + 5:
                return exchange, closes
        except Exception:
            continue

    return None, None


def short_description(info):
    desc = info.get("description", "") if info else ""
    if not desc:
        return "لا يوجد وصف متاح من CoinMarketCap."

    desc = desc.replace("\n", " ").strip()
    words = desc.split()

    return " ".join(words[:28]) + ("..." if len(words) > 28 else "")


def format_alert(coin, info, exchange, rsi):
    name = coin.get("name", "-")
    symbol = coin.get("symbol", "-")
    rank = coin.get("cmc_rank", "-")

    quote = coin.get("quote", {}).get("USD", {})
    price = quote.get("price", 0)
    market_cap = quote.get("market_cap", 0)
    volume_24h = quote.get("volume_24h", 0)

    desc = short_description(info)

    return f"""
🚨 تشبع بيعي قوي

العملة: {name} ({symbol})
الترتيب: #{rank}
المنصة المركزية: {exchange}
RSI 4H: {rsi:.2f}

السعر: ${price:,.6f}
Market Cap: ${market_cap:,.0f}
Volume 24H: ${volume_24h:,.0f}

تعريف مختصر:
{desc}

ليست توصية شراء، فقط تنبيه فني لوجود RSI أقل من {RSI_MAX}.
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
            coin_id = str(coin.get("id"))
            info = info_map.get(coin_id, {})

            if not symbol:
                continue

            if is_excluded_coin(coin, info):
                print(f"Excluded: {symbol}")
                continue

            exchange, closes = get_centralized_exchange_data(symbol)

            if not exchange:
                continue

            rsi = calculate_rsi(closes, RSI_PERIOD)

            if rsi < RSI_MAX:
                alert_key = f"{symbol}-{exchange}"

                if alert_key not in sent_alerts:
                    msg = format_alert(coin, info, exchange, rsi)
                    send_telegram(msg)
                    sent_alerts.add(alert_key)
                    print(f"Alert sent: {symbol} RSI={rsi:.2f} Exchange={exchange}")

            time.sleep(0.25)

    except Exception as e:
        print("Scan error:", e)
        send_telegram(f"خطأ في البوت: {e}")


def bot_loop():
    send_telegram("بوت RSI أقل من 20 بدأ العمل.")
    while True:
        run_scan()
        time.sleep(INTERVAL_MINUTES * 60)


threading.Thread(target=bot_loop, daemon=True).start()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
