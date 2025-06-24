import requests
import zipfile
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta

# Hardcoded URLs to download
URL_OLD = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/PUBLIC_MTPASADUIDAVAILABILITY_202506241500_0000000469074180.zip"
URL_NEW = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/PUBLIC_MTPASADUIDAVAILABILITY_202506241800_0000000469093579.zip"
NTFY_URL = "https://ntfy.sh/pasa-alerts"

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
    start_date = None
    prev_date = None
    prev_change = None

    for _, row in group.iterrows():
        cur_date = pd.to_datetime(row["DAY"])
        cur_change = int(row["CHANGE"])

        if start_date is None:
            start_date = cur_date
            prev_date = cur_date
            prev_change = cur_change
            continue

        if cur_date == prev_date + timedelta(days=1) and cur_change == prev_change:
            prev_date = cur_date
        else:
            output.append((start_date, prev_date, prev_change))
            start_date = cur_date
            prev_date = cur_date
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

    message_lines = []

    if changes.empty:
        message_lines.append("No DUID availability changes detected.")
    else:
        message_lines.append("🔄 Changes in Availability by DUID:")
        for duid, group in changes.groupby("DUID"):
            grouped_ranges = group_consecutive_changes(group)
            message_lines.append(f"\n{duid}:")
            for start, end, change in grouped_ranges:
                if start == end:
                    message_lines.append(f"  {start.date()}: {change:+} MW")
                else:
                    message_lines.append(f"  {start.date()} to {end.date()}: {change:+} MW")

    full_message = "\n".join(message_lines)
    print("\n" + full_message)
    requests.post(NTFY_URL, data=full_message.encode("utf-8"))

if __name__ == "__main__":
    df_old = extract_csv(URL_OLD)
    df_new = extract_csv(URL_NEW)
    compare_availability(df_old, df_new)
