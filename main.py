# Standard Library Imports
import asyncio
import csv
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse

# Third-Party Library Imports
import httpx
import pandas as pd
import plotly.graph_objects as go
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langdetect import detect, DetectorFactory

load_dotenv()

DetectorFactory.seed = 0  # Ensures consistent results

class RelevantLogsFilter(logging.Filter):
    def filter(self, record):
        # Always allow logs from your "scraper" logger
        if record.name == "scraper":
            return True
        # Allow specific httpx logs that mention an HTTP request
        if record.name.startswith("httpx") and "HTTP Request" in record.getMessage():
            return True
        # Block everything else
        return False

# Create handlers
file_handler = logging.FileHandler("scraper.log", encoding="utf-8")
stream_handler = logging.StreamHandler()

# Apply filter
relevant_filter = RelevantLogsFilter()
file_handler.addFilter(relevant_filter)
stream_handler.addFilter(relevant_filter)

# Formatter
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

# Configure root logger with both handlers
logging.basicConfig(handlers=[file_handler, stream_handler], level=logging.INFO)

# Your custom logger
logger = logging.getLogger("scraper")
logger.setLevel(logging.INFO)

# Silence other noisy libraries at the source
for noisy in ["kaleido", "plotly", "selenium", "urllib3"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

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

        # Extract text from main content areas
        self.extract_text_by_tags(soup, ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], content)
        self.extract_text_by_tags(soup, ['p'], content)
        self.extract_text_by_tags(soup, ['li'], content)
        self.extract_text_by_tags(soup, ['th', 'td'], content)

        return content

    def is_mostly_khmer(self, text: str, char_ratio: float = 0.4, min_khmer_chars: int = 10) -> bool:
        khmer_chars = sum(1 for c in text if '\u1780' <= c <= '\u17FF')
        total_chars = len(text)
        if total_chars == 0:
            return False
        ratio = khmer_chars / total_chars
        return khmer_chars >= min_khmer_chars and ratio >= char_ratio


    def extract_text_by_tags(self, soup: BeautifulSoup, tags: List[str], content: Dict[str, List[str]]):
        """
        Extract and classify text by tag (headings or paragraphs) and update content dict in-place.
        
        Args:
            soup: BeautifulSoup object
            tags: List of HTML tags to extract (e.g., ['h1', 'h2'] or ['p'])
            content: Dict to be updated (english_text / khmer_text)
        """

        for element in soup.find_all(tags):
            if element.name == 'td':
                # Special handling for nested <tr> inside <td>
                nested_trs = element.find_all('tr')
                if nested_trs:
                    for tr in nested_trs:
                        self._process_text_block(tr.get_text(separator=' ', strip=True), content)
                    continue  # skip processing outer <td> text again
            self._process_text_block(element.get_text(separator=' ', strip=True), content)

    def _process_text_block(self, raw_text: str, content: Dict[str, List[str]]):
        """
        Helper to clean, detect language, and append to content dictionary.
        """
        if not raw_text or len(raw_text) <= 5:
            return
        
        cleaned_text = self.clean_text(raw_text)
        if not cleaned_text:
            return

        if self.is_mostly_khmer(cleaned_text):
            lang = "km"
        else:
            try:
                lang = detect(cleaned_text)
                if lang not in ("en", "km"):
                    lang = "en"
            except:
                lang = "unknown"

        if lang == "en":
            content['english_text'].append(cleaned_text)
        elif lang == "km":
            content['khmer_text'].append(cleaned_text)

    def extract_tables_to_dataframes(self, soup: BeautifulSoup) -> List[Dict[str, pd.DataFrame]]:
        """
        Extracts tables with associated titles and subheadings from the HTML.
        Returns a list of dicts: {'title': str, 'detail': Optional[str], 'data': DataFrame}
        """
        tables = soup.find_all("table")
        extracted = []

        # Get the first <p> in the document once
        first_p = soup.find("p")
        first_p_text = first_p.get_text(strip=True) if first_p else ""

        for idx, table in enumerate(tables):
            # Try to get a main title from heading or caption
            title_tag = table.find_previous(lambda tag: (
                tag.name in ["h1", "h2", "h3", "div", "button", "span"] and
                ("Required" in tag.get_text() or "Courses" in tag.get_text())
            ))
            title = title_tag.get_text(strip=True) if title_tag else f"Table {idx+1}"

            # Look for a detail/subheading from a nearby <p> or smaller tag
            detail_tag = table.find_previous(lambda tag: tag.name in ["p", "small", "h4", "h5", "h6"] and tag != title_tag)
            detail = detail_tag.get_text(strip=True) if detail_tag else None

            # Extract headers and rows
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    rows.append(cells)

            # Handle header-less tables
            if not headers and rows:
                col_count = max(len(row) for row in rows)
                headers = [f"Column {i+1}" for i in range(col_count)]

            if rows:
                df = pd.DataFrame(rows, columns=headers)
                extracted.append({
                    "title": title,
                    "detail": detail,
                    "data": df
                })

        # Only modify the first table if it exists
        if extracted:
            extracted[0]["title"] = extracted[0]["detail"]
            extracted[0]["detail"] = first_p_text

        return extracted
    
    def save_plotly_table(self, df: pd.DataFrame, output_path: str, title: Optional[str] = None, detail: Optional[str] = None, first: bool = False):
        row_count = len(df)
        col_count = len(df.columns)

        row_height = 30
        col_width = 120
        fig_height = 100 + row_count * row_height
        fig_width = max(500, col_count * col_width)

        if first and detail:
            detail = detail.split(".")[0]  # Shorten detail to first sentence
            split_detail = split_detail_text(detail)
            title_texts = f"{title}<br><span style='font-size:12px;color:gray'>{split_detail}</span>"
        else:
            title_texts = title

        fig = go.Figure(data=[go.Table(
            header=dict(
                values=list(df.columns),
                fill_color='lightgrey',
                align='left',
                font=dict(size=12)
            ),
            cells=dict(
                values=[df[col] for col in df.columns],
                fill_color='white',
                align='left',
                font=dict(size=11),
                height=row_height
            )
        )])

        # Adjust top spacing based on whether detail is present
        if first and detail:
            top_margin = 120  # More space for title + subtitle
            extra_height = 40
        else:
            top_margin = 60  # Small gap even without detail
            extra_height = 20

        fig.update_layout(
            title=dict(
                text=title_texts,
                x=0.5,
                xanchor='center',
                font=dict(size=16)
            ) if title else None,
            autosize=False,
            width=fig_width,
            height=fig_height + extra_height,
            margin=dict(l=20, r=20, t=top_margin, b=20)
        )


        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if output_path.endswith(".png"):
            fig.write_image(output_path, scale=2)
            logger.info(f"Table saved to {output_path}")

        
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

            tables = self.extract_tables_to_dataframes(soup)
            for i, item in enumerate(tables):

                safe_title = safe_filename(tables[0]["title"])  # Always using tables[0]
                output_path = f"images/{safe_title}_{i+1}.png"

                self.save_plotly_table(
                    df=item["data"],
                    output_path=output_path,
                    title=item["title"],
                    detail=item["detail"] if i == 0 else None,
                    first=(i == 0)  # only true for the first table
                )
            
            if self.delay > 0:
                await asyncio.sleep(self.delay)

            return content

        except httpx.TimeoutException:
            logger.error(f"Timeout scraping {url}")
        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")

        return None
    
    @staticmethod
    async def scrape_limited(scraper, client, url, semaphore):
        async with semaphore:
            return await scraper.scrape_url(client, url)

    async def scrape_multiple_urls(self, urls: List[str]) -> List[Dict]:
        """
        Scrape content from multiple URLs using httpx.AsyncClient with HTTP/2.

        Args:
            urls: List of URLs to scrape

        Returns:
            List of dictionaries with scraped content
        """
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        semaphore = asyncio.Semaphore(5)  # Limit concurrent requests to 5

        async with httpx.AsyncClient(http2=True, headers=self.headers, cookies=self.cookies, limits=limits) as client:
            tasks = [WebScraper.scrape_limited(self, client, url, semaphore) for url in urls]
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
            if "aupp.edu.kh" not in parsed.netloc:
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
                    for text in item.get("english_text", []):
                        writer.writerow({"ID": row_id, "English_Text": text, "Khmer_Text": ""})
                        row_id += 1
                    for text in item.get("khmer_text", []):
                        writer.writerow({"ID": row_id, "English_Text": "", "Khmer_Text": text})
                        row_id += 1

            logger.info(f"Data successfully saved to {filename}")
        except Exception as e:
            logger.error(f"Error saving to CSV: {e}")

        return str(file_path)

