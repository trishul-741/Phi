import os
import torch
import boto3
from pymongo import MongoClient
from torch.utils.data import Dataset, DataLoader
from transformers import DistilBertTokenizer
from dotenv import load_dotenv

load_dotenv()

class PhishingDataset(Dataset):
    def __init__(self, use_direct_minio=True, local_dir="./local_dataset", max_length=512):
        """
        Set use_direct_minio=True to stream directly from MinIO (Saves disk space).
        Set use_direct_minio=False to read from local disk (Faster GPU training, requires running extract_local.py first).
        """
        self.use_direct_minio = use_direct_minio
        self.local_dir = local_dir
        self.max_length = max_length
        
        mongo_client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
        db = mongo_client.phish_guard
        self.records = list(db.scans.find({"status": "success", "minio_txt_key": {"$exists": True}}))
        
        self.tokenizer = DistilBertTokenizer.from_pretrained('distilbert-base-uncased')
        self.chars = "abcdefghijklmnopqrstuvwxyz0123456789-,;.!?:'\"/\\|_@#$%^&*~`+-=<>()[]{}"
        self.char_dict = {c: i + 1 for i, c in enumerate(self.chars)}
        
        self.s3_client = None 

    def _init_s3(self):
        if self.s3_client is None:
            endpoint = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
            if not endpoint.startswith("http"):
                endpoint = f"http://{endpoint}"
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "admin"),
                aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", "password123")
            )

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx):
        record = self.records[idx]
        label = 1 if record['label'] == 'phishing' else 0
        
        url = record['url'].lower()
        url_tensor = torch.zeros(200, dtype=torch.long)
        for i, char in enumerate(url[:200]):
            url_tensor[i] = self.char_dict.get(char, 0)
            
        text_content = ""
        txt_key = record['minio_txt_key']
        
        if self.use_direct_minio:
            self._init_s3()
            try:
                obj = self.s3_client.get_object(Bucket=os.getenv("MINIO_BUCKET", "dl-artifacts"), Key=txt_key)
                text_content = obj['Body'].read().decode('utf-8', errors='ignore')
            except Exception:
                pass
        else:
            try:
                with open(os.path.join(self.local_dir, txt_key), "r", encoding="utf-8") as f:
                    text_content = f.read()
            except Exception:
                pass
                
        inputs = self.tokenizer(
            text_content, 
            return_tensors='pt', 
            max_length=self.max_length, 
            padding='max_length', 
            truncation=True
        )
        
        return {
            'input_ids': inputs['input_ids'].squeeze(0),
            'attention_mask': inputs['attention_mask'].squeeze(0),
            'url_tensor': url_tensor,
            'label': torch.tensor(label, dtype=torch.float32)
        }

if __name__ == "__main__":
    dataset = PhishingDataset(use_direct_minio=True) 
    dataloader = DataLoader(dataset, batch_size=32, shuffle=True, num_workers=4)
    
    batch = next(iter(dataloader))
    print("Input IDs shape:", batch['input_ids'].shape)
    print("URL Tensor shape:", batch['url_tensor'].shape)
    print("Labels shape:", batch['label'].shape)