#!/usr/bin/env python3
import requests
import zipfile
import pandas as pd
import re
from io import BytesIO
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
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
        m = re.search(r'_(\d{12})_', filename)
        return datetime.strptime(m.group(1), "%Y%m%d%H%M") if m else datetime.min
    sorted_files = sorted(matches, key=extract_dt, reverse=True)
    return BASE_URL + sorted_files[1], BASE_URL + sorted_files[0]

def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url); r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        fname = z.namelist()[0]
        print(f"✅ Extracting: {fname}")
        with z.open(fname) as f:
            return pd.read_csv(f, skiprows=1, low_memory=False)

def group_availability_ranges(df):
    """Return dict DUID → list of (start, end, availability)."""
    out = {}
    for duid, grp in df.groupby("DUID"):
        grp = grp.sort_values("DAY")
        ranges = []
        start = prev = None
        prev_val = None
        for _, row in grp.iterrows():
            day = pd.to_datetime(row["DAY"])
            val = int(row["PASAAVAILABILITY"])
            if start is None:
                start = prev = day
                prev_val = val
            elif day == prev + timedelta(days=1) and val == prev_val:
                prev = day
            else:
                ranges.append((start, prev, prev_val))
                start = prev = day
                prev_val = val
        if start is not None:
            ranges.append((start, prev, prev_val))
        out[duid] = ranges
    return out

def compare_availability(df_old, df_new):
    # Load DUID metadata
    try:
        info = pd.read_csv("duid_info.csv")
        name_map   = info.set_index("DUID")["UNIT_NAME"].to_dict()
        region_map = info.set_index("DUID")["REGION"].to_dict()
    except:
        name_map = region_map = {}

    msg_lines = []

    # 1) Numeric changes
    old = df_old[["DUID","DAY","PASAAVAILABILITY"]].rename(columns={"PASAAVAILABILITY":"OLD"})
    new = df_new[["DUID","DAY","PASAAVAILABILITY"]].rename(columns={"PASAAVAILABILITY":"NEW"})
    merged = pd.merge(old, new, on=["DUID","DAY"])
    merged["DELTA"] = merged["NEW"] - merged["OLD"]
    numeric = merged[merged["DELTA"].abs() >= 100]

    if not numeric.empty:
        msg_lines.append("🔄 Availability changes (≥100 MW):")
        for duid, grp in numeric.groupby("DUID"):
            name   = name_map.get(duid, duid)
            region = region_map.get(duid, "UNKNOWN")
            msg_lines.append(f"\n🔺 {duid} | {name} | {region}")
            for _, row in grp.iterrows():
                day   = row["DAY"]
                delta = row["DELTA"]
                msg_lines.append(f"   {day}: {delta:+} MW")

    # 2) Timing shifts
    old_ranges = group_availability_ranges(df_old)
    new_ranges = group_availability_ranges(df_new)

    shifts = []
    for duid in set(old_ranges) & set(new_ranges):
        for o_start, o_end, val in old_ranges[duid]:
            for n_start, n_end, v2 in new_ranges[duid]:
                if val == v2 and (o_start != n_start or o_end != n_end):
                    # compute months+days shift
                    rd = relativedelta(n_start, o_start)
                    months = rd.years*12 + rd.months
                    days   = rd.days
                    parts = []
                    if months: parts.append(f"{months} month{'s' if months>1 else ''}")
                    if days:   parts.append(f"{days} day{'s' if days>1 else ''}")
                    span = " ".join(parts) or "0 days"

                    # quarter labels
                    q_old = f"Q{((o_start.month-1)//3)+1} {o_start.year}"
                    q_new = f"Q{((n_start.month-1)//3)+1} {n_start.year}"
                    transition = f"moved from {q_old} to {q_new}" if q_old!=q_new else f"stayed in {q_old}"

                    name   = name_map.get(duid, duid)
                    msg_lines.append(
                        f"⏩ {duid} | {name}: outage of {val:+} MW shifted {span} "
                        f"({o_start.date()}→{n_start.date()}) — {transition}"
                    )
    if not shifts and numeric.empty:
        msg_lines.append("No changes detected.")

    full = "\n".join(msg_lines)
    print(full)
    requests.post(NTFY_URL, data=full.encode("utf-8"))

def run_scheduler(test_mode=False):
    if test_mode:
        print("🧪 TEST MODE")
    else:
        now = datetime.now(pytz.timezone("Australia/Sydney"))
        print(f"🕒 {now}")

    try:
        u_old, u_new = fetch_latest_two_urls()
        df_old = extract_csv(u_old)
        df_new = extract_csv(u_new)
        compare_availability(df_old, df_new)
    except Exception as e:
        print("❌ ERROR:", e)

if __name__=="__main__":
    run_scheduler("--test" in sys.argv)
