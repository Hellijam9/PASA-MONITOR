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

    for state_code, url_template in NEO_CSV_LINKS.items():
        url = url_template.format(today=today)
        try:
            df = pd.read_csv(url)
            if df.shape[1] < 13:
                print(f"⚠️ NeoPoint CSV for {state_code} missing expected columns, skipping")
                continue
            for _, row in df.iterrows():
                sid = row.iloc[6]
                substation_to_state[sid] = state_code
                outage_id = str(row.iloc[2]).strip()  # OUTAGEID from column C
                equip_desc = str(row.iloc[10]).strip()
                set_desc = str(row.iloc[12]).strip()
                neo_details[outage_id] = (equip_desc, set_desc)
        except Exception as e:
            print(f"⚠️ Failed loading NeoPoint CSV for {state_code}: {e}")

    return substation_to_state

# rest of the code remains unchanged
