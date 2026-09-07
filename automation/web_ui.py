#!/usr/bin/env python3
"""
Web Management UI & Orchestrator Dashboard for OpenShorts Autonomous Pipeline.
Provides an interactive control center to:
- Add YouTube URLs to the queue
- Monitor scheduler progress and real-time logs
- Preview and manage generated 9:16 Shorts
- Publish clips to YouTube with 1 click or on a schedule
- Edit pipeline settings (.env)
"""

import os
import sys
import json
import time
import asyncio
import threading
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add current dir to sys.path so imports work
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.insert(0, str(current_dir))
sys.path.insert(0, str(project_root))

from scheduler import (
    load_queue,
    save_queue,
    add_video_to_queue,
    run_pipeline_step,
    CURRENT_STATE,
    RECENT_LOGS,
    QUEUE_FILE,
    OUTPUT_DIR,
    OPENSHORTS_API_URL,
    POLL_INTERVAL_SEC
)

from poster import (
    check_youtube_auth_status,
    upload_short_to_youtube,
    resolve_credentials_paths
)

logger = logging.getLogger("ShortsWebUI")

app = FastAPI(title="OpenShorts Pipeline Control Center", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Background scheduler thread handle
SCHEDULER_THREAD = None
SCHEDULER_STOP_EVENT = threading.Event()

def background_scheduler_worker():
    """Background worker that continuously ticks the scheduler."""
    logger.info("Background scheduler thread started.")
    CURRENT_STATE["is_running"] = True
    while not SCHEDULER_STOP_EVENT.is_set():
        try:
            run_pipeline_step()
        except Exception as e:
            logger.exception(f"Error in background scheduler iteration: {e}")
        
        # Sleep in small slices to respond quickly to stop event
        for _ in range(POLL_INTERVAL_SEC * 2):
            if SCHEDULER_STOP_EVENT.is_set():
                break
            time.sleep(0.5)

    CURRENT_STATE["is_running"] = False
    logger.info("Background scheduler thread stopped.")

@app.on_event("startup")
def on_startup():
    global SCHEDULER_THREAD
    # Auto-start scheduler thread on startup if enabled
    auto_start = os.getenv("RUN_SCHEDULER_WITH_WEB_UI", "true").lower() in ("1", "true", "yes")
    if auto_start and (SCHEDULER_THREAD is None or not SCHEDULER_THREAD.is_alive()):
        SCHEDULER_STOP_EVENT.clear()
        SCHEDULER_THREAD = threading.Thread(target=background_scheduler_worker, daemon=True)
        SCHEDULER_THREAD.start()

# Data models
class QueueItemRequest(BaseModel):
    url: str
    id: Optional[str] = None
    layouts: Optional[str] = "auto"
    target_clips: Optional[str] = None
    auto_post: Optional[bool] = False
    schedule_delay_hours: Optional[float] = 1.0
    schedule_interval_hours: Optional[float] = 3.0

class SettingsUpdateRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    auto_post: Optional[bool] = None
    auto_post_interval_hours: Optional[float] = None
    poll_interval_sec: Optional[int] = None
    ffmpeg_encoder: Optional[str] = None
    whisper_model: Optional[str] = None
    whisper_device: Optional[str] = None

class PublishClipRequest(BaseModel):
    video_id: str
    clip_index: int
    title: Optional[str] = None
    delay_hours: Optional[float] = 0.0

# API Endpoints
@app.get("/api/status")
def get_system_status():
    """Returns current system health, worker status, and queue summary."""
    queue = load_queue()
    youtube_status = check_youtube_auth_status() if check_youtube_auth_status else {"status": "disabled"}
    
    total_completed_clips = sum(len(item.get("clips", [])) for item in queue.get("completed", []))

    return {
        "scheduler": {
            "is_running": CURRENT_STATE.get("is_running", False),
            "current_stage": CURRENT_STATE.get("current_stage", "idle"),
            "current_item": CURRENT_STATE.get("current_item"),
            "current_job_id": CURRENT_STATE.get("current_job_id"),
            "last_poll": CURRENT_STATE.get("last_poll_time"),
            "openshorts_api": OPENSHORTS_API_URL
        },
        "youtube_auth": youtube_status,
        "queue_summary": {
            "pending": len(queue.get("pending", [])),
            "processing": len(queue.get("processing", [])),
            "completed": len(queue.get("completed", [])),
            "failed": len(queue.get("failed", [])),
            "total_clips": total_completed_clips
        }
    }

@app.get("/api/queue")
def get_queue():
    """Returns full queue structure."""
    return load_queue()

@app.post("/api/queue")
def enqueue_video(payload: QueueItemRequest):
    """Enqueues a single YouTube video for clipping."""
    url = payload.url.strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")

    options = {
        "layouts": payload.layouts or "auto",
        "auto_post": bool(payload.auto_post),
        "schedule_delay_hours": payload.schedule_delay_hours or 1.0,
        "schedule_interval_hours": payload.schedule_interval_hours or 3.0,
    }
    if payload.target_clips:
        options["target_clips"] = payload.target_clips

    item = add_video_to_queue(url=url, video_id=payload.id, options=options)
    return {"status": "ok", "message": "Video added to pending queue", "item": item}

@app.post("/api/queue/batch")
async def enqueue_batch(request: Request):
    """Accepts multiple URLs (e.g. from multiline textarea) and queues them all."""
    data = await request.json()
    urls_text = data.get("urls", "")
    lines = [line.strip() for line in urls_text.splitlines() if line.strip() and line.strip().startswith("http")]
    
    if not lines:
        raise HTTPException(status_code=400, detail="No valid URLs provided.")

    options = {
        "layouts": data.get("layouts", "auto"),
        "auto_post": bool(data.get("auto_post", False)),
        "schedule_delay_hours": float(data.get("schedule_delay_hours", 1.0)),
        "schedule_interval_hours": float(data.get("schedule_interval_hours", 3.0)),
    }

    added = []
    for idx, url in enumerate(lines):
        item = add_video_to_queue(url=url, options=options)
        added.append(item)

    return {"status": "ok", "count": len(added), "added": added}

@app.delete("/api/queue/{category}/{item_id}")
def delete_queue_item(category: str, item_id: str):
    """Deletes an item from pending, completed, or failed queue."""
    queue = load_queue()
    if category not in queue:
        raise HTTPException(status_code=400, detail="Invalid category.")

    initial_len = len(queue[category])
    queue[category] = [item for item in queue[category] if item.get("id") != item_id]

    if len(queue[category]) == initial_len:
        raise HTTPException(status_code=404, detail="Item not found.")

    save_queue(queue)
    return {"status": "ok", "message": f"Deleted item {item_id} from {category}"}

@app.post("/api/queue/retry/{item_id}")
def retry_failed_item(item_id: str):
    """Moves a failed item back to pending queue."""
    queue = load_queue()
    failed_items = [i for i in queue.get("failed", []) if i.get("id") == item_id]
    if not failed_items:
        raise HTTPException(status_code=404, detail="Failed item not found.")

    item = failed_items[0]
    queue["failed"] = [i for i in queue.get("failed", []) if i.get("id") != item_id]
    item.pop("error", None)
    item.pop("failed_at", None)
    item["retried_at"] = datetime.now(timezone.utc).isoformat()
    queue["pending"].append(item)
    save_queue(queue)
    return {"status": "ok", "message": f"Item {item_id} moved back to pending"}

@app.post("/api/scheduler/toggle")
def toggle_scheduler():
    """Starts or stops the background scheduler loop."""
    global SCHEDULER_THREAD
    if CURRENT_STATE.get("is_running"):
        SCHEDULER_STOP_EVENT.set()
        CURRENT_STATE["is_running"] = False
        return {"status": "ok", "message": "Scheduler stopped."}
    else:
        SCHEDULER_STOP_EVENT.clear()
        SCHEDULER_THREAD = threading.Thread(target=background_scheduler_worker, daemon=True)
        SCHEDULER_THREAD.start()
        CURRENT_STATE["is_running"] = True
        return {"status": "ok", "message": "Scheduler started."}

@app.get("/api/logs")
def get_logs():
    """Returns recent log entries from the ring buffer."""
    return {"logs": list(RECENT_LOGS)}

@app.get("/api/video-file/{video_id}/{filename}")
def stream_video_file(video_id: str, filename: str):
    """Streams a processed video clip for browser preview."""
    target_path = OUTPUT_DIR / f"video_{video_id}" / filename
    if not target_path.exists():
        # Fallback without video_ prefix
        target_path = OUTPUT_DIR / video_id / filename
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found.")

    return FileResponse(str(target_path), media_type="video/mp4")

@app.post("/api/clips/publish")
def manual_publish_clip(payload: PublishClipRequest):
    """Manually triggers YouTube publishing for a specific clip."""
    if not upload_short_to_youtube:
        raise HTTPException(status_code=500, detail="YouTube Auto-Poster module not available.")

    queue = load_queue()
    target_item = next((i for i in queue.get("completed", []) if i.get("id") == payload.video_id), None)
    if not target_item:
        raise HTTPException(status_code=404, detail="Video task not found.")

    clips = target_item.get("clips", [])
    if payload.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip index out of bounds.")

    clip = clips[payload.clip_index]
    video_path = clip.get("local_path")
    if not video_path or not Path(video_path).exists():
        # Reconstruct path from relative
        video_path = str(OUTPUT_DIR / f"video_{payload.video_id}" / f"short_{payload.clip_index+1:02d}.mp4")

    if not Path(video_path).exists():
        raise HTTPException(status_code=404, detail=f"Local video file not found at {video_path}")

    title = payload.title or clip.get("youtube_short_title") or clip.get("title") or "YouTube Short"
    delay = float(payload.delay_hours or 0.0)
    sched_time = datetime.now(timezone.utc) + timedelta(hours=delay) if delay > 0 else None

    try:
        res = upload_short_to_youtube(
            video_file_path=video_path,
            title=title,
            scheduled_publish_time=sched_time
        )
        clip["youtube_status"] = res.get("status")
        clip["youtube_id"] = res.get("id")
        clip["youtube_url"] = res.get("url")
        clip["publish_at"] = res.get("publishAt")
        clip["status"] = "scheduled" if res.get("publishAt") else "published"
        save_queue(queue)
        return {"status": "ok", "result": res}
    except Exception as e:
        logger.error(f"Error publishing clip: {e}")
        clip["youtube_error"] = str(e)
        save_queue(queue)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/settings")
def get_settings():
    """Returns current environment configurations (masking secret keys)."""
    env_file = project_root / ".env"
    key = os.getenv("GEMINI_API_KEY", "")
    masked_key = (key[:6] + "..." + key[-4:]) if len(key) > 10 else ("***" if key else "")

    return {
        "gemini_api_key_masked": masked_key,
        "gemini_api_key_set": bool(key and key != "your_gemini_api_key_here"),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        "auto_post": os.getenv("AUTO_POST", "false").lower() in ("1", "true", "yes"),
        "auto_post_interval_hours": float(os.getenv("AUTO_POST_INTERVAL_HOURS", "3.0")),
        "poll_interval_sec": int(os.getenv("POLL_INTERVAL_SEC", "30")),
        "ffmpeg_encoder": os.getenv("FFMPEG_ENCODER", "x264"),
        "whisper_model": os.getenv("WHISPER_MODEL", "small"),
        "whisper_device": os.getenv("WHISPER_DEVICE", "cpu"),
        "openshorts_api_url": OPENSHORTS_API_URL
    }

@app.post("/api/settings")
def update_settings(payload: SettingsUpdateRequest):
    """Updates settings in .env file."""
    env_file = project_root / ".env"
    lines = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()

    env_map = {}
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env_map[k.strip()] = v.strip()

    if payload.gemini_api_key is not None and payload.gemini_api_key.strip():
        env_map["GEMINI_API_KEY"] = payload.gemini_api_key.strip()
        os.environ["GEMINI_API_KEY"] = payload.gemini_api_key.strip()

    if payload.gemini_model is not None:
        env_map["GEMINI_MODEL"] = payload.gemini_model.strip()
        os.environ["GEMINI_MODEL"] = payload.gemini_model.strip()

    if payload.auto_post is not None:
        val = "1" if payload.auto_post else "0"
        env_map["AUTO_POST"] = val
        os.environ["AUTO_POST"] = val

    if payload.auto_post_interval_hours is not None:
        env_map["AUTO_POST_INTERVAL_HOURS"] = str(payload.auto_post_interval_hours)
        os.environ["AUTO_POST_INTERVAL_HOURS"] = str(payload.auto_post_interval_hours)

    if payload.poll_interval_sec is not None:
        env_map["POLL_INTERVAL_SEC"] = str(payload.poll_interval_sec)
        os.environ["POLL_INTERVAL_SEC"] = str(payload.poll_interval_sec)

    if payload.ffmpeg_encoder is not None:
        env_map["FFMPEG_ENCODER"] = payload.ffmpeg_encoder.strip()
        os.environ["FFMPEG_ENCODER"] = payload.ffmpeg_encoder.strip()

    if payload.whisper_model is not None:
        env_map["WHISPER_MODEL"] = payload.whisper_model.strip()
        os.environ["WHISPER_MODEL"] = payload.whisper_model.strip()

    if payload.whisper_device is not None:
        env_map["WHISPER_DEVICE"] = payload.whisper_device.strip()
        os.environ["WHISPER_DEVICE"] = payload.whisper_device.strip()

    new_content = "\n".join(f"{k}={v}" for k, v in env_map.items()) + "\n"
    env_file.write_text(new_content, encoding="utf-8")
    logger.info("Updated .env configuration file from Web UI.")
    return {"status": "ok", "message": "Settings updated successfully."}

# HTML Single Page Dashboard
@app.get("/", response_class=HTMLResponse)
def index_html():
    template_path = current_dir / "templates" / "index.html"
    if template_path.exists():
        return HTMLResponse(template_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>templates/index.html not found</h1>", status_code=500)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("WEB_UI_PORT", "8080"))
    logger.info(f"Starting OpenShorts Web UI & Scheduler on http://0.0.0.0:{port}")
    uvicorn.run("web_ui:app", host="0.0.0.0", port=port, reload=False)
