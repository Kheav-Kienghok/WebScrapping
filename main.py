import logging
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from typing import List, Dict, Optional
import aiohttp
import httpx
import asyncio
import csv
import re
from datetime import datetime
from langdetect import detect, DetectorFactory
from pathlib import Path
from dotenv import load_dotenv
import os
import time

load_dotenv()

DetectorFactory.seed = 0  # Ensures consistent results

# Set up logging for debugging and monitoring
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class WebScraper:
    def __init__(self, delay: float = 1.0, timeout: int = 30, cookies: Optional[Dict[str, str]] = None):
        """
        Initialize the scraper with configuration and compile regex patterns

        Args:
            delay: Delay between requests to be respectful to the server
            timeout: Request timeout in seconds
        """
        self.delay = delay
        self.timeout = timeout
        self.cookies = cookies or {}

        # Compile regex patterns for better performance
        self.whitespace_pattern = re.compile(r'\s+')
        self.dash_pattern = re.compile(r'(?<=\d)[\u2013\u2014\u2015\u2212-](?=\d)')
        self.dot_pattern = re.compile(r'\.{2,}')

        # Headers to mimic a real browser
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }

    def clean_text(self, text: str) -> str:
        """
        Optimized text cleaning using pre-compiled regex patterns

        Args:
            text: Raw text to clean

        Returns:
            Cleaned text
        """
        if not text:
            return ""

        # Use pre-compiled patterns for better performance
        text = self.whitespace_pattern.sub(" ", text.strip())
        text = self.dash_pattern.sub("", text)
        text = self.dot_pattern.sub("", text)

        return text.strip()
    
    def extract_content(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """
        Fixed content extraction with proper deduplication and separator handling
        Now extracts all heading elements as titles and content from div, main, div, and p elements
        Excludes footer content

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Dictionary with paired 'english' and 'khmer' text lists
        """
        content = {
            'english_text': [],
            'khmer_text': []
        }
        
        # Remove footer and unwanted elements
        for unwanted in soup.find_all(['header']):
            unwanted.decompose()

        # Remove footer section if it exists
        footer_section = soup.find("div", attrs={"data-elementor-type": "footer"})
        if footer_section:
            footer_section.decompose()

        # Extract post_info text and assign based on language
        post_info_text = self.extract_post_info_paragraph(soup)
        if post_info_text:
            try:
                lang = detect(post_info_text)
            except Exception:
                lang = "unknown"

            if lang == "en" and post_info_text not in content['english_text']:
                content['english_text'].append(post_info_text)
            elif lang == "km" and post_info_text not in content['khmer_text']:
                content['khmer_text'].append(post_info_text)

        # Extract headings
        self.extract_text_by_tags(soup, ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], content)

        # Extract paragraphs
        self.extract_text_by_tags(soup, ['p'], content)

        return content

    def extract_text_by_tags(self, soup: BeautifulSoup, tags: List[str], content: Dict[str, List[str]]):
        """
        Extract and classify text by tag (headings or paragraphs) and update content dict in-place.
        
        Args:
            soup: BeautifulSoup object
            tags: List of HTML tags to extract (e.g., ['h1', 'h2'] or ['p'])
            content: Dict to be updated (english_text / khmer_text)
        """

        for element in soup.find_all(tags):
            raw_text = element.get_text(strip=True)
            if not raw_text or len(raw_text) <= 5:
                continue
                
            cleaned_text = self.clean_text(raw_text)
            if not cleaned_text:
                continue

            # Attempt language detection
            try:
                lang = detect(cleaned_text)
            except Exception:
                lang = "unknown"

            # Khmer script detection (Unicode range: U+1780 to U+17FF)
            if re.search(r'[\u1780-\u17FF]', cleaned_text):
                lang = "km"

            if lang not in ("en", "km"):
                lang = "en"

            # Append to appropriate list with alignment
            if lang == "en":
                content['english_text'].append(cleaned_text)
            elif lang == "km":
                content['khmer_text'].append(cleaned_text)

        
    async def scrape_url(self, client: httpx.AsyncClient, url: str) -> Optional[Dict[str, List[str]]]:
        """
        Scrape content from a single URL using httpx with HTTP/2 enabled.

        Args:
            client: httpx.AsyncClient for making requests
            url: URL to scrape

        Returns:
            Dictionary with extracted content or None if failed
        """
        if not self.validate_url(url):
            logger.warning(f"Invalid URL: {url}")
            return None

        try:
            logger.info(f"Scraping: {url}")

            response = await client.get(url, timeout=self.timeout)
            if response.status_code != 200:
                logger.warning(f"HTTP {response.status_code} for {url}")
                return None

            html = response.text
            soup = BeautifulSoup(html, 'html.parser')

            content = self.extract_content(soup)
            content['url'] = url
            content['status'] = 'success'

            if self.delay > 0:
                await asyncio.sleep(self.delay)

            return content

        except httpx.TimeoutException:
            logger.error(f"Timeout scraping {url}")
        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")

        return None

    async def scrape_multiple_urls(self, urls: List[str]) -> List[Dict]:
        """
        Scrape content from multiple URLs using httpx.AsyncClient with HTTP/2.

        Args:
            urls: List of URLs to scrape

        Returns:
            List of dictionaries with scraped content
        """
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)

        async with httpx.AsyncClient(http2=True, headers=self.headers, cookies=self.cookies, limits=limits) as client:
            tasks = [self.scrape_url(client, url) for url in urls]
            results = await asyncio.gather(*tasks)
            return [res for res in results if res]  # filter out None

    def extract_post_info_paragraph(self, soup: BeautifulSoup) -> str:
        """
        Extracts and formats post info as: 'Published on <date> in <category>'
        """
        container = soup.find(class_='elementor-post-info')
        if not container:
            return ""

        publish_date = ""
        category = ""

        # Extract the <time> element (publish date)
        time_tag = container.find('time')
        if time_tag:
            publish_date = time_tag.get_text(strip=True)

        # Extract the category from the last span with class ending in terms-list-item
        category_span = container.find('span', class_='elementor-post-info__terms-list-item')
        if category_span:
            category = category_span.get_text(strip=True)

        # Build the final string
        result = ""
        if publish_date:
            result += f"Published on {publish_date}"
        if category:
            result += f" in {category}"

        return result.strip()


    def validate_url(self, url: str) -> bool:
        """
        Validate if URL is properly formatted and from the expected domain

        Args:
            url: URL to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            parsed = urlparse(url)

            # Check if URL has proper structure
            if not parsed.scheme or not parsed.netloc:
                return False

            # Check if it's from the expected domain (optional)
            if "aupp.edu.kh" not in parsed.netloc and "mfaic.gov.kh" not in parsed.netloc:
                logger.warning(f"URL {url} is not from expected domains")
                # Don't return False here to allow other domains if needed

            return True

        except Exception:
            return False
        
    def save_to_csv(self, data: List[Dict], filename: Optional[str] = None, output_dir: str = "output") -> str:
        """
        Save scraped data to a CSV file in a directory using pathlib.

        Args:
            data: List of dictionaries with 'url', 'english_text', and 'khmer_text'
            filename: Optional CSV filename
            output_dir: Directory to save the file into

        Returns:
            The filename used to save the CSV
        """
        # Create output path using pathlib
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate timestamped filename if not provided
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"scraped_content_{timestamp}.csv"

        file_path = output_path / filename
        
        try:
            with file_path.open(mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=["ID", "English_Text", "Khmer_Text"])
                writer.writeheader()
                
                row_id = 1
                for item in data:

                    english_text = self.remove_duplicates_preserve_order(item.get("english_text", []))
                    khmer_text = self.remove_duplicates_preserve_order(item.get("khmer_text", []))

                    for text in english_text:
                        writer.writerow({"ID": row_id, "English_Text": text, "Khmer_Text": ""})
                        row_id += 1
                    for text in khmer_text:
                        writer.writerow({"ID": row_id, "English_Text": "", "Khmer_Text": text})
                        row_id += 1

            logger.info(f"Data successfully saved to {filename}")
        except Exception as e:
            logger.error(f"Error saving to CSV: {e}")

        return str(file_path)

    def remove_duplicates_preserve_order(self, items):
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
    

async def main():
    scraper = WebScraper(delay=1.0, timeout=20)

    # Load cookies from .env
    cookies = {
        '_ga': os.getenv("GA"),
        '_ga_4PDMBFF7QV': os.getenv("GA_4PDMBFF7QV"),
        'cf_clearance': os.getenv("CF_CLEARANCE"),
        '_I_': os.getenv("I_COOKIE"),
    }
    scraper.cookies = cookies

    urls = []
    print("Enter URLs to scrape. Press Enter on an empty line to start scraping:")

    while True:
        url_input = input("  > ").strip()
        if not url_input:
            break  # Empty input ends the loop

        if not scraper.validate_url(url_input):
            print("❌ Invalid URL or unsupported domain.")
            continue

        urls.append(url_input)

    if not urls:
        print("No valid URLs provided. Exiting.")
        return
    
    start_time = time.time()
    print(f"Starting scraping {len(urls)} URLs...")

    # Scrape all provided URLs
    logger.info(f"Starting scraping {len(urls)} URLs at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = await scraper.scrape_multiple_urls(urls)
    scraper.save_to_csv(results, output_dir="outputs")
    print(f"Scraping completed. Results saved to 'outputs' directory.")

    end_time = time.time()
    print(f"Total time taken: {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(main())