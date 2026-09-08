#!/usr/bin/env python3
"""
Social Media Multi-Platform Auto-Poster.
Supports N-accounts for:
- YouTube Shorts (YouTube Data API v3)
- TikTok (TikTok Content Posting API v2 & Direct/Draft & Upload-Post)
- Instagram Reels (Meta Graph API Resumable Upload & Container Publish)
- Twitter / X (Twitter API v1.1 Chunked Video Upload + v2 Tweet)
"""

import os
import sys
import time
import json
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
try:
    import httpx
except ImportError:
    httpx = None

try:
    from requests_oauthlib import OAuth1
except ImportError:
    OAuth1 = None

# Setup logging
logger = logging.getLogger("ShortsPoster")

# Google API Client for YouTube
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    YOUTUBE_SDK_AVAILABLE = True
except ImportError:
    YOUTUBE_SDK_AVAILABLE = False
    logger.warning("Google API Client libs not installed. YouTube running in Dry-Run mode.")

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

# ---------------------------------------------------------------------------
# Helpers & Credential Resolvers
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# YouTube Poster & Checker
# ---------------------------------------------------------------------------

def check_youtube_auth_status(client_secrets_file: str = None, token_file: str = None) -> Dict[str, Any]:
    """Checks current YouTube credentials status for Web UI and healthchecks."""
    if not YOUTUBE_SDK_AVAILABLE:
        return {"status": "unavailable", "message": "Google API Client libs not installed (Dry Run mode)"}

    secrets_file, token_file = resolve_credentials_paths(client_secrets_file, token_file)

    if token_file.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), YOUTUBE_SCOPES)
            if creds and creds.valid:
                # Optionally fetch channel info
                try:
                    yt = build("youtube", "v3", credentials=creds)
                    ch = yt.channels().list(part="snippet", mine=True).execute()
                    items = ch.get("items", [])
                    if items:
                        ch_title = items[0]["snippet"]["title"]
                        return {
                            "status": "authenticated",
                            "message": f"Авторизовано канал: {ch_title}",
                            "channel_title": ch_title
                        }
                except Exception:
                    pass
                return {"status": "authenticated", "message": f"Авторизовано через {token_file.name}"}
            elif creds and creds.expired and creds.refresh_token:
                return {"status": "refreshable", "message": "Токен прострочено, але може оновитись автоматично"}
        except Exception as e:
            return {"status": "error", "message": f"Пошкоджений файл токена: {e}"}

    if secrets_file.is_file():
        return {"status": "ready_to_auth", "message": f"Знайдено {secrets_file.name}, потрібна авторизація каналу"}

    return {"status": "missing_secrets", "message": f"Відсутній {secrets_file.name}. Завантажте OAuth 2.0 Client credentials"}

