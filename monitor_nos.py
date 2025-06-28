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

# Fetch the 30th-oldest and the newest NEMWEB public network ZIP URLs
def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = sorted(set(re.findall(r'PUBLIC_NETWORK_\d{14}_\d+\.zip', r.text)))
    if len(matches) < 30:
        raise ValueError("❌ Not enough NOS ZIP files found.")

    def extract_dt(fn):
        m = re.search(r'PUBLIC_NETWORK_(\d{14})_', fn)
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S") if m else datetime.min

    files = [(extract_dt(fn), fn) for fn in matches]
    files.sort(reverse=True)

    print("📂 Top 5 files sorted by timestamp:")
    for ts, fn in files[:5]:
        print(f"  {ts}  →  {fn}")

    # Return the 30th most recent (index 29) and the latest (index 0)
    return BASE_URL + files[29][1], BASE_URL + files[0][1]

# Download and parse the CSV content from a NEMWEB ZIP URL
def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        fn = z.namelist()[0]
        print(f"✅ Extracting: {fn}")
        with z.open(fn) as f:
            # Read only lines starting with 'D'
            lines = [line.decode('utf-8', 'ignore') for line in f if line.startswith(b'D')]

    # Fixed-width parsing according to NEMWEB spec
    widths = [1,15,15,5,10,15,15,15,15,10,12,15,15,20,20,20,80,5,20,20,20,20]
    df = pd.read_fwf(StringIO(''.join(lines)), widths=widths, header=None)
    # Assign column names based on spec
    cols = [
        "RECTYPE","REPORTID","RECORDTYPE","VERSION","OUTAGEID","SUBSTATIONID",
        "EQUIPMENTTYPE","EQUIPMENTID","STARTTIME","ENDTIME","SUBMITTEDDATE",
        "OUTAGESTATUSCODE","RESUBMITREASON","RESUBMITOUTAGEID","RECALLTIMEDAY",
        "RECALLTIMENIGHT","REASON","ISSECONDARY","ACTUAL_STARTTIME",
        "ACTUAL_ENDTIME","COMPANYREFCODE","ELEMENTID"
    ][:df.shape[1]]
    df.columns = cols
    df["OUTAGEID"] = df["OUTAGEID"].astype(str).str.strip()
    return df

# Safely parse a NEMWEB datetime field

def parse_datetime_safe(val):
    try:
        s = str(val).replace('COMP','').strip()
        return pd.to_datetime(s, errors='coerce')
    except:
        return pd.NaT

# Compare two outage DataFrames and send notification via ntfy

def compare_outages(df_old, df_new):
    old_ids = set(df_old["OUTAGEID"])
    new_ids = set(df_new["OUTAGEID"])
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    lines = []

    if added:
        lines.append(f"🟥 {len(added)} new outages:")
        for oid in added:
            row = df_new[df_new["OUTAGEID"] == oid].iloc[0]
            start = parse_datetime_safe(row["STARTTIME"])
            end = parse_datetime_safe(row["ENDTIME"])
            dur = (end - start).days + 1 if pd.notna(start) and pd.notna(end) else '?'  
            lines.append(
                f"  {row['SUBSTATIONID']} | {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → "
                f"{start.date() if pd.notna(start) else '?'} to {end.date() if pd.notna(end) else '?'} "
                f"({dur} days)"
            )

    if removed:
        lines.append(f"🟩 {len(removed)} cleared outages:")
        for oid in removed:
            row = df_old[df_old["OUTAGEID"] == oid].iloc[0]
            start = parse_datetime_safe(row["ACTUAL_STARTTIME"])
            end = parse_datetime_safe(row["ACTUAL_ENDTIME"])
            dur = (end - start).days + 1 if pd.notna(start) and pd.notna(end) else '?'  
            lines.append(
                f"  {row['SUBSTATIONID']} | {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → "
                f"{start.date() if pd.notna(start) else '?'} to {end.date() if pd.notna(end) else '?'} "
                f"({dur} days)"
            )

    msg = '\n'.join(lines) if lines else "No new or cleared network outages detected."
    print(msg)
    # Send via ntfy
    requests.post(NTFY_URL, data=msg.encode('utf-8'))

# Main
if __name__ == "__main__":
    test = "--test" in sys.argv
    if test:
        print("🧪 Running in TEST mode – simulating now.")
    u_old, u_new = fetch_latest_two_urls()
    df_old = extract_csv(u_old)
    df_new = extract_csv(u_new)
    compare_outages(df_old, df_new)
