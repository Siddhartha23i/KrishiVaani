# KrishiVaani — Railway Production Deployment Guide

## 1. Overview & Architecture Preservation

This deployment configuration is prepared specifically for **Railway** to run KrishiVaani's Telugu-first voice assistant in continuous production.

### Preserved Core Architecture:
- **Telegram Bot Interface:** Continuous long-polling mode via `python -m app.telegram.run` (no webhooks, no public HTTP tunnels required).
- **Speech-to-Text (STT):** Gnani Prisma v3.0 (`gnani-vachana==0.9.0`).
- **LLM Reasoning:** Groq API using model `openai/gpt-oss-120b`.
- **Text-to-Speech (TTS):** Gnani Timbre v2.5 Kaveri voice (16 kHz WAV encoded to mono OGG Opus).
- **Meteorology & Warnings:** WeatherAPI short-range forecasts and IMD district alerts.
- **Agricultural Evidence RAG:** SQLite-backed approved PJTSAU/TGDPS advisory retrieval.
- **Privacy & Location Minimisation:** Telegram user consent persistence with temporary 30-minute in-memory location context.

---

## 2. Linux Compatibility & Dependency Check

- **Base Image:** `python:3.11-slim` (Debian-based, matching the local Python 3.11 runtime).
- **Audio Conversion & System FFmpeg:** In Linux, audio conversion between OGG Opus (Telegram voice notes) and linear PCM WAV requires `ffmpeg` with `libopus`. The Dockerfile installs Debian's official `ffmpeg` and packages `imageio-ffmpeg` to ensure seamless voice note decoding and synthesis.
- **Zero Windows Dependencies:** Verified that all imported libraries (`python-telegram-bot`, `gnani-vachana`, `groq`, `pydantic-settings`, `httpx`, `requests`, `PyMuPDF`, `beautifulsoup4`) are cross-platform with pre-built Linux wheels. Windows-only packages (`pywin32`, `comtypes`) are completely bypassed and excluded.

---

## 3. Persistent Volume & Knowledge Paths

### Exact Local & Container Paths:
| Resource | Local Relative Path | Container Path (with Railway Volume Mounted at `/app/data`) |
| :--- | :--- | :--- |
| **SQLite Database** | `data/krishivaani.db` | `/app/data/krishivaani.db` |
| **Approved PJTAU PDFs** | `data/pjtau/raw_pdfs/*.pdf` | `/app/data/pjtau/raw_pdfs/*.pdf` |
| **Approved TGDPS PDFs** | `data/tgdps/raw_pdfs/*.pdf` | `/app/data/tgdps/raw_pdfs/*.pdf` |
| **Seed Knowledge Backup** | `data_seed/` | `/app/data_seed/` |

