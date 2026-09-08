#!/usr/bin/env python3
"""
Autonomous Short-Video Orchestrator.
Monitors video source queue, calls OpenShorts API (local/docker instance using Cloud LLM API),
processes clips, and schedules them for auto-posting via YouTube Data API.
"""

import os
import sys
import time
import json
import shutil
import logging
import collections
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Ring buffer for live logs streaming to Web UI
RECENT_LOGS = collections.deque(maxlen=300)

class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            RECENT_LOGS.append({
                "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": msg
            })
        except Exception:
            pass

# Setup Logging
log_handler = MemoryLogHandler()
log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scheduler.log", encoding="utf-8"),
        log_handler
    ]
)
logger = logging.getLogger("ShortsScheduler")

# Configuration from environment
OPENSHORTS_API_URL = os.getenv("OPENSHORTS_API_URL", "http://localhost:8000").rstrip("/")
QUEUE_FILE = Path(os.getenv("QUEUE_FILE", "queue.json"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "processed_shorts"))
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "30"))
JOB_CHECK_INTERVAL_SEC = int(os.getenv("JOB_CHECK_INTERVAL_SEC", "10"))
AUTO_POST_GLOBAL = os.getenv("AUTO_POST", "false").lower() in ("1", "true", "yes")
AUTO_POST_INTERVAL_HOURS = float(os.getenv("AUTO_POST_INTERVAL_HOURS", "3"))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Try importing auto-poster & accounts
try:
    from automation.poster import (
        upload_short_to_youtube,
        check_youtube_auth_status,
        post_clip_to_account,
        test_account_connection
    )
    from automation.accounts import get_account, load_accounts_raw
except ImportError:
    try:
        from poster import (
            upload_short_to_youtube,
            check_youtube_auth_status,
            post_clip_to_account,
            test_account_connection
        )
        from accounts import get_account, load_accounts_raw
    except ImportError:
        upload_short_to_youtube = None
        check_youtube_auth_status = None
        post_clip_to_account = None
        get_account = None
        load_accounts_raw = None

# Current status state for Web UI
CURRENT_STATE = {
    "is_running": False,
    "last_poll_time": None,
    "current_item": None,
    "current_job_id": None,
    "current_stage": "idle"
}

def api_request(method, endpoint, payload=None):
    """Sends an HTTP request to the OpenShorts API."""
    url = f"{OPENSHORTS_API_URL}{endpoint}"
    headers = {"Accept": "application/json"}
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key and gemini_key != "your_gemini_api_key_here":
        headers["X-Gemini-Key"] = gemini_key

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, {"detail": err_body}
    except Exception as e:
        logger.error(f"Failed to connect to OpenShorts API at {url}: {e}")
        return 500, {"detail": str(e)}

def load_queue():
    """Reads the current queue safely from queue.json."""
    if not QUEUE_FILE.exists():
        initial_data = {"pending": [], "processing": [], "completed": [], "failed": []}
        save_queue(initial_data)
        return initial_data
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Error loading queue file {QUEUE_FILE}: {e}")
        return {"pending": [], "processing": [], "completed": [], "failed": []}

