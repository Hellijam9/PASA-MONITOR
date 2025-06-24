import requests
import zipfile
import pandas as pd
from io import BytesIO

# Hardcoded URLs to download
URL_OLD = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/PUBLIC_MTPASADUIDAVAILABILITY_202506241500_0000000469074180.zip"
URL_NEW = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/PUBLIC_MTPASADUIDAVAILABILITY_202506241800_0000000469093579.zip"

def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        file_name = z.namelist()[0]
        print(f"✅ Extracting: {file_name}")
        with z.open(file_name) as f:
            df = pd.read_csv(f, skiprows=1, low_memory=False)
            return df

def compare_availability(df_old, df_new):
    cols = ["DUID", "DAY", "PASAAVAILABILITY"]
    df_old = df_old[cols].copy()
    df_new = df_new[cols].copy()
    df_old.rename(columns={"PASAAVAILABILITY": "AVAIL_OLD"}, inplace=True)
    df_new.rename(columns={"PASAAVAILABILITY": "AVAIL_NEW"}, inplace=True)
    merged = pd.merge(df_old, df_new, on=["DUID", "DAY"])
    merged["CHANGE"] = merged["AVAIL_NEW"] - merged["AVAIL_OLD"]
    changes = merged[merged["CHANGE"] != 0]
    if changes.empty:
        print("No DUID availability changes detected.")
    else:
        print("\n🔄 Changes in Availability by DUID:")
        for duid, group in changes.groupby("DUID"):
            print(f"\n{duid}:")
            for _, row in group.iterrows():
                print(f"  {row['DAY']}: {int(row['CHANGE']):+} MW")

if __name__ == "__main__":
    df_old = extract_csv(URL_OLD)
    df_new = extract_csv(URL_NEW)
    compare_availability(df_old, df_new)
