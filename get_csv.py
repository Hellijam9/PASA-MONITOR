import requests
import zipfile
import pandas as pd
from io import BytesIO

# Hardcoded URLs to compare
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
            return pd.read_csv(f, skiprows=1, low_memory=False)

def compare_availability(df1, df2):
    cols = ["DUID", "Date", "Availability"]
    df1 = df1[cols].copy()
    df2 = df2[cols].copy()
    df1.rename(columns={"Availability": "Avail_1"}, inplace=True)
    df2.rename(columns={"Availability": "Avail_2"}, inplace=True)
    merged = pd.merge(df1, df2, on=["DUID", "Date"])
    merged["Change"] = merged["Avail_2"] - merged["Avail_1"]
    changed = merged[merged["Change"] != 0]
    return changed.sort_values(["DUID", "Date"])

def main():
    df1 = extract_csv(URL_OLD)
    df2 = extract_csv(URL_NEW)
    changes = compare_availability(df1, df2)
    if changes.empty:
        print("No changes detected.")
    else:
        print("\nChanges by DUID:")
        for duid, group in changes.groupby("DUID"):
            print(f"\n{duid}:")
            for _, row in group.iterrows():
                print(f"  {row['Date']}: {int(row['Change']):+} MW")

if __name__ == "__main__":
    main()
