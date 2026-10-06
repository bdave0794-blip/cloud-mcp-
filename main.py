import os
import requests
from fastmcp import FastMCP
from cloud_data import supabase, upload_asset, create_job

mcp = FastMCP("YouTube Cloud Engine")

@mcp.tool()
async def health_check() -> dict:
    return {"status": "healthy", "engine": "FastMCP Cloud"}

@mcp.tool()
async def fetch_channel_stats(channel_id: str) -> dict:
    api_key = os.environ.get("YOUTUBE_API_KEY")
    url = f"https://www.googleapis.com/youtube/v3/channels?part=statistics&id={channel_id}&key={api_key}"
    res = requests.get(url, timeout=10)
    if res.status_code == 200:
        items = res.json().get("items", [])
        return items[0]["statistics"] if items else {"error": "Channel not found."}
    return {"error": f"API call failed with status {res.status_code}"}

@mcp.tool()
async def generate_and_store_voiceover(job_id: str, script_text: str, voice_id: str) -> dict:
    eleven_key = os.environ.get("ELEVENLABS_API_KEY")
    tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": eleven_key, "Content-Type": "application/json"}
    payload = {"text": script_text, "model_id": "eleven_monolingual_v1"}
    
    res = requests.post(tts_url, json=payload, headers=headers, timeout=60)
    if res.status_code == 200:
        temp_file = f"/tmp/{job_id}.mp3"
        with open(temp_file, "wb") as f:
            f.write(res.content)
        audio_url = upload_asset(temp_file, f"audio/{job_id}.mp3")
        os.remove(temp_file)
        if supabase:
            supabase.table("video_jobs").update({"audio_url": audio_url, "status": "audio_ready"}).eq("id", job_id).execute()
        return {"status": "success", "job_id": job_id, "audio_url": audio_url}
    return {"status": "error", "message": res.text}

@mcp.tool()
async def check_job_status(job_id: str) -> dict:
    if not supabase:
        return {"error": "Supabase not configured"}
    res = supabase.table("video_jobs").select("*").eq("id", job_id).execute()
    return res.data[0] if res.data else {"error": "Job not found"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    mcp.run(transport="sse", host="0.0.0.0", port=port)
