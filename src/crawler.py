import asyncio
import json
import os
from io import BytesIO
from kafka import KafkaConsumer
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from config import s3_client, db

async def process_url(context, message, semaphore):
    async with semaphore:  # STRICTLY LIMIT CONCURRENCY
        page = await context.new_page()
        await stealth_async(page)  # Activate Stealth Mode
        
        data = message.value
        url = data['url']
        
        try:
            print(f"Processing: {url}")
            # 1. Anti-Evasion Navigation
            # Wait for network idle (waits for background AJAX to finish)
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # 2. Simulate Human Behavior (Mouse Jiggle)
            await page.mouse.move(100, 100)
            await page.mouse.down()
            await page.mouse.move(200, 200)
            await page.mouse.up()
            
            # 3. Capture Data
            screenshot = await page.screenshot(full_page=True, type='png')
            html = await page.content()
            
            # 4. Save to MinIO (Screenshots)
            filename = f"{data['type']}/{data['source']}_{data['id']}.png"
            s3_client.put_object(
                Bucket="screenshots",
                Key=filename,
                Body=BytesIO(screenshot)
            )
            
            # 5. Save Metadata to Mongo
            db.scans.insert_one({
                "url": url,
                "phish_id": data.get('id'),
                "s3_key": filename,
                "html_content": html,
                "label": data['type'], # 1 for phishing, 0 for legit
                "status": "success"
            })
            print(f"✅ Saved: {url}")

        except Exception as e:
            print(f"❌ Failed {url}: {e}")
            # Log failure to DB so we don't retry forever
            db.scans.insert_one({"url": url, "status": "failed", "error": str(e)})
        finally:
            await page.close()

async def run_crawler():
    print("[DEBUG] 1. Initializing Kafka Consumer...")
    consumer = KafkaConsumer(
        'urls_to_scan',
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "localhost:19092"),
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        auto_offset_reset='earliest',
        group_id='crawler_test_3'  # Changed to 3 to force re-reading the 100 URLs
    )
    print("[DEBUG] 2. Successfully connected to Redpanda Queue.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        print("[DEBUG] 3. Playwright browser launched.")
        
        semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENCY", 2)))
        tasks = []
        
        print("[DEBUG] 4. Listening for URLs...")
        while True:
            # 1. Non-blocking pull from the queue
            msg_pack = consumer.poll(timeout_ms=500)
            
            for tp, messages in msg_pack.items():
                for message in messages:
                    print(f"[DEBUG] Fetched from queue: {message.value.get('url')}")
                    task = asyncio.create_task(process_url(context, message, semaphore))
                    tasks.append(task)
            
            # 2. CRITICAL: Pause the while loop for a millisecond to let Playwright do the work!
            await asyncio.sleep(0.1)
            
            # 3. Clean up finished tasks from memory
            tasks = [t for t in tasks if not t.done()]

if __name__ == "__main__":
    asyncio.run(run_crawler())