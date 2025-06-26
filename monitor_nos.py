import pandas as pd
import requests
from datetime import datetime
import pytz
import sys

NTFY_URL = "https://ntfy.sh/pasa-alerts"

# Today's date for NeoPoint query
TODAY = datetime.now().strftime("%Y-%m-%d")
NEO_BASE = (
    "https://www.neopoint.com.au/Service/Csv?"
    "f=106%20Flows%20and%20Constraints%5CNOS%20Planned%20Outages%20by%20Region"
    "&from={date}%2000%3A00&period=Daily&instances={state}&section=-1&key=gfi2016"
)
STATES = ["NSW1", "QLD1", "VIC1", "SA1"]


def fetch_neopoint_csv(state):
    url = NEO_BASE.format(date=TODAY, state=state)
    df = pd.read_csv(url)
    df.columns = df.columns.str.strip()

    # Auto-locate the outage ID column
    outage_col = next((c for c in df.columns if "OUTAGEID" in c.upper()), None)
    if not outage_col:
        raise ValueError(f"OUTAGEID column not found in {state} CSV")

    df["OUTAGEID"] = df[outage_col].astype(str)
    return df


def load_all_enrichment():
    frames = [fetch_neopoint_csv(state) for state in STATES]
    return pd.concat(frames, ignore_index=True)


def fetch_latest_nos_files():
    import zipfile
    import re
    from io import BytesIO

    BASE_URL = "https://www.nemweb.com.au/Reports/CURRENT/Network/"
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = re.findall(r"PUBLIC_NETWORK_\d{14}_\d+\\.zip", r.text)
    if len(matches) < 2:
        raise ValueError("❌ Not enough NOS ZIP files found.")

    def extract_dt(f):
        m = re.search(r"_(\d{12})_", f)
        return datetime.strptime(m.group(1), "%Y%m%d%H%M") if m else datetime.min

    sorted_files = sorted(matches, key=extract_dt, reverse=True)
    return BASE_URL + sorted_files[1], BASE_URL + sorted_files[0]


def extract_nos_csv(url):
    import zipfile
    from io import BytesIO, StringIO

    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        file_name = z.namelist()[0]
        with z.open(file_name) as f:
            lines = [line.decode("utf-8") for line in f if line.startswith(b"D")]
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
            df["OUTAGEID"] = df["OUTAGEID"].astype(str)
            return df


def compare_and_alert(df_old, df_new, enrichment):
    old_ids = set(df_old["OUTAGEID"])
    new_ids = set(df_new["OUTAGEID"])
    added = df_new[df_new["OUTAGEID"].isin(new_ids - old_ids)]
    removed = df_old[df_old["OUTAGEID"].isin(old_ids - new_ids)]

    enrichment = enrichment.set_index("OUTAGEID")

    def build_lines(label, df):
        if df.empty:
            return []
        lines = [f"{label} {len(df)} outages:"]
        for sub, group in df.groupby("SUBSTATIONID"):
            lines.append(f"\n{sub}:")
            for _, row in group.iterrows():
                start = pd.to_datetime(row["STARTTIME"])
                end = pd.to_datetime(row["ENDTIME"])
                days = (end - start).days + 1
                qtr = f"Q{((start.month - 1) // 3 + 1)} {start.year}"
                eid = row["EQUIPMENTID"]
                etype = row["EQUIPMENTTYPE"]
                enrich = enrichment.loc.get(row["OUTAGEID"], {})
                enrich_str = f" ({enrich.get('SUBSTATION_DESCRIPTION','').strip()})" if isinstance(enrich, pd.Series) else ""
                lines.append(f"  {etype} {eid}{enrich_str} → {start.date()} to {end.date()} ({days} days, {qtr})")
        return lines

    msg_lines = build_lines("🟥 New", added) + [""] + build_lines("🟩 Cleared", removed)
    full_message = "\n".join(msg_lines).strip()
    print("\n" + full_message)
    requests.post(NTFY_URL, data=full_message.encode("utf-8"))


def run_scheduler(test_mode=False):
    if test_mode:
        print("🧪 Running in TEST mode – simulating now.")
    else:
        tz = pytz.timezone("Australia/Sydney")
        print(f"🕒 Current AEST Time: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        url_old, url_new = fetch_latest_nos_files()
        df_old = extract_nos_csv(url_old)
        df_new = extract_nos_csv(url_new)
        enrichment = load_all_enrichment()
        compare_and_alert(df_old, df_new, enrichment)
    except Exception as e:
        print(f"❌ ERROR: {e}")


if __name__ == "__main__":
    run_scheduler(test_mode="--test" in sys.argv)
