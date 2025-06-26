import requests
import zipfile
import pandas as pd
import re
from io import BytesIO, StringIO
from datetime import datetime
import pytz
import sys
from urllib.parse import quote

BASE_URL = "https://www.nemweb.com.au/Reports/CURRENT/Network/"
NTFY_URL = "https://ntfy.sh/pasa-alerts"

# Get today's outage metadata from NeoPoint dynamically
def fetch_outage_metadata():
    today = datetime.now().strftime("%Y-%m-%d")
    base_url = "https://www.neopoint.com.au/Service/Csv"
    params = {
        "f": "106 Flows and Constraints\\NOS Planned Outages by Region",
        "from": f"{today} 00:00",
        "period": "Daily",
        "section": "-1",
        "key": "gfi2016"
    }
    regions = ["NSW1", "QLD1", "VIC1", "SA1"]
    lookup_frames = []

    for region in regions:
        params_encoded = "&".join([f"{k}={quote(str(v))}" for k, v in {**params, "instances": region}.items()])
        url = f"{base_url}?{params_encoded}"
        df = pd.read_csv(url)
        df["REGION"] = region
        lookup_frames.append(df)

    return pd.concat(lookup_frames, ignore_index=True)


def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = re.findall(r'PUBLIC_NETWORK_\d{14}_\d+\.zip', r.text)
    if len(matches) < 2:
        raise ValueError("❌ Not enough NOS ZIP files found.")

    def extract_dt(filename):
        match = re.search(r'_(\d{12})_', filename)
        return datetime.strptime(match.group(1), "%Y%m%d%H%M") if match else datetime.min

    sorted_files = sorted(matches, key=extract_dt, reverse=True)
    return BASE_URL + sorted_files[1], BASE_URL + sorted_files[0]


def extract_csv(url):
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        file_name = z.namelist()[0]
        with z.open(file_name) as f:
            lines = [line.decode("utf-8") for line in f if line.startswith(b"D")]
            df = pd.read_fwf(StringIO("".join(lines)), widths=[
                1, 15, 15, 5, 10, 15, 15, 15, 15, 10, 12,
                15, 15, 20, 20, 20, 30, 5, 20, 20, 20, 20
            ], header=None)
            df.columns = [
                "RECTYPE", "REPORTID", "RECORDTYPE", "VERSION", "OUTAGEID", "SUBSTATIONID",
                "EQUIPMENTTYPE", "EQUIPMENTID", "STARTTIME", "ENDTIME", "SUBMITTEDDATE",
                "OUTAGESTATUSCODE", "RESUBMITREASON", "RESUBMITOUTAGEID", "RECALLTIMEDAY",
                "RECALLTIMENIGHT", "LASTCHANGED", "REASON", "ISSECONDARY", "ACTUAL_STARTTIME",
                "ACTUAL_ENDTIME", "COMPANYREFCODE", "ELEMENTID"
            ][:df.shape[1]]
            return df


def format_duration(start, end):
    delta = end - start
    days = delta.days
    if days < 7:
        return f"{days} day{'s' if days != 1 else ''}"
    elif days < 30:
        weeks = round(days / 7)
        return f"{weeks} week{'s' if weeks != 1 else ''}"
    elif days < 365:
        months = round(days / 30)
        return f"{months} month{'s' if months != 1 else ''}"
    else:
        years = days // 365
        rem_months = round((days % 365) / 30)
        return f"{years} year{'s' if years != 1 else ''}, {rem_months} month{'s' if rem_months != 1 else ''}"


def compare_outages(df_old, df_new, lookup_df):
    old_ids = set(df_old["OUTAGEID"])
    new_ids = set(df_new["OUTAGEID"])
    added = df_new[df_new["OUTAGEID"].isin(new_ids - old_ids)]
    removed = df_old[df_old["OUTAGEID"].isin(old_ids - new_ids)]

    lookup = lookup_df.set_index("Outage Id")
    message_lines = []

    def enrich(row):
        meta = lookup.loc[row["OUTAGEID"]] if row["OUTAGEID"] in lookup.index else None
        return {
            "region": meta["REGION"] if meta is not None else "",
            "substation": meta["Substation Name"] if meta is not None else row["SUBSTATIONID"],
            "tnsp": meta["TNSP"] if meta is not None and "TNSP" in meta else ""
        }

    if added.empty and removed.empty:
        message_lines.append("No new or cleared network outages detected.")
    else:
        if not added.empty:
            subs = added["SUBSTATIONID"].nunique()
            message_lines.append(f"🟥 {len(added)} new outages across {subs} substations:")
            for sub, group in added.groupby("SUBSTATIONID"):
                meta = enrich(group.iloc[0])
                message_lines.append(f"\n{meta['substation']} ({meta['region']}, {meta['tnsp']}):")
                for _, row in group.iterrows():
                    start = pd.to_datetime(row["STARTTIME"])
                    end = pd.to_datetime(row["ENDTIME"])
                    duration = format_duration(start, end)
                    qtr = (start.month - 1) // 3 + 1
                    qtr_str = f"Q{qtr} {start.year}"
                    message_lines.append(f"  {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → {start.date()} to {end.date()} ({duration}, {qtr_str})")

        if not removed.empty:
            subs = removed["SUBSTATIONID"].nunique()
            message_lines.append(f"\n🟩 {len(removed)} cleared outages across {subs} substations:")
            for sub, group in removed.groupby("SUBSTATIONID"):
                meta = enrich(group.iloc[0])
                message_lines.append(f"\n{meta['substation']} ({meta['region']}, {meta['tnsp']}):")
                for _, row in group.iterrows():
                    start = pd.to_datetime(row["STARTTIME"])
                    end = pd.to_datetime(row["ENDTIME"])
                    duration = format_duration(start, end)
                    qtr = (start.month - 1) // 3 + 1
                    qtr_str = f"Q{qtr} {start.year}"
                    message_lines.append(f"  {row['EQUIPMENTTYPE']} {row['EQUIPMENTID']} → {start.date()} to {end.date()} ({duration}, {qtr_str})")

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
        metadata_df = fetch_outage_metadata()
        compare_outages(df_old, df_new, metadata_df)
    except Exception as e:
        print(f"❌ ERROR: {e}")


if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    run_scheduler(test_mode=test_mode)