def save_queue(data):
    """Atomically saves the updated queue to queue.json (prevent partial writes)."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = QUEUE_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(QUEUE_FILE)

def add_video_to_queue(url: str, video_id: str = None, options: dict = None):
    """Adds a new video task to the queue safely."""
    queue = load_queue()
    if not video_id:
        video_id = f"video_{int(time.time())}"
    
    item = {
        "id": video_id,
        "url": url,
        "options": options or {"layouts": "auto", "auto_post": False},
        "added_at": datetime.now(timezone.utc).isoformat()
    }
    queue["pending"].append(item)
    save_queue(queue)
    logger.info(f"Added video [{video_id}] to pending queue: {url}")
    return item

def submit_video_job(youtube_url, options=None):
    """Submits a YouTube URL to OpenShorts for processing with proper overrides."""
    options = options or {}
    body = {
        "url": youtube_url,
        "acknowledged": True,
        "force_low_quality": options.get("force_low_quality", True),  # Bypass Quality Gate confirmation prompt
        "layouts": options.get("layouts", "auto"),
        "output_format": options.get("output_format", "auto")
    }

    # Optional parameters pass-through
    for opt in ("target_clips", "clip_min_seconds", "clip_max_seconds", "captions", "auto_hook", "auto_hook_mode", "auto_hook_seconds", "auto_hook_style"):
        if opt in options:
            body[opt] = options[opt]

    if "clip_min_seconds" not in body and os.getenv("CLIP_MIN_SECONDS"):
        body["clip_min_seconds"] = os.getenv("CLIP_MIN_SECONDS")
    if "clip_max_seconds" not in body and os.getenv("CLIP_MAX_SECONDS"):
        body["clip_max_seconds"] = os.getenv("CLIP_MAX_SECONDS")
    if "auto_hook" not in body and os.getenv("AUTO_HOOK"):
        body["auto_hook"] = os.getenv("AUTO_HOOK")
    if "auto_hook_mode" not in body and os.getenv("AUTO_HOOK_MODE"):
        body["auto_hook_mode"] = os.getenv("AUTO_HOOK_MODE")
    if "auto_hook_seconds" not in body and os.getenv("AUTO_HOOK_SECONDS"):
        body["auto_hook_seconds"] = os.getenv("AUTO_HOOK_SECONDS")
    if "auto_hook_style" not in body and os.getenv("AUTO_HOOK_STYLE"):
        body["auto_hook_style"] = os.getenv("AUTO_HOOK_STYLE")
    if os.getenv("FFMPEG_ENCODER"):
        body["ffmpeg_encoder"] = os.getenv("FFMPEG_ENCODER")
    if os.getenv("WHISPER_MODEL"):
        body["whisper_model"] = os.getenv("WHISPER_MODEL")
    if os.getenv("WHISPER_DEVICE"):
        body["whisper_device"] = os.getenv("WHISPER_DEVICE")
    if os.getenv("WHISPER_COMPUTE"):
        body["whisper_compute"] = os.getenv("WHISPER_COMPUTE")

    logger.info(f"Submitting video to OpenShorts: {youtube_url} (layouts: {body['layouts']})")
    status, res = api_request("POST", "/api/process", body)
    
    if status >= 400:
        logger.error(f"Error submitting job ({status}): {res}")
        return None

    # In case quality confirmation still occurred
    if res.get("needs_confirmation"):
        logger.warning(f"OpenShorts requested quality confirmation, forcing low quality...")
        body["force_low_quality"] = True
        status, res = api_request("POST", "/api/process", body)
        if status >= 400:
            return None

    return res.get("job_id")

def download_clip(clip_url, destination_path):
    """Downloads or copies rendered short clip to local storage with encoding safety."""
    try:
        destination_path = Path(destination_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if local file exists in OpenShorts output directory
        parsed = urllib.parse.urlparse(clip_url)
        path_str = urllib.parse.unquote(parsed.path)
        if "/videos/" in path_str:
            rel_part = path_str.split("/videos/", 1)[-1]
            for candidate_base in (Path("openshorts-repo/output"), Path("output"), Path("../openshorts-repo/output")):
                local_file = candidate_base / rel_part
                if local_file.exists():
                    shutil.copy2(local_file, destination_path)
                    logger.info(f"Copied clip from local directory to: {destination_path}")
                    return True

        # Fallback to quoted HTTP request
        quoted_url = urllib.parse.quote(clip_url, safe=":/%?&=+#@")
        req = urllib.request.Request(quoted_url, headers={"User-Agent": "ShortsScheduler/2.0"})
        with urllib.request.urlopen(req, timeout=300) as resp, open(destination_path, "wb") as out:
            shutil.copyfileobj(resp, out)
        logger.info(f"Downloaded clip to: {destination_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to download clip from {clip_url}: {e}")
        return False

def monitor_job(job_id):
    """Polls OpenShorts for job status with retry resilience until completed or failed."""
    logger.info(f"Monitoring OpenShorts job: {job_id}")
    CURRENT_STATE["current_job_id"] = job_id
    CURRENT_STATE["current_stage"] = "processing"

    consecutive_errors = 0
    max_consecutive_errors = 6
    last_log = ""

    while True:
        status, payload = api_request("GET", f"/api/status/{job_id}")
        if status >= 400:
            consecutive_errors += 1
            logger.warning(f"Status poll temporary error #{consecutive_errors}/{max_consecutive_errors} (HTTP {status})")
            if consecutive_errors >= max_consecutive_errors:
                logger.error(f"Too many consecutive poll errors for job {job_id}. Aborting.")
                return "failed", None
            time.sleep(JOB_CHECK_INTERVAL_SEC)
            continue

        consecutive_errors = 0
        state = payload.get("status")
        logs = payload.get("logs") or []
        
        if logs and logs[-1] != last_log:
            last_log = logs[-1]
            logger.info(f"[{job_id}] Progress: {last_log}")

        if state == "completed":
            result = payload.get("result") or {}
            logger.info(f"Job {job_id} successfully completed!")
            return "completed", result
        elif state == "failed":
            logger.error(f"Job {job_id} failed according to OpenShorts API!")
            return "failed", None

        time.sleep(JOB_CHECK_INTERVAL_SEC)

def run_pipeline_step():
    """Main single iteration step of the autonomous loop (concurrency-safe)."""
    try:
        load_dotenv(override=True)
    except Exception:
        pass
    CURRENT_STATE["last_poll_time"] = datetime.now(timezone.utc).isoformat()
    queue = load_queue()
    if not queue.get("pending"):
        CURRENT_STATE["current_stage"] = "idle"
        CURRENT_STATE["current_item"] = None
        CURRENT_STATE["current_job_id"] = None
        return

    # Pop the first pending item atomically and persist immediately
    item = queue["pending"].pop(0)
    url = item["url"]
    item_id = item.get("id", str(int(time.time())))
    item["id"] = item_id
    save_queue(queue)

    CURRENT_STATE["current_item"] = item
    CURRENT_STATE["current_stage"] = "submitting"

    logger.info(f"Starting processing for queued video [{item_id}]: {url}")

    job_id = submit_video_job(url, item.get("options"))
    if not job_id:
        item["error"] = "Failed to submit job to OpenShorts API"
        item["failed_at"] = datetime.now(timezone.utc).isoformat()
        
        fresh_queue = load_queue()
        fresh_queue["failed"].append(item)
        save_queue(fresh_queue)
        CURRENT_STATE["current_stage"] = "idle"
        return

    item["job_id"] = job_id
    item["started_at"] = datetime.now(timezone.utc).isoformat()
    
    # Save into processing list
    fresh_queue = load_queue()
    fresh_queue["processing"].append(item)
    save_queue(fresh_queue)

    # Monitor job (this can take 5-30 minutes)
    state, result = monitor_job(job_id)

    # Re-read FRESH queue from disk to preserve any new tasks added during processing!
    fresh_queue = load_queue()
    fresh_queue["processing"] = [p for p in fresh_queue.get("processing", []) if p.get("job_id") != job_id]

    if state == "completed" and result:
        CURRENT_STATE["current_stage"] = "downloading_clips"
        clips = result.get("clips") or []
        downloaded_clips = []
        video_dir = OUTPUT_DIR / f"video_{item_id}"
        video_dir.mkdir(parents=True, exist_ok=True)

        for i, clip in enumerate(clips):
            title = clip.get("title") or clip.get("video_title_for_youtube_short") or f"Short #{i+1}"
            raw_clip_url = clip.get("video_url") or ""
            if raw_clip_url.startswith("/"):
                clip_url = f"{OPENSHORTS_API_URL}{raw_clip_url}"
            else:
                clip_url = raw_clip_url

            clip_filename = f"short_{i+1:02d}.mp4"
            dest_path = video_dir / clip_filename

            if download_clip(clip_url, dest_path):
                rel_path = f"video_{item_id}/{clip_filename}"
                downloaded_clips.append({
                    "clip_index": i,
                    "title": title,
                    "relative_path": rel_path,
                    "local_path": str(dest_path.resolve()),
                    "hook_text": clip.get("viral_hook_text") or "",
                    "youtube_short_title": title,
                    "status": "ready_for_posting"
                })

        item["clips"] = downloaded_clips
        item["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Handle Auto-Posting across configured target accounts (YouTube, TikTok, Instagram, X)
        options = item.get("options") or {}
        target_account_ids = options.get("target_accounts") or []
        auto_post = bool(options.get("auto_post", AUTO_POST_GLOBAL)) or bool(target_account_ids)

        if auto_post:
            CURRENT_STATE["current_stage"] = "auto_posting"
            stagger_hours = float(options.get("schedule_interval_hours", AUTO_POST_INTERVAL_HOURS))
            initial_delay = float(options.get("schedule_delay_hours", 1.0))

            target_accounts = []
            if get_account and target_account_ids:
                for aid in target_account_ids:
                    acc = get_account(aid)
                    if acc and acc.get("enabled", True):
                        target_accounts.append(acc)

            # Fallback to all enabled accounts if auto_post requested without specific account list
            if not target_accounts and load_accounts_raw:
                target_accounts = [a for a in load_accounts_raw() if a.get("enabled", True)]

            if target_accounts and post_clip_to_account:
                logger.info(f"Auto-posting {len(downloaded_clips)} clips to {len(target_accounts)} target account(s)...")
                for idx, clip_info in enumerate(downloaded_clips):
                    clip_info.setdefault("postings", {})
                    sched_time = datetime.now(timezone.utc) + timedelta(hours=initial_delay + (idx * stagger_hours))

                    for acc in target_accounts:
                        acc_id = acc.get("id")
                        acc_name = acc.get("name")
                        try:
                            post_res = post_clip_to_account(
                                account=acc,
                                video_path=clip_info["local_path"],
                                title=clip_info["youtube_short_title"],
                                description=clip_info.get("hook_text", ""),
                                scheduled_time=sched_time
                            )
                            clip_info["postings"][acc_id] = {
                                "account_id": acc_id,
                                "account_name": acc_name,
                                "platform": acc.get("platform"),
                                "status": post_res.get("status"),
                                "url": post_res.get("url"),
                                "id": post_res.get("id"),
                                "publish_at": post_res.get("publishAt"),
                                "error": None
                            }
                            # Preserve YouTube backward compatibility fields
                            if acc.get("platform") == "youtube":
                                clip_info["youtube_status"] = post_res.get("status")
                                clip_info["youtube_id"] = post_res.get("id")
                                clip_info["youtube_url"] = post_res.get("url")
                                clip_info["publish_at"] = post_res.get("publishAt")
                            logger.info(f"Clip #{idx+1} posted to [{acc_name}] ({acc.get('platform')}): {post_res.get('url')}")
                        except Exception as e:
                            logger.error(f"Failed to post clip #{idx+1} to [{acc_name}]: {e}")
                            clip_info["postings"][acc_id] = {
                                "account_id": acc_id,
                                "account_name": acc_name,
                                "platform": acc.get("platform"),
                                "status": "posting_failed",
                                "error": str(e)
                            }
                            if acc.get("platform") == "youtube":
                                clip_info["youtube_error"] = str(e)

                    # Update overall clip status
                    statuses = [p.get("status") for p in clip_info["postings"].values()]
                    if any(s == "scheduled" for s in statuses):
                        clip_info["status"] = "scheduled"
                    elif any(s in ("published", "uploaded", "simulated", "draft") for s in statuses):
                        clip_info["status"] = "published"
                    elif all(s == "posting_failed" for s in statuses):
                        clip_info["status"] = "posting_failed"

            elif upload_short_to_youtube:
                logger.info(f"Auto-posting {len(downloaded_clips)} clips to default YouTube channel...")
                for idx, clip_info in enumerate(downloaded_clips):
                    try:
                        sched_time = datetime.now(timezone.utc) + timedelta(hours=initial_delay + (idx * stagger_hours))
                        post_res = upload_short_to_youtube(
                            video_file_path=clip_info["local_path"],
                            title=clip_info["youtube_short_title"],
                            scheduled_publish_time=sched_time
                        )
                        clip_info["youtube_status"] = post_res.get("status")
                        clip_info["youtube_id"] = post_res.get("id")
                        clip_info["youtube_url"] = post_res.get("url")
                        clip_info["publish_at"] = post_res.get("publishAt")
                        clip_info["status"] = "scheduled" if post_res.get("publishAt") else "published"
                        logger.info(f"Clip #{idx+1} posted to YouTube: {post_res.get('url')}")
                    except Exception as e:
                        logger.error(f"Failed to auto-post clip #{idx+1}: {e}")
                        clip_info["youtube_error"] = str(e)
                        clip_info["status"] = "posting_failed"

        fresh_queue["completed"].append(item)
        logger.info(f"Video [{item_id}] completed! Generated {len(downloaded_clips)} shorts.")
    else:
        item["error"] = "Job failed during execution in OpenShorts"
        item["failed_at"] = datetime.now(timezone.utc).isoformat()
        fresh_queue["failed"].append(item)

    save_queue(fresh_queue)
    CURRENT_STATE["current_stage"] = "idle"
    CURRENT_STATE["current_item"] = None
    CURRENT_STATE["current_job_id"] = None

def main_loop():
    """Runs the autonomous daemon loop."""
    CURRENT_STATE["is_running"] = True
    logger.info("=== OpenShorts Autonomous Scheduler Started ===")
    logger.info(f"OpenShorts API URL: {OPENSHORTS_API_URL}")
    logger.info(f"Queue File: {QUEUE_FILE.resolve()}")
    logger.info(f"Output Directory: {OUTPUT_DIR.resolve()}")
    logger.info(f"Auto-post globally enabled: {AUTO_POST_GLOBAL}")

    while True:
        try:
            run_pipeline_step()
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user.")
            CURRENT_STATE["is_running"] = False
            break
        except Exception as e:
            logger.exception(f"Unexpected error in daemon loop: {e}")
        
        time.sleep(POLL_INTERVAL_SEC)

if __name__ == "__main__":
    main_loop()
