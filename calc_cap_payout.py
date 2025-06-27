#!/usr/bin/env python3
import requests
import pandas as pd
from io import StringIO
from datetime import datetime
from urllib.parse import quote

# ── CONFIG ─────────────────────────────────────────
NTFY_TOPIC = "cap-payouts"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
CAP_STRIKE = 300.0          # $/MWh
CAP_VOLUME = 1.0            # MW
INTERVAL_HOURS = 5 / 60     # hours per 5-minute interval

# 5-minute pre-dispatch CSV URL template
PD_CSV_URL = (
    "https://neopoint.com.au/Service/Csv"
    "?f=101%20Prices%5CDispatch%20and%20Predispatch%20Prices%205min"
    "&from={from_time}&period=Daily&instances=&section=-1&key=gfi2016"
)

def fetch_pd():
    now = datetime.now()
    from_time_str = now.strftime("%Y-%m-%d %H:%M")
    from_time_encoded = quote(from_time_str)
    url = PD_CSV_URL.format(from_time=from_time_encoded)
    print(f"🔗 Fetching: {url}")
    resp = requests.get(url)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    # Convert first column to datetime
    df.columns = df.columns.str.strip()
    df.rename(columns={df.columns[0]: 'DateTime'}, inplace=True)
    df['DateTime'] = pd.to_datetime(df['DateTime'])
    return df

def compute_payouts(df):
    # Data covers next 12 hours inherently, so compute on full df
    results = {}
    for col in df.columns:
        if col.endswith("Price"):
            region = col.replace(" Price", "")
            # per-interval payout
            payouts = (df[col] - CAP_STRIKE).clip(lower=0) * CAP_VOLUME * INTERVAL_HOURS
            # sum and divide by 60 as requested
            results[region] = payouts.sum() / 60
    return results

def send_ntfy(results):
    lines = ["CAP PAYOUT NEXT 12 HOURS"]
    for region, payout in results.items():
        lines.append(f"• {region}: ${payout:,.2f}")
    msg = "\n".join(lines)
    print(msg)
    requests.post(NTFY_URL, data=msg.encode("utf-8"))

def main():
    df = fetch_pd()
    results = compute_payouts(df)
    send_ntfy(results)

if __name__ == "__main__":
    main()