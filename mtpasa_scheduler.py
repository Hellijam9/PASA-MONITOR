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

    print("🧾 HTML preview:")
    print(r.text[:1000])  # Show first 1000 characters of the HTML

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

def group_consecutive_changes(group):
    output = []
    group = group.sort_values("DAY")
    start_date = prev_date = prev_change = None
    for _, row in group.iterrows():
        cur_date = pd.to_datetime(row["DAY"])
        cur_change = int(row["CHANGE"])
        if start_date is None:
            start_date = prev_date = cur_date
            prev_change = cur_change
            continue
        if cur_date == prev_date + timedelta(days=1) and cur_change == prev_change:
            prev_date = cur_date
        else:
            output.append((start_date, prev_date, prev_change))
            start_date = prev_date = cur_date
            prev_change = cur_change
    if start_date is not None:
        output.append((start_date, prev_date, prev_change))
    return output

def compare_availability(df_old, df_new):
    cols = ["DUID", "DAY", "PASAAVAILABILITY"]
    df_old = df_old[cols].copy()
    df_new = df_new[cols].copy()
    df_old.rename(columns={"PASAAVAILABILITY": "AVAIL_OLD"}, inplace=True)
    df_new.rename(columns={"PASAAVAILABILITY": "AVAIL_NEW"}, inplace=True)
    merged = pd.merge(df_old, df_new, on=["DUID", "DAY"])
    merged["CHANGE"] = merged["AVAIL_NEW"] - merged["AVAIL_OLD"]
    changes = merged[merged["CHANGE"] != 0]

    # Load DUID info
    try:
        duid_info = pd.read_csv("duid_info.csv")
        info_map = duid_info.set_index("DUID")[["REGION", "UNIT_NAME"]].to_dict("index")
    except Exception as e:
        print(f"⚠️ Could not load duid_info.csv: {e}")
        info_map = {}

    message_lines = []

    if changes.empty:
        message_lines.append("No DUID availability changes detected.")
    else:
        message_lines.append("🔄 Changes in Availability by DUID (≥100 MW):")
        for duid, group in changes.groupby("DUID"):
            grouped_ranges = group_consecutive_changes(group)
            region = info_map.get(duid, {}).get("REGION", "UNKNOWN")
            name = info_map.get(duid, {}).get("UNIT_NAME", duid)
            printed_header = False
            for start, end, change in grouped_ranges:
                if abs(change) < 100:
                    continue
                if not printed_header:
                    message_lines.append(f"\n{name} ({duid}, {region}):")
                    printed_header = True
                duration = (end - start).days + 1
                if duration == 1:
                    label = "1 day"
                elif duration < 7:
                    label = f"{duration} days"
                elif duration < 30:
                    label = f"{duration // 7} week(s)"
                else:
                    label = f"{duration // 30} month(s)"
                quarter = (start.month - 1) // 3 + 1
                qtr_str = f"Q{quarter} {start.year}"
                message_lines.append(
                    f"  {start.date()} to {end.date()} ({label}, {qtr_str}): {change:+} MW"
                )

    full_message = "\n".join(message_lines)
    print("\n" + full_message)
    requests.post(NTFY_URL, data=full_message.encode("utf-8"))


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
        compare_availability(df_old, df_new)
    except Exception as e:
        print(f"❌ ERROR: {e}")

# Entry point
if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    run_scheduler(test_mode=test_mode)
