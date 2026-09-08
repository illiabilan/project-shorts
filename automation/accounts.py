#!/usr/bin/env python3
"""
Accounts management module for multi-platform auto-posting.
Supports N-accounts for YouTube, TikTok, Instagram, and Twitter (X).
Stores configuration safely in credentials/accounts.json.
"""

import os
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any

logger = logging.getLogger("AccountsManager")

# Project paths
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"
CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

ACCOUNTS_FILE = Path(os.getenv("ACCOUNTS_FILE", str(CREDENTIALS_DIR / "accounts.json")))

PLATFORMS = {
    "youtube": {
        "name": "YouTube Shorts",
        "icon": "fa-brands fa-youtube",
        "color": "text-red-500",
        "bg": "bg-red-500/10",
        "border": "border-red-500/30"
    },
    "tiktok": {
        "name": "TikTok",
        "icon": "fa-brands fa-tiktok",
        "color": "text-cyan-400",
        "bg": "bg-cyan-500/10",
        "border": "border-cyan-500/30"
    },
    "instagram": {
        "name": "Instagram Reels",
        "icon": "fa-brands fa-instagram",
        "color": "text-pink-400",
        "bg": "bg-pink-500/10",
        "border": "border-pink-500/30"
    },
    "twitter": {
        "name": "X (Twitter)",
        "icon": "fa-brands fa-x-twitter",
        "color": "text-slate-200",
        "bg": "bg-slate-500/10",
        "border": "border-slate-500/30"
    }
}

def mask_string(val: Optional[str], show_start: int = 4, show_end: int = 4) -> str:
    """Safely masks sensitive credentials for client-side display."""
    if not val or not isinstance(val, str):
        return ""
    s = val.strip()
    if len(s) <= (show_start + show_end):
        return "***"
    return f"{s[:show_start]}...{s[-show_end:]}"

def mask_account_secrets(account: Dict[str, Any]) -> Dict[str, Any]:
    """Returns a copy of the account with masked credentials for UI rendering."""
    acc = json.loads(json.dumps(account))
    creds = acc.get("credentials", {})
    masked_creds = {}

    platform = acc.get("platform", "").lower()
    for key, val in creds.items():
        if isinstance(val, str):
            if "key" in key.lower() or "secret" in key.lower() or "token" in key.lower() or "password" in key.lower():
                masked_creds[key] = mask_string(val)
                masked_creds[f"{key}_set"] = bool(val)
            else:
                masked_creds[key] = val
        else:
            masked_creds[key] = val

    acc["credentials"] = masked_creds
    return acc

def load_accounts_raw() -> List[Dict[str, Any]]:
    """Loads raw accounts list from JSON storage with fallback migration."""
    if not ACCOUNTS_FILE.exists():
        initial = []
        # Check if legacy credentials/client_secrets.json exists
        legacy_secrets = CREDENTIALS_DIR / "client_secrets.json"
        legacy_token = CREDENTIALS_DIR / "token.json"
        if legacy_secrets.exists() or legacy_token.exists():
            initial.append({
                "id": "yt_default",
                "platform": "youtube",
                "name": "YouTube (За замовчуванням)",
                "enabled": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "credentials": {
                    "client_secrets_file": str(legacy_secrets),
                    "token_file": str(legacy_token),
                    "privacy_status": "public",
                    "category_id": "22",
                    "made_for_kids": False
                },
                "settings": {
                    "default_tags": ["#Shorts", "#ViralShorts", "#AI"]
                },
                "status": {
                    "status": "ready" if legacy_token.exists() else "ready_to_auth",
                    "message": "Знайдено збережені файли YouTube авторизації"
                }
            })
        save_accounts_raw(initial)
        return initial

    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "accounts" in data:
            return data["accounts"]
        return []
    except Exception as e:
        logger.error(f"Error loading accounts file {ACCOUNTS_FILE}: {e}")
        return []

