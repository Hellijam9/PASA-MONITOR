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

NEO_CSV_LINKS = {
    "NSW1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Daily&instances=NSW1&section=-1&key=gfi2016",
    "QLD1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Daily&instances=QLD1&section=-1&key=gfi2016",
    "VIC1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Daily&instances=VIC1&section=-1&key=gfi2016",
    "SA1": "https://www.neopoint.com.au/Service/Csv?f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region&from={today}%2000%3A00&period=Daily&instances=SA1&section=-1&key=gfi2016"
}

def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = sorted(set(re.findall(r'PUBLIC_NETWORK_\d{14}_\d+\.zip', r.text)))
    if len(matches) < 2:
        raise ValueError("❌ Not enough NOS ZIP files found.")

    def extract_dt(filename):
        m = re.search(r'PUBLIC_NETWORK_(\d{14})_', filename)
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S") if m else datetime.min

    files_with_times = [(extract_dt(f), f) for f in matches]
    files_with_times.sort(reverse=True)
    print("📂 Top 5 files sorted by timestamp:")
    for ts, f in files_with_times[:5]:
        print(f"  {ts}  →  {f}")
    return BASE_URL + files_with_times[1][1], BASE_URL + files_with_times[0][1]

def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        fn = z.namelist()[0]
        print(f"✅ Extracting: {fn}")
        with z.open(fn) as f:
            df = pd.read_csv(f, header=None, skiprows=2)
            df.columns = list(range(df.shape[1]))
            df[4] = df[4].astype(str).str.strip().str.lstrip("0")
            print(f"🔎 Sample outage IDs from {fn}: {df[4].dropna().unique()[:5]}")
            return df

def load_neo_mapping():
    today = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%Y-%m-%d")
    mapping = {}
    for state, tmpl in NEO_CSV_LINKS.items():
        url = tmpl.format(today=today)
        try:
            df = pd.read_csv(url, header=None, encoding="utf-8", on_bad_lines='skip')
            # Keep only rows where column 2 is a numeric Outage ID
            df = df[df[2].astype(str).str.match(r'^\d+$')]
            for _, row in df.iterrows():
                oid = row[2].strip().lstrip("0")
                mapping[oid] = {
                    "state": str(row[3]).strip(),
                    "owner": str(row[4]).strip(),
                    "substation_desc": str(row[6]).strip(),
                    "equipment_desc": str(row[9]).strip(),
                    "set_desc": str(row[11]).strip()
                }
        except Exception as e:
            print(f"⚠️ Failed loading NeoPoint {state}: {e}")
    print(f"📦 NeoPoint mapping loaded with {len(mapping)} outage IDs")
    return mapping

def parse_dt(v):
    try:
        return pd.to_datetime(str(v).replace("COMP", "").strip(), errors="coerce")
    except:
        return pd.NaT

def compare_outages(old, new):
    col = 4
    old[col] = old[col].astype(str).str.strip().str.lstrip("0")
    new[col] = new[col].astype(str).str.strip().str.lstrip("0")
    oids = set(old[col])
    nids = set(new[col])
    print(f"🔁 Comparing {len(oids)} old vs {len(nids)} new IDs")
    added = nids - oids
    removed = oids - nids
    if not added and not removed:
        print("No new or cleared network outages detected.")
        return
    print(f"🟥 New: {len(added)}")
    print(f"🟩 Cleared: {len(removed)}")
    md = load_neo_mapping()
    lines = []
    for label, ids, df_ in [("🟥", added, new), ("🟩", removed, old)]:
        if ids:
            lines.append(f"{label} {len(ids)} outages:")
            for oid in ids:
                row = df_[df_[col] == oid]
                if row.empty: continue
                r = row.iloc[0]
                s = parse_dt(r[9])
                e = parse_dt(r[10])
                dur = max((e - s).days + 1, 0) if pd.notna(s) and pd.notna(e) else "?"
                q = (s.month - 1)//3 + 1 if pd.notna(s) else "?"
                info = md.get(oid, {})
                lines.append(
                    f"  {info.get('state','?')} | {info.get('owner','?')} | {info.get('substation_desc','?')} | "
                    f"{info.get('equipment_desc','?')} | {info.get('set_desc','?')} | "
                    f"{s.date() if pd.notna(s) else '?'} to {e.date() if pd.notna(e) else '?'} "
                    f"({dur} days, Q{q} {s.year if pd.notna(s) else '?'})"
                )
    msg = "\n".join(lines)
    print("\n" + msg)
    requests.post(NTFY_URL, data=msg.encode("utf-8"))

def run_scheduler(test=False):
    if test:
        print("🧪 Running in TEST mode – simulating now.")
    else:
        now = datetime.now(pytz.timezone("Australia/Sydney"))
        print(f"🕒 Current AEST Time: {now}")
    try:
        u1, u2 = fetch_latest_two_urls()
        df1 = extract_csv(u1)
        df2 = extract_csv(u2)
        compare_outages(df1, df2)
    except Exception as ex:
        print(f"❌ ERROR: {ex}")

if __name__ == "__main__":
    run_scheduler("--test" in sys.argv)
