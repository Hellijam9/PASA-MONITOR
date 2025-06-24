import requests
import zipfile
import pandas as pd
from io import BytesIO

ZIP_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/PUBLIC_MTPASADUIDAVAILABILITY_202506241500_0000000469074180.zip"

def main():
    print(f"Downloading: {ZIP_URL}")
    r = requests.get(ZIP_URL)
    r.raise_for_status()

    with zipfile.ZipFile(BytesIO(r.content)) as z:
        all_files = z.namelist()
        print("📦 Files in ZIP:")
        for f in all_files:
            print(f" - {f}")

        csv_files = [f for f in all_files if f.lower().endswith(".csv")]
        if not csv_files:
            print("❌ No CSV file found in ZIP.")
            return

        print(f"✅ Extracting: {csv_files[0]}")
        with z.open(csv_files[0]) as f:
            df = pd.read_csv(f)
            print(df.head())

if __name__ == "__main__":
    main()
