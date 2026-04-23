import os
from dotenv import load_dotenv
from pymongo import MongoClient
import boto3

load_dotenv()

# MongoDB Connection
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client["phish_guard"]

# MinIO (S3) Connection
s3_client = boto3.client(
    "s3",
    endpoint_url=os.getenv("MINIO_ENDPOINT"),
    aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("MINIO_SECRET_KEY")
)

# Ensure Bucket Exists
try:
    s3_client.create_bucket(Bucket="screenshots")
except:
    pass