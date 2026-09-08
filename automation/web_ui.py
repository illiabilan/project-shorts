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
sys.path.insert(0, str(project_root / "openshorts-repo"))

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
    resolve_credentials_paths,
    test_account_connection,
    post_clip_to_account
)

from accounts import (
    load_accounts_raw,
    get_masked_accounts,
    get_account,
    upsert_account,
    delete_account,
    update_account_status,
    PLATFORMS
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
    target_accounts: Optional[List[str]] = []
    schedule_delay_hours: Optional[float] = 1.0
    schedule_interval_hours: Optional[float] = 3.0
    options: Optional[dict] = None

class SettingsUpdateRequest(BaseModel):
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    auto_post: Optional[bool] = None
    auto_post_interval_hours: Optional[float] = None
    poll_interval_sec: Optional[int] = None
    ffmpeg_encoder: Optional[str] = None
    whisper_model: Optional[str] = None
    whisper_device: Optional[str] = None

class TestLLMRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None

class PublishClipRequest(BaseModel):
    video_id: str
    clip_index: int
    title: Optional[str] = None
    delay_hours: Optional[float] = 0.0
    account_ids: Optional[List[str]] = None

class AccountUpsertRequest(BaseModel):
    id: Optional[str] = None
    platform: str
    name: Optional[str] = None
    enabled: Optional[bool] = True
    credentials: Optional[dict] = {}
    settings: Optional[dict] = {}

class AccountTestRequest(BaseModel):
    platform: str
    id: Optional[str] = None
    credentials: Optional[dict] = {}

# API Endpoints
@app.get("/api/status")
def get_system_status():
    """Returns current system health, worker status, accounts summary, and queue summary."""
    queue = load_queue()
    youtube_status = check_youtube_auth_status() if check_youtube_auth_status else {"status": "disabled"}
    
    total_completed_clips = sum(len(item.get("clips", [])) for item in queue.get("completed", []))
    accounts = load_accounts_raw() if load_accounts_raw else []

    accounts_by_platform = {}
    for a in accounts:
        p = a.get("platform", "unknown")
        accounts_by_platform[p] = accounts_by_platform.get(p, 0) + 1

    return {
        "scheduler": {
            "is_running": CURRENT_STATE.get("is_running", False),
            "current_stage": CURRENT_STAGE if 'CURRENT_STAGE' in globals() else CURRENT_STATE.get("current_stage", "idle"),
            "current_item": CURRENT_STATE.get("current_item"),
            "current_job_id": CURRENT_STATE.get("current_job_id"),
            "last_poll": CURRENT_STATE.get("last_poll_time"),
            "openshorts_api": OPENSHORTS_API_URL
        },
        "youtube_auth": youtube_status,
        "accounts_summary": {
            "total": len(accounts),
            "enabled": len([a for a in accounts if a.get("enabled", True)]),
            "by_platform": accounts_by_platform
        },
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

    opt = payload.options or {}
    target_accounts = payload.target_accounts if payload.target_accounts else opt.get("target_accounts", [])
    layouts = opt.get("layouts", payload.layouts or "auto")
    auto_post = bool(payload.auto_post) or bool(opt.get("auto_post")) or bool(target_accounts)
    schedule_delay = opt.get("schedule_delay_hours") or opt.get("delay_hours") or payload.schedule_delay_hours or 1.0
    schedule_interval = opt.get("schedule_interval_hours") or payload.schedule_interval_hours or 3.0

    options = {
        "layouts": layouts,
        "auto_post": auto_post,
        "target_accounts": target_accounts,
        "schedule_delay_hours": float(schedule_delay),
        "schedule_interval_hours": float(schedule_interval),
    }
    target_clips = payload.target_clips or opt.get("target_clips")
    if target_clips:
        options["target_clips"] = target_clips

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

    target_accounts = data.get("target_accounts") or []
    options = {
        "layouts": data.get("layouts", "auto"),
        "auto_post": bool(data.get("auto_post", False)) or bool(target_accounts),
        "target_accounts": target_accounts,
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
    """Manually triggers publishing for a specific clip to selected or default accounts."""
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
        video_path = str(OUTPUT_DIR / f"video_{payload.video_id}" / f"short_{payload.clip_index+1:02d}.mp4")

    if not Path(video_path).exists():
        raise HTTPException(status_code=404, detail=f"Local video file not found at {video_path}")

    title = payload.title or clip.get("youtube_short_title") or clip.get("title") or "Short Video"
    delay = float(payload.delay_hours or 0.0)
    sched_time = datetime.now(timezone.utc) + timedelta(hours=delay) if delay > 0 else None

    # Resolve target accounts
    req_account_ids = payload.account_ids or []
    all_accounts = load_accounts_raw() if load_accounts_raw else []

    target_accounts = []
    if req_account_ids:
        for aid in req_account_ids:
            acc = get_account(aid) if get_account else next((a for a in all_accounts if a.get("id") == aid), None)
            if acc:
                target_accounts.append(acc)
    elif target_item.get("options", {}).get("target_accounts"):
        for aid in target_item["options"]["target_accounts"]:
            acc = get_account(aid) if get_account else next((a for a in all_accounts if a.get("id") == aid), None)
            if acc and acc.get("enabled", True):
                target_accounts.append(acc)
    else:
        target_accounts = [a for a in all_accounts if a.get("enabled", True)]

    results = {}
    clip.setdefault("postings", {})

    if target_accounts and post_clip_to_account:
        for acc in target_accounts:
            aid = acc["id"]
            acc_name = acc.get("name")
            try:
                res = post_clip_to_account(
                    account=acc,
                    video_path=video_path,
                    title=title,
                    description=clip.get("hook_text", ""),
                    scheduled_time=sched_time
                )
                clip["postings"][aid] = {
                    "account_id": aid,
                    "account_name": acc_name,
                    "platform": acc.get("platform"),
                    "status": res.get("status"),
                    "url": res.get("url"),
                    "id": res.get("id"),
                    "publish_at": res.get("publishAt"),
                    "error": None
                }
                if acc.get("platform") == "youtube":
                    clip["youtube_status"] = res.get("status")
                    clip["youtube_id"] = res.get("id")
                    clip["youtube_url"] = res.get("url")
                    clip["publish_at"] = res.get("publishAt")
                results[aid] = res
            except Exception as e:
                logger.error(f"Failed manual publishing to {acc_name}: {e}")
                clip["postings"][aid] = {
                    "account_id": aid,
                    "account_name": acc_name,
                    "platform": acc.get("platform"),
                    "status": "posting_failed",
                    "error": str(e)
                }
                results[aid] = {"status": "error", "error": str(e)}

        statuses = [p.get("status") for p in clip["postings"].values()]
        if any(s == "scheduled" for s in statuses):
            clip["status"] = "scheduled"
        elif any(s in ("published", "uploaded", "simulated", "draft") for s in statuses):
            clip["status"] = "published"
        save_queue(queue)
        return {"status": "ok", "results": results}

    elif upload_short_to_youtube:
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
            logger.error(f"Error publishing clip to YouTube: {e}")
            clip["youtube_error"] = str(e)
            save_queue(queue)
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=500, detail="Модуль автопостингу або акаунти не налаштовані.")

# Accounts API Endpoints
@app.get("/api/accounts")
def list_accounts():
    """Returns all configured social accounts (with masked credentials) and platform definitions."""
    return {
        "accounts": get_masked_accounts(),
        "platforms": PLATFORMS
    }

@app.post("/api/accounts")
def save_account(payload: AccountUpsertRequest):
    """Creates or updates a social account."""
    try:
        acc = upsert_account(payload.model_dump())
        return {"status": "ok", "account": acc}
    except Exception as e:
        logger.exception(f"Error saving account: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/accounts/{account_id}")
def remove_account(account_id: str):
    """Deletes an account configuration."""
    success = delete_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found.")
    return {"status": "ok", "message": f"Акаунт {account_id} успішно видалено."}

@app.post("/api/accounts/test")
def test_account(payload: AccountTestRequest):
    """Tests authentication/connectivity to social account platform."""
    target_acc = None
    if payload.id:
        target_acc = get_account(payload.id)

    if not target_acc:
        target_acc = {
            "id": payload.id or f"test_{int(time.time())}",
            "platform": payload.platform,
            "credentials": payload.credentials or {}
        }
    else:
        # Merge credentials if override passed
        if payload.credentials:
            creds = dict(target_acc.get("credentials", {}))
            for k, v in payload.credentials.items():
                if v and not (isinstance(v, str) and v.startswith("***")):
                    creds[k] = v
            target_acc["credentials"] = creds

    try:
        success, message = test_account_connection(target_acc)
        if payload.id:
            update_account_status(
                account_id=payload.id,
                status_str="ready" if success else "error",
                message=message
            )
        return {"status": "ok" if success else "error", "success": success, "message": message}
    except Exception as e:
        logger.exception("Error testing account connection")
        if payload.id:
            update_account_status(payload.id, "error", str(e))
        return {"status": "error", "success": False, "message": f"Помилка тестування: {e}"}

@app.get("/api/settings")
def get_settings():
    """Returns current environment configurations (masking secret keys) and provider metadata."""
    current_provider = (os.getenv("LLM_PROVIDER") or "gemini").lower()
    llm_key = os.getenv("LLM_API_KEY", "")
    masked_llm_key = (llm_key[:6] + "..." + llm_key[-4:]) if len(llm_key) > 10 else ("***" if llm_key else "")

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    masked_gemini_key = (gemini_key[:6] + "..." + gemini_key[-4:]) if len(gemini_key) > 10 else ("***" if gemini_key else "")

    providers_config = {
        "gemini": {
            "name": "Google AI Studio (Gemini)",
            "models": ["gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-3.7-flash", "gemini-2.5-pro"],
            "default_model": "gemini-3.1-flash-lite",
            "default_base_url": "",
            "key_hint": "Отримати безкоштовно на aistudio.google.com",
            "key_link": "https://aistudio.google.com/",
            "key_placeholder": "AIzaSy..."
        },
        "openrouter": {
            "name": "OpenRouter (Claude, Llama, DeepSeek, Gemini...)",
            "models": ["google/gemini-2.5-flash", "anthropic/claude-3.5-sonnet", "anthropic/claude-3.5-haiku", "meta-llama/llama-3.3-70b-instruct", "deepseek/deepseek-chat", "openai/gpt-4o-mini"],
            "default_model": "google/gemini-2.5-flash",
            "default_base_url": "https://openrouter.ai/api/v1",
            "key_hint": "Один API-ключ для сотень моделей на openrouter.ai/keys",
            "key_link": "https://openrouter.ai/keys",
            "key_placeholder": "sk-or-v1-..."
        },
        "fireworks": {
            "name": "Fireworks AI (Швидкі відкриті моделі)",
            "models": ["accounts/fireworks/models/llama-v3p3-70b-instruct", "accounts/fireworks/models/deepseek-v3", "accounts/fireworks/models/qwen2p5-72b-instruct"],
            "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
            "default_base_url": "https://api.fireworks.ai/inference/v1",
            "key_hint": "Отримати API-ключ на fireworks.ai/api-keys",
            "key_link": "https://fireworks.ai/api-keys",
            "key_placeholder": "fw_..."
        },
        "anthropic": {
            "name": "Anthropic (Claude 3.5 / 3.7)",
            "models": ["claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022", "claude-3-7-sonnet-20250219"],
            "default_model": "claude-3-5-haiku-20241022",
            "default_base_url": "https://api.anthropic.com/v1",
            "key_hint": "Отримати API-ключ на console.anthropic.com",
            "key_link": "https://console.anthropic.com/",
            "key_placeholder": "sk-ant-..."
        },
        "openai": {
            "name": "OpenAI (GPT-4o, GPT-4o-mini)",
            "models": ["gpt-4o-mini", "gpt-4o"],
            "default_model": "gpt-4o-mini",
            "default_base_url": "https://api.openai.com/v1",
            "key_hint": "Отримати API-ключ на platform.openai.com",
            "key_link": "https://platform.openai.com/api-keys",
            "key_placeholder": "sk-..."
        },
        "groq": {
            "name": "Groq (Надшвидкі Llama)",
            "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
            "default_model": "llama-3.3-70b-versatile",
            "default_base_url": "https://api.groq.com/openai/v1",
            "key_hint": "Отримати API-ключ на console.groq.com/keys",
            "key_link": "https://console.groq.com/keys",
            "key_placeholder": "gsk_..."
        },
        "ollama": {
            "name": "Ollama / Local (Локальний запуск на ПК)",
            "models": ["llama3.1:8b", "qwen2.5:14b", "mistral:7b"],
            "default_model": "llama3.1:8b",
            "default_base_url": "http://localhost:11434/v1",
            "key_hint": "Локальний сервер Ollama (ключ не обов'язковий)",
            "key_link": "https://ollama.com/",
            "key_placeholder": "ollama"
        },
        "custom": {
            "name": "Кастомний OpenAI-Compatible сервер",
            "models": [],
            "default_model": "default",
            "default_base_url": "http://localhost:8000/v1",
            "key_hint": "Будь-який сумісний з OpenAI сервер",
            "key_link": "",
            "key_placeholder": "Ваш токен або пароль..."
        }
    }

    # Determine which key is active for current provider
    if current_provider == "gemini":
        active_key_masked = masked_gemini_key
        active_key_set = bool(gemini_key and gemini_key != "your_gemini_api_key_here")
    else:
        active_key_masked = masked_llm_key
        active_key_set = bool(llm_key)

    return {
        "llm_provider": current_provider,
        "llm_model": os.getenv("LLM_MODEL", ""),
        "llm_base_url": os.getenv("LLM_BASE_URL", ""),
        "llm_api_key_masked": masked_llm_key,
        "llm_api_key_set": bool(llm_key),
        "active_key_masked": active_key_masked,
        "active_key_set": active_key_set,
        "gemini_api_key_masked": masked_gemini_key,
        "gemini_api_key_set": bool(gemini_key and gemini_key != "your_gemini_api_key_here"),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        "auto_post": os.getenv("AUTO_POST", "false").lower() in ("1", "true", "yes"),
        "auto_post_interval_hours": float(os.getenv("AUTO_POST_INTERVAL_HOURS", "3.0")),
        "poll_interval_sec": int(os.getenv("POLL_INTERVAL_SEC", "30")),
        "ffmpeg_encoder": os.getenv("FFMPEG_ENCODER", "x264"),
        "whisper_model": os.getenv("WHISPER_MODEL", "small"),
        "whisper_device": os.getenv("WHISPER_DEVICE", "cpu"),
        "openshorts_api_url": OPENSHORTS_API_URL,
        "providers_config": providers_config
    }


@app.post("/api/settings")
def update_settings(payload: SettingsUpdateRequest):
    """Updates settings in .env file and active environment."""
    env_file = project_root / ".env"
    lines = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()

    env_map = {}
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env_map[k.strip()] = v.strip()

    if payload.llm_provider is not None:
        p_val = payload.llm_provider.strip().lower()
        env_map["LLM_PROVIDER"] = p_val
        os.environ["LLM_PROVIDER"] = p_val

    if payload.llm_api_key is not None and payload.llm_api_key.strip():
        val = payload.llm_api_key.strip()
        env_map["LLM_API_KEY"] = val
        os.environ["LLM_API_KEY"] = val
        # Also set GEMINI_API_KEY if provider is gemini
        if env_map.get("LLM_PROVIDER") == "gemini":
            env_map["GEMINI_API_KEY"] = val
            os.environ["GEMINI_API_KEY"] = val

    if payload.llm_model is not None and payload.llm_model.strip():
        val = payload.llm_model.strip()
        env_map["LLM_MODEL"] = val
        os.environ["LLM_MODEL"] = val
        if env_map.get("LLM_PROVIDER") == "gemini":
            env_map["GEMINI_MODEL"] = val
            os.environ["GEMINI_MODEL"] = val

    if payload.llm_base_url is not None:
        val = payload.llm_base_url.strip()
        env_map["LLM_BASE_URL"] = val
        os.environ["LLM_BASE_URL"] = val

    if payload.gemini_api_key is not None and payload.gemini_api_key.strip():
        val = payload.gemini_api_key.strip()
        env_map["GEMINI_API_KEY"] = val
        os.environ["GEMINI_API_KEY"] = val

    if payload.gemini_model is not None and payload.gemini_model.strip():
        val = payload.gemini_model.strip()
        env_map["GEMINI_MODEL"] = val
        os.environ["GEMINI_MODEL"] = val

    if payload.auto_post is not None:
        val = "1" if payload.auto_post else "0"
        env_map["AUTO_POST"] = val
        os.environ["AUTO_POST"] = val

    if payload.auto_post_interval_hours is not None:
        val = str(payload.auto_post_interval_hours)
        env_map["AUTO_POST_INTERVAL_HOURS"] = val
        os.environ["AUTO_POST_INTERVAL_HOURS"] = val

    if payload.poll_interval_sec is not None:
        val = str(payload.poll_interval_sec)
        env_map["POLL_INTERVAL_SEC"] = val
        os.environ["POLL_INTERVAL_SEC"] = val

    if payload.ffmpeg_encoder is not None:
        val = payload.ffmpeg_encoder.strip()
        env_map["FFMPEG_ENCODER"] = val
        os.environ["FFMPEG_ENCODER"] = val

    if payload.whisper_model is not None:
        val = payload.whisper_model.strip()
        env_map["WHISPER_MODEL"] = val
        os.environ["WHISPER_MODEL"] = val

    if payload.whisper_device is not None:
        val = payload.whisper_device.strip()
        env_map["WHISPER_DEVICE"] = val
        os.environ["WHISPER_DEVICE"] = val

    new_content = "\n".join(f"{k}={v}" for k, v in env_map.items()) + "\n"
    env_file.write_text(new_content, encoding="utf-8")

    # Also sync to openshorts-repo/.env
    openshorts_env = project_root / "openshorts-repo" / ".env"
    try:
        openshorts_env.write_text(new_content, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not sync openshorts-repo/.env: {e}")

    logger.info("Updated .env configuration file from Web UI.")
    return {"status": "ok", "message": "Налаштування успішно збережено!"}


@app.post("/api/settings/test-llm")
def test_llm_endpoint(payload: TestLLMRequest):
    """Tests LLM provider connectivity without running a video job."""
    try:
        import llm_backend
        api_key = payload.api_key.strip() if payload.api_key else None
        success, message = llm_backend.test_llm_connection(
            provider_name=payload.provider,
            key=api_key,
            model=payload.model,
            custom_base_url=payload.base_url
        )
        return {"status": "ok" if success else "error", "success": success, "message": message}
    except Exception as e:
        logger.exception("Error testing LLM connection")
        return {"status": "error", "success": False, "message": f"Помилка перевірки: {e}"}

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
