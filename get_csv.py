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
            print(df.head())

if __name__ == "__main__":
    extract_csv(URL_OLD)
    extract_csv(URL_NEW)
