import os
import tempfile
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import yt_dlp

app = FastAPI(title="Vidora Media Engine")

# Testing default. Before public launch, restrict this to your Vidora website origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

ALLOWED_HOSTS = ("facebook.com", "fb.watch", "instagram.com")


def validate_url(url: str):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = any(host == domain or host.endswith("." + domain) for domain in ALLOWED_HOSTS)
    if parsed.scheme not in ("http", "https") or not allowed:
        raise HTTPException(
            status_code=400,
            detail="الرابط غير مدعوم. استخدم رابطاً عاماً من فيسبوك أو إنستجرام."
        )


@app.get("/")
def root():
    return {"service": "Vidora Media Engine", "status": "running"}


@app.get("/api/health")
def health():
    return {"ok": True, "service": "Vidora Media Engine"}


@app.get("/api/info")
def info(url: str = Query(...)):
    validate_url(url)
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=False)

        formats = []
        for item in data.get("formats", []):
            if item.get("url") and item.get("vcodec") != "none":
                formats.append({
                    "format_id": item.get("format_id"),
                    "ext": item.get("ext"),
                    "height": item.get("height"),
                    "filesize": item.get("filesize") or item.get("filesize_approx"),
                    "format_note": item.get("format_note"),
                })

        return {
            "title": data.get("title"),
            "thumbnail": data.get("thumbnail"),
            "duration": data.get("duration"),
            "formats": formats,
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"تعذر فحص الفيديو: {str(exc)[:300]}")


@app.get("/api/download")
def download(url: str = Query(...), format_id: str = Query("best")):
    validate_url(url)
    temp_dir = tempfile.mkdtemp(prefix="vidora_")
    output_template = os.path.join(temp_dir, "video.%(ext)s")

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": format_id if format_id != "best" else "best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        created = [
            os.path.join(temp_dir, name)
            for name in os.listdir(temp_dir)
            if os.path.isfile(os.path.join(temp_dir, name))
        ]
        if not created:
            raise RuntimeError("لم يتم إنشاء ملف فيديو")

        path = created[0]
        return FileResponse(
            path,
            filename="vidora-video" + os.path.splitext(path)[1],
            media_type="application/octet-stream",
            background=None,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"تعذر تنزيل الفيديو: {str(exc)[:300]}")
