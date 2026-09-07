#!/usr/bin/env python3
"""
Social Media Auto-Poster for YouTube Shorts.
Uploads processed 9:16 short videos directly to YouTube using YouTube Data API v3,
supporting schedule dates (publishAt), titles, descriptions, and hashtags.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ShortsPoster")

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    YOUTUBE_SDK_AVAILABLE = True
except ImportError:
    YOUTUBE_SDK_AVAILABLE = False
    logger.warning("Google API Client libs not installed. Running in Dry-Run / Local Staging Mode.")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def resolve_credentials_paths(client_secrets_path: str = None, token_path: str = None):
    """Finds existing client_secrets.json and token.json paths across project directory."""
    if not client_secrets_path:
        env_secrets = os.getenv("YOUTUBE_CLIENT_SECRETS")
        candidates = [
            env_secrets,
            "credentials/client_secrets.json",
            "client_secrets.json"
        ]
        client_secrets_path = next((c for c in candidates if c and Path(c).is_file()), "credentials/client_secrets.json")

    if not token_path:
        env_token = os.getenv("YOUTUBE_TOKEN_FILE")
        candidates = [
            env_token,
            "credentials/token.json",
            "token.json"
        ]
        token_path = next((c for c in candidates if c and Path(c).is_file()), "credentials/token.json")

    return Path(client_secrets_path), Path(token_path)

def check_youtube_auth_status():
    """Checks current YouTube credentials status for Web UI and healthchecks."""
    if not YOUTUBE_SDK_AVAILABLE:
        return {"status": "unavailable", "message": "Google API Client libs not installed (Dry Run mode)"}

    secrets_file, token_file = resolve_credentials_paths()

    if token_file.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
            if creds and creds.valid:
                return {"status": "authenticated", "message": f"Authenticated via {token_file}"}
            elif creds and creds.expired and creds.refresh_token:
                return {"status": "refreshable", "message": "Token expired but can refresh automatically"}
        except Exception as e:
            return {"status": "error", "message": f"Corrupt token file: {e}"}

    if secrets_file.is_file():
        return {"status": "ready_to_auth", "message": f"Found {secrets_file}, authorization needed"}

    return {"status": "missing_secrets", "message": f"Missing {secrets_file}. Place OAuth 2.0 Client credentials there"}

def get_authenticated_service(client_secrets_file: str = None, token_file: str = None):
    """Authenticates with YouTube API and returns the service object."""
    if not YOUTUBE_SDK_AVAILABLE:
        raise RuntimeError("google-api-python-client is not installed.")

    secrets_path, token_path = resolve_credentials_paths(client_secrets_file, token_file)

    creds = None
    if token_path.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            logger.warning(f"Could not load credentials from {token_path}: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            logger.info("Refreshing expired YouTube OAuth2 token...")
            creds.refresh(Request())
        else:
            if not secrets_path.is_file():
                raise FileNotFoundError(
                    f"Missing client secrets at '{secrets_path}'. "
                    "Download OAuth 2.0 Credentials (Desktop application) from Google Cloud Console "
                    "and place it in 'credentials/client_secrets.json'."
                )
            logger.info(f"Initiating OAuth flow using {secrets_path}...")
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        logger.info(f"Saved refreshed YouTube OAuth credentials to {token_path}")

    return build("youtube", "v3", credentials=creds)

def upload_short_to_youtube(
    video_file_path: str,
    title: str,
    description: str = "",
    tags: list = None,
    scheduled_publish_time: datetime = None,
    client_secrets_file: str = None,
    token_file: str = None
):
    """
    Uploads a short video to YouTube.
    If scheduled_publish_time is provided (in UTC), status.privacyStatus will be set to 'private'
    and status.publishAt will set the exact schedule.
    """
    if tags is None:
        tags = ["Shorts", "ViralShorts", "AIClips"]

    full_title = f"{title} #Shorts" if "#Shorts" not in title else title
    full_description = f"{description}\n\nGenerated automatically via OpenShorts Pipeline.\n#Shorts #AI"

    if not YOUTUBE_SDK_AVAILABLE:
        logger.info(f"[DRY RUN] Simulating upload for video: {video_file_path}")
        logger.info(f"[DRY RUN] Title: {full_title}")
        if scheduled_publish_time:
            logger.info(f"[DRY RUN] Scheduled for: {scheduled_publish_time.isoformat()}")
        return {
            "id": "DRY_RUN_ID",
            "title": full_title,
            "status": "simulated",
            "url": "https://youtube.com/shorts/DRY_RUN_ID",
            "publishAt": scheduled_publish_time.isoformat() if scheduled_publish_time else None
        }

    youtube = get_authenticated_service(client_secrets_file, token_file)

    body = {
        "snippet": {
            "title": full_title[:100],
            "description": full_description,
            "tags": tags,
            "categoryId": "22"  # People & Blogs / Entertainment
        },
        "status": {
            "privacyStatus": "private" if scheduled_publish_time else "public",
            "selfDeclaredMadeForKids": False
        }
    }

    if scheduled_publish_time:
        publish_str = scheduled_publish_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body["status"]["publishAt"] = publish_str
        body["status"]["privacyStatus"] = "private"

    # Use 4MB chunk size for reliable upload tracking
    media = MediaFileUpload(video_file_path, chunksize=4 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    logger.info(f"Uploading '{full_title}' to YouTube...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    short_url = f"https://youtube.com/shorts/{video_id}"
    logger.info(f"Successfully uploaded short! {short_url}")

    return {
        "id": video_id,
        "title": full_title,
        "status": "uploaded",
        "url": short_url,
        "publishAt": body["status"].get("publishAt")
    }

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python poster.py <path_to_video.mp4> <title> [schedule_hours_from_now]")
        status_info = check_youtube_auth_status()
        print(f"Current Auth Status: {status_info['status']} - {status_info['message']}")
        sys.exit(1)

    video_path = sys.argv[1]
    video_title = sys.argv[2]
    hours_delay = float(sys.argv[3]) if len(sys.argv) > 3 else 0

    sched_time = datetime.now(timezone.utc) + timedelta(hours=hours_delay) if hours_delay > 0 else None

    res = upload_short_to_youtube(
        video_file_path=video_path,
        title=video_title,
        scheduled_publish_time=sched_time
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
