import requests
import zipfile
from io import BytesIO

# Hardcoded URLs to download
URL_OLD = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/PUBLIC_MTPASADUIDAVAILABILITY_202506241500_0000000469074180.zip"
URL_NEW = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/PUBLIC_MTPASADUIDAVAILABILITY_202506241800_0000000469093579.zip"

def download_zip(url):
    print(f"Downloading: {url}")
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        file_name = z.namelist()[0]
        print(f"✅ Found file in ZIP: {file_name}")

if __name__ == "__main__":
    download_zip(URL_OLD)
    download_zip(URL_NEW)
