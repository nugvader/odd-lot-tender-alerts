import requests
import re
import datetime
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
import os

# --- CONFIG ---
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM")

# --- HELPER: Send email ---
def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = ALERT_EMAIL_FROM
    msg["To"] = ALERT_EMAIL_TO

    response = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}",
                 "Content-Type": "application/json"},
        json={
            "personalizations": [{"to": [{"email": ALERT_EMAIL_TO}]}],
            "from": {"email": ALERT_EMAIL_FROM},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        },
    )
    if response.status_code >= 400:
        print("Email failed:", response.text)

# --- HELPER: get filings ---
def get_tender_filings():
    url = "https://efts.sec.gov/LATEST/search-index"
    query = {
        "q": "formType:(SC%20TO-I%20OR%20SC%20TO-T%20OR%2013E-3)",
        "category": "custom",
        "from": 0,
        "size": 40,
        "sort": [{"filedAt": {"order": "desc"}}],
    }
    r = requests.post(url, json=query)
    r.raise_for_status()
    return r.json()["hits"]["hits"]

# --- HELPER: extract details ---
def parse_offer(text):
    m_range = re.search(r"\$?(\d+(?:\.\d+)?)\s*[-–]\s*\$?(\d+(?:\.\d+)?)", text)
    m_oddlot = re.search(r"fewer\s+than\s+100\s+shares|odd\s+lot", text, re.I)
    return (float(m_range.group(1)), float(m_range.group(2)), bool(m_oddlot)) if m_range else None

# --- MAIN ---
def main():
    today = datetime.date.today()
    results = get_tender_filings()

    qualifying = []
    for f in results:
        cik = f["_source"]["cik"]
        title = f["_source"]["displayNames"][0]
        link = f"https://www.sec.gov/Archives/{f['_id']}.txt"

        txt = requests.get(link).text
        parsed = parse_offer(txt)
        if not parsed:
            continue
        low, high, has_oddlot = parsed
        if not has_oddlot:
            continue

        # Try to find a ticker
        ticker_match = re.search(r"(?i)trading symbol[s]?:?\s*([A-Z\.]{1,5})", txt)
        if not ticker_match:
            continue
        ticker = ticker_match.group(1).upper()

        try:
            price = yf.Ticker(ticker).history(period="1d")["Close"].iloc[-1]
        except Exception:
            continue

        if price <= low:
            qualifying.append((ticker, price, low, title, link))

    if qualifying:
        body = "\n\n".join(
            [f"{t} @ ${p:.2f} ≤ ${l:.2f}\n{n}\n{url}" for t, p, l, n, url in qualifying]
        )
        send_email("Odd Lot Tender Alert", body)
    else:
        print("No qualifying offers today.")

if __name__ == "__main__":
    main()


