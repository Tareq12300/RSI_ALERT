# -*- coding: utf-8 -*-

import os
import time
import json
import math
import logging
from datetime import datetime, timezone

import requests
import pandas as pd
from flask import Flask, jsonify

BOT_NAME = "بوت أبو علاوي للتنبيهات"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
CMC_API_KEY = os.getenv("CMC_API_KEY", "").strip()

TIMEFRAME = "4h"
THRESHOLD = 0
RSI_LENGTH = 14

STOP_LOSS_PERCENT = 20
TAKE_PROFIT_PERCENT = 40

SCAN_INTERVAL_SECONDS = 900
KLINE_LIMIT = 200

CMC_LIMIT = 1000
CMC_MAX_RANK = 1000
CMC_MIN_MARKET_CAP = 0

ENABLE_LONG = True

PORT = int(os.getenv("PORT", "8080"))
ALERTS_FILE = "sent_alerts.json"

app = Flask(__name__)
SESSION = requests.Session()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s"
)


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(x):
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except:
        return None


def load_sent_alerts():
    if not os.path.exists(ALERTS_FILE):
        return {}

    try:
        with open(ALERTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_sent_alerts(data):
    try:
        if len(data) > 5000:
            data = dict(list(data.items())[-3000:])

        with open(ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram token/chat id missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        r = SESSION.post(url, json=payload, timeout=20)
        return r.status_code == 200
    except Exception as e:
        logging.warning(f"Telegram error: {e}")
        return False


def send_welcome_message():
    msg = (
        f"🚀 *أهلاً بك في بوت أبو علاوي للتنبيهات*\n\n"
        f"✅ البوت يعمل الآن بنجاح\n"
        f"📊 تحليل العملات الرقمية تلقائياً\n"
        f"📈 إشارات شراء فقط عند RSI أقل من 30\n"
        f"🕓 الفريم: `{TIMEFRAME}`\n"
        f"🏦 المنصة: `OKX`\n"
        f"🌐 المصدر الإضافي: `CoinMarketCap`\n\n"
        f"⚡ يتم فحص السوق وإرسال التنبيهات تلقائياً\n"
        f"🔥 بالتوفيق للجميع\n\n"
        f"`{now_utc()}`"
    )

    send_telegram(msg)


def calc_rsi(close, length=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / length,
        min_periods=length,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / length,
        min_periods=length,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))

    return rsi.astype(float)


def get_cmc_symbols_and_data():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY
    }

    params = {
        "start": 1,
        "limit": CMC_LIMIT,
        "convert": "USD",
        "sort": "market_cap"
    }

    out = {}

    try:
        r = SESSION.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()

        data = r.json().get("data", [])

        for item in data:
            symbol = item.get("symbol", "").upper()
            rank = int(item.get("cmc_rank") or 999999)

            quote = item.get("quote", {}).get("USD", {})
            market_cap = float(quote.get("market_cap") or 0)
            volume_24h = float(quote.get("volume_24h") or 0)

            if not symbol:
                continue

            if rank > CMC_MAX_RANK:
                continue

            if market_cap < CMC_MIN_MARKET_CAP:
                continue

            out[symbol] = {
                "market_cap": market_cap,
                "volume_24h": volume_24h,
                "rank": rank
            }

        logging.info(f"CMC symbols loaded: {len(out)}")
        return out

    except Exception as e:
        logging.warning(f"CMC failed: {e}")
        return {}


def get_okx_pairs():
    url = "https://www.okx.com/api/v5/public/instruments"

    params = {
        "instType": "SPOT"
    }

    out = {}

    try:
        r = SESSION.get(url, params=params, timeout=30)
        r.raise_for_status()

        for item in r.json().get("data", []):
            if item.get("quoteCcy") == "USDT" and item.get("state") == "live":
                base = item.get("baseCcy", "").upper()
                inst_id = item.get("instId", "")

                if base and inst_id:
                    out[base] = inst_id

        logging.info(f"OKX pairs loaded: {len(out)}")

    except Exception as e:
        logging.warning(f"OKX pairs failed: {e}")

    return out


def normalize_ohlcv(rows):
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        rows,
        columns=["ts", "open", "high", "low", "close", "volume"]
    )

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
    df = df.dropna(subset=["ts", "open", "high", "low", "close"])
    df = df.sort_values("ts").reset_index(drop=True)

    return df


def fetch_okx_klines(pair, tf="4h", limit=200):
    if tf == "4h":
        bar = "4H"
    else:
        bar = "1D"

    url = "https://www.okx.com/api/v5/market/candles"

    params = {
        "instId": pair,
        "bar": bar,
        "limit": str(limit)
    }

    r = SESSION.get(url, params=params, timeout=20)
    r.raise_for_status()

    raw = r.json().get("data", [])

    rows = []

    for x in raw:
        rows.append([
            x[0],
            x[1],
            x[2],
            x[3],
            x[4],
            x[5]
        ])

    return normalize_ohlcv(rows)


def fetch_daily_diff(pair):
    try:
        df = fetch_okx_klines(pair, "1d", 5)

        if len(df) < 2:
            return None

        today = safe_float(df.iloc[-1]["close"])
        yesterday = safe_float(df.iloc[-2]["close"])

        if today is None or yesterday is None:
            return None

        if yesterday == 0:
            return None

        return (today - yesterday) / yesterday

    except:
        return None


