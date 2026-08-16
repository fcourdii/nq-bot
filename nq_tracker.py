import json
import xml.etree.ElementTree as ET
import pandas as pd
import requests
import yfinance as yf
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

# ==========================================
# 0. TELEGRAM SETTINGS
# ==========================================
# Paste your credentials here:
TELEGRAM_BOT_TOKEN = "8844653630:AAEG1wzo7qpqsoFLoBL9tmeq_6WEdNx6KoY"
TELEGRAM_CHAT_ID = "8567795259"

def send_telegram_alert(message_html):
    """Sends a push notification directly to your Telegram chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_html,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("📱 Telegram push alert sent successfully!")
        else:
            print(f"⚠️ Telegram send error: {res.text}")
    except Exception as e:
        print(f"⚠️ Could not send Telegram alert: {e}")

# ==========================================
# 1. SETUP FINBERT SENTIMENT AI MODEL
# ==========================================
print("Initializing FinBERT Sentiment Model...")
model_name = "ProsusAI/finbert"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name)
nlp_sentiment = pipeline("sentiment-analysis", model=model, tokenizer=tokenizer)

# ==========================================
# 2. COLLECT FOREX FACTORY RED FOLDERS
# ==========================================
def get_red_folders():
    """Fetches high-impact economic calendar events targeting USD."""
    urls = [
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    red_folders = []

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                events = response.json()
                for event in events:
                    if event.get("impact") == "High" and event.get("country") == "USD":
                        red_folders.append({
                            "time": event.get("date"),
                            "event": event.get("title")
                        })
                if red_folders:
                    break
        except Exception:
            continue

    return red_folders

# ==========================================
# 3. INTERMARKET & TECH DRIVERS
# ==========================================
def get_market_drivers():
    """Tracks 10Y Yields, Nasdaq Volatility, USD, and Key Tech Giants."""
    tickers = {
        "10Y Yield (TNX)": "^TNX",
        "Nasdaq Vol (VXN)": "^VXN",
        "US Dollar (DXY)": "DX-Y.NYB",
        "Nvidia (NVDA)": "NVDA",
        "Apple (AAPL)": "AAPL",
        "Microsoft (MSFT)": "MSFT"
    }

    results = {}
    for label, sym in tickers.items():
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

# ==========================================
# 4. BACKGROUND NEWS SENTIMENT SCORE
# ==========================================
def get_news_sentiment_score():
    """Calculates news sentiment score quietly without printing headlines."""
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

        nq_keywords = [
            "fed", "nasdaq", "tech", "rates", "inflation",
            "yield", "nvidia", "apple", "ai", "stocks", "semiconductor",
            "earnings", "treasury", "powell", "cpi", "jobs"
        ]
        
        filtered_headlines = [
            h for h in headlines
            if any(key in h.lower() for key in nq_keywords)
        ]

        if not filtered_headlines:
            return 0.0

        results = nlp_sentiment(filtered_headlines)
        sentiments = [r["label"] for r in results]
        mapped = [1 if s == "positive" else (-1 if s == "negative" else 0) for s in sentiments]
        
        return float(sum(mapped) / len(mapped)) if mapped else 0.0

    except Exception:
        return 0.0

# ==========================================
# 5. CALCULATE COMPOSITE BIAS SCORE
# ==========================================
def calculate_composite_bias(news_index, drivers):
    """Combines News (30%), 10Y Yields (30%), Volatility (20%), and Tech (20%)."""
    score = news_index * 0.30

    if drivers:
        # 10Y Yield: Spikes = Bearish for NQ (-0.30)
        tnx = drivers.get("10Y Yield (TNX)", 0.0)
        if tnx > 0.5:
            score -= 0.30
        elif tnx < -0.5:
            score += 0.30

        # Nasdaq Volatility (VXN): Spikes = Bearish for NQ (-0.20)
        vxn = drivers.get("Nasdaq Vol (VXN)", 0.0)
        if vxn > 1.0:
            score -= 0.20
        elif vxn < -1.0:
            score += 0.20

        # Tech Avg: Green = Bullish for NQ (+0.20)
        tech_symbols = ["Nvidia (NVDA)", "Apple (AAPL)", "Microsoft (MSFT)"]
        tech_changes = [drivers[s] for s in tech_symbols if s in drivers]
        if tech_changes:
            avg_tech = sum(tech_changes) / len(tech_changes)
            if avg_tech > 0.5:
                score += 0.20
            elif avg_tech < -0.5:
                score -= 0.20

    return max(-1.0, min(1.0, round(score, 2)))

# ==========================================
# 6. RUN AND DISPATCH ALERT
# ==========================================
if __name__ == "__main__":
    print("\nScanning market data...")

    # 1. Fetch Red Folders
    red_folders = get_red_folders()
    if red_folders:
        events_text = "\n".join([f"• <b>{ev['event']}</b>: <code>{ev['time']}</code>" for ev in red_folders[:5]])
    else:
        events_text = "• <i>No high-impact USD events upcoming</i>"

    # 2. Fetch Drivers & Sentiment
    drivers = get_market_drivers()
    news_score = get_news_sentiment_score()
    bias_score = calculate_composite_bias(news_score, drivers)

    # 3. Determine Verdict Label
    if bias_score >= 0.50:
        verdict = "🟢 <b>STRONGLY BULLISH</b> (Risk-On)"
    elif bias_score >= 0.15:
        verdict = "🟢 <b>MILDLY BULLISH</b> (Upside Bias)"
    elif bias_score <= -0.50:
        verdict = "🔴 <b>STRONGLY BEARISH</b> (Risk-Off)"
    elif bias_score <= -0.15:
        verdict = "🔴 <b>MILDLY BEARISH</b> (Downside Bias)"
    else:
        verdict = "⚪ <b>NEUTRAL / CHOP</b> (Mixed Signals)"

    # Format Drivers
    drivers_text = "\n".join([f"• {k}: <code>{v:+.2f}%</code>" for k, v in drivers.items()])

    # 4. Build Telegram Message
    message = (
        f"🚨 <b>NQ MACRO & BIAS UPDATE</b>\n\n"
        f"🎯 <b>BIAS SCORE:</b> <code>{bias_score:+.2f}</code>\n"
        f"📊 <b>VERDICT:</b> {verdict}\n\n"
        f"🔴 <b>UPCOMING RED FOLDERS:</b>\n{events_text}\n\n"
        f"📈 <b>KEY MARKET DRIVERS:</b>\n{drivers_text}"
    )

    # 5. Send to Phone
    send_telegram_alert(message)