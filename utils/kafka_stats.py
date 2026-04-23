import asyncio
import os
import logging
from aiokafka import AIOKafkaConsumer, TopicPartition

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,  # Suppress aiokafka internal noise
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:19092")
TOPICS = [
    "urls_to_scan",
    "artifacts_ready",
    "urls_failed",
]

METADATA_WAIT_S = 3  # Seconds to wait for broker metadata to load


# ─────────────────────────────────────────────
# Core: Get message count for one topic
# ─────────────────────────────────────────────
async def get_topic_message_count(topic: str) -> dict:
    """
    Returns a dict with per-partition counts and a total.
    FIX 1: Uses group_id="stats-checker" to avoid coordinator CancelledError.
    FIX 2: Waits for metadata to load before calling partitions_for_topic().
    FIX 3: Wraps consumer.stop() in try/except to handle shutdown cleanly.
    """
    consumer = AIOKafkaConsumer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="stats-checker",           # FIX 1: Prevents coordinator crash
        auto_offset_reset="earliest",
        enable_auto_commit=False,           # Read-only — never commit offsets
        request_timeout_ms=10000,
        metadata_max_age_ms=5000,
    )

    try:
        await consumer.start()

        # FIX 2: Give broker time to sync metadata before querying partitions
        await asyncio.sleep(METADATA_WAIT_S)

        partitions = consumer.partitions_for_topic(topic)

        if not partitions:
            return {"error": f"Topic '{topic}' not found or has no messages yet."}

        # Build TopicPartition objects for all partitions
        tps = [TopicPartition(topic, p) for p in sorted(partitions)]

        # Fetch beginning and end offsets
        beginning_offsets = await consumer.beginning_offsets(tps)
        end_offsets        = await consumer.end_offsets(tps)

        result = {}
        total = 0

        for tp in tps:
            start  = beginning_offsets[tp]
            end    = end_offsets[tp]
            count  = end - start
            result[f"partition_{tp.partition}"] = {
                "start_offset": start,
                "end_offset":   end,
                "message_count": count,
            }
            total += count

        result["total"] = total
        return result

    except Exception as e:
        return {"error": str(e)}

    finally:
        # FIX 3: Always attempt clean shutdown, suppress CancelledError
        try:
            await consumer.stop()
        except Exception:
            pass  # Safe to ignore shutdown errors in a stats-only script


# ─────────────────────────────────────────────
# Pretty Print Helper
# ─────────────────────────────────────────────
def print_topic_stats(topic: str, result: dict):
    BOLD  = "\033[1m"
    GREEN = "\033[92m"
    RED   = "\033[91m"
    CYAN  = "\033[96m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN}{'─' * 50}{RESET}")
    print(f"{BOLD}📊 Topic: {topic}{RESET}")
    print(f"{'─' * 50}")

    if "error" in result:
        print(f"  {RED}⚠  {result['error']}{RESET}")
        return

    for key, val in result.items():
        if key == "total":
            continue
        p = val
        print(
            f"  Partition {key.split('_')[1]:>3} │ "
            f"Start: {p['start_offset']:>10,} │ "
            f"End: {p['end_offset']:>10,} │ "
            f"Messages: {p['message_count']:>10,}"
        )

    total = result.get("total", 0)
    color = GREEN if total > 0 else RED
    print(f"{'─' * 50}")
    print(f"  {BOLD}{color}TOTAL MESSAGES : {total:,}{RESET}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
async def main():
    print(f"\n🔌 Connecting to Kafka at {KAFKA_BOOTSTRAP}...")
    print(f"⏳ Waiting {METADATA_WAIT_S}s for broker metadata to load...\n")

    grand_total = 0

    for topic in TOPICS:
        result = await get_topic_message_count(topic)
        print_topic_stats(topic, result)
        if "total" in result:
            grand_total += result["total"]

    print(f"\n{'═' * 50}")
    print(f"  \033[1m\033[93m GRAND TOTAL (all topics) : {grand_total:,}\033[0m")
    print(f"{'═' * 50}\n")


if __name__ == "__main__":
    asyncio.run(main())