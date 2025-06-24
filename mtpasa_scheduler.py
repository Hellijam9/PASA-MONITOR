import requests
import zipfile
import pandas as pd
import re
import os
import json
from io import BytesIO
from datetime import datetime, timedelta

BASE_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"
NTFY_URL = "https://ntfy.sh/pasa-alerts"
STORAGE_FILE = "saturday_runs.json"

# DEBUG MODE (set to None for live mode)
DEBUG_TIME = None  # e.g., datetime(2025, 6, 30, 7, 0) for Monday 07:00 AM


def now():
    return DEBUG_TIME or datetime.now()


def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = set(re.findall(r'PUBLIC_MTPASADUIDAVAILABILITY_\d{12}_\d+\.zip', r.text))
    if len(matches) < 2:
        raise ValueError("❌ Not enough unique MTPASA ZIP files found.")

    def extract_dt(f):
        return datetime.strptime(re.search(r'_(\d{12})_', f).group(1), "%Y%m%d%H%M")

    sorted_files = sorted(matches, key=extract_dt, reverse=True)
    return BASE_URL + sorted_files[1], BASE_URL + sorted_files[0]  # old, new


def extract_csv(url):
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f, skiprows=1, low_memory=False)


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

    if start_date:
        output.append((start_date, prev_date, prev_change))
    return output


def compare_availability(df_old, df_new):
    df_old = df_old[["DUID", "DAY", "PASAAVAILABILITY"]].copy().rename(columns={"PASAAVAILABILITY": "AVAIL_OLD"})
    df_new = df_new[["DUID", "DAY", "PASAAVAILABILITY"]].copy().rename(columns={"PASAAVAILABILITY": "AVAIL_NEW"})
    merged = pd.merge(df_old, df_new, on=["DUID", "DAY"])
    merged["CHANGE"] = merged["AVAIL_NEW"] - merged["AVAIL_OLD"]
    changes = merged[merged["CHANGE"] != 0]

    lines = []
    if changes.empty:
        lines.append("No DUID availability changes detected.")
    else:
        lines.append("🔄 Changes in Availability by DUID:")
        for duid, group in changes.groupby("DUID"):
            lines.append(f"\n{duid}:")
            for start, end, change in group_consecutive_changes(group):
                if start == end:
                    lines.append(f"  {start.date()}: {change:+} MW")
                else:
                    lines.append(f"  {start.date()} to {end.date()}: {change:+} MW")
    return "\n".join(lines)


def store_message(label, message):
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {}
    data[label] = message
    with open(STORAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_stored_messages():
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE, "r") as f:
            return json.load(f)
    return {}


def scheduler_logic():
    current_time = now()
    dow = current_time.strftime("%a")
    hour = current_time.hour
    minute = current_time.minute

    weekday_push_times = [(9, 20), (12, 20), (15, 20)]
    is_weekday = dow in ["Mon", "Tue", "Wed", "Thu", "Fri"]

    # ---- Real-time weekday NTFY runs ----
    if (hour, minute) in weekday_push_times and is_weekday:
        old_url, new_url = fetch_latest_two_urls()
        msg = compare_availability(extract_csv(old_url), extract_csv(new_url))
        requests.post(NTFY_URL, data=msg.encode("utf-8"))
        return

    # ---- Sat runs: just store ----
    if dow == "Sat":
        label = current_time.strftime("SAT_%H%M")
        old_url, new_url = fetch_latest_two_urls()
        msg = compare_availability(extract_csv(old_url), extract_csv(new_url))
        store_message(label, msg)
        return

    # ---- Tue–Fri 7am: send Fri 18:20 summary ----
    if dow in ["Tue", "Wed", "Thu", "Fri"] and (hour, minute) == (7, 0):
        old_url, new_url = fetch_latest_two_urls()
        msg = compare_availability(extract_csv(old_url), extract_csv(new_url))
        requests.post(NTFY_URL, data=msg.encode("utf-8"))
        return

    # ---- Mon 7am: full weekend summary ----
    if dow == "Mon" and (hour, minute) == (7, 0):
        old_url, new_url = fetch_latest_two_urls()
        friday_msg = compare_availability(extract_csv(old_url), extract_csv(new_url))
        weekend_msgs = load_stored_messages()

        summary = ["🔁 Full Weekend Recap", "\nFriday 18:20 → Saturday 09:20:", friday_msg]
        for label in sorted(weekend_msgs):
            summary.append(f"\n{label}:")
            summary.append(weekend_msgs[label])

        full = "\n".join(summary)
        requests.post(NTFY_URL, data=full.encode("utf-8"))
        return


if __name__ == "__main__":
    scheduler_logic()
