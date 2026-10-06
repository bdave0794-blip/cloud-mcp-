import os
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from supabase import Client, create_client


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing environment variable: {name}")
    return value


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    url = _require("SUPABASE_URL")
    if "supabase.com/dashboard" in url:
        raise ConfigError(
            "SUPABASE_URL is the dashboard link. Use https://<project-ref>.supabase.co"
        )
    return create_client(url, _require("SUPABASE_KEY"))


@lru_cache(maxsize=1)
def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=_require("R2_ENDPOINT_URL"),
        aws_access_key_id=_require("R2_ACCESS_KEY"),
        aws_secret_access_key=_require("R2_SECRET_KEY"),
        region_name="auto",
    )


def upload_bytes(data: bytes, key: str, content_type: str = "audio/mpeg") -> str:
    """Upload bytes to R2 and return the public URL."""
    bucket = os.environ.get("R2_BUCKET_NAME", "yt-automation-assets")
    public_domain = _require("R2_PUBLIC_DOMAIN").rstrip("/")
    try:
        get_s3_client().put_object(
            Bucket=bucket, Key=key, Body=data, ContentType=content_type
        )
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"R2 upload failed: {e}") from e
    return f"{public_domain}/{key}"


def create_job(topic: str, script_text: str | None = None) -> str:
    row = {"topic": topic, "status": "pending"}
    if script_text:
        row["script_text"] = script_text
    res = get_supabase().table("video_jobs").insert(row).execute()
    return res.data[0]["id"]


def update_job(job_id: str, **fields) -> None:
    get_supabase().table("video_jobs").update(fields).eq("id", job_id).execute()


def get_job(job_id: str) -> dict | None:
    res = get_supabase().table("video_jobs").select("*").eq("id", job_id).execute()
    return res.data[0] if res.data else None
