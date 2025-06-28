#!/usr/bin/env python3
import requests
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta
from urllib.parse import quote

# Create_Cap_payout_yesterday.py
# Fetches full 24h of Neopoint Region Cap payout data for yesterday
# and posts a consolidated ntfy message to topic "Cap_yesterday".

# ── CONFIG ─────────────────────────────────────────
NTFY_TOPIC     = "Cap_yesterday"
NTFY_URL       = "https://ntfy.sh/{cap_yesterday}"
INTERVAL_HOURS = 5/60  # hours per 5-minute interval

# List of region instances
REGION_INSTANCES = ["NSW1", "QLD1", "SA1", "VIC1"]

# URL template for Region Cap payout (5-min intervals)
URL_TEMPLATE = (
    "https://www.neopoint.com.au/Service/Csv"
    "?f=101%20Prices%5CRegion%20Cap%20payout%205min"
    "&from={from_time}&period=Daily&instances={instance}"
    "&section=-1&key=gfi2016"
)

def fetch_region_data(instance, from_ts):
    """
    Fetch CSV for a given region instance from a specified timestamp.
    Returns a DataFrame with DateTime and payout columns.
    """
    url = URL_TEMPLATE.format(from_time=quote(from_ts), instance=instance)
    print(f"🔗 Fetching {instance}: {url}")
    resp = requests.get(url)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    # Clean and parse DateTime column
    df.columns = df.columns.str.strip()
    df.rename(columns={df.columns[0]: "DateTime"}, inplace=True)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    return df


def compute_region_payout(df):
    """
    Applies INTERVAL_HOURS multiplication to each payout value, then sums.
    Assumes each non-DateTime column is the payout for that 5-min interval.
    """
    total = 0.0
    for col in df.columns:
        if col != "DateTime":
            # multiply each interval's payout by hours per interval, then sum
            interval_series = df[col] * INTERVAL_HOURS
            total += interval_series.sum()
    return total


def main():
    # Build timestamp for yesterday at 00:00
    yesterday_ts = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 00:00")
    results = {}

    for instance in REGION_INSTANCES:
        df = fetch_region_data(instance, yesterday_ts)
        region_label = ''.join(filter(str.isalpha, instance))
        payout = compute_region_payout(df)
        results[region_label] = payout

    # Build and send ntfy message
    lines = ["CAP PAYOUT YESTERDAY"]
    for region, value in results.items():
        lines.append(f"• {region}: ${value:,.2f}")
    message = "\n".join(lines)
    print(message)
    requests.post(NTFY_URL, data=message.encode("utf-8"))


if __name__ == "__main__":
    main()