### Volume Mount Configuration:
- **Mount Path:** `/app/data`
- **Volume Initialization Guarantee:** When an empty persistent volume is attached at `/app/data`, `docker-entrypoint.sh` and [`ensure_database_initialized()`](file:///d:/Sid_Folder/Sid_projects/Gnani_Project/app/db/database.py) check if `/app/data/krishivaani.db` exists:
  - **First Boot:** Copies the 51 approved knowledge items and raw PDFs from `/app/data_seed/` into `/app/data/`.
  - **Subsequent Restarts & Redeployments:** Detects the existing database and preserves all live farmer consent records, sessions, and database updates. It **never** resets or overwrites active data.

---

## 4. Environment Variables Specification

Set these in the **Railway Dashboard → Service → Variables** tab. Never commit values to Git.

### Required Variables:
| Variable Name | Description | Example / Format |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Bot API token from Telegram [@BotFather](https://t.me/BotFather) | `123456789:ABCdefGHIjklMNOpqrsTUVwxyz` |
| `GROQ_API_KEY` | API Key for Groq Cloud LLM inference | `gsk_...` |
| `GNANI_API_KEY` | API Key for Gnani Speech platform (Prisma STT & Timbre TTS) | `...` |
| `WEATHERAPI_API_KEY` | API Key for WeatherAPI meteorological forecast data | `...` |

### Optional / Recommended Variables:
| Variable Name | Default Value | Description |
| :--- | :--- | :--- |
| `GROQ_MODEL_ID` | `openai/gpt-oss-120b` | Groq reasoning model ID |
| `GROQ_REQUEST_TIMEOUT_SECONDS` | `15.0` | Timeout for LLM completions |
| `GROQ_MAX_TOKENS` | `1500` | Max tokens generated per query |
| `GROQ_TEMPERATURE` | `0.1` | Temperature for factual evidence compliance |
| `DATABASE_PATH` | `/app/data/krishivaani.db` | Absolute path to persistent SQLite database |
| `IMD_API_KEY` | `""` | IMD District Warning API Key |
| `IMD_JWT_TOKEN` | `""` | IMD District Warning JWT Token |
| `DEBUG` | `False` | Application debug mode |

---

## 5. Railway Configuration Files

### A. [`Dockerfile`](file:///d:/Sid_Folder/Sid_projects/Gnani_Project/Dockerfile)
```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app
COPY data_seed /app/data_seed

COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "app.telegram.run"]
```

### B. [`railway.json`](file:///d:/Sid_Folder/Sid_projects/Gnani_Project/railway.json)
```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "startCommand": "python -m app.telegram.run",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

### C. [`docker-entrypoint.sh`](file:///d:/Sid_Folder/Sid_projects/Gnani_Project/docker-entrypoint.sh)
Ensures Unix LF line endings, creates `/app/data` directories, copies seed files on fresh volume creation, and uses `exec "$@"` so Python runs as PID 1 to receive shutdown and restart signals directly.

---

## 6. Process Crash Recovery & High Availability

1. **Telegram Polling Resilience:**
   - In [`app/telegram/handlers.py`](file:///d:/Sid_Folder/Sid_projects/Gnani_Project/app/telegram/handlers.py), all message handlers catch unexpected exceptions, delivering safe polite Telugu fallback voice notices without crashing the polling loop.
   - Idempotent `UpdateDeduplicator` ensures retried Telegram updates are never executed twice.
2. **Container Restart Policy:**
   - `railway.json` sets `restartPolicyType: "ON_FAILURE"` with `restartPolicyMaxRetries: 10`.
   - If an unhandled process termination or out-of-memory event occurs, Railway immediately re-spawns the container.
3. **Clean Polling Resumption:**
   - [`app/telegram/run.py`](file:///d:/Sid_Folder/Sid_projects/Gnani_Project/app/telegram/run.py) starts polling with `drop_pending_updates=True`. If the bot was offline, it safely flushes queued backlog items to avoid cascading rate-limit loops.

---

## 7. Step-by-Step GitHub + Railway Deployment Instructions

### Step 1: Initialize Git and Push to a Private GitHub Repository
1. In PowerShell, initialize Git and check status:
   ```powershell
   git init
   git status
   ```
2. Verify that `.env`, `data/`, and `*.data.json` are **NOT** staged (guaranteed by `.gitignore`):
   ```powershell
   git status --ignored
   ```
3. Commit and push to your private GitHub repository:
   ```powershell
   git add .
   git commit -m "Prepare KrishiVaani for Railway production deployment"
   git branch -M main
   git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/<YOUR_REPOSITORY_NAME>.git
   git push -u origin main
   ```

### Step 2: Create a New Project on Railway
1. Log in to your [Railway Dashboard](https://railway.com/dashboard).
2. Click **+ New Project**.
3. Select **Deploy from GitHub repo**.
4. Choose your private KrishiVaani repository.
5. Click **Deploy Now**. (The initial build will start, but you must configure the volume and variables before the bot can poll).

### Step 3: Attach the Persistent Volume
1. In the Railway Project canvas, click on your newly created service.
2. Navigate to the **Volumes** tab.
3. Click **+ Add Volume**.
4. Configure the volume:
   - **Mount Path:** `/app/data`
5. Click **Add Volume**.

### Step 4: Configure Environment Variables
1. In your Railway service, open the **Variables** tab.
2. Add the four required keys:
   - `TELEGRAM_BOT_TOKEN`
   - `GROQ_API_KEY`
   - `GNANI_API_KEY`
   - `WEATHERAPI_API_KEY`
3. (Optional) Add `GROQ_MODEL_ID` set to `openai/gpt-oss-120b`.
4. Click **Deploy Changes**.

### Step 5: Verify Deployment & Logs
1. Click on the **Deployments** tab and select the active deployment.
2. Open the **Deploy Logs**.
3. You should see:
   ```text
   [KrishiVaani] Starting container entrypoint...
   [KrishiVaani] Initializing database from approved seed (/app/data_seed/krishivaani.db)...
   [KrishiVaani] Database initialized successfully.
   [KrishiVaani] Volume initialization complete. Executing command: python -m app.telegram.run
   INFO - Database and schema verified successfully.
   INFO - Starting KrishiVaani Telegram bot polling...
   INFO - Initializing GroqProvider for model 'openai/gpt-oss-120b'
   ```
4. Open Telegram, find your bot, and send a Telugu voice message:
   `"నమస్తే , రేపు నిజామాబాద్ లో వర్షం పడుతుందా?"`
5. The bot will reply with a natural conversational Telugu voice note.
