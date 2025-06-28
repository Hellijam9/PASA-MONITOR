import requests
import zipfile
import pandas as pd
import re
from io import BytesIO
from datetime import datetime
import pytz
import sys

BASE_URL = "https://www.nemweb.com.au/Reports/CURRENT/Network/"
NTFY_URL = "https://ntfy.sh/outage-alerts"

# NeoPoint CSV links with Two Years period
NEO_CSV_LINKS = {
    "NSW1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Two%20Years&instances=NSW1&section=-5&key=gfi2016",
    "QLD1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Two%20Years&instances=QLD1&section=-5&key=gfi2016",
    "VIC1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Two%20Years&instances=VIC1&section=-5&key=gfi2016",
    "SA1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Two%20Years&instances=SA1&section=-5&key=gfi2016"
}

# Fetch the two most recent AEMO network outage files
def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = sorted(set(re.findall(r'PUBLIC_NETWORK_\d{14}_\d+\.zip', r.text)))
    if len(matches) < 2:
        raise ValueError("❌ Not enough NOS ZIP files found.")

    def extract_dt(fn):
        m = re.search(r'PUBLIC_NETWORK_(\d{14})_', fn)
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S") if m else datetime.min

    items = [(extract_dt(fn), fn) for fn in matches]
    items.sort(reverse=True)
    print("📂 Top 5 files sorted by timestamp:")
    for ts, fn in items[:5]:
        print(f"  {ts}  →  {fn}")
    return BASE_URL + items[1][1], BASE_URL + items[0][1]

# Extract outage CSV from ZIP, get outage IDs
def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        fn = z.namelist()[0]
        print(f"✅ Extracting: {fn}")
        with z.open(fn) as f:
            df = pd.read_csv(f, header=None, skiprows=2)
            df.columns = range(df.shape[1])
            df[4] = df[4].astype(str).str.strip().str.lstrip("0")
            print(f"🔎 Sample outage IDs: {df[4].dropna().unique()[:5]}")
            return df

# Load NeoPoint metadata for planned outages
def load_neo_mapping():
    today = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%Y-%m-%d")
    mapping = {}
    for region, tmpl in NEO_CSV_LINKS.items():
        url = tmpl.format(today=today)
        try:
            df = pd.read_csv(url, header=None, encoding="utf-8", on_bad_lines='skip')
            df = df[df[2].astype(str).str.strip().str.match(r'^\d+$')]
            print(f"📊 {region} rows: {len(df)}")
            for _, r in df.iterrows():
                oid = r[2].strip().lstrip("0")
                mapping[oid] = {
                    "state": r[3],
                    "owner": r[4],
                    "substation_desc": r[6],
                    "equipment_desc": r[9],
                    "set_desc": r[11]
                }
        except Exception as e:
            print(f"⚠️ NeoPoint {region} load error: {e}")
    print(f"📦 NeoPoint mapping count: {len(mapping)} IDs")
    return mapping

# Safe parse datetime
def parse_dt(v):
    try:
        return pd.to_datetime(str(v).replace("COMP", "").strip(), errors="coerce")
    except:
        return pd.NaT

# Compare old vs new outages, fallback to AEMO data for cleared
def compare_outages(old, new):
    col = 4
    old[col] = old[col].str.strip().str.lstrip("0")
    new[col] = new[col].str.strip().str.lstrip("0")
    oids, nids = set(old[col]), set(new[col])
    print(f"🔁 Comparing {len(oids)} old vs {len(nids)} new IDs")
    added, removed = nids - oids, oids - nids
    if not added and not removed:
        print("No new or cleared network outages detected.")
        return
    print(f"🟥 New: {len(added)} | 🟩 Cleared: {len(removed)}")
    meta = load_neo_mapping()
    lines = []
    for label, ids, df_ in [("🟥", added, new), ("🟩", removed, old)]:
        if ids:
            lines.append(f"{label} {len(ids)} outages:")
            for oid in ids:
                row = df_[df_[col] == oid]
                if row.empty:
                    continue
                r = row.iloc[0]
                # choose appropriate date fields
                s = parse_dt(r[9])
                e = parse_dt(r[10])
                info = meta.get(oid)
                if not info:
                    # For cleared outages, use actual start/end from AEMO
                    s = parse_dt(r[19])
                    e = parse_dt(r[20])
                    info = {
                        "state": "AEMO",
                        "owner": "AEMO",
                        "substation_desc": r[6],
                        "equipment_desc": f"{r[7]} {r[8]}",
                        "set_desc": r[17]
                    }
                # compute duration and quarter once dates set
                dur = max((e - s).days + 1, 0) if pd.notna(s) and pd.notna(e) else "?"
                qtr = (s.month - 1)//3 + 1 if pd.notna(s) else "?"
                lines.append(
                    f"  {info['state']} | {info['owner']} | {info['substation_desc']} | "
                    f"{info['equipment_desc']} | {info['set_desc']} | "
                    f"{s.date() if pd.notna(s) else '?'} to {e.date() if pd.notna(e) else '?'} "
                    f"({dur} days, Q{qtr} {s.year if pd.notna(s) else '?'})"
                )
    msg = "\n".join(lines)
    print("\n" + msg)
    requests.post(NTFY_URL, data=msg.encode("utf-8"))

# Entry point
def run_scheduler(test=False):
    if test:
        print("🧪 Running in TEST mode – simulating now.")
    else:
        print(f"🕒 Current AEST Time: {datetime.now(pytz.timezone('Australia/Sydney'))}")
    try:
        u1, u2 = fetch_latest_two_urls()
        df1, df2 = extract_csv(u1), extract_csv(u2)
        compare_outages(df1, df2)
    except Exception as ex:
        print(f"❌ ERROR: {ex}")

if __name__ == "__main__":
    run_scheduler("--test" in sys.argv)
