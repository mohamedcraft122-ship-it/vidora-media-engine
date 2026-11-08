import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="Vidora Media Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

ALLOWED_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "fb.watch",
    "instagram.com",
    "www.instagram.com",
}


def validate_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()

    if parsed.scheme not in ("http", "https") or host not in ALLOWED_HOSTS:
        raise HTTPException(
            status_code=400,
            detail="الرابط غير مدعوم. استخدم رابط فيديو عام من Facebook أو Instagram.",
        )
    return url.strip()


def ydl_options(**extra):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": False,
        "socket_timeout": 30,
    }
    options.update(extra)
    return options


@app.get("/")
def home():
    return {"service": "Vidora Media Engine", "status": "running"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/info")
def video_info(url: str = Query(..., min_length=8)):
    url = validate_url(url)

    try:
        with yt_dlp.YoutubeDL(ydl_options()) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise ValueError("No video information returned")

        formats = []
        for item in info.get("formats", []):
            height = item.get("height")
            format_id = item.get("format_id")

            if not format_id or not height:
                continue

            formats.append({
                "format_id": str(format_id),
                "height": int(height),
                "ext": item.get("ext"),
                "vcodec": item.get("vcodec"),
                "acodec": item.get("acodec"),
                "filesize": item.get("filesize") or item.get("filesize_approx"),
            })

        seen = set()
        unique_formats = []

        for item in formats:
            if item["format_id"] not in seen:
                seen.add(item["format_id"])
                unique_formats.append(item)

        return {
            "title": info.get("title") or "Vidora video",
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "formats": unique_formats,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="تعذر فحص الفيديو. تأكد أن الرابط عام ويمكن الوصول إليه، ثم حاول مرة أخرى.",
        ) from exc


@app.get("/api/download")
def download_video(
    url: str = Query(..., min_length=8),
    format_id: Optional[str] = Query(default=None),
):
    url = validate_url(url)

    if format_id and not re.fullmatch(r"[A-Za-z0-9._-]+", format_id):
        raise HTTPException(
            status_code=400,
            detail="صيغة الجودة غير صالحة."
        )

    temp_dir = tempfile.mkdtemp(prefix="vidora_")
    output_template = str(Path(temp_dir) / "vidora_video.%(ext)s")

    try:
        with yt_dlp.YoutubeDL(ydl_options()) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise ValueError("Video not found")

        chosen = None

        if format_id:
            chosen = next(
                (
                    f for f in info.get("formats", [])
                    if str(f.get("format_id")) == str(format_id)
                ),
                None,
            )

        if format_id and not chosen:
            raise HTTPException(
                status_code=404,
                detail="الجودة المختارة لم تعد متاحة. افحص الرابط واختر الجودة مرة أخرى.",
            )

        if chosen:
            has_audio = chosen.get("acodec") not in (None, "none")

            if has_audio:
                format_selector = str(format_id)
            else:
                format_selector = f"{format_id}+bestaudio"
        else:
            format_selector = "bestvideo+bestaudio/best"

        options = ydl_options(
            format=format_selector,
            outtmpl=output_template,
            merge_output_format="mp4",
        )

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        files = [
            p for p in Path(temp_dir).iterdir()
            if p.is_file() and p.stat().st_size > 0
        ]

        if not files:
            raise FileNotFoundError("Downloaded file was not created")

        result_file = max(files, key=lambda p: p.stat().st_size)

        safe_name = re.sub(
            r'[\\/:*?"<>|]+',
            "_",
            info.get("title") or "Vidora_video"
        )
        safe_name = safe_name.strip()[:100] or "Vidora_video"

        return FileResponse(
            path=str(result_file),
            media_type="video/mp4",
            filename=f"{safe_name}.mp4",
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="فشل تنزيل الفيديو أو دمج الصوت. قد تكون الجودة غير متاحة أو يحتاج yt-dlp إلى تحديث.",
        ) from exc
