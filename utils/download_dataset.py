import os
from minio import Minio
from pymongo import MongoClient
from tqdm import tqdm

client = Minio("localhost:9000",
               access_key="admin",
               secret_key="password123",
               secure=False)

# Minio's list_objects crashes with OOMs when iterating millions of items 
# because of the xl.meta flat directory structure cache. We query mongo directly instead.
mongo_client = MongoClient("localhost:27017")
db = mongo_client["phish_guard"]
records = list(db["scans"].find({"status": "success"}))
txt_objects = [r.get("minio_txt_key") for r in records if r.get("minio_txt_key")]
print(f"Found {len(txt_objects):,} text files to download")

for obj_name in tqdm(txt_objects, desc="Downloading"):
    local_path = os.path.join("./local_dataset", obj_name)
    if os.path.exists(local_path):
        continue # Skip already downloaded
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    try:
        client.fget_object("dl-artifacts", obj_name, local_path)
    except Exception as e:
        pass

print("Download complete.")