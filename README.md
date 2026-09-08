<div align="center">

# 🎬 Project Shorts

**Fully autonomous local AI studio to turn long-form YouTube videos into viral 9:16 Shorts, TikToks & Reels**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![FFmpeg VA-API](https://img.shields.io/badge/FFmpeg-VA--API_&_NVENC-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![AMD ROCm](https://img.shields.io/badge/AMD-ROCm_Hardware-ED1C24?style=for-the-badge&logo=amd&logoColor=white)](https://rocm.docs.amd.com/)
[![Gemini 3.6 Flash](https://img.shields.io/badge/Google-Gemini_AI-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://aistudio.google.com/)

[Features](#-features) • [Architecture](#-architecture) • [Quick Start](#-quick-start) • [Hardware Acceleration](#-hardware-acceleration) • [Configuration](#-configuration) • [YouTube Auto-Posting](#-youtube-auto-posting--oauth)

<br/>

**Languages / Мови:** [🇬🇧 English](README.md) • [🇺🇦 Українська](README.uk.md)

</div>

---

## 💡 What is Project Shorts?

**Project Shorts** is a private, unlimited, and fully automated content generation pipeline running entirely on your own local hardware. It ingests any long-form YouTube video (podcasts, lectures, interviews, gaming streams), finds the highest-retention viral moments using AI, tracks active speakers in dynamic 9:16 vertical frames, generates animated word-by-word subtitles, creates freeze-frame hook intro cards, and automatically schedules uploads to YouTube Shorts.

**Zero monthly SaaS subscriptions. Zero watermarks. Zero minute quotas.**

---

## ✨ Features

* 🧠 **Multi-Provider AI Intelligence**: Seamless support for Google Gemini (3.6 Flash / 3.1 Flash-Lite), OpenRouter (Claude 3.5 Sonnet, Llama 3.3 70B, DeepSeek V3), Fireworks AI, Anthropic Claude, OpenAI (GPT-4o), and local Ollama.
* ⚡ **GPU Hardware Acceleration (VA-API & NVENC)**: Renders a 70-second 1080x1920 vertical video in just **~4–5 seconds** on AMD Radeon GPUs (RX 7000/6000 series) and NVIDIA GeForce RTX cards.
* 🎙️ **Local Faster-Whisper ASR**: Free, highly accurate speech-to-text with word-level timestamps (`large-v3-turbo` / `small` / `base`) running on GPU (ROCm / CUDA) or CPU.
* 🎯 **Smart Face Tracking (MediaPipe + YOLO)**: Active speaker detection that smoothly keeps subjects centered in 9:16 (modes: *Track*, *Split-screen* for multi-person podcasts, *Screencast*).
* 🖼️ **Freeze-Frame Hook Intro Card**: Generates a beautiful 1.8s intro card with heavy Gaussian blur (`radius=30`) of the first frame, soft dark vignette, and prominent hook title. Subtitle synchronization is 100% preserved without drift or audio delay.
* 🎨 **Modern Material Design 3 Web Dashboard**:
  - Interactive video processing queue with live stage-by-stage status.
  - Video gallery with in-browser preview player and direct download links.
  - 3-mode theme switcher (Light, Dark, System Auto).
  - Complete control over all pipeline and encoder settings without touching `.env`.
* 📅 **Autonomous Scheduling & Auto-Posting**:
  - 1-click interactive OAuth 2.0 authorization in the browser.
  - Automatic scheduled publishing to YouTube Shorts (`publishAt`) with custom intervals (e.g. every 3 hours).

---

## 🏛️ Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│               WEB CONTROL CENTER (http://localhost:8080)               │
│   • YouTube URL submission (single links or batch mode)                │
│   • Live pipeline monitoring, service healthchecks & log streaming     │
│   • Rendered 9:16 Shorts gallery with embedded video player            │
│   • Interactive settings (.env) & YouTube OAuth authorization          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│           Safe Atomic Queue (queue.json) & Scheduler (scheduler.py)    │
│   • Atomic file writes to prevent race conditions & task loss          │
│   • Quality Gate bypass for bulletproof yt-dlp downloading             │
│   • Automatic retries with exponential backoff on transient errors     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               OpenShorts AI Engine (http://localhost:8000)             │
│   • Gemini / OpenRouter: Viral moment detection + catchy hook titles   │
│   • MediaPipe / YOLO: Dynamic face tracking & intelligent 9:16 crop    │
│   • Faster-Whisper: Word-level timestamps & animated ASS subtitles     │
│   • FFmpeg Engine: Freeze-frame intro card + VA-API / NVENC rendering   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    YouTube Auto-Poster / Deliverables                  │
│   • Saves finished .mp4 deliverables to processed_shorts/              │
│   • Automatic scheduled publishing (publishAt) at set intervals        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Option 1: Linux / macOS (1-Command Setup)

1. **Clone the repository**:
   ```bash
   git clone git@github.com:illiabilan/project-shorts.git
   cd project-shorts
   ```

2. **Run the automated setup script**:
   ```bash
   ./setup.sh
   ```
   The script automatically:
   - Installs the high-speed `uv` Python package manager;
   - Provisions a Python 3.11 virtual environment;
   - Clones the customized engine fork [`illiabilan/openshorts`](https://github.com/illiabilan/openshorts);
   - Installs all dependencies and verifies system FFmpeg;
   - Initializes your local `.env` configuration.

3. **Launch the entire system**:
   ```bash
   ./start.sh
   # or: .venv/bin/python run_all.py
   ```
   *The Web Dashboard will automatically open in your browser at:* **`http://localhost:8080`**.

4. **Stopping the system**:
   ```bash
   ./stop.sh
   # or press Ctrl + C in the terminal
   ```

---

### Option 2: Windows (1-Click Setup, No Terminal Required)

1. Download or clone this repository into any folder.
2. Double-click **`Встановити_Windows.bat`** (the script will install all requirements, download portable FFmpeg if needed, and place a **Project Shorts** shortcut on your Desktop).
3. Daily launch: double-click the **`Project Shorts`** Desktop shortcut (or **`Запустити_Shorts.bat`** / **`Запустити_Shorts_Вікно.vbs`**).
4. For non-technical users, see the simple step-by-step guide: [ІНСТРУКЦІЯ_ДЛЯ_КУМА.txt](ІНСТРУКЦІЯ_ДЛЯ_КУМА.txt).

---

### Option 3: Docker / Podman Compose

```bash
cp .env.example .env

# Using Docker:
docker compose up -d --build

# Using Podman:
podman-compose up -d --build
```

---

## ⚙️ Configuration

All settings can be configured via the **Settings** tab in the Web Dashboard or in the `.env` file:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | `gemini` | AI Provider (`gemini`, `openrouter`, `fireworks`, `anthropic`, `openai`, `ollama`) |
| `GEMINI_API_KEY` | - | Free API key from [Google AI Studio](https://aistudio.google.com/) |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Model for viral transcript analysis and hook generation |
| `FFMPEG_ENCODER` | `vaapi` | Video encoder: `vaapi` (AMD GPU), `nvenc` (NVIDIA GPU), `x264` (CPU) |
| `WHISPER_MODEL` | `large-v3-turbo` | Whisper model size (`large-v3-turbo`, `small`, `base`) |
| `WHISPER_DEVICE` | `cuda` | Whisper compute device: `cuda` (ROCm / CUDA) or `cpu` |
| `WHISPER_COMPUTE`| `float16` | Compute precision (`float16` for GPU, `int8` for CPU) |
| `CLIP_MIN_SECONDS` | `20.0` | Minimum short clip duration in seconds |
| `CLIP_MAX_SECONDS` | `180.0` | Maximum short clip duration in seconds (supports TikTok >60s) |
| `AUTO_HOOK` | `1` | `1` to enable hook title, `0` to disable |
| `AUTO_HOOK_MODE` | `intro` | `intro` (freeze-frame card with blur) or `overlay` (header over video) |
| `AUTO_HOOK_SECONDS` | `1.8` | Duration of the intro card in seconds |
| `AUTO_HOOK_STYLE` | `classic` | Hook visual style (`classic`, `dark`, `yellow`, `red`, `outline`) |
| `AUTO_POST` | `false` | Enable automatic YouTube Shorts scheduling |
| `AUTO_POST_INTERVAL_HOURS`| `3.0` | Interval between published videos in hours |

---

## ⚡ Hardware Acceleration

The optimal architecture is **hybrid**:
* **Content Intelligence (LLM)**: Handled by cloud-based **Gemini 3.6 Flash** (1M token context window analyzes a 1-hour podcast in 2–3 seconds for less than $0.001).
* **ASR & Video Rendering**: Handled locally on your GPU:
  - **AMD Radeon GPUs (RX 7000 / 6000 series, e.g. RX 7800 XT)**: Enable `FFMPEG_ENCODER=vaapi`. A 70-second video with custom filters and subtitles concatenates in just **4.8 seconds** with virtually zero CPU load!
  - **NVIDIA GeForce RTX**: Set `FFMPEG_ENCODER=nvenc` and `WHISPER_DEVICE=cuda`.

---

## 📤 YouTube Auto-Posting & OAuth

1. Download your `client_secrets.json` (OAuth 2.0 Client ID, Desktop Application) from the [Google Cloud Console](https://console.cloud.google.com/).
2. Place it at `credentials/client_secrets.json`.
3. In the Web Dashboard, open the Accounts modal and click **"Authorize Google"** (or run `./auth_youtube.sh` in terminal).
4. Approve the channel access in your browser.
5. Done! The token is securely stored and the scheduler will automatically publish deliverables according to your configured interval.

---

## 📄 License

This project is open source and available under the [MIT License](LICENSE). Feel free to use it for personal channels, media agencies, or content automation.

