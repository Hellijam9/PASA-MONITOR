import requests
import zipfile
import pandas as pd
import re
from io import BytesIO
from datetime import datetime
import pytz
import sys

BASE_URL = "https://www.nemweb.com.au/Reports/Current/OutageSchedule/"
NTFY_URL = "https://ntfy.sh/pasa-alerts"


def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = set(re.findall(r'PUBLIC_AEMO_NETWORK_OUTAGE_\\d{12}_\\d+\\.zip', r.text))
    if len(matches) < 2:
        raise ValueError("❌ Not enough NOS ZIP files found.")

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
            lines = [line.decode("utf-8") for line in f if line.startswith(b"D")]
            columns = [
                "OUTAGEID", "SUBSTATIONID", "EQUIPMENTTYPE", "EQUIPMENTID",
                "STARTTIME", "ENDTIME", "OUTAGESTATUSCODE", "LASTCHANGED", "ELEMENTID"
            ]
            data = []
            for line in lines:
                tokens = re.split(r'\s{2,}', line[1:].strip())
                if len(tokens) >= 9:
                    try:
                        row = {
                            "OUTAGEID": tokens[0],
                            "SUBSTATIONID": tokens[1],
                            "EQUIPMENTTYPE": tokens[2],
                            "EQUIPMENTID": tokens[3],
                            "STARTTIME": tokens[4],
                            "ENDTIME": tokens[5],
                            "OUTAGESTATUSCODE": tokens[6],
                            "LASTCHANGED": tokens[7],
                            "ELEMENTID": tokens[8]
                        }
                        data.append(row)
                    except Exception:
                        continue
            return pd.DataFrame(data)


def compare_outages(df_old, df_new):
    old_ids = set(df_old["OUTAGEID"])
    new_ids = set(df_new["OUTAGEID"])

    added = df_new[df_new["OUTAGEID"].isin(new_ids - old_ids)]
    removed = df_old[df_old["OUTAGEID"].isin(old_ids - new_ids)]

    message_lines = []

    if added.empty and removed.empty:
        message_lines.append("No new or cleared network outages detected.")
    else:
        if not added.empty:
            message_lines.append("🟥 New Outages:")
            for _, row in added.iterrows():
                start = pd.to_datetime(row["STARTTIME"])
                end = pd.to_datetime(row["ENDTIME"])
                duration = (end - start).days + 1
                label = ("1 day" if duration == 1 else f"{duration} days")
                quarter = (start.month - 1) // 3 + 1
                qtr = f"Q{quarter} {start.year}"
                message_lines.append(f"  {row['SUBSTATIONID']} {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → {start.date()} to {end.date()} ({label}, {qtr})")

        if not removed.empty:
            message_lines.append("\n🟩 Cleared Outages:")
            for _, row in removed.iterrows():
                start = pd.to_datetime(row["STARTTIME"])
                end = pd.to_datetime(row["ENDTIME"])
                duration = (end - start).days + 1
                label = ("1 day" if duration == 1 else f"{duration} days")
                quarter = (start.month - 1) // 3 + 1
                qtr = f"Q{quarter} {start.year}"
                message_lines.append(f"  {row['SUBSTATIONID']} {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → {start.date()} to {end.date()} ({label}, {qtr})")

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
        compare_outages(df_old, df_new)
    except Exception as e:
        print(f"❌ ERROR: {e}")


if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    run_scheduler(test_mode=test_mode)
