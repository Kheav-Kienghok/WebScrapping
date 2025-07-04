# 🕸️ WebScraper for AUPP and Related Sites

This project is an asynchronous web scraper built in Python that extracts English and Khmer content from structured web pages such as those from `https://www.aupp.edu.kh`. It automatically classifies text by language and saves the results to a CSV file for further analysis.

---

## 🚀 Features

- ✅ **Asynchronous scraping** with `httpx` + `asyncio` for high performance
- 🌐 **HTTP/2 support** with custom headers and user-agent rotation
- 🌍 **Auto language detection** (English / Khmer) using `langdetect`
- 📤 **Clean CSV export** with deduplicated content
- 🕓 **Rate limiting** and retry logic for large scraping batches
- 📊 **Logging system** for debugging and monitoring
- 🎯 **Robots.txt compliance** checking

---

## � Project Structure

```
Web_Scrapping/
├── main.py                    # Main scraper script
├── get_cookies_playwright.py  # Cookie extraction utility
├── CrawlRobots.py            # Robots.txt checker
├── requirements.txt          # Python dependencies
├── aupp.edu.kh_page_urls.txt # Sample URLs for testing
├── outputs/                  # Generated CSV files
└── scraper.log              # Application logs
```

---

## 📦 Installation

### Prerequisites
- Python 3.13
- pip package manager

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Kheav-Kienghok/WebScrapping.git
   cd WebScrapping
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## 🧪 Usage

### Basic Usage

Run the main scraper:
```bash
python main.py
```

The script will prompt you to enter URLs:
- Enter one URL per line
- Press Enter on an empty line to start scraping
- The scraper will process all URLs asynchronously

### Advanced Usage

**Check robots.txt compliance:**
```bash
python CrawlRobots.py
```

**Extract cookies using Playwright:**
```bash
python get_cookies_playwright.py
```

---

## 📊 Output

### CSV Files
Scraped results are saved in timestamped CSV files in the `outputs/` directory:
```
outputs/scraped_content_YYYYMMDD_HHMMSS.csv
```

### CSV Structure
| Column | Description |
|--------|-------------|
| `ID` | Unique identifier for each scraped item |
| `English_Text` | Extracted English content |
| `Khmer_Text` | Extracted Khmer content |

> **Note:** Each row contains only one type of text for clean alignment and further processing.

### Logging
Application logs are saved to `scraper.log` with detailed information about:
- Scraping progress
- Error handling
- Rate limiting
- Language detection results

---

## ⚙️ Configuration

### Rate Limiting
The scraper includes built-in rate limiting to respect target servers:
- Default delay between requests: 1-2 seconds
- Configurable retry attempts for failed requests
- Automatic backoff on rate limit responses

### Language Detection
- Uses `langdetect` library for automatic language classification
- Supports English and Khmer text detection
- Fallback handling for undetected languages

---

## 📋 Requirements

Main dependencies:
- `httpx` - Async HTTP client
- `beautifulsoup4` - HTML parsing
- `langdetect` - Language detection
- `python-dotenv` - Environment variable management
- `playwright` - Browser automation (for cookie extraction)

For a complete list, see `requirements.txt`.

---

## ⚠️ Disclaimer

This tool is for educational and research purposes only. Please ensure you:
- Respect robots.txt files
- Follow website terms of service
- Use appropriate rate limiting
- Obtain necessary permissions before scraping