def get_youtube_service(client_secrets_file: str = None, token_file: str = None):
    """Authenticates with YouTube API and returns the service object."""
    if not YOUTUBE_SDK_AVAILABLE:
        raise RuntimeError("google-api-python-client is not installed.")

    secrets_path, token_path = resolve_credentials_paths(client_secrets_file, token_file)

    creds = None
    if token_path.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), YOUTUBE_SCOPES)
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
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), YOUTUBE_SCOPES)
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
    token_file: str = None,
    privacy_status: str = "public"
) -> Dict[str, Any]:
    """Uploads a short video to YouTube with scheduled publishing support."""
    if tags is None:
        tags = ["Shorts", "ViralShorts", "AIClips"]

    full_title = f"{title} #Shorts" if "#Shorts" not in title else title
    full_description = f"{description}\n\nGenerated automatically via OpenShorts Pipeline.\n#Shorts #AI"

    if not YOUTUBE_SDK_AVAILABLE:
        logger.info(f"[DRY RUN] Simulating upload for video: {video_file_path}")
        return {
            "id": f"DRY_RUN_YT_{int(time.time())}",
            "title": full_title,
            "status": "simulated",
            "url": "https://youtube.com/shorts/simulated",
            "publishAt": scheduled_publish_time.isoformat() if scheduled_publish_time else None
        }

    youtube = get_youtube_service(client_secrets_file, token_file)

    body = {
        "snippet": {
            "title": full_title[:100],
            "description": full_description,
            "tags": tags,
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": "private" if scheduled_publish_time else privacy_status,
            "selfDeclaredMadeForKids": False
        }
    }

    if scheduled_publish_time:
        publish_str = scheduled_publish_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body["status"]["publishAt"] = publish_str
        body["status"]["privacyStatus"] = "private"

    media = MediaFileUpload(video_file_path, chunksize=4 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    logger.info(f"Uploading '{full_title}' to YouTube...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"YouTube upload progress: {int(status.progress() * 100)}%")

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

# ---------------------------------------------------------------------------
# TikTok Poster & Checker
# ---------------------------------------------------------------------------

def check_tiktok_account_status(creds: Dict[str, Any]) -> Dict[str, Any]:
    """Tests TikTok credentials validity."""
    access_token = creds.get("access_token")
    upload_post_key = creds.get("upload_post_key")

    if access_token:
        url = "https://open.tiktokapis.com/v2/user/info/?fields=open_id,union_id,avatar_url,display_name"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json().get("data", {}).get("user", {})
                d_name = data.get("display_name") or data.get("open_id") or "TikTok User"
                return {"status": "authenticated", "message": f"Авторизовано профіль: {d_name}", "user_info": data}
            else:
                err_msg = r.json().get("error", {}).get("message") or r.text
                return {"status": "error", "message": f"TikTok API помилка: {err_msg}"}
        except Exception as e:
            return {"status": "error", "message": f"Не вдалося з'єднатись з TikTok: {e}"}

    if upload_post_key:
        return {"status": "authenticated", "message": "Підключено через Upload-Post API"}

    return {"status": "missing_credentials", "message": "Потрібен Access Token або Upload-Post API Key"}

def upload_short_to_tiktok(
    video_file_path: str,
    title: str,
    description: str = "",
    tags: list = None,
    creds: Dict[str, Any] = None,
    scheduled_publish_time: datetime = None
) -> Dict[str, Any]:
    """
    Uploads short to TikTok using official Content Posting API v2,
    or fallback to Upload-Post / Direct Simulation.
    """
    creds = creds or {}
    access_token = creds.get("access_token")
    upload_post_key = creds.get("upload_post_key")
    post_mode = creds.get("post_mode", "DIRECT_POST") # DIRECT_POST or MEDIA_UPLOAD (Draft)
    privacy_level = creds.get("privacy_level", "PUBLIC_TO_EVERYONE")

    full_tags = " ".join(f"#{t.lstrip('#')}" for t in (tags or ["Shorts", "Viral", "AI"]))
    full_caption = f"{title} {full_tags}\n{description}".strip()[:2100]

    video_p = Path(video_file_path)
    if not video_p.is_file():
        raise FileNotFoundError(f"Video file not found: {video_file_path}")

    file_size = video_p.stat().st_size

    # Method 1: Official TikTok Content Posting API v2
    if access_token:
        logger.info(f"Publishing to TikTok via Official Content Posting API ({post_mode})...")
        init_endpoint = (
            "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
            if post_mode == "MEDIA_UPLOAD"
            else "https://open.tiktokapis.com/v2/post/publish/video/init/"
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8"
        }

        # Initialize chunk upload
        chunk_size = min(file_size, 10 * 1024 * 1024) # 10MB chunk
        total_chunk_count = (file_size + chunk_size - 1) // chunk_size

        payload = {
            "post_info": {
                "title": full_caption,
                "privacy_level": privacy_level,
                "disable_duet": False,
                "disable_stitch": False,
                "disable_comment": False,
                "video_cover_timestamp_ms": 1000
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunk_count
            }
        }

        r = requests.post(init_endpoint, headers=headers, json=payload, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"TikTok Init Failed ({r.status_code}): {r.text}")

        init_data = r.json().get("data", {})
        publish_id = init_data.get("publish_id")
        upload_url = init_data.get("upload_url")

        if not upload_url:
            raise RuntimeError(f"TikTok did not return upload_url: {r.text}")

        # Upload video in chunks
        with open(video_p, "rb") as vf:
            for chunk_idx in range(total_chunk_count):
                chunk_bytes = vf.read(chunk_size)
                start_byte = chunk_idx * chunk_size
                end_byte = start_byte + len(chunk_bytes) - 1
                chunk_headers = {
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk_bytes)),
                    "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}"
                }
                up_resp = requests.put(upload_url, headers=chunk_headers, data=chunk_bytes, timeout=120)
                if up_resp.status_code not in (200, 201, 206):
                    raise RuntimeError(f"TikTok Chunk upload error: {up_resp.status_code} {up_resp.text}")

        logger.info(f"TikTok upload complete, publish_id: {publish_id}")
        return {
            "id": publish_id,
            "title": full_caption,
            "status": "published" if post_mode == "DIRECT_POST" else "draft",
            "url": f"https://www.tiktok.com/@creator/video/{publish_id}",
            "publish_id": publish_id
        }

    # Method 2: Upload-Post API
    if upload_post_key:
        logger.info("Publishing to TikTok via Upload-Post API...")
        url = "https://api.upload-post.com/api/upload"
        headers = {"Authorization": f"Apikey {upload_post_key}"}
        user = creds.get("upload_post_user") or "default"

        data_payload = {
            "user": user,
            "title": full_caption,
            "platform[]": ["tiktok"],
            "tiktok_title": full_caption,
            "post_mode": post_mode,
            "async_upload": "true"
        }

        with open(video_p, "rb") as f:
            files = {"video": (video_p.name, f.read(), "video/mp4")}

        resp = requests.post(url, headers=headers, data=data_payload, files=files, timeout=120)
        if resp.status_code not in (200, 201, 202):
            raise RuntimeError(f"Upload-Post Error ({resp.status_code}): {resp.text}")

        res_json = resp.json()
        return {
            "id": res_json.get("id") or str(int(time.time())),
            "title": full_caption,
            "status": "submitted",
            "url": res_json.get("post_url") or "https://www.tiktok.com",
            "response": res_json
        }

    # Method 3: Dry-Run Simulation
    logger.info(f"[SIMULATION] TikTok post simulated for {video_file_path}")
    return {
        "id": f"SIMULATED_TT_{int(time.time())}",
        "title": full_caption,
        "status": "simulated",
        "url": "https://www.tiktok.com/@simulated"
    }

