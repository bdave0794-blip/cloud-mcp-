import os
import subprocess
import sys
import tempfile

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].strip().rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"].strip()
if SUPABASE_URL.startswith(("eyJ", "sb_")) or not KEY.startswith(("eyJ", "sb_")):
    sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY look wrong or swapped; re-save both secrets")
if not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = "https://" + SUPABASE_URL
BUCKET = os.environ.get("VIDEO_BUCKET", "video")
W = int(os.environ.get("VIDEO_W", "1920"))
H = int(os.environ.get("VIDEO_H", "1080"))
HDR = {"apikey": KEY}
if KEY.startswith("eyJ"):
    HDR["Authorization"] = f"Bearer {KEY}"

WORDS_PER_CAPTION = 7


def get_job(job_id):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/video_jobs",
        params={"id": f"eq.{job_id}", "select": "*"},
        headers=HDR,
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise RuntimeError(f"Job {job_id} not found")
    return rows[0]


def update_job(job_id, **fields):
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/video_jobs",
        params={"id": f"eq.{job_id}"},
        headers={**HDR, "Content-Type": "application/json", "Prefer": "return=minimal"},
        json=fields,
        timeout=30,
    )
    r.raise_for_status()


def audio_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path]
    )
    return float(out.decode().strip())


def make_chunks(script):
    chunks, cur = [], []
    for word in script.split():
        cur.append(word)
        if len(cur) >= WORDS_PER_CAPTION or word[-1] in ".?!":
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def ass_time(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(path, chunks, duration):
    total_chars = sum(len(c) for c in chunks) or 1
    font_size = int(H * 0.06)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_size},&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,4,2,5,{int(W*0.08)},{int(W*0.08)},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines, t = [], 0.0
    for c in chunks:
        dur = duration * len(c) / total_chars
        lines.append(
            f"Dialogue: 0,{ass_time(t)},{ass_time(t + dur)},Default,,0,0,0,,{{\\fad(150,100)\\fscx85\\fscy85\\t(0,200,\\fscx100\\fscy100)}}{c}"
        )
        t += dur
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")


def run_ffmpeg(tmp, duration):
    d = f"{duration + 0.5:.3f}"
    bar = f"color=c=0x38bdf8:s={W}x16:r=30:d={d}"
    fg = (f"[0:v][2:v]overlay=x='-w+w*t/{duration:.3f}':y={H}-16[v1];"
          f"[v1]subtitles=captions.ass[v]")
    backgrounds = [
        f"gradients=s={W}x{H}:c0=0x0f172a:c1=0x1e3a8a:x0=0:y0=0:x1={W}:y1={H}:speed=0.03:r=30:d={d}",
        f"color=c=0x0f172a:s={W}x{H}:r=30:d={d}",
    ]
    for i, bg in enumerate(backgrounds):
        try:
            run_ffmpeg(tmp, duration)
            return
        except subprocess.CalledProcessError:
            if i == len(backgrounds) - 1:
                raise


def main(job_id):
    try:
        job = get_job(job_id)
        if not job.get("audio_url"):
            raise RuntimeError("Job has no audio_url; generate the voiceover first")
        if not job.get("script_text"):
            raise RuntimeError("Job has no script_text")

        update_job(job_id, status="rendering")

        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "audio.mp3")
            with requests.get(job["audio_url"], stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(audio, "wb") as f:
                    for part in r.iter_content(1 << 16):
                        f.write(part)

            duration = audio_duration(audio)
            write_ass(os.path.join(tmp, "captions.ass"),
                      make_chunks(job["script_text"]), duration)

            out = os.path.join(tmp, "out.mp4")
            subprocess.check_call(
                ["ffmpeg", "-y",
                 "-f", "lavfi", "-i", f"color=c=0x0f172a:s={W}x{H}:r=30",
                 "-i", "audio.mp3",
                 "-vf", "subtitles=captions.ass",
                 "-map", "0:v", "-map", "1:a",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", "out.mp4"],
                cwd=tmp,
            )

            with open(out, "rb") as f:
                up = requests.post(
                    f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{job_id}.mp4",
                    headers={**HDR, "Content-Type": "video/mp4", "x-upsert": "true"},
                    data=f,
                    timeout=300,
                )
            up.raise_for_status()

        video_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{job_id}.mp4"
        update_job(job_id, video_url=video_url, status="rendered", error_message=None)
        print("Rendered:", video_url)

    except Exception as e:
        update_job(job_id, status="render_failed", error_message=str(e)[:500])
        raise


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python render.py <job_id>")
    main(sys.argv[1].strip())
