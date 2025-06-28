import requests
import zipfile
import pandas as pd
import re
from io import BytesIO, StringIO
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

    # Deduplicate file matches from HTML
    matches = sorted(set(re.findall(r'PUBLIC_NETWORK_\d{14}_\d+\.zip', r.text)))

    if len(matches) < 30:
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

    return BASE_URL + files_with_times[29][1], BASE_URL + files_with_times[0][1]


def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        file_name = z.namelist()[0]
        print(f"✅ Extracting: {file_name}")
        with z.open(file_name) as f:
            lines = [line.decode("utf-8") for line in f if line.startswith(b"D")]
            if not lines:
                raise ValueError("❌ No data lines found starting with 'D'.")
            df = pd.read_fwf(StringIO("".join(lines)), widths=[
                1, 15, 15, 5, 10, 15, 15, 15, 15, 10, 12, 15, 15, 20, 20, 20, 30, 5, 20, 20, 20, 20
            ], header=None)

            df.columns = [
                "RECTYPE", "REPORTID", "RECORDTYPE", "VERSION", "OUTAGEID", "SUBSTATIONID",
                "EQUIPMENTTYPE", "EQUIPMENTID", "STARTTIME", "ENDTIME", "SUBMITTEDDATE",
                "OUTAGESTATUSCODE", "RESUBMITREASON", "RESUBMITOUTAGEID", "RECALLTIMEDAY",
                "RECALLTIMENIGHT", "LASTCHANGED", "REASON", "ISSECONDARY", "ACTUAL_STARTTIME",
                "ACTUAL_ENDTIME", "COMPANYREFCODE", "ELEMENTID"
            ][:df.shape[1]]
            return df




def load_neo_mapping():
    today = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%Y-%m-%d")
    substation_to_state = {}

    for state_code, url_template in NEO_CSV_LINKS.items():
        url = url_template.format(today=today)
        try:
            df = pd.read_csv(url)

            # Using column indexes (based on your CSVs)
            # Assume:  substationid at col 6, state is from state_code key directly
            # Just map substationid to state_code
            # Defensive check for required column index
            if df.shape[1] < 7:
                print(f"⚠️ NeoPoint CSV for {state_code} missing expected columns, skipping")
                continue

            # Column index 6 is substationid based on your examples (0-based)
            # Loop rows to build dict
            for substation_id in df.iloc[:,6].dropna().unique():
                substation_to_state[substation_id] = state_code

        except Exception as e:
            print(f"⚠️ Failed loading NeoPoint CSV for {state_code}: {e}")

    return substation_to_state
    
def compare_outages(df_old, df_new):
    # Load mapping once
    substation_to_state = load_neo_mapping()

    old_ids = set(df_old["OUTAGEID"])
    new_ids = set(df_new["OUTAGEID"])

    added = df_new[df_new["OUTAGEID"].isin(new_ids - old_ids)]
    removed = df_old[df_old["OUTAGEID"].isin(old_ids - new_ids)]

    message_lines = []

    if added.empty and removed.empty:
        message_lines.append("No new or cleared network outages detected.")
    else:
        if not added.empty:
            message_lines.append(f"🟥 {len(added)} new outages:")
            for state, group_state in added.groupby(lambda r: substation_to_state.get(added.loc[r, "SUBSTATIONID"], "UNKNOWN")):
                message_lines.append(f"\nState: {state}")
                for substation, group_sub in group_state.groupby("SUBSTATIONID"):
                    message_lines.append(f"  Substation: {substation}")
                    for _, row in group_sub.iterrows():
                        try:
                            start_str = str(row["STARTTIME"]).strip().replace('"', '').replace(',', '')
                            end_str = str(row["ENDTIME"]).strip().replace('"', '').replace(',', '')
                            start = pd.to_datetime(start_str, errors="raise")
                            end = pd.to_datetime(end_str, errors="raise")
                        except Exception:
                            continue  # Skip rows with bad datetime
                        duration = (end - start).days + 1
                        qtr = (start.month - 1) // 3 + 1
                        message_lines.append(f"    {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → {start.date()} to {end.date()} ({duration} days, Q{qtr} {start.year})")

        if not removed.empty:
            message_lines.append(f"\n🟩 {len(removed)} cleared outages:")
            for state, group_state in removed.groupby(lambda r: substation_to_state.get(removed.loc[r, "SUBSTATIONID"], "UNKNOWN")):
                message_lines.append(f"\nState: {state}")
                for substation, group_sub in group_state.groupby("SUBSTATIONID"):
                    message_lines.append(f"  Substation: {substation}")
                    for _, row in group_sub.iterrows():
                        try:
                            start_str = str(row["STARTTIME"]).strip().replace('"', '').replace(',', '')
                            end_str = str(row["ENDTIME"]).strip().replace('"', '').replace(',', '')
                            start = pd.to_datetime(start_str, errors="raise")
                            end = pd.to_datetime(end_str, errors="raise")
                        except Exception:
                            continue  # Skip rows with bad datetime
                        duration = (end - start).days + 1
                        qtr = (start.month - 1) // 3 + 1
                        message_lines.append(f"    {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → {start.date()} to {end.date()} ({duration} days, Q{qtr} {start.year})")

    full_message = "\n".join(message_lines)
    print("\n" + full_message)
    if "🟥" in full_message or "🟩" in full_message:
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