# ---------------------------------------------------------------------------
# Instagram Reels Poster & Checker
# ---------------------------------------------------------------------------

def check_instagram_account_status(creds: Dict[str, Any]) -> Dict[str, Any]:
    """Verifies Instagram Business / Creator Account ID and Access Token via Meta Graph API."""
    account_id = creds.get("instagram_account_id")
    token = creds.get("access_token")

    if not account_id or not token:
        return {"status": "missing_credentials", "message": "Введіть Instagram Account ID та User/Page Access Token"}

    url = f"https://graph.facebook.com/v20.0/{account_id}"
    params = {"fields": "id,username,name,profile_picture_url", "access_token": token}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            username = data.get("username") or data.get("name") or account_id
            return {
                "status": "authenticated",
                "message": f"Авторизовано Instagram: @{username}",
                "account_info": data
            }
        else:
            err = r.json().get("error", {}).get("message") or r.text
            return {"status": "error", "message": f"Meta Graph API помилка: {err}"}
    except Exception as e:
        return {"status": "error", "message": f"Не вдалося перевірити Instagram токен: {e}"}

def upload_short_to_instagram(
    video_file_path: str,
    title: str,
    description: str = "",
    tags: list = None,
    creds: Dict[str, Any] = None,
    scheduled_publish_time: datetime = None
) -> Dict[str, Any]:
    """Uploads vertical clip to Instagram Reels via Meta Graph API Resumable Upload."""
    creds = creds or {}
    account_id = creds.get("instagram_account_id")
    token = creds.get("access_token")

    full_tags = " ".join(f"#{t.lstrip('#')}" for t in (tags or ["Reels", "Viral", "Shorts"]))
    caption = f"{title}\n\n{description}\n\n{full_tags}".strip()[:2200]

    video_p = Path(video_file_path)
    if not video_p.is_file():
        raise FileNotFoundError(f"Video file not found: {video_file_path}")

    if not account_id or not token:
        logger.info(f"[SIMULATION] Instagram Reels upload simulated for {video_file_path}")
        return {
            "id": f"SIMULATED_IG_{int(time.time())}",
            "title": caption,
            "status": "simulated",
            "url": "https://www.instagram.com/reels/simulated"
        }

    file_size = video_p.stat().st_size
    logger.info(f"Initializing Instagram Reels Resumable Upload ({file_size} bytes)...")

    # Step 1: Create Resumable Upload Session Container
    init_url = f"https://graph.facebook.com/v20.0/{account_id}/media"
    init_params = {
        "upload_type": "resumable",
        "media_type": "REELS",
        "caption": caption,
        "share_to_feed": "true" if creds.get("share_to_feed", True) else "false",
        "access_token": token
    }
    r = requests.post(init_url, data=init_params, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Instagram container init error ({r.status_code}): {r.text}")

    init_res = r.json()
    container_id = init_res.get("id")
    upload_uri = init_res.get("uri")

    if not upload_uri:
        raise RuntimeError(f"Meta Graph API did not return upload URI: {init_res}")

    # Step 2: Upload Video Bytes
    logger.info(f"Uploading video bytes to Meta Graph Video server: {upload_uri}")
    with open(video_p, "rb") as vf:
        video_data = vf.read()

    upload_headers = {
        "Authorization": f"OAuth {token}",
        "offset": "0",
        "file_size": str(file_size)
    }
    up_resp = requests.post(upload_uri, headers=upload_headers, data=video_data, timeout=300)
    if up_resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"Instagram binary upload error ({up_resp.status_code}): {up_resp.text}")

    # Step 3: Poll status until FINISHED
    logger.info(f"Checking Instagram container processing status ({container_id})...")
    status_url = f"https://graph.facebook.com/v20.0/{container_id}"
    ready = False
    for _ in range(30):
        time.sleep(3)
        st_resp = requests.get(status_url, params={"fields": "status_code", "access_token": token}, timeout=10)
        if st_resp.status_code == 200:
            st_code = st_resp.json().get("status_code")
            logger.info(f"Instagram container status: {st_code}")
            if st_code == "FINISHED":
                ready = True
                break
            elif st_code in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram processing failed with status: {st_code}")

    if not ready:
        raise TimeoutError("Timed out waiting for Instagram video container processing.")

    # Step 4: Publish Container
    publish_url = f"https://graph.facebook.com/v20.0/{account_id}/media_publish"
    pub_resp = requests.post(publish_url, data={"creation_id": container_id, "access_token": token}, timeout=30)
    if pub_resp.status_code not in (200, 201):
        raise RuntimeError(f"Instagram media_publish error ({pub_resp.status_code}): {pub_resp.text}")

    media_id = pub_resp.json().get("id")
    ig_url = f"https://www.instagram.com/reel/{media_id}/"
    logger.info(f"Successfully published to Instagram Reels: {ig_url}")

    return {
        "id": media_id,
        "title": caption,
        "status": "published",
        "url": ig_url,
        "container_id": container_id
    }

