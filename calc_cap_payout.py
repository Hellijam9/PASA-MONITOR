#!/usr/bin/env python3
import requests
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta

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
    "&from={date}%2000%3A00&period=Daily&instances=&section=-1&key=gfi2016"
)

def fetch_pd(date_str):
    url = PD_CSV_URL.format(date=date_str)
    resp = requests.get(url)
    resp.raise_for_status()
    # Read without parse_dates, then detect first column as datetime
    df = pd.read_csv(StringIO(resp.text))
    # Identify datetime column (first column)
    dt_col = df.columns[0]
    df[dt_col] = pd.to_datetime(df[dt_col])
    df.rename(columns={dt_col: 'DateTime'}, inplace=True)
    df.columns = df.columns.str.strip()
    return df

def compute_next_12h_payouts(df):
    now = datetime.now()
    cutoff = now + timedelta(hours=12)
    df12 = df[(df["DateTime"] >= now) & (df["DateTime"] < cutoff)]
    results = {}
    for col in df12.columns:
        if col.endswith("Price"):
            region = col.replace(" Price", "")
            payouts = (df12[col] - CAP_STRIKE).clip(lower=0) * CAP_VOLUME * INTERVAL_HOURS
            results[region] = payouts.sum()
    return results

def send_ntfy(results):
    lines = ["CAP PAYOUT NEXT 12 HOURS"]
    for region, payout in results.items():
        lines.append(f"• {region}: ${payout:,.2f}")
    msg = "\n".join(lines)
    print(msg)
    requests.post(NTFY_URL, data=msg.encode("utf-8"))

def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    df = fetch_pd(date_str)
    results = compute_next_12h_payouts(df)
    send_ntfy(results)

if __name__ == "__main__":
    main()
