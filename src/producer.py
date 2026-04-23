import json
import requests
import zipfile
import io
import os
from kafka import KafkaProducer
from config import db

PRODUCER = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "localhost:19092"),
    value_serializer=lambda x: json.dumps(x).encode('utf-8')
)

def fetch_phishtank():
    print("Fetching PhishTank feed...")
    url = "http://data.phishtank.com/data/online-valid.json" 
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status() # Fails fast if blocked (403/429)
        data = response.json()
        
        count = 0
        for entry in data[:]: 
            target_url = entry['url']
            
            if db.scans.find_one({"url": target_url}):
                continue

            payload = {
                "url": target_url,
                "type": "phishing",
                "source": "phishtank",
                "id": entry['phish_id']
            }
            PRODUCER.send('urls_to_scan', value=payload)
            count += 1
            
        print(f"Queued {count} new phishing URLs.")
        PRODUCER.flush()
    except Exception as e:
        print(f"Error fetching feed: {e}")

def fetch_tranco_legit():
    print("Fetching Tranco Top 1M legitimate list...")
    url = "https://tranco-list.eu/top-1m.csv.zip"
    try:
        response = requests.get(url, timeout=30)
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            csv_filename = z.namelist()[0]
            with z.open(csv_filename) as f:
                count = 0
                for line in f:
                    if count >= 50000: # Limit to 5000 for testing
                        break
                    
                    # Tranco format is "rank,domain"
                    domain = line.decode('utf-8').strip().split(',')[1]
                    target_url = f"http://{domain}"
                    
                    if db.scans.find_one({"url": target_url}):
                        continue
                        
                    payload = {
                        "url": target_url,
                        "type": "legitimate",
                        "source": "tranco",
                        "id": count + 1
                    }
                    PRODUCER.send('urls_to_scan', value=payload)
                    count += 1
                    
        print(f"Queued {count} legitimate URLs.")
        PRODUCER.flush()
    except Exception as e:
        print(f"Error fetching Tranco: {e}")

if __name__ == "__main__":
    fetch_phishtank()
    fetch_tranco_legit()