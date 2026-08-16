import http.server
import json
import os
import socketserver
import threading
import xml.etree.ElementTree as ET
import pandas as pd
import requests
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import yfinance as yf

# ==========================================
# 0. BACKGROUND DUMMY WEB SERVER FOR RENDER
# ==========================================
def start_render_health_server():
    port = int(os.environ.get("PORT", 10000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.serve_forever()

threading.Thread(target=start_render_health_server, daemon=True).start()

# ==========================================
# 1. TELEGRAM SETTINGS
# ==========================================
TELEGRAM_BOT_TOKEN = "8844653630:AAEG1wzo7qpqsoFLoBL9tmeq_6WEdNx6KoY"
TELEGRAM_CHAT_ID = "8567795259"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# ==========================================
# 2. LIGHTWEIGHT SENTIMENT ANALYZER (VADER)
# ==========================================
sia = SentimentIntensityAnalyzer()
sia.lexicon.update({
    "hawkish": -2.0, "rate hike": -2.5, "inflation rises": -2.0,
    "yields spike": -2.0, "selloff": -2.5, "recession": -2.0,
    "dovish": 2.0, "rate cut": 2.5, "rally": 2.0, "cooling inflation": 2.0,
    "bullish": 2.0, "record high": 2.0, "breakout": 1.5, "safe haven": 2.0
})

# ==========================================
# 3. COLLECT FOREX FACTORY RED FOLDERS
# ==========================================
def get_red_folders():
    urls = [
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    red_folders = []
    seen_events = set()

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                events = response.json()
                for event in events:
                    impact = str(event.get("impact", "")).lower()
                    country = str(event.get("country", "")).upper()
                    title = event.get("title", "")
                    date = event.get("date", "")
                    
                    # Capture High impact or Red Folder USD releases
                    if "high" in impact and country == "USD":
                        key = f"{title}_{date}"
                        if key not in seen_events:
                            seen_events.add(key)
                            red_folders.append({
                                "time": date,
                                "event": title
                            })
        except Exception:
            continue

    return red_folders

def fetch_pct_changes(ticker_dict):
    results = {}
    for label, sym in ticker_dict.items():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="2d")
            if len(hist) >= 2:
                prev_close = hist["Close"].iloc[-2]
                curr_price = hist["Close"].iloc[-1]
                pct_change = ((curr_price - prev_close) / prev_close) * 100
                results[label] = round(pct_change, 2)
        except Exception:
            continue
    return results

def get_filtered_news_sentiment(keywords):
    rss_url = "https://finance.yahoo.com/news/rssindex"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(rss_url, headers=headers, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        headlines = []
        for item in root.findall(".//item"):
            title_node = item.find("title")
            if title_node is not None and title_node.text:
                headlines.append(title_node.text)

        filtered = [h for h in headlines if any(k in h.lower() for k in keywords)]
        if not filtered:
            return 0.0

        scores = [sia.polarity_scores(h)["compound"] for h in filtered]
        return float(sum(scores) / len(scores)) if scores else 0.0
    except Exception:
        return 0.0

# ==========================================
# 4. NQ (NASDAQ) REPORT ENGINE
# ==========================================
def generate_nq_report():
    tickers = {
        "10Y Yield (TNX)": "^TNX",
        "Nasdaq Vol (VXN)": "^VXN",
        "US Dollar (DXY)": "DX-Y.NYB",
        "Nvidia (NVDA)": "NVDA",
        "Apple (AAPL)": "AAPL",
        "Microsoft (MSFT)": "MSFT",
    }
    drivers = fetch_pct_changes(tickers)
    nq_keywords = ["fed", "nasdaq", "tech", "rates", "inflation", "yield", "nvidia", "apple", "ai", "stocks", "semiconductor", "earnings", "treasury", "powell", "cpi", "jobs"]
    news_score = get_filtered_news_sentiment(nq_keywords)
    
    score = news_score * 0.30
    if drivers:
        tnx = drivers.get("10Y Yield (TNX)", 0.0)
        if tnx > 0.5: score -= 0.30
        elif tnx < -0.5: score += 0.30

        vxn = drivers.get("Nasdaq Vol (VXN)", 0.0)
        if vxn > 1.0: score -= 0.20
        elif vxn < -1.0: score += 0.20

        tech_symbols = ["Nvidia (NVDA)", "Apple (AAPL)", "Microsoft (MSFT)"]
        tech_changes = [drivers[s] for s in tech_symbols if s in drivers]
        if tech_changes:
            avg_tech = sum(tech_changes) / len(tech_changes)
            if avg_tech > 0.5: score += 0.20
            elif avg_tech < -0.5: score -= 0.20

    bias_score = max(-1.0, min(1.0, round(score, 2)))
    
    if bias_score >= 0.50: verdict = "🟢 <b>STRONGLY BULLISH</b> (Risk-On)"
    elif bias_score >= 0.15: verdict = "🟢 <b>MILDLY BULLISH</b> (Upside Bias)"
    elif bias_score <= -0.50: verdict = "🔴 <b>STRONGLY BEARISH</b> (Risk-Off)"
    elif bias_score <= -0.15: verdict = "🔴 <b>MILDLY BEARISH</b> (Downside Bias)"
    else: verdict = "⚪ <b>NEUTRAL / CHOP</b> (Mixed Signals)"

    red_folders = get_red_folders()
    events_text = "\n".join([f"• <b>{ev['event']}</b>: <code>{ev['time']}</code>" for ev in red_folders[:5]]) if red_folders else "• <i>No high-impact USD events upcoming</i>"
    drivers_text = "\n".join([f"• {k}: <code>{v:+.2f}%</code>" for k, v in drivers.items()])

    return (
        f"📊 <b>NQ MACRO & BIAS UPDATE</b>\n\n"
        f"🎯 <b>BIAS SCORE:</b> <code>{bias_score:+.2f}</code>\n"
        f"📈 <b>VERDICT:</b> {verdict}\n\n"
        f"🔴 <b>UPCOMING RED FOLDERS:</b>\n{events_text}\n\n"
        f"📉 <b>KEY MARKET DRIVERS:</b>\n{drivers_text}"
    )

# ==========================================
# 5. GC (GOLD) REPORT ENGINE
# ==========================================
def generate_gc_report():
    tickers = {
        "US Dollar (DXY)": "DX-Y.NYB",
        "10Y Yield (TNX)": "^TNX",
        "Silver (SI)": "SI=F",
        "Gold Miners (GDX)": "GDX",
        "Crude Oil (CL)": "CL=F",
        "S&P 500 Vol (VIX)": "^VIX",
    }
    drivers = fetch_pct_changes(tickers)
    gc_keywords = ["gold", "precious metals", "dollar", "dxy", "inflation", "cpi", "fed", "rate cut", "central bank", "yields", "treasury", "geopolitical", "safe-haven", "silver", "war"]
    news_score = get_filtered_news_sentiment(gc_keywords)

    score = news_score * 0.25
    if drivers:
        # DXY inverse correlation (35% weight)
        dxy = drivers.get("US Dollar (DXY)", 0.0)
        if dxy > 0.2: score -= 0.35
        elif dxy < -0.2: score += 0.35

        # 10Y Yield inverse correlation (20% weight)
        tnx = drivers.get("10Y Yield (TNX)", 0.0)
        if tnx > 0.5: score -= 0.20
        elif tnx < -0.5: score += 0.20

        # Silver correlation (10% weight)
        silver = drivers.get("Silver (SI)", 0.0)
        if silver > 0.5: score += 0.10
        elif silver < -0.5: score -= 0.10

        # Safe-Haven Spike / VIX
        vix = drivers.get("S&P 500 Vol (VIX)", 0.0)
        if vix > 3.0: score += 0.10

    bias_score = max(-1.0, min(1.0, round(score, 2)))

    if bias_score >= 0.50: verdict = "🟢 <b>STRONGLY BULLISH</b> (Gold Demand High)"
    elif bias_score >= 0.15: verdict = "🟢 <b>MILDLY BULLISH</b> (Upside Bias)"
    elif bias_score <= -0.50: verdict = "🔴 <b>STRONGLY BEARISH</b> (Heavy Dollar/Yield Headwind)"
    elif bias_score <= -0.15: verdict = "🔴 <b>MILDLY BEARISH</b> (Downside Bias)"
    else: verdict = "⚪ <b>NEUTRAL / RANGEBOUND</b> (Mixed Signals)"

    red_folders = get_red_folders()
    events_text = "\n".join([f"• <b>{ev['event']}</b>: <code>{ev['time']}</code>" for ev in red_folders[:5]]) if red_folders else "• <i>No high-impact USD events upcoming</i>"
    drivers_text = "\n".join([f"• {k}: <code>{v:+.2f}%</code>" for k, v in drivers.items()])

    return (
        f"🪙 <b>GOLD (GC) MACRO & BIAS UPDATE</b>\n\n"
        f"🎯 <b>BIAS SCORE:</b> <code>{bias_score:+.2f}</code>\n"
        f"📊 <b>VERDICT:</b> {verdict}\n\n"
        f"🔴 <b>UPCOMING RED FOLDERS:</b>\n{events_text}\n\n"
        f"📈 <b>KEY GOLD DRIVERS:</b>\n{drivers_text}"
    )

# ==========================================
# 6. TELEGRAM COMMAND HANDLERS
# ==========================================
@bot.message_handler(commands=["start"])
def send_welcome(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("📊 Scan NQ Market"), KeyboardButton("🪙 Scan GC Gold"))
    bot.reply_to(
        message,
        "👋 <b>Trading Bias Assistant Ready!</b>\nChoose an asset below to get a live macro read:",
        parse_mode="HTML",
        reply_markup=markup,
    )

@bot.message_handler(commands=["scan", "nq"])
@bot.message_handler(func=lambda msg: msg.text == "📊 Scan NQ Market")
def handle_nq_scan(message):
    bot.reply_to(message, "⏳ <i>Scanning NQ tech drivers & sentiment...</i>", parse_mode="HTML")
    report = generate_nq_report()
    bot.send_message(message.chat.id, report, parse_mode="HTML")

@bot.message_handler(commands=["gc", "gold"])
@bot.message_handler(func=lambda msg: msg.text == "🪙 Scan GC Gold")
def handle_gc_scan(message):
    bot.reply_to(message, "⏳ <i>Scanning Gold yields, DXY & safe-haven drivers...</i>", parse_mode="HTML")
    report = generate_gc_report()
    bot.send_message(message.chat.id, report, parse_mode="HTML")

if __name__ == "__main__":
    print("🤖 Dual NQ/GC Bot is live and listening...")
    bot.infinity_polling()
