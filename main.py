import asyncio
import os

import httpx
from fastmcp import FastMCP

import cloud_data as db

mcp = FastMCP("YouTube Cloud Engine")

ELEVEN_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")


@mcp.tool()
async def health_check() -> dict:
    """Confirm the server is running and report which settings are configured."""
    env = ["SUPABASE_URL", "SUPABASE_KEY", "R2_ENDPOINT_URL", "R2_ACCESS_KEY",
           "R2_SECRET_KEY", "R2_PUBLIC_DOMAIN", "YOUTUBE_API_KEY", "ELEVENLABS_API_KEY"]
    return {
        "status": "healthy",
        "engine": "FastMCP Cloud",
        "configured": {name: bool(os.environ.get(name, "").strip()) for name in env},
    }


@mcp.tool()
async def create_video_job(topic: str, script_text: str = "") -> dict:
    """Create a new job row and return its job_id (needed for the voiceover tool)."""
    try:
        job_id = await asyncio.to_thread(db.create_job, topic, script_text or None)
        return {"status": "success", "job_id": job_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def fetch_channel_stats(channel_id: str) -> dict:
    """Get subscriber, view and video counts for a YouTube channel ID."""
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return {"error": "YOUTUBE_API_KEY is not set."}
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "statistics", "id": channel_id, "key": api_key},
        )
    if res.status_code != 200:
        return {"error": f"YouTube API returned {res.status_code}", "details": res.text[:300]}
    items = res.json().get("items", [])
    return items[0]["statistics"] if items else {"error": "Channel not found."}


@mcp.tool()
async def generate_and_store_voiceover(job_id: str, script_text: str, voice_id: str) -> dict:
    """Generate speech with ElevenLabs, store the MP3 in R2, and update the job."""
    eleven_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not eleven_key:
        return {"status": "error", "message": "ELEVENLABS_API_KEY is not set."}
    try:
        await asyncio.to_thread(db.update_job, job_id, status="generating_audio")
        async with httpx.AsyncClient(timeout=120) as client:
            res = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": eleven_key},
                json={
                    "text": script_text,
                    "model_id": ELEVEN_MODEL,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            )
        if res.status_code != 200:
            raise RuntimeError(f"ElevenLabs returned {res.status_code}: {res.text[:300]}")

        audio_url = await asyncio.to_thread(db.upload_bytes, res.content, f"audio/{job_id}.mp3")
        await asyncio.to_thread(db.update_job, job_id, audio_url=audio_url, status="audio_ready")
        return {"status": "success", "job_id": job_id, "audio_url": audio_url}
    except Exception as e:
        try:
            await asyncio.to_thread(db.update_job, job_id, status="failed", error_message=str(e)[:500])
        except Exception:
            pass
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def check_job_status(job_id: str) -> dict:
    """Look up the current state of a job."""
    try:
        job = await asyncio.to_thread(db.get_job, job_id)
        return job or {"error": "Job not found."}
    except Exception as e:
        return {"error": str(e)}


import video
video.register(mcp)


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
