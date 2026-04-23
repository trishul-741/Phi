import asyncio
import os
import socket
import logging
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient

logging.basicConfig(level=logging.WARNING)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:19092")
HOST = KAFKA_BOOTSTRAP.split(":")[0]
PORT = int(KAFKA_BOOTSTRAP.split(":")[1])

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg):  print(f"  {RED}❌ {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}⚠️  {msg}{RESET}")
def info(msg):  print(f"  {CYAN}ℹ️  {msg}{RESET}")
def header(msg):print(f"\n{BOLD}{'─'*50}\n  {msg}\n{'─'*50}{RESET}")


# ─────────────────────────────────────────────
# Step 1: Raw TCP connection check
# ─────────────────────────────────────────────
def check_tcp():
    header("STEP 1 — TCP Connection to Kafka Broker")
    info(f"Trying to connect to {HOST}:{PORT} ...")
    try:
        sock = socket.create_connection((HOST, PORT), timeout=5)
        sock.close()
        ok(f"TCP connection to {HOST}:{PORT} succeeded.")
        return True
    except socket.timeout:
        fail(f"Connection to {HOST}:{PORT} TIMED OUT.")
        warn("Kafka broker is not reachable. Is it running?")
        return False
    except ConnectionRefusedError:
        fail(f"Connection to {HOST}:{PORT} REFUSED.")
        warn("Kafka is not running on this port. Check your docker-compose or Kafka config.")
        return False
    except Exception as e:
        fail(f"Unexpected TCP error: {e}")
        return False


# ─────────────────────────────────────────────
# Step 2: Kafka broker metadata check
# ─────────────────────────────────────────────
async def check_broker():
    header("STEP 2 — Kafka Broker Metadata")
    admin = AIOKafkaAdminClient(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        request_timeout_ms=8000,
    )
    try:
        await admin.start()
        ok("Successfully connected to Kafka broker.")

        topics = await admin.list_topics()
        if topics:
            ok(f"Broker is active. Found {len(topics)} topic(s):")
            for t in sorted(topics):
                info(f"  → {t}")
        else:
            warn("Broker connected but NO topics exist yet.")
            info("Run producer1.py first to create and populate topics.")

        return True

    except Exception as e:
        fail(f"Could not connect to Kafka broker: {type(e).__name__}: {e}")
        warn("Possible causes:")
        info("  1. Kafka container/service is not running")
        info("  2. Wrong port in KAFKA_BOOTSTRAP env variable")
        info("  3. Firewall blocking the port")
        return False
    finally:
        try:
            await admin.close()
        except Exception:
            pass


# ─────────────────────────────────────────────
# Step 3: Try publishing a test message
# ─────────────────────────────────────────────
async def check_producer():
    header("STEP 3 — Producer Test (Publish 1 message)")
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        request_timeout_ms=8000,
    )
    try:
        await producer.start()
        await producer.send_and_wait(
            "kafka_diagnostics_test",
            b'{"test": "ping", "source": "kafka_diagnose.py"}'
        )
        ok("Successfully published a test message to 'kafka_diagnostics_test' topic.")
        return True
    except Exception as e:
        fail(f"Producer failed: {type(e).__name__}: {e}")
        return False
    finally:
        try:
            await producer.stop()
        except Exception:
            pass


# ─────────────────────────────────────────────
# Step 4: Check offsets for PhishGuard topics
# ─────────────────────────────────────────────
async def check_topic_offsets():
    header("STEP 4 — PhishGuard Topic Offset Check")
    topics = ["urls_to_scan", "artifacts_ready", "urls_failed"]

    consumer = AIOKafkaConsumer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="diagnostics-checker",
        enable_auto_commit=False,
        request_timeout_ms=8000,
    )
    try:
        await consumer.start()
        await asyncio.sleep(3)  # Wait for metadata

        for topic in topics:
            partitions = consumer.partitions_for_topic(topic)
            if not partitions:
                warn(f"Topic '{topic}': Does not exist or has 0 messages.")
                continue

            from aiokafka import TopicPartition
            tps = [TopicPartition(topic, p) for p in sorted(partitions)]
            beginning = await consumer.beginning_offsets(tps)
            end = await consumer.end_offsets(tps)
            total = sum(end[tp] - beginning[tp] for tp in tps)

            if total > 0:
                ok(f"Topic '{topic}': {total:,} messages")
            else:
                warn(f"Topic '{topic}': Exists but 0 messages published yet.")

    except Exception as e:
        fail(f"Consumer check failed: {type(e).__name__}: {e}")
    finally:
        try:
            await consumer.stop()
        except Exception:
            pass


# ─────────────────────────────────────────────
# Step 5: Print resolution guide
# ─────────────────────────────────────────────
def print_resolution_guide():
    header("STEP 5 — Resolution Guide")
    print(f"""
  {BOLD}If Kafka is NOT running:{RESET}
  Start it with Docker:
  {CYAN}  docker-compose up -d{RESET}

  Or start manually (Redpanda):
  {CYAN}  docker run -d --name redpanda -p 19092:19092 \\
    redpandadata/redpanda:latest \\
    redpanda start --overprovisioned \\
    --kafka-addr PLAINTEXT://0.0.0.0:19092{RESET}

  {BOLD}If Kafka IS running but topics are empty:{RESET}
  {CYAN}  python .\\src\\producer1.py{RESET}
  Then re-run:
  {CYAN}  python .\\utils\\kafka_stats.py{RESET}

  {BOLD}If wrong port:{RESET}
  Set the correct bootstrap in your .env:
  {CYAN}  KAFKA_BOOTSTRAP=localhost:9092   # standard Kafka
  {CYAN}  KAFKA_BOOTSTRAP=localhost:19092  # Redpanda default{RESET}
""")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
async def main():
    print(f"\n{BOLD}{CYAN}{'═'*50}")
    print(f"  🔍 PhishGuard — Kafka Diagnostic Tool")
    print(f"  Broker: {KAFKA_BOOTSTRAP}")
    print(f"{'═'*50}{RESET}")

    # Step 1: TCP (sync)
    tcp_ok = check_tcp()
    if not tcp_ok:
        print_resolution_guide()
        return

    # Step 2: Broker metadata
    broker_ok = await check_broker()
    if not broker_ok:
        print_resolution_guide()
        return

    # Step 3: Producer test
    await check_producer()

    # Step 4: Topic offsets
    await check_topic_offsets()

    # Step 5: Guide
    print_resolution_guide()

    print(f"\n{BOLD}{'═'*50}")
    print(f"  Diagnostic complete.")
    print(f"{'═'*50}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())