def save_accounts_raw(accounts: List[Dict[str, Any]]) -> None:
    """Atomically writes accounts list to storage."""
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = ACCOUNTS_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(accounts, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(ACCOUNTS_FILE)

def get_account(account_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves full unmasked account by ID."""
    accounts = load_accounts_raw()
    for acc in accounts:
        if acc.get("id") == account_id:
            return acc
    return None

def get_masked_accounts() -> List[Dict[str, Any]]:
    """Retrieves all accounts with masked credentials for Web UI."""
    accounts = load_accounts_raw()
    return [mask_account_secrets(a) for a in accounts]

def upsert_account(data: Dict[str, Any]) -> Dict[str, Any]:
    """Creates or updates an account."""
    accounts = load_accounts_raw()
    account_id = data.get("id")
    platform = (data.get("platform") or "youtube").lower()
    
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}. Supported: {list(PLATFORMS.keys())}")

    now_iso = datetime.now(timezone.utc).isoformat()
    existing_idx = None
    existing_acc = None

    if account_id:
        for idx, acc in enumerate(accounts):
            if acc.get("id") == account_id:
                existing_idx = idx
                existing_acc = acc
                break

    if not account_id:
        account_id = f"{platform}_{int(time.time())}"

    # Merge credentials carefully so we do not wipe out existing secrets if masked/empty
    new_creds = data.get("credentials", {})
    if existing_acc:
        merged_creds = dict(existing_acc.get("credentials", {}))
        for k, v in new_creds.items():
            if v is not None and v != "" and not (isinstance(v, str) and v.startswith("***")):
                merged_creds[k] = v
        final_creds = merged_creds
    else:
        final_creds = new_creds

    # Handle platform specific file paths if raw JSON provided
    if platform == "youtube":
        client_secrets_json = final_creds.pop("client_secrets_json", None)
        if client_secrets_json and isinstance(client_secrets_json, str) and client_secrets_json.strip():
            secrets_path = CREDENTIALS_DIR / f"client_secrets_{account_id}.json"
            secrets_path.write_text(client_secrets_json.strip(), encoding="utf-8")
            final_creds["client_secrets_file"] = str(secrets_path)

        token_json = final_creds.pop("token_json", None)
        if token_json and isinstance(token_json, str) and token_json.strip():
            token_path = CREDENTIALS_DIR / f"token_{account_id}.json"
            token_path.write_text(token_json.strip(), encoding="utf-8")
            final_creds["token_file"] = str(token_path)

        if not final_creds.get("client_secrets_file"):
            default_secrets = CREDENTIALS_DIR / "client_secrets.json"
            if default_secrets.exists():
                final_creds["client_secrets_file"] = str(default_secrets)

        if not final_creds.get("token_file"):
            final_creds["token_file"] = str(CREDENTIALS_DIR / f"token_{account_id}.json")

    account_entry = {
        "id": account_id,
        "platform": platform,
        "name": data.get("name") or f"{PLATFORMS[platform]['name']} #{len(accounts)+1}",
        "enabled": bool(data.get("enabled", True)),
        "created_at": existing_acc.get("created_at") if existing_acc else now_iso,
        "updated_at": now_iso,
        "credentials": final_creds,
        "settings": data.get("settings") or {
            "default_tags": ["#Shorts", "#AIClips"],
            "title_prefix": "",
            "title_suffix": ""
        },
        "status": existing_acc.get("status") if existing_acc else {
            "status": "configured",
            "message": "Акаунт створено. Перевірте підключення."
        }
    }

    if existing_idx is not None:
        accounts[existing_idx] = account_entry
    else:
        accounts.append(account_entry)

    save_accounts_raw(accounts)
    logger.info(f"Upserted account [{account_id}] ({platform})")
    return account_entry

def delete_account(account_id: str) -> bool:
    """Deletes an account and associated credential files if dedicated."""
    accounts = load_accounts_raw()
    target = None
    for acc in accounts:
        if acc.get("id") == account_id:
            target = acc
            break

    if not target:
        return False

    accounts = [acc for acc in accounts if acc.get("id") != account_id]
    save_accounts_raw(accounts)

    # Clean up account-specific files if they exist
    for file_key in ("client_secrets_file", "token_file"):
        path_str = target.get("credentials", {}).get(file_key)
        if path_str and account_id in path_str:
            p = Path(path_str)
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                    logger.info(f"Removed account credential file: {p}")
                except Exception as e:
                    logger.warning(f"Could not remove {p}: {e}")

    logger.info(f"Deleted account [{account_id}]")
    return True

def update_account_status(account_id: str, status_str: str, message: str, extra: Dict[str, Any] = None) -> None:
    """Updates the cached connectivity status for an account."""
    accounts = load_accounts_raw()
    updated = False
    for acc in accounts:
        if acc.get("id") == account_id:
            status_obj = {
                "status": status_str,
                "message": message,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
            if extra:
                status_obj.update(extra)
            acc["status"] = status_obj
            updated = True
            break
    if updated:
        save_accounts_raw(accounts)
