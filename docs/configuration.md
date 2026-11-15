# Configuration & Environment Variables

This document provides the complete reference for all environment variables used by KrishiVaani, verified against [`app/core/config.py`](../app/core/config.py).

## Environment Variables Reference

| Variable Name | Required / Optional | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | **Required** | `None` | Telegram Bot API token obtained from [@BotFather](https://t.me/BotFather). Powers asynchronous long-polling. |
| `SARVAM_API_KEY` | **Required** | `None` | Primary LLM inference API key for Sarvam AI (`sarvam-105b-conversations`). |
| `USER_ID_HASH_SALT` | **Required** | `None` | Secret cryptographic salt for HMAC-SHA256 hashing of Telegram user IDs before SQLite persistence. |
| `GNANI_API_KEY` | **Required** | `None` | Gnani AI API key powering Prisma v3.0 Speech-to-Text and Timbre v2.5 Text-to-Speech (Kaveri voice). |
| `GROQ_API_KEY` | **Optional (Fallback)** | `None` | Groq Cloud API key. Automatically invoked if Sarvam encounters provider or network failure. |
| `LLM_PROVIDER` | Optional | `sarvam` | Active LLM provider selection (`sarvam` or `groq`). |
| `SARVAM_MODEL` | Optional | `sarvam-105b-conversations` | Sarvam AI conversational model identifier. |
| `SARVAM_MAX_TOKENS` | Optional | `900` | Maximum token limit for Sarvam responses. |
| `SARVAM_LENGTH_RETRY_MULTIPLIER` | Optional | `1.5` | Multiplier for token expansion upon incomplete completion retry. |
| `GROQ_MODEL_ID` | Optional | `openai/gpt-oss-120b` | Groq fallback model identifier. |
| `GROQ_REQUEST_TIMEOUT_SECONDS` | Optional | `15.0` | Timeout in seconds for Groq API calls. |
| `GROQ_MAX_TOKENS` | Optional | `1200` | Maximum token limit for Groq completions. |
| `GROQ_TEMPERATURE` | Optional | `0.1` | Sampling temperature for factual evidence adherence. |
| `GROQ_REASONING_EFFORT` | Optional | `low` | Reasoning effort parameter for supported models. |
| `WEATHERAPI_API_KEY` | Optional | `None` | WeatherAPI.com key for live 3-day meteorological forecasts and current conditions. |
| `WEATHERAPI_BASE_URL` | Optional | `https://api.weatherapi.com/v1` | WeatherAPI REST endpoint base URL. |
| `WEATHER_REQUEST_TIMEOUT_SECONDS` | Optional | `10.0` | Timeout in seconds for meteorological provider lookups. |
| `IMD_API_KEY` | Optional | `None` | India Meteorological Department (IMD) API key for district weather warnings. |
| `IMD_JWT_TOKEN` | Optional | `None` | IMD public warning JWT authorization token. |
| `DATABASE_PATH` | Optional | `BASE_DIR / data / krishivaani.db` | Path to persistent SQLite database (`/app/data/krishivaani.db` on Railway). |
| `DEBUG` | Optional | `False` | Enables verbose FastAPI debugging and route reload. |
| `PJTAU_ARCHIVE_URL` | Optional | `https://pjtau.edu.in/agromet-advisories/` | Source URL for PJTSAU agromet advisory bulletins. |
| `PJTAU_DATA_DIR` | Optional | `BASE_DIR / data / pjtau` | Storage directory for downloaded PJTSAU PDFs. |
| `PJTAU_MAX_PDF_SIZE_BYTES` | Optional | `26214400` (25 MB) | Maximum accepted PDF size for bulletin ingestion. |
| `PJTAU_REQUEST_TIMEOUT_SECONDS` | Optional | `20.0` | Ingestion scrape timeout for PJTSAU portal. |
| `TGDPS_PORTAL_URL` | Optional | `https://tgdps.telangana.gov.in/` | Source URL for TGDPS weather reports. |
| `TGDPS_DATA_DIR` | Optional | `BASE_DIR / data / tgdps` | Storage directory for downloaded TGDPS PDFs. |
| `TGDPS_MAX_PDF_SIZE_BYTES` | Optional | `26214400` (25 MB) | Maximum accepted PDF size for TGDPS reports. |
| `TGDPS_REQUEST_TIMEOUT_SECONDS` | Optional | `20.0` | Ingestion scrape timeout for TGDPS portal. |

---

## Local Setup

Create a `.env` file from the checked-in template:

```bash
cp .env.example .env
```

Populate the required credentials:

```dotenv
TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
SARVAM_API_KEY="your-sarvam-api-key"
USER_ID_HASH_SALT="random-secure-string-for-hmac-hashing"
GNANI_API_KEY="your-gnani-api-key"

# Optional fallback and weather:
GROQ_API_KEY="your-groq-api-key"
WEATHERAPI_API_KEY="your-weatherapi-key"
```

> [!IMPORTANT]
> Never commit `.env` or any production secrets to version control. The repository `.gitignore` strictly excludes `.env` and local database files.

