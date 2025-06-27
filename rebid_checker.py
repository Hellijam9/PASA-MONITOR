#!/usr/bin/env python3
import requests
import pandas as pd
import os
from io import StringIO
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────
PLANT_CSV    = "Scheduled+Plant+Information+Fuel(-2).csv"
STATE_FILE   = "last_rebids.csv"
NTFY_TOPIC   = "rebid-alerts"
NTFY_URL     = f"https://ntfy.sh/{NTFY_TOPIC}"

REDBID_URLS = {
    "NSW1": "https://www.neopoint.com.au/Service/Csv?f=104%20Bids%20-%20Energy%5CRegion%20Rebids%20Explanation&from={today}%2000%3A00&period=Daily&instances=GEN%3BNSW1&section=-1&key=gfi2016",
    "QLD1": "https://www.neopoint.com.au/Service/Csv?f=104%20Bids%20-%20Energy%5CRegion%20Rebids%20Explanation&from={today}%2000%3A00&period=Daily&instances=GEN%3BQLD1&section=-1&key=gfi2016",
    "VIC1": "https://www.neopoint.com.au/Service/Csv?f=104%20Bids%20-%20Energy%5CRegion%20Rebids%20Explanation&from={today}%2000%3A00&period=Daily&instances=GEN%3BVIC1&section=-1&key=gfi2016",
    "SA1":  "https://www.neopoint.com.au/Service/Csv?f=104%20Bids%20-%20Energy%5CRegion%20Rebids%20Explanation&from={today}%2000%3A00&period=Daily&instances=GEN%3BSA1&section=-1&key=gfi2016",
}

INCLUDED_FUELS = {"black coal", "brown coal", "hydro", "gas"}

# ── HELPERS ───────────────────────────────────────
def load_mapping():
    df = pd.read_csv(PLANT_CSV)
    df.columns = df.columns.str.upper().str.strip()
    df["FUEL"]    = df["FUEL"].str.lower().str.strip()
    df["DUID"]    = df["DUID"].astype(str).str.upper().str.strip()
    df["REGION"]  = df["REGIONID"].str.upper().str.strip()
    df["COMPANY"] = df["PORTFOLIO"].str.strip()
    df["STATION"] = df["STATIONNAME"].str.strip()
    return df[df["FUEL"].isin(INCLUDED_FUELS)][["DUID","STATION","COMPANY","REGION"]]

def fetch_rebids(url):
    today = datetime.now().strftime("%Y-%m-%d")
    text = requests.get(url.format(today=today)).text
    df = pd.read_csv(StringIO(text))
    df.columns = df.columns.str.upper().str.strip()
    return df

def send_ntfy(msg):
    print("🔔 Sending ntfy alert:\n", msg, "\n")
    requests.post(NTFY_URL, data=msg.encode("utf-8"))

# ── MAIN ──────────────────────────────────────────
def main():
    mapping = load_mapping()
    if mapping.empty:
        print("⚠️ No matching DUIDs—check your plant CSV.")
        return

    seen = pd.read_csv(STATE_FILE) if os.path.exists(STATE_FILE) else pd.DataFrame(columns=["DUID","TIME","REGION"])
    all_new = []

    for region, url in REDBID_URLS.items():
        df = fetch_rebids(url)

        # Find the DUID column (ends with ' DUID')
        duid_cols = [c for c in df.columns if c.endswith(" DUID")]
        if not duid_cols:
            print(f"❌ No DUID column in {region} CSV; got: {df.columns.tolist()}")
            continue
        duid_col = duid_cols[0]

        # TIME = OFFERDATE
        if "OFFERDATE" not in df.columns:
            print(f"❌ 'OFFERDATE' missing in {region} CSV; got: {df.columns.tolist()}")
            continue

        # REASON = *REBIDEXPLANATION
        reason_cols = [c for c in df.columns if c.endswith("REBIDEXPLANATION")]
        if not reason_cols:
            print(f"❌ No REBIDEXPLANATION in {region} CSV; got: {df.columns.tolist()}")
            continue
        reason_col = reason_cols[0]

        # Build subset
        sub = df[[duid_col, "OFFERDATE", reason_col]].rename(
            columns={duid_col:"DUID", "OFFERDATE":"TIME", reason_col:"REASON"}
        )
        sub["DUID"]   = sub["DUID"].astype(str).str.upper().str.strip()
        sub["REGION"] = region

        # Filter to your DUIDs
        sub = sub[sub["DUID"].isin(mapping["DUID"])]

        # Diff against seen
        merged = sub.merge(seen, on=["DUID","TIME","REGION"], how="left", indicator=True)
        new    = merged[merged["_merge"]=="left_only"].drop(columns="_merge")

        print(f"[{region}] fetched {len(sub)} rows, {len(new)} new rebid(s).")
        if not new.empty:
            all_new.append((region, new))

    # Send grouped alerts
    if all_new:
        lines = []
        for region, df_new in all_new:
            lines.append(f"📍 {region} — {len(df_new)} new rebid(s)")
            enriched = df_new.merge(mapping, on="DUID", how="left")
            for company, grp in enriched.groupby("COMPANY"):
                lines.append(f"\n🏢 {company}")
                for _, r in grp.iterrows():
                    lines.append(f" • {r.DUID} @ {r.TIME} — {r.STATION} — {r.REASON}")
        send_ntfy("\n".join(lines))
    else:
        print("No new rebids detected.")

    # Update state
    updated = pd.concat([seen] + [n for _, n in all_new], ignore_index=True)
    updated.drop_duplicates(["DUID","TIME","REGION"], inplace=True)
    updated.to_csv(STATE_FILE, index=False)
    print(f"State file updated: {len(updated)} entries.")

if __name__=="__main__":
    main()
