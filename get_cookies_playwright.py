import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def get_cookies_as_dict(url: str) -> dict:
    """
    Uses Playwright to visit a page and return cookies as a dictionary.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(url)
        
        # Ensure all DOM and JS content is loaded
        await page.wait_for_load_state("networkidle")  # wait until no network for 500ms
        await asyncio.sleep(10) 
        await page.wait_for_timeout(10000)  # wait 10 seconds more just in case

        cookies = await context.cookies()

        # You can close the browser after you’re done
        await browser.close()

        return {cookie['name']: cookie['value'] for cookie in cookies}

def save_cookies_to_file(cookie_dict: dict, filename: str = "outputs/cookies.json") -> None:
    """
    Save cookies as a JSON file.
    """
    output_path = Path(filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(cookie_dict, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    url = input("Enter the URL to scrape cookies from: ").strip()
    cookies = asyncio.run(get_cookies_as_dict(url))
    print("Cookies:", cookies)

    save_cookies_to_file(cookies, "output/aupp_cookies.json")
