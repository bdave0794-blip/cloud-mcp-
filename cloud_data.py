import os
import boto3
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("R2_ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("R2_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("R2_SECRET_KEY"),
        region_name="auto"
    )

def upload_asset(file_path: str, destination_name: str) -> str:
    bucket_name = os.environ.get("R2_BUCKET_NAME", "yt-automation-assets")
    public_domain = os.environ.get("R2_PUBLIC_DOMAIN", "").rstrip("/")
    s3 = get_s3_client()
    s3.upload_file(file_path, bucket_name, destination_name)
    return f"{public_domain}/{destination_name}"

def create_job(topic: str, script_text: str = None) -> str:
    data = {"topic": topic, "status": "pending"}
    if script_text:
        data["script_text"] = script_text
    res = supabase.table("video_jobs").insert(data).execute()
    return res.data[0]["id"]
