import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"

def fetch_latest_two():
    print("🔍 Scraping AEMO directory listing...")
    r = requests.get(BASE_URL)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    zip_links = [a['href'] for a in soup.find_all('a', href=True) 
                 if a['href'].endswith(".zip") and "PUBLIC_MTPASADUIDAVAILABILITY" in a['href']]

    zip_links.sort(key=lambda x: x.split("_")[2])  # oldest to newest
    return zip_links[-2:]  # last two

if __name__ == "__main__":
    urls = fetch_latest_two()
    print("🆕 Latest two MTPASA ZIP URLs by datetime (newest first):")
    for url in reversed(urls):  # reverse to show newest first
        print(BASE_URL + url)
