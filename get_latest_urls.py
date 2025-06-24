import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"

def fetch_latest_two():
    print("🔍 Scraping AEMO directory listing...")
    r = requests.get(BASE_URL)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    links = [a['href'] for a in soup.find_all('a', href=True)]
    zips = [link for link in links if link.endswith(".zip") and "PUBLIC_MTPASADUIDAVAILABILITY" in link]

    # Sort by the timestamp embedded in the filename
    zips_sorted = sorted(zips, key=lambda x: x.split("_")[2])  # uses e.g. 202506241800

    if len(zips_sorted) < 2:
        raise Exception("❌ Less than two ZIP files found.")

    return [BASE_URL + zips_sorted[-2], BASE_URL + zips_sorted[-1]]  # OLD first, NEW second

if __name__ == "__main__":
    urls = fetch_latest_two()
    print("🆕 Latest two MTPASA ZIP URLs by datetime:")
    for url in urls:
        print(url)