# ---------------------------------------------------------------------------
# Twitter / X Poster & Checker
# ---------------------------------------------------------------------------

def check_twitter_account_status(creds: Dict[str, Any]) -> Dict[str, Any]:
    """Validates Twitter / X API Key and OAuth tokens."""
    api_key = creds.get("api_key")
    api_secret = creds.get("api_secret")
    access_token = creds.get("access_token")
    access_token_secret = creds.get("access_token_secret")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        return {
            "status": "missing_credentials",
            "message": "Потрібні API Key, API Secret, Access Token та Access Token Secret (OAuth 1.0a)"
        }

    if not OAuth1:
        return {"status": "error", "message": "requests_oauthlib не встановлено"}

    auth = OAuth1(api_key, api_secret, access_token, access_token_secret)
    try:
        r = requests.get("https://api.twitter.com/2/users/me", auth=auth, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", {})
            uname = data.get("username") or data.get("name") or "X User"
            return {
                "status": "authenticated",
                "message": f"Авторизовано X: @{uname}",
                "user_info": data
            }
        else:
            err = r.json().get("detail") or r.text
            return {"status": "error", "message": f"X API помилка ({r.status_code}): {err}"}
    except Exception as e:
        return {"status": "error", "message": f"Помилка з'єднання з X: {e}"}

def upload_short_to_twitter(
    video_file_path: str,
    title: str,
    description: str = "",
    tags: list = None,
    creds: Dict[str, Any] = None,
    scheduled_publish_time: datetime = None
) -> Dict[str, Any]:
    """Uploads video to Twitter via v1.1 Chunked Upload and posts Tweet via v2 API."""
    creds = creds or {}
    api_key = creds.get("api_key")
    api_secret = creds.get("api_secret")
    access_token = creds.get("access_token")
    access_token_secret = creds.get("access_token_secret")

    full_tags = " ".join(f"#{t.lstrip('#')}" for t in (tags or ["Shorts", "Video"]))
    tweet_text = f"{title} {full_tags}\n{description}".strip()[:275]

    video_p = Path(video_file_path)
    if not video_p.is_file():
        raise FileNotFoundError(f"Video file not found: {video_file_path}")

    if not all([api_key, api_secret, access_token, access_token_secret]) or not OAuth1:
        logger.info(f"[SIMULATION] X / Twitter post simulated for {video_file_path}")
        return {
            "id": f"SIMULATED_X_{int(time.time())}",
            "title": tweet_text,
            "status": "simulated",
            "url": "https://x.com/simulated"
        }

    auth = OAuth1(api_key, api_secret, access_token, access_token_secret)
    file_size = video_p.stat().st_size
    upload_url = "https://upload.twitter.com/1.1/media/upload.json"

    # Step 1: INIT
    logger.info(f"Initializing Twitter Chunked Upload ({file_size} bytes)...")
    init_data = {
        "command": "INIT",
        "total_bytes": str(file_size),
        "media_type": "video/mp4",
        "media_category": "tweet_video"
    }
    r = requests.post(upload_url, data=init_data, auth=auth, timeout=30)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Twitter INIT error ({r.status_code}): {r.text}")

    media_id = r.json().get("media_id_string")

    # Step 2: APPEND chunks
    chunk_size = 4 * 1024 * 1024 # 4MB
    segment_id = 0
    with open(video_p, "rb") as vf:
        while True:
            chunk = vf.read(chunk_size)
            if not chunk:
                break
            append_data = {
                "command": "APPEND",
                "media_id": media_id,
                "segment_index": str(segment_id)
            }
            files = {"media": chunk}
            ar = requests.post(upload_url, data=append_data, files=files, auth=auth, timeout=120)
            if ar.status_code not in (200, 204):
                raise RuntimeError(f"Twitter APPEND error ({ar.status_code}): {ar.text}")
            segment_id += 1

    # Step 3: FINALIZE
    logger.info(f"Finalizing Twitter video upload (media_id: {media_id})...")
    fin_data = {"command": "FINALIZE", "media_id": media_id}
    fr = requests.post(upload_url, data=fin_data, auth=auth, timeout=30)
    if fr.status_code not in (200, 201):
        raise RuntimeError(f"Twitter FINALIZE error ({fr.status_code}): {fr.text}")

    fin_json = fr.json()
    processing_info = fin_json.get("processing_info")

    # Step 4: Check async processing if required
    while processing_info and processing_info.get("state") in ("pending", "in_progress"):
        wait_secs = processing_info.get("check_after_secs", 5)
        logger.info(f"Waiting {wait_secs}s for Twitter video processing...")
        time.sleep(wait_secs)
        sr = requests.get(upload_url, params={"command": "STATUS", "media_id": media_id}, auth=auth, timeout=20)
        if sr.status_code != 200:
            break
        processing_info = sr.json().get("processing_info")

    if processing_info and processing_info.get("state") == "failed":
        err_detail = processing_info.get("error", {}).get("message", "Unknown error")
        raise RuntimeError(f"Twitter video processing failed: {err_detail}")

    # Step 5: Post Tweet via v2 API
    logger.info("Posting Tweet with uploaded video...")
    tweet_payload = {
        "text": tweet_text,
        "media": {"media_ids": [media_id]}
    }
    tr = requests.post("https://api.twitter.com/2/tweets", json=tweet_payload, auth=auth, timeout=30)
    if tr.status_code not in (200, 201):
        raise RuntimeError(f"Twitter post Tweet error ({tr.status_code}): {tr.text}")

    tweet_data = tr.json().get("data", {})
    tweet_id = tweet_data.get("id")
    tweet_url = f"https://x.com/i/status/{tweet_id}"
    logger.info(f"Successfully posted to X: {tweet_url}")

    return {
        "id": tweet_id,
        "title": tweet_text,
        "status": "published",
        "url": tweet_url,
        "media_id": media_id
    }

# ---------------------------------------------------------------------------
# Universal Dispatcher & Multi-Account Router
# ---------------------------------------------------------------------------

def test_account_connection(account: Dict[str, Any]) -> Tuple[bool, str]:
    """Tests connectivity and authentication for any social account."""
    platform = account.get("platform", "").lower()
    creds = account.get("credentials", {})

    if platform == "youtube":
        st = check_youtube_auth_status(
            client_secrets_file=creds.get("client_secrets_file"),
            token_file=creds.get("token_file")
        )
        ok = st.get("status") in ("authenticated", "refreshable")
        return ok, st.get("message", "")

    elif platform == "tiktok":
        st = check_tiktok_account_status(creds)
        ok = st.get("status") == "authenticated"
        return ok, st.get("message", "")

    elif platform == "instagram":
        st = check_instagram_account_status(creds)
        ok = st.get("status") == "authenticated"
        return ok, st.get("message", "")

    elif platform == "twitter":
        st = check_twitter_account_status(creds)
        ok = st.get("status") == "authenticated"
        return ok, st.get("message", "")

    return False, f"Невідома платформа: {platform}"

def post_clip_to_account(
    account: Dict[str, Any],
    video_path: str,
    title: str,
    description: str = "",
    tags: list = None,
    scheduled_time: datetime = None
) -> Dict[str, Any]:
    """Dispatches publishing of a clip to a specific configured account."""
    platform = account.get("platform", "").lower()
    creds = account.get("credentials", {})
    account_id = account.get("id")
    account_name = account.get("name")

    # Apply title prefix/suffix from settings if present
    settings = account.get("settings", {})
    pfx = settings.get("title_prefix", "")
    sfx = settings.get("title_suffix", "")
    effective_title = f"{pfx}{title}{sfx}".strip()

    combined_tags = list(set((tags or []) + settings.get("default_tags", [])))

    logger.info(f"Dispatching clip upload to account '{account_name}' [{account_id}] ({platform})")

    if platform == "youtube":
        res = upload_short_to_youtube(
            video_file_path=video_path,
            title=effective_title,
            description=description,
            tags=combined_tags,
            scheduled_publish_time=scheduled_time,
            client_secrets_file=creds.get("client_secrets_file"),
            token_file=creds.get("token_file"),
            privacy_status=creds.get("privacy_status", "public")
        )
    elif platform == "tiktok":
        res = upload_short_to_tiktok(
            video_file_path=video_path,
            title=effective_title,
            description=description,
            tags=combined_tags,
            creds=creds,
            scheduled_publish_time=scheduled_time
        )
    elif platform == "instagram":
        res = upload_short_to_instagram(
            video_file_path=video_path,
            title=effective_title,
            description=description,
            tags=combined_tags,
            creds=creds,
            scheduled_publish_time=scheduled_time
        )
    elif platform == "twitter":
        res = upload_short_to_twitter(
            video_file_path=video_path,
            title=effective_title,
            description=description,
            tags=combined_tags,
            creds=creds,
            scheduled_publish_time=scheduled_time
        )
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    # Add account metadata to result
    res["account_id"] = account_id
    res["account_name"] = account_name
    res["platform"] = platform
    res["timestamp"] = datetime.now(timezone.utc).isoformat()
    return res

if __name__ == "__main__":
    print("Multi-Platform Poster Engine loaded successfully.")
