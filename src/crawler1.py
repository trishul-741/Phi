import asyncio
import json
import io
import os
import logging
import random
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError
from motor.motor_asyncio import AsyncIOMotorClient
from playwright.async_api import async_playwright, BrowserContext
from playwright_stealth import stealth_async
from minio import Minio
from minio.error import S3Error
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("crawler")

MONGO_URI          = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
KAFKA_BOOTSTRAP    = os.getenv("KAFKA_BOOTSTRAP", "localhost:19092")
KAFKA_GROUP_ID     = os.getenv("KAFKA_GROUP_ID", "crawler-group")
KAFKA_TOPIC_IN     = os.getenv("KAFKA_TOPIC_URLS", "urls_to_scan")
KAFKA_TOPIC_OUT    = os.getenv("KAFKA_TOPIC_ARTIFACTS", "artifacts_ready")
KAFKA_TOPIC_DLQ    = os.getenv("KAFKA_TOPIC_DLQ", "urls_failed")
MAX_CONCURRENCY    = int(os.getenv("MAX_CONCURRENCY", 12))
MAX_PENDING_TASKS  = MAX_CONCURRENCY
PAGE_TIMEOUT_MS    = int(os.getenv("PAGE_TIMEOUT_MS", 15000))
POLITENESS_MIN_S   = float(os.getenv("POLITENESS_MIN_S", 0.5))
POLITENESS_MAX_S   = float(os.getenv("POLITENESS_MAX_S", 2.0))
MINIO_ENDPOINT     = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_BUCKET       = os.getenv("MINIO_BUCKET", "dl-artifacts")

MINIO_ACCESS_KEY   = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY   = os.getenv("MINIO_SECRET_KEY", "password123")
MINIO_SECURE       = os.getenv("MINIO_SECURE", "false").lower() == "true"

db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.phish_guard

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

async def ensure_bucket():
    loop = asyncio.get_running_loop()
    try:
        exists = await loop.run_in_executor(None, minio_client.bucket_exists, MINIO_BUCKET)
        if not exists:
            await loop.run_in_executor(None, minio_client.make_bucket, MINIO_BUCKET)
    except S3Error as e:
        logger.critical(f"[MinIO] Failed to ensure bucket: {e}")
        raise

def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc) and len(url) < 2048
    except Exception:
        return False

def safe_key_segment(value: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', value)

async def upload_to_minio(loop, key: str, data: bytes):
    await loop.run_in_executor(
        None,
        lambda: minio_client.put_object(
            MINIO_BUCKET,
            key,
            io.BytesIO(data),
            len(data),
            content_type="application/octet-stream"
        )
    )

async def process_url(browser, payload: dict, semaphore: asyncio.Semaphore, producer: AIOKafkaProducer):
    async with semaphore:
        required_keys = {'url', 'type', 'source', 'id'}
        if not required_keys.issubset(payload.keys()):
            return

        target_url = payload['url']
        if not is_valid_url(target_url):
            return

        context: BrowserContext = await browser.new_context(
            java_script_enabled=True,
            bypass_csp=True,
            ignore_https_errors=True,
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = await context.new_page()
        await stealth_async(page)
        loop = asyncio.get_running_loop()

        safe_type   = safe_key_segment(payload['type'])
        safe_source = safe_key_segment(payload['source'])
        safe_id     = safe_key_segment(str(payload['id']))
        prefix      = f"{safe_type}/{safe_source}_{safe_id}"

        try:
            response = await page.goto(target_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            await page.wait_for_timeout(2000)
            await asyncio.sleep(random.uniform(POLITENESS_MIN_S, POLITENESS_MAX_S))

            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            visible_text = soup.get_text(separator=' ', strip=True)

            txt_bytes  = visible_text.encode('utf-8')
            html_bytes = html_content.encode('utf-8')

            txt_key  = f"{prefix}.txt"
            html_key = f"{prefix}.html"

            await asyncio.gather(
                upload_to_minio(loop, txt_key, txt_bytes),
                upload_to_minio(loop, html_key, html_bytes),
            )

            http_status = response.status if response else None
            meta_doc = {
                "url":            target_url,
                "label":          payload['type'],
                "source":         payload['source'],
                "minio_txt_key":  txt_key,
                "minio_html_key": html_key,
                "http_status":    http_status,
                "status":         "success",
            }

            await db.scans.insert_one(meta_doc)
            meta_doc.pop("_id", None)
            await producer.send_and_wait(KAFKA_TOPIC_OUT, json.dumps(meta_doc).encode('utf-8'))
            logger.info(f"[Crawler] ✅ Success: {target_url}")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            await db.scans.insert_one({
                "url":    target_url,
                "label":  payload.get('type'),
                "source": payload.get('source'),
                "status": "failed",
                "error":  error_msg,
            })

            retry_count = payload.get("retries", 0)
            if retry_count < 3:
                dlq_payload = {**payload, "retries": retry_count + 1, "last_error": error_msg}
                try:
                    await producer.send_and_wait(KAFKA_TOPIC_DLQ, json.dumps(dlq_payload).encode('utf-8'))
                except KafkaError:
                    pass
        finally:
            await page.close()
            await context.close()

async def run_crawler():
    await ensure_bucket()

    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC_IN,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        auto_commit_interval_ms=5000,
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        max_poll_records=MAX_CONCURRENCY,
    )

    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        enable_idempotence=True,
        acks="all",
        compression_type="gzip",
    )

    await consumer.start()
    await producer.start()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )

        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        tasks: set = set()

        try:
            async for message in consumer:
                while len(tasks) >= MAX_PENDING_TASKS:
                    await asyncio.sleep(0.1)

                task = asyncio.create_task(process_url(browser, message.value, semaphore, producer))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await consumer.stop()
            await producer.flush()
            await producer.stop()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_crawler())