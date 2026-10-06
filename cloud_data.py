"""Database + file storage helpers (Supabase only)."""
import os
from functools import lru_cache

from supabase import Client, create_client

AUDIO_BUCKET = os.environ.get("AUDIO_BUCKET", "audio")


class ConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing environment variable: {name}")
    return value


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    url = _require("SUPABASE_URL")
    if "supabase.com/dashboard" in url:
        raise ConfigError("SUPABASE_URL must be https://<project-ref>.supabase.co")
    return create_client(url, _require("SUPABASE_KEY"))


def upload_bytes(data: bytes, key: str, content_type: str = "audio/mpeg") -> str:
    """Upload to the public Supabase Storage bucket and return its public URL."""
    storage = get_supabase().storage.from_(AUDIO_BUCKET)
    storage.upload(key, data, {"content-type": content_type, "upsert": "true"})
    return storage.get_public_url(key)


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
