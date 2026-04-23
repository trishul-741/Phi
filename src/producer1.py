import asyncio
import json
import zipfile
import io
import os
import logging
import random
import re
import httpx
import dnstwist
from urllib.parse import urlparse
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("producer")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:19092")
MONGO_URI       = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
PHISHTANK_URL   = os.getenv("PHISHTANK_URL", "http://data.phishtank.com/data/online-valid.json")
TRANCO_URL      = os.getenv("TRANCO_URL", "https://tranco-list.eu/top-1m.csv.zip")
MAX_URLS        = int(os.getenv("MAX_URLS_PER_SOURCE", 50000))
KAFKA_TOPIC     = os.getenv("KAFKA_TOPIC_URLS", "urls_to_scan")
FLUSH_INTERVAL  = int(os.getenv("FLUSH_INTERVAL", 1000))

BRANDS = [
    "paypal.com", "chase.com", "apple.com", "microsoft.com",
    "amazon.com", "google.com", "facebook.com", "netflix.com"
]

db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.phish_guard

def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc) and len(url) < 2048
    except Exception:
        return False

def sanitize_id(value: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', str(value))

async def safe_send(producer: AIOKafkaProducer, topic: str, payload: dict, retries: int = 3):
    for attempt in range(1, retries + 1):
        try:
            await producer.send_and_wait(topic, json.dumps(payload).encode("utf-8"))
            return True
        except KafkaError as e:
            wait = 2 ** attempt + random.uniform(0, 1)
            await asyncio.sleep(wait)
        except Exception:
            return False
    return False

async def fetch_phishtank(producer: AIOKafkaProducer):
    logger.info("[PhishTank] Fetching feed...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        try:
            response = await client.get(PHISHTANK_URL, timeout=30.0)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"[PhishTank] Request error: {e}")
            return

    count = 0
    skipped = 0

    for entry in data:
        if count >= MAX_URLS:
            break

        target_url = entry.get('url')
        if not target_url or not is_valid_url(target_url):
            skipped += 1
            continue

        if await db.scans.find_one({"url": target_url}):
            skipped += 1
            continue

        payload = {
            "url": target_url,
            "type": "phishing",
            "source": "phishtank",
            "id": sanitize_id(entry.get('phish_id', f"pt_{count}")),
            "retries": 0,
        }

        sent = await safe_send(producer, KAFKA_TOPIC, payload)
        if sent:
            count += 1

        if count % FLUSH_INTERVAL == 0:
            await producer.flush()
            logger.info(f"[PhishTank] Queued {count} URLs (skipped {skipped} invalid/duplicates)")

    await producer.flush()
    logger.info(f"[PhishTank] Done. Queued: {count} | Skipped: {skipped}")

async def fetch_tranco(producer: AIOKafkaProducer):
    logger.info("[Tranco] Fetching top-1M list...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        try:
            response = await client.get(TRANCO_URL, timeout=60.0)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"[Tranco] Request error: {e}")
            return

    count = 0
    skipped = 0

    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            csv_filename = z.namelist()[0]
            with z.open(csv_filename) as f:
                for raw_line in f:
                    if count >= MAX_URLS:
                        break

                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    parts = line.split(",")

                    if len(parts) < 2 or not parts[1].strip():
                        skipped += 1
                        continue

                    target_url = f"https://{parts[1].strip()}"

                    if not is_valid_url(target_url):
                        skipped += 1
                        continue
                        
                    if await db.scans.find_one({"url": target_url}):
                        skipped += 1
                        continue

                    payload = {
                        "url": target_url,
                        "type": "legitimate",
                        "source": "tranco",
                        "id": sanitize_id(f"tranco_{count}"),
                        "retries": 0,
                    }

                    sent = await safe_send(producer, KAFKA_TOPIC, payload)
                    if sent:
                        count += 1

                    if count % FLUSH_INTERVAL == 0:
                        await producer.flush()
                        logger.info(f"[Tranco] Queued {count} URLs (skipped {skipped} invalid/duplicates)")

    except zipfile.BadZipFile as e:
        logger.error(f"[Tranco] Failed to parse ZIP: {e}")
        return

    await producer.flush()
    logger.info(f"[Tranco] Done. Queued: {count} | Skipped: {skipped}")

async def generate_zero_day_lexical(producer: AIOKafkaProducer):
    logger.info("[DNSTwist] Starting domain permutation generation...")
    count = 0
    skipped = 0

    for brand in BRANDS:
        if count >= MAX_URLS:
            break

        try:
            fuzzer = dnstwist.Fuzzer(brand)
            await asyncio.to_thread(fuzzer.generate)

            for domain in fuzzer.domains:
                if count >= MAX_URLS:
                    break

                domain_name = domain.get("domain") or domain.get("domain-name")
                if not domain_name:
                    skipped += 1
                    continue

                target_url = f"http://{domain_name}"

                if not is_valid_url(target_url):
                    skipped += 1
                    continue
                    
                if await db.scans.find_one({"url": target_url}):
                    skipped += 1
                    continue

                payload = {
                    "url": target_url,
                    "type": "phishing",
                    "source": "dnstwist",
                    "id": sanitize_id(f"zd_{count}"),
                    "brand": brand,
                    "retries": 0,
                }

                sent = await safe_send(producer, KAFKA_TOPIC, payload)
                if sent:
                    count += 1

                if count % FLUSH_INTERVAL == 0:
                    await producer.flush()

        except Exception:
            continue

    await producer.flush()
    logger.info(f"[DNSTwist] Done. Total Queued: {count} | Skipped: {skipped}")

async def main():
    logger.info("[System] Connecting to Kafka broker...")

    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        request_timeout_ms=30000,
        metadata_max_age_ms=15000,
        enable_idempotence=True,
        acks="all",                         
        compression_type="gzip",            
        max_batch_size=65536,
        linger_ms=100,                      
    )

    try:
        await producer.start()
        logger.info("[System] Kafka Connected. Starting all sources concurrently...")

        await asyncio.gather(
            fetch_phishtank(producer),
            fetch_tranco(producer),
            generate_zero_day_lexical(producer),
        )

    except Exception as e:
        logger.critical(f"[System] Fatal error in producer: {type(e).__name__}: {e}")
        raise
    finally:
        logger.info("[System] Flushing and stopping producer...")
        await producer.flush()
        await producer.stop()
        logger.info("[System] Producer shut down cleanly.")

if __name__ == "__main__":
    asyncio.run(main())