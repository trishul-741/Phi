import os
import concurrent.futures
import boto3
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
if not MINIO_ENDPOINT.startswith("http"):
    MINIO_ENDPOINT = f"http://{MINIO_ENDPOINT}"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "password123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "dl-artifacts")
LOCAL_DIR = "./local_dataset"

def download_artifact(txt_key):
    s3_client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY
    )
    
    local_path = os.path.join(LOCAL_DIR, txt_key).replace("\\", "/")
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    if not os.path.exists(local_path):
        try:
            s3_client.download_file(MINIO_BUCKET, txt_key, local_path)
        except Exception as e:
            print(f"Failed to download {txt_key}: {e}")

if __name__ == "__main__":
    db_client = MongoClient(MONGO_URI)
    db = db_client.phish_guard
    
    print("Fetching records from MongoDB...")
    raw_records = list(db.scans.find({"status": "success", "minio_txt_key": {"$exists": True}}))
    
    seen_keys = set()
    unique_keys = []
    for r in raw_records:
        key = r.get("minio_txt_key")
        if key and key not in seen_keys:
            seen_keys.add(key)
            unique_keys.append(key)
            
    print(f"Found {len(unique_keys)} unique files to download. Starting extraction...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        list(executor.map(download_artifact, unique_keys))
        
    print("Extraction complete.")