def safe_filename(text: str, max_length: int = 80) -> str:
    text = re.sub(r"<.*?>", "", text)              # remove HTML tags
    text = re.sub(r"[^\w\s-]", "", text)           # remove punctuation
    text = re.sub(r"\s+", "_", text.strip())       # spaces to underscores
    return text[:max_length]

def remove_global_duplicates(results):
    global_seen_en = set()
    global_seen_km = set()
    new_results = []

    for item in results:
        new_en = []
        for text in item.get("english_text", []):
            if text not in global_seen_en:
                global_seen_en.add(text)
                new_en.append(text)

        new_km = []
        for text in item.get("khmer_text", []):
            if text not in global_seen_km:
                global_seen_km.add(text)
                new_km.append(text)

        if new_en or new_km:
            new_results.append({
                "url": item.get("url", ""),
                "status": item.get("status", ""),
                "english_text": new_en,
                "khmer_text": new_km,
            })

    return new_results

def split_detail_text(detail: str, max_length: int = 80) -> str:
    words = detail.strip().split()
    if len(words) <= 10:
        return detail  # short enough, no need to break

    # Try to break in half
    mid = len(words) // 2
    # Try to break at nearest punctuation after the midpoint
    for i in range(mid, len(words)):
        if words[i][-1] in ".,":
            return " ".join(words[:i+1]) + "<br>" + " ".join(words[i+1:])

    # If no good punctuation, just split in the middle
    return " ".join(words[:mid]) + "<br>" + " ".join(words[mid:])


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
    print("Enter URLs to scrape (e.g., https://www.aupp.edu.kh/harvard-law-professor-speaks-at-aupp/).")
    print("Press Enter on an empty line to start scraping:\n")

    while True:
        url_input = input("  > ").strip()
        if not url_input:
            print("\nStarting scraping...")
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
    results = remove_global_duplicates(results)  # Remove duplicates inside the text lists

    scraper.save_to_csv(results, output_dir="outputs")
    print(f"Scraping completed. Results saved to 'outputs' directory.")

    end_time = time.time()
    print(f"Total time taken: {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(main())