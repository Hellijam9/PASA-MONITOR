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
            df = pd.read_csv(f, skiprows=2, header=None)
            df.columns = list(range(df.shape[1]))  # Just label as 0,1,2,...
            df = df.rename(columns={
                4: "OUTAGEID",
                6: "SUBSTATIONID",
                7: "EQUIPMENTTYPE",
                8: "EQUIPMENTID",
                9: "STARTTIME",
                10: "ENDTIME"
            })
            df = df[["OUTAGEID", "SUBSTATIONID", "EQUIPMENTTYPE", "EQUIPMENTID", "STARTTIME", "ENDTIME"]]
            df["OUTAGEID"] = df["OUTAGEID"].astype(str).str.strip()
            return df

def load_neo_mapping():
    today = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%Y-%m-%d")
    mapping = {}  # outage_id → {state, owner, substation_desc, equipment_desc, set_desc}

    for state_code, url_template in NEO_CSV_LINKS.items():
        url = url_template.format(today=today)
        try:
            df = pd.read_csv(url, skiprows=1, header=None)
            for _, row in df.iterrows():
                outage_id = str(row[2]).strip()
                mapping[outage_id] = {
                    "state": row[3] if pd.notna(row[3]) else state_code,
                    "owner": row[4],
                    "substation_desc": row[6],
                    "equipment_desc": row[9],
                    "set_desc": row[11]
                }
        except Exception as e:
            print(f"⚠️ Failed loading NeoPoint CSV for {state_code}: {e}")

    return mapping

def compare_outages(df_old, df_new):
    mapping = load_neo_mapping()
    old_ids = set(df_old["OUTAGEID"])
    new_ids = set(df_new["OUTAGEID"])

    added = df_new[df_new["OUTAGEID"].isin(new_ids - old_ids)]
    removed = df_old[df_old["OUTAGEID"].isin(old_ids - new_ids)]

    def parse_dt(val):
        try:
            return pd.to_datetime(str(val).replace("COMP", "").strip(), errors="coerce")
        except:
            return pd.NaT

    lines = []

    if added.empty and removed.empty:
        lines.append("No new or cleared network outages detected.")
    else:
        if not added.empty:
            lines.append(f"🟥 {len(added)} new outages:")
            for _, row in added.iterrows():
                outage_id = row["OUTAGEID"]
                info = mapping.get(outage_id, {})
                start = parse_dt(row["STARTTIME"])
                end = parse_dt(row["ENDTIME"])
                if pd.isna(start) or pd.isna(end):
                    continue
                duration = (end - start).days + 1
                qtr = (start.month - 1) // 3 + 1
                lines.append(
                    f"  {info.get('state','?')} | {info.get('owner','?')} | {info.get('substation_desc','?')} | "
                    f"{info.get('equipment_desc','?')} | {info.get('set_desc','?')} | {start.date()} to {end.date()} "
                    f"({duration} days, Q{qtr} {start.year})"
                )

        if not removed.empty:
            lines.append(f"\n🟩 {len(removed)} cleared outages:")
            for _, row in removed.iterrows():
                outage_id = row["OUTAGEID"]
                info = mapping.get(outage_id, {})
                start = parse_dt(row["STARTTIME"])
                end = parse_dt(row["ENDTIME"])
                if pd.isna(start) or pd.isna(end):
                    continue
                duration = (end - start).days + 1
                qtr = (start.month - 1) // 3 + 1
                lines.append(
                    f"  {info.get('state','?')} | {info.get('owner','?')} | {info.get('substation_desc','?')} | "
                    f"{info.get('equipment_desc','?')} | {info.get('set_desc','?')} | {start.date()} to {end.date()} "
                    f"({duration} days, Q{qtr} {start.year})"
                )

    final = "\n".join(lines)
    print("\n" + final)
    if "🟥" in final or "🟩" in final:
        requests.post(NTFY_URL, data=final.encode("utf-8"))

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
