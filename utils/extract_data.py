import os
import json
import pandas as pd
from pymongo import MongoClient
from tqdm import tqdm

# --- Configuration ---
MONGO_URI = "mongodb://127.0.0.1:27017/"
DB_NAME = "phish_guard"
COLLECTION_NAME = "scans"
# The directory where calibrate.py/train.py expect files
LOCAL_DATASET_DIR = "./local_dataset" 

def export_data_for_kaggle():
    # 1. Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # 2. Fetch records
    # We filter for 'success' and presence of the text key
    query = {"status": "success", "minio_txt_key": {"$exists": True}}
    records = list(collection.find(query))
    print(f"Found {len(records)} records to export.")

    # 3. Setup local storage
    os.makedirs(LOCAL_DATASET_DIR, exist_ok=True)
    
    exported_rows = []

    # 4. Process and Save
    for rec in tqdm(records, desc="Exporting"):
        txt_key = rec["minio_txt_key"]
        
        # In a real senior-dev scenario, you'd fetch from MinIO here.
        # Since your preprocessing.py reads from LOCAL_DATASET_DIR,
        # we ensure the folder structure exists for the text files.
        local_txt_path = os.path.join(LOCAL_DATASET_DIR, txt_key)
        os.makedirs(os.path.dirname(local_txt_path), exist_ok=True)

        # Logic to "Save Locally": 
        # If the files are already in your local MinIO path, 
        # ensure they are copied to LOCAL_DATASET_DIR.
        
        exported_rows.append({
            "url": rec["url"],
            "label": rec.get("label", ""),
            "source": rec.get("source", "unknown"),
            "minio_txt_key": txt_key
        })

    # 5. Create the Metadata Manifest
    # This CSV tells the Kaggle version of build_dataframe() what to load
    df = pd.DataFrame(exported_rows)
    df.to_csv("metadata.csv", index=False)
    
    print("\nExport Complete.")
    print(f"1. Upload '{LOCAL_DATASET_DIR}' folder to Kaggle Dataset (contains .txt files).")
    print(f"2. Upload 'metadata.csv' to Kaggle Dataset.")

if __name__ == "__main__":
    export_data_for_kaggle()