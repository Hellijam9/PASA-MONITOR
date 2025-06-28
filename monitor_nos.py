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

neo_details = {}  # OUTAGEID → (equipment_desc, set_desc)


def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
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
            lines = [line.decode("utf-8", errors="ignore").strip() for line in f if line.startswith(b"D")]
            if not lines:
                raise ValueError("❌ No data lines found starting with 'D'.")

            df = pd.read_fwf(StringIO("\n".join(lines)), widths=[
                1, 15, 15, 5, 10, 15, 15, 15, 15, 10, 12, 15, 15, 20, 20, 20, 80, 5, 20, 20, 20, 20
            ], header=None)

            df.columns = [
                "RECTYPE", "REPORTID", "RECORDTYPE", "VERSION", "OUTAGEID", "SUBSTATIONID",
                "EQUIPMENTTYPE", "EQUIPMENTID", "STARTTIME", "ENDTIME", "SUBMITTEDDATE",
                "OUTAGESTATUSCODE", "RESUBMITREASON", "RESUBMITOUTAGEID", "RECALLTIMEDAY",
                "RECALLTIMENIGHT", "REASON", "ISSECONDARY", "ACTUAL_STARTTIME",
                "ACTUAL_ENDTIME", "COMPANYREFCODE", "ELEMENTID"
            ][:df.shape[1]]

            df["OUTAGEID"] = df["OUTAGEID"].astype(str).str.strip()
            df["SUBSTATIONID"] = df["SUBSTATIONID"].astype(str).str.strip()
            df["STARTTIME"] = df["STARTTIME"].astype(str).str.replace("COMP", "", regex=False)
            df["ENDTIME"] = df["ENDTIME"].astype(str).str.replace("COMP", "", regex=False)

            return df


def load_neo_mapping():
    global neo_details
    today = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%Y-%m-%d")
    substation_to_state = {}

    for _, url_template in NEO_CSV_LINKS.items():
        url = url_template.format(today=today)
        try:
            df = pd.read_csv(url)
            if df.shape[1] < 13:
                print(f"⚠️ NeoPoint CSV missing expected columns, skipping")
                continue
            for _, row in df.iterrows():
                sid = str(row.iloc[6]).strip()
                state = str(row.iloc[3]).strip()
                outage_id = str(row.iloc[2]).strip()
                equip_desc = str(row.iloc[10]).strip()
                set_desc = str(row.iloc[12]).strip()
                substation_to_state[sid] = state
                neo_details[outage_id] = (equip_desc, set_desc)
        except Exception as e:
            print(f"⚠️ Failed loading NeoPoint CSV: {e}")

    return substation_to_state


def compare_outages(df_old, df_new):
    substation_to_state = load_neo_mapping()

    def parse_datetime_safe(val):
        try:
            val_clean = str(val).strip().replace('"', '').replace(',', '')
            val_clean = val_clean.split()[0] + " " + val_clean.split()[1].split("C")[0]
            return pd.to_datetime(val_clean, errors="coerce", dayfirst=False)
        except Exception:
            return pd.NaT

    old_ids = set(df_old["OUTAGEID"])
    new_ids = set(df_new["OUTAGEID"])

    added = df_new[df_new["OUTAGEID"].isin(new_ids - old_ids)]
    removed = df_old[df_old["OUTAGEID"].isin(old_ids - new_ids)]

    message_lines = []

    if added.empty and removed.empty:
        message_lines.append("No new or cleared network outages detected.")
    else:
        if not added.empty:
            message_lines.append(f"🔵 {len(added)} new outages:")
            for state, group_state in added.groupby(lambda r: substation_to_state.get(added.loc[r, "SUBSTATIONID"], "UNKNOWN")):
                message_lines.append(f"\nState: {state}")
                for substation, group_sub in group_state.groupby("SUBSTATIONID"):
                    message_lines.append(f"  Substation: {substation}")
                    for _, row in group_sub.iterrows():
                        start = parse_datetime_safe(row["STARTTIME"])
                        end = parse_datetime_safe(row["ENDTIME"])
                        if pd.isna(start) or pd.isna(end):
                            continue
                        duration = (end - start).days + 1
                        qtr = (start.month - 1) // 3 + 1
                        eqdesc, setdesc = neo_details.get(row["OUTAGEID"], ("", ""))
                        message_lines.append(
                            f"    {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → {start.date()} to {end.date()} ({duration} days, Q{qtr} {start.year}) | {eqdesc} | {setdesc}")

        if not removed.empty:
            message_lines.append(f"\n🔺 {len(removed)} cleared outages:")
            for state, group_state in removed.groupby(lambda r: substation_to_state.get(removed.loc[r, "SUBSTATIONID"], "UNKNOWN")):
                message_lines.append(f"\nState: {state}")
                for substation, group_sub in group_state.groupby("SUBSTATIONID"):
                    message_lines.append(f"  Substation: {substation}")
                    for _, row in group_sub.iterrows():
                        start = parse_datetime_safe(row["STARTTIME"])
                        end = parse_datetime_safe(row["ENDTIME"])
                        if pd.isna(start) or pd.isna(end):
                            continue
                        duration = (end - start).days + 1
                        qtr = (start.month - 1) // 3 + 1
                        eqdesc, setdesc = neo_details.get(row["OUTAGEID"], ("", ""))
                        message_lines.append(
                            f"    {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → {start.date()} to {end.date()} ({duration} days, Q{qtr} {start.year}) | {eqdesc} | {setdesc}")

    full_message = "\n".join(message_lines)
    print("\n" + full_message)
    if "🔵" in full_message or "🔺" in full_message:
        requests.post(NTFY_URL, data=full_message.encode("utf-8"))


def run_scheduler(test_mode=False):
    if test_mode:
        print("🧚 Running in TEST mode – simulating now.")
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
