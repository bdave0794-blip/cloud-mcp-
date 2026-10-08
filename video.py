"""Video rendering through Rendi (hosted FFmpeg). Version 1: voiceover over a plain background."""
import asyncio
import os

import httpx

import cloud_data as db

RENDI = "https://api.rendi.dev/v1"
FFMPEG = (
    "-f lavfi -i color=c=0x1f3864:s=1280x720:r=24 -i {{in_1}} -shortest "
    "-c:v libx264 -tune stillimage -pix_fmt yuv420p -c:a aac -b:a 192k "
    "-movflags +faststart {{out_1}}"
)


def _headers() -> dict:
    key = os.environ.get("RENDI_API_KEY", "").strip()
    if not key:
        raise db.ConfigError("RENDI_API_KEY is not set.")
    return {"X-API-KEY": key}


async def _poll(client, command_id, wait_seconds):
    """Return the command data once finished, or None if still running."""
    waited = 0
    while True:
        res = await client.get(f"{RENDI}/commands/{command_id}", headers=_headers())
        data = res.json()
        if data.get("status") not in ("QUEUED", "PROCESSING"):
            return data
        if waited >= wait_seconds:
            return None
        await asyncio.sleep(3)
        waited += 3


async def _finish(job_id, data):
    if data.get("status") == "SUCCESS":
        url = data["output_files"]["out_1"]["storage_url"]
        await asyncio.to_thread(
            db.update_job, job_id, video_url=url, status="completed", error_message=None
        )
        return {"status": "success", "job_id": job_id, "video_url": url}
    msg = f"Rendi status {data.get('status')}: {str(data)[:400]}"
    await asyncio.to_thread(db.update_job, job_id, status="failed", error_message=msg)
    return {"status": "error", "message": msg}


def register(mcp):
    @mcp.tool()
    async def render_video(job_id: str) -> dict:
        """Render an MP4 for a job that has audio ready, using Rendi."""
        try:
            job = await asyncio.to_thread(db.get_job, job_id)
            if not job:
                return {"status": "error", "message": "Job not found."}
            if not job.get("audio_url"):
                return {"status": "error", "message": "This job has no audio yet."}
            headers = _headers()
            await asyncio.to_thread(db.update_job, job_id, status="rendering_video")
            body = {
                "input_files": {"in_1": job["audio_url"]},
                "output_files": {"out_1": f"{job_id}.mp4"},
                "ffmpeg_command": FFMPEG,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.post(f"{RENDI}/run-ffmpeg-command", headers=headers, json=body)
                if res.status_code >= 300:
                    raise RuntimeError(f"Rendi returned {res.status_code}: {res.text[:300]}")
                command_id = res.json()["command_id"]
                data = await _poll(client, command_id, 60)
            if data is None:
                return {"status": "rendering", "job_id": job_id, "command_id": command_id,
                        "message": "Still rendering. Run check_render_status with these ids."}
            return await _finish(job_id, data)
        except Exception as e:
            try:
                await asyncio.to_thread(db.update_job, job_id, status="failed", error_message=str(e)[:500])
            except Exception:
                pass
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def check_render_status(job_id: str, command_id: str) -> dict:
        """Check a render that was still running, and finish the job if it is done."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                data = await _poll(client, command_id, 0)
            if data is None:
                return {"status": "rendering", "job_id": job_id, "command_id": command_id}
            return await _finish(job_id, data)
        except Exception as e:
            return {"status": "error", "message": str(e)}
