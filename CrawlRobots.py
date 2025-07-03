import requests
import xml.etree.ElementTree as ET
import os
import logging
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

cookies = {
    '_ga': os.getenv("GA"),
    '_ga_4PDMBFF7QV': os.getenv("GA_4PDMBFF7QV"),
    'cf_clearance': os.getenv("CF_CLEARANCE"),
    '_I_': os.getenv("I_COOKIE")
}

def get_sitemap_urls(sitemap_url: str) -> list:
    try:
        resp = requests.get(sitemap_url, headers=headers, cookies=cookies, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logging.error(f"❌ Failed to fetch {sitemap_url}: {e}")
        return []

    try:
        root = ET.fromstring(resp.content)
        return [url.text.strip() for url in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    except ET.ParseError:
        logging.error(f"❌ Failed to parse XML from {sitemap_url}")
        return []

def main():
    base_url = input("Enter the URL to scrape (e.g., https://www.aupp.edu.kh): ").strip().rstrip("/")
    parsed = urlparse(base_url)
    domain = parsed.netloc.replace("www.", "")

    # Try sitemap index first
    sitemap_index_url = f"{base_url}/sitemap_index.xml"
    sitemap_links = get_sitemap_urls(sitemap_index_url)

    # Fallback to sitemap.xml
    if not sitemap_links:
        logging.warning("⚠️ Falling back to /sitemap.xml")
        fallback = get_sitemap_urls(f"{base_url}/sitemap.xml")
        sitemap_links = fallback if fallback else []

    if not sitemap_links:
        logging.warning("⚠️ No sitemaps found.")
        return

    all_page_urls = []

    for sitemap in sitemap_links:
        logging.info(f"📦 Parsing sitemap: {sitemap}")
        urls = get_sitemap_urls(sitemap)
        all_page_urls.extend(urls)

    if all_page_urls:
        filename = f"{domain}_page_urls.txt"
        with open(filename, "w", encoding="utf-8") as f:
            for url in all_page_urls:
                f.write(url + "\n")
        logging.info(f"\n✅ Total pages found: {len(all_page_urls)}")
        logging.info(f"📄 URLs saved to: {filename}")
    else:
        logging.warning("⚠️ No URLs found in sitemaps.")

if __name__ == "__main__":
    main()