def analyze_symbol(symbol, pair, cmc_info):
    try:
        df = fetch_okx_klines(pair, TIMEFRAME, KLINE_LIMIT)

        if df.empty or len(df) < RSI_LENGTH + 5:
            return None

        df["rsi"] = calc_rsi(df["close"], RSI_LENGTH)

        price = safe_float(df.iloc[-1]["close"])
        rsi = safe_float(df.iloc[-1]["rsi"])
        candle_ts = int(df.iloc[-1]["ts"])

        if price is None or rsi is None:
            return None

        close_diff = fetch_daily_diff(pair)

        if close_diff is None:
            return None

        buying = close_diff > THRESHOLD

        long_condition = (
            ENABLE_LONG and
            buying and
            rsi < 30
        )

        if not long_condition:
            return None

        stop = price * (1 - STOP_LOSS_PERCENT / 100)
        take = price * (1 + TAKE_PROFIT_PERCENT / 100)

        return {
            "symbol": symbol,
            "price": price,
            "rsi": rsi,
            "close_diff": close_diff,
            "stop": stop,
            "take": take,
            "market_cap": cmc_info.get("market_cap", 0),
            "volume_24h": cmc_info.get("volume_24h", 0),
            "rank": cmc_info.get("rank", "-"),
            "candle_ts": candle_ts
        }

    except Exception as e:
        logging.warning(f"{symbol} failed: {e}")
        return None


def format_money(value):
    try:
        value = float(value)

        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:,.2f}B"

        if value >= 1_000_000:
            return f"${value / 1_000_000:,.2f}M"

        if value >= 1_000:
            return f"${value / 1_000:,.2f}K"

        return f"${value:,.2f}"

    except:
        return "$0"


def format_signal_message(sig):
    diff_pct = sig["close_diff"] * 100

    return (
        f"🟢 *إشارة شراء قوية*\n\n"
        f"💎 *العملة:* `{sig['symbol']}USDT`\n"
        f"🏦 *المنصة:* `OKX`\n"
        f"🕓 *الفريم:* `4H`\n"
        f"🏅 *CMC Rank:* `{sig['rank']}`\n\n"
        f"💰 *السعر الحالي:* `{sig['price']:.8f}`\n"
        f"📈 *RSI:* `{sig['rsi']:.2f}`\n"
        f"📊 *فرق الإغلاق اليومي:* `{diff_pct:.2f}%`\n\n"
        f"🏛 *Market Cap:* `{format_money(sig['market_cap'])}`\n"
        f"📦 *24H Volume:* `{format_money(sig['volume_24h'])}`\n\n"
        f"🛑 *وقف الخسارة:* `{sig['stop']:.8f}`\n"
        f"🎯 *جني الأرباح:* `{sig['take']:.8f}`\n\n"
        f"🚀 *تم اكتشاف فرصة شراء مطابقة للشروط*\n\n"
        f"`{now_utc()}`"
    )


def scan_once():
    sent_alerts = load_sent_alerts()

    cmc_data = get_cmc_symbols_and_data()

    if not cmc_data:
        logging.warning("No CMC data loaded")
        return

    okx_pairs = get_okx_pairs()

    final_pairs = {}

    for symbol in cmc_data.keys():
        if symbol in okx_pairs:
            final_pairs[symbol] = okx_pairs[symbol]

    logging.info(f"Final OKX watchlist: {len(final_pairs)}")

    total = len(final_pairs)

    for index, (symbol, pair) in enumerate(final_pairs.items(), start=1):
        logging.info(f"[{index}/{total}] تحليل {symbol}")

        sig = analyze_symbol(
            symbol=symbol,
            pair=pair,
            cmc_info=cmc_data.get(symbol, {})
        )

        if not sig:
            continue

        current_candle = int(sig["candle_ts"] / (4 * 60 * 60 * 1000))

        alert_key = f"{symbol}_OKX_4H_LONG_{current_candle}"

        if alert_key in sent_alerts:
            continue

        msg = format_signal_message(sig)

        ok = send_telegram(msg)

        if ok:
            sent_alerts[alert_key] = now_utc()
            save_sent_alerts(sent_alerts)
            logging.info(f"Signal sent: {symbol}")

        time.sleep(0.25)


@app.route("/")
def home():
    return jsonify({
        "ok": True,
        "bot": BOT_NAME,
        "time": now_utc()
    })


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "time": now_utc()
    })


def main():
    logging.info(f"{BOT_NAME} Started")

    send_welcome_message()

    while True:
        try:
            scan_once()
            logging.info(f"Sleeping {SCAN_INTERVAL_SECONDS}s")
            time.sleep(SCAN_INTERVAL_SECONDS)

        except Exception as e:
            logging.exception(e)
            send_telegram(f"⚠️ *Bot Error*\n`{str(e)[:500]}`")
            time.sleep(60)


if __name__ == "__main__":
    import threading

    threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=PORT,
            debug=False,
            use_reloader=False
        ),
        daemon=True
    ).start()

    main()
