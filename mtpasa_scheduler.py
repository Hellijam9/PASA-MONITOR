# This script adds detection of moved outages in MTPASA DUID availability
# and keeps existing logic for new and cleared outages untouched

import requests
import zipfile
import pandas as pd
import re
from io import BytesIO
from datetime import datetime, timedelta
import pytz
import sys

BASE_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"
NTFY_URL = "https://ntfy.sh/pasa-alerts"


def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = set(re.findall(r'PUBLIC_MTPASADUIDAVAILABILITY_\d{12}_\d+\.zip', r.text))
    if len(matches) < 2:
        raise ValueError("❌ Not enough unique MTPASA ZIP files found.")

    def extract_dt(filename):
        match = re.search(r'_(\d{12})_', filename)
        return datetime.strptime(match.group(1), "%Y%m%d%H%M") if match else datetime.min

    sorted_files = sorted(matches, key=extract_dt, reverse=True)
    return BASE_URL + sorted_files[1], BASE_URL + sorted_files[0]


def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        file_name = z.namelist()[0]
        print(f"✅ Extracting: {file_name}")
        with z.open(file_name) as f:
            df = pd.read_csv(f, skiprows=1, low_memory=False)
            return df


def detect_moved_outages(df_old, df_new):
    cols = ["DUID", "DAY", "PASAAVAILABILITY"]
    df_old = df_old[cols].copy()
    df_new = df_new[cols].copy()
    df_old["DAY"] = pd.to_datetime(df_old["DAY"])
    df_new["DAY"] = pd.to_datetime(df_new["DAY"])

    def build_outage_map(df):
        outages = {}
        for duid, group in df.groupby("DUID"):
            group = group.sort_values("DAY")
            periods = []
            in_outage = False
            for _, row in group.iterrows():
                avail = row["PASAAVAILABILITY"]
                if avail == 0 and not in_outage:
                    start = row["DAY"]
                    in_outage = True
                    mw = avail
                elif avail == 0 and in_outage:
                    continue
                elif avail > 0 and in_outage:
                    end = row["DAY"] - timedelta(days=1)
                    periods.append((start, end, mw))
                    in_outage = False
            if in_outage:
                end = group["DAY"].iloc[-1]
                periods.append((start, end, mw))
            outages[duid] = periods
        return outages

    old_outages = build_outage_map(df_old)
    new_outages = build_outage_map(df_new)
    moved = []

    for duid in set(old_outages) & set(new_outages):
        for old_period in old_outages[duid]:
            for new_period in new_outages[duid]:
                if old_period[2] == new_period[2]:
                    if old_period[0] != new_period[0] or old_period[1] != new_period[1]:
                        moved.append((duid, old_period, new_period))

    return moved


def quarter_str(dt):
    q = (dt.month - 1) // 3 + 1
    return f"Q{q} {dt.year}"


def format_moved_output(moved):
    lines = []
    try:
        duid_meta = pd.read_csv("duid_owner_units_capacity.csv")
        duid_meta["DUID"] = duid_meta["DUID"].str.strip().str.upper()
        meta_map = duid_meta.set_index("DUID")["Owner"].to_dict()
    except Exception as e:
        print(f"⚠️ Could not load duid_owner_units_capacity.csv: {e}")
        meta_map = {}

    if moved:
        lines.append("\n🔁 Moved Outages:")
        for duid, (old_start, old_end, mw), (new_start, new_end, _) in moved:
            old_q = quarter_str(old_start)
            new_q = quarter_str(new_start)
            old_duration = (old_end - old_start).days + 1
            new_duration = (new_end - new_start).days + 1
            owner = meta_map.get(duid, "UNKNOWN")
            lines.append(f"{duid} ({owner}):")
            lines.append(f"  ⤷ Previously: {old_start.date()} to {old_end.date()} ({old_duration} days, {old_q})")
            lines.append(f"  ⤷ Now:       {new_start.date()} to {new_end.date()} ({new_duration} days, {new_q})")
            lines.append(f"  ⤷ MW drop:   {mw} MW")
    return lines


def run_scheduler(test_mode=False):
    if test_mode:
        print("Running in TEST mode – simulating now.")
    else:
        tz = pytz.timezone("Australia/Sydney")
        now = datetime.now(tz)
        print(f"Current AEST Time: {now.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        url_old, url_new = fetch_latest_two_urls()
        df_old = extract_csv(url_old)
        df_new = extract_csv(url_new)

        moved_outages = detect_moved_outages(df_old, df_new)
        moved_output = format_moved_output(moved_outages)

        full_message = "\n".join(moved_output)
        print("\n" + full_message)
        if full_message:
            requests.post(NTFY_URL, data=full_message.encode("utf-8"))
    except Exception as e:
        print(f"❌ ERROR: {e}")


if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    run_scheduler(test_mode=test_mode)
