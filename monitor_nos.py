#!/usr/bin/env python3
import requests
import zipfile
import pandas as pd
import re
from io import BytesIO
from datetime import datetime
import pytz
import sys

BASE_URL = "https://www.nemweb.com.au/Reports/CURRENT/Network/"
NTFY_URL = "https://ntfy.sh/outage-alerts"

NEO_CSV_LINKS = {
    "NSW1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Daily&instances=NSW1&section=-1&key=gfi2016",
    "QLD1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Daily&instances=QLD1&section=-1&key=gfi2016",
    "VIC1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Daily&instances=VIC1&section=-1&key=gfi2016",
    "SA1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Daily&instances=SA1&section=-1&key=gfi2016"
}

def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = sorted(set(re.findall(r'PUBLIC_NETWORK_\d{14}_\d+\.zip', r.text)))
    if len(matches) < 2:
        raise ValueError("❌ Not enough NOS ZIP files found.")

    def extract_dt(filename):
        match = re.search(r'PUBLIC_NETWORK_(\d{14})_', filename)
        if match:
            return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        return datetime.min

    files_with_times = [(extract_dt(f), f) for f in matches]
    files_with_times.sort(reverse=True)

    print("📂 Top 5 files sorted by timestamp:")
    for ts, f in files_with_times[:5]:
        print(f"  {ts}  →  {f}")

    return BASE_URL + files_with_times[1][1], BASE_URL + files_with_times[0][1]

def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        file_name = z.namelist()[0]
        print(f"✅ Extracting: {file_name}")
        with z.open(file_name) as f:
            df = pd.read_csv(f, header=None, skiprows=2)
            df.columns = list(range(df.shape[1]))
            df[4] = df[4].astype(str).str.strip().str.lstrip("0")
            print(f"🔎 Sample outage IDs from {file_name}: {df[4].dropna().unique()[:5]}")
            return df

def load_neo_mapping():
    today = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%Y-%m-%d")
    mapping = {}

    for state_code, url_template in NEO_CSV_LINKS.items():
        url = url_template.format(today=today)
        try:
            df = pd.read_csv(url, skiprows=1, header=None)

            for _, row in df.iterrows():
                if pd.isna(row[2]):
                    continue

                outage_id = str(row[2]).strip().lstrip("0")
                if outage_id == "":
                    continue

                mapping[outage_id] = {
                    "state": str(row[3]).strip() if pd.notna(row[3]) else state_code,
                    "owner": str(row[4]).strip() if pd.notna(row[4]) else "?",
                    "substation_desc": str(row[6]).strip() if pd.notna(row[6]) else "?",
                    "equipment_desc": str(row[9]).strip() if pd.notna(row[9]) else "?",
                    "set_desc": str(row[11]).strip() if pd.notna(row[11]) else "?"
                }

        except Exception as e:
            print(f"⚠️ Failed loading NeoPoint CSV for {state_code}: {e}")

    print(f"📦 NeoPoint mapping loaded with {len(mapping)} outage IDs")
    return mapping


def parse_dt(val):
    try:
        return pd.to_datetime(str(val).replace("COMP", "").strip(), errors="coerce")
    except:
        return pd.NaT

def compare_outages(df_old, df_new):
    outage_col = 4
    df_old[outage_col] = df_old[outage_col].astype(str).str.strip().str.lstrip("0")
    df_new[outage_col] = df_new[outage_col].astype(str).str.strip().str.lstrip("0")

    old_ids = set(df_old[outage_col])
    new_ids = set(df_new[outage_col])

    print(f"🔁 Comparing {len(old_ids)} old IDs vs {len(new_ids)} new IDs")

    added_ids = new_ids - old_ids
    removed_ids = old_ids - new_ids

    if not added_ids and not removed_ids:
        print("No new or cleared network outages detected.")
        return

    print(f"🟥 New: {len(added_ids)}")
    print(f"🟩 Cleared: {len(removed_ids)}")

    mapping = load_neo_mapping()
    lines = []

    if added_ids:
        lines.append(f"🟥 {len(added_ids)} new outages:")
        for outage_id in added_ids:
            row = df_new[df_new[outage_col] == outage_id]
            if row.empty:
                continue
            row = row.iloc[0]
            start = parse_dt(row[9])
            end = parse_dt(row[10])
            duration = (end - start).days + 1 if pd.notna(start) and pd.notna(end) else "?"
            qtr = (start.month - 1) // 3 + 1 if pd.notna(start) else "?"
            info = mapping.get(outage_id, {})
            lines.append(
                f"  {info.get('state', '?')} | {info.get('owner', '?')} | {info.get('substation_desc', '?')} | "
                f"{info.get('equipment_desc', '?')} | {info.get('set_desc', '?')} | "
                f"{start.date() if pd.notna(start) else '?'} to {end.date() if pd.notna(end) else '?'} "
                f"({duration} days, Q{qtr} {start.year if pd.notna(start) else '?'})"
            )

    if removed_ids:
        lines.append(f"\n🟩 {len(removed_ids)} cleared outages:")
        for outage_id in removed_ids:
            row = df_old[df_old[outage_col] == outage_id]
            if row.empty:
                continue
            row = row.iloc[0]
            start = parse_dt(row[9])
            end = parse_dt(row[10])
            duration = (end - start).days + 1 if pd.notna(start) and pd.notna(end) else "?"
            qtr = (start.month - 1) // 3 + 1 if pd.notna(start) else "?"
            info = mapping.get(outage_id, {})
            lines.append(
                f"  {info.get('state', '?')} | {info.get('owner', '?')} | {info.get('substation_desc', '?')} | "
                f"{info.get('equipment_desc', '?')} | {info.get('set_desc', '?')} | "
                f"{start.date() if pd.notna(start) else '?'} to {end.date() if pd.notna(end) else '?'} "
                f"({duration} days, Q{qtr} {start.year if pd.notna(start) else '?'})"
            )

    message = "\n".join(lines)
    print("\n" + message)
    requests.post(NTFY_URL, data=message.encode("utf-8"))

def run_scheduler(test_mode=False):
    if test_mode:
        print("🧪 Running in TEST mode – simulating now.")
    else:
        tz = pytz.timezone("Australia/Sydney")
        now = datetime.now(tz)
        print(f"🕒 Current AEST Time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        url_old, url_new = fetch_latest_two_urls()
        df_old = extract_csv(url_old)
        df_new = extract_csv(url_new)
        compare_outages(df_old, df_new)
    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    run_scheduler(test_mode=test_mode)
