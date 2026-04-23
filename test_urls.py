import asyncio
import httpx
from playwright.async_api import async_playwright

urls = [
    "https://unsplash.com/",
    "https://www.linkedin.com/feed/",
    "https://www.coeptech.ac.in/",
    "https://www.vit.edu/"
]

api_url = "http://127.0.0.1:8000/predict"

async def extract_html(page, url):
    try:
        await page.goto(url, timeout=15000)
        await page.wait_for_load_state("domcontentloaded")
        content = await page.content()
        return content
    except Exception as e:
        print(f"Failed to fetch {url} fully via Playwright: {e}")
        return ""

async def test_urls():
    print("Starting tests...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for url in urls:
                print(f"\n--- Testing: {url} ---")
                html_content = await extract_html(page, url)
                if not html_content:
                    print("Warning: HTML content is empty or fetch failed. Proceeding with empty HTML.")
                
                payload = {
                    "url": url,
                    "html_content": html_content
                }
                
                try:
                    response = await client.post(api_url, json=payload)
                    if response.status_code == 200:
                        data = response.json()
                        print(f"Status: {data.get('status')}")
                        print(f"Confidence: {data.get('confidence'):.4f}")
                    else:
                        print(f"API Error. Status Code: {response.status_code}")
                        print(f"Response: {response.text}")
                except Exception as e:
                    print(f"Failed to connect to API: {e}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_urls())
