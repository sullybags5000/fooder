# Fooder

A Telegram bot that turns a meal photo into a Fitbit food log entry.

Snap → LLM estimates calories + macros → you confirm → logged to Fitbit.

## Stack

- **Telegram Bot API** (python-telegram-bot) — chat UX, no mobile app needed
- **Vision LLM** — Gemini 2.0 Flash (default, cheap) or OpenAI GPT-4o-mini
- **Fitbit Web API** — OAuth 2.0 PKCE, custom food log endpoint
- **FastAPI** — webhook receiver + Fitbit OAuth callback
- **SQLite** — stores Fitbit tokens per Telegram chat

## Architecture

```
Phone (Telegram)
    │ photo + optional caption
    ▼
Fooder (FastAPI + python-telegram-bot)
    │
    ├──▶ Vision LLM  →  MealAnalysis JSON
    │
    └──▶ Fitbit API  →  POST /1/user/-/foods/log.json
```

## Setup

### 1. Telegram bot

- Message `@BotFather` on Telegram → `/newbot` → copy the token.

### 2. Fitbit app

- Go to https://dev.fitbit.com/apps → Register a new app.
- App type: **Server**. OAuth 2.0 redirect URL: `http://localhost:8000/fitbit/callback`
  (or your public URL). Scopes needed: **nutrition**.
- Copy Client ID and Client Secret.

### 3. Vision LLM key

Pick one:
- Gemini: https://aistudio.google.com/apikey (has a free tier)
- OpenAI: https://platform.openai.com/api-keys

### 4. Configure

```bash
cp .env.example .env
$EDITOR .env
```

### 5. Run

```bash
./scripts/run_dev.sh
```

This uses polling (no webhook) — good for development. For production, set
`TELEGRAM_WEBHOOK_URL` and run:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Usage

1. `/start` in Telegram
2. `/connect` → open the Fitbit link → approve
3. Send a meal photo (optionally with a caption like "large portion, with butter")
4. Review the estimate → tap **Log it**
5. Entry appears in your Fitbit food diary

## Project layout

```
fooder/
├── app/
│   ├── main.py          # FastAPI + polling entrypoint
│   ├── config.py        # Pydantic settings (loads .env)
│   ├── db.py            # SQLite storage (tokens, pending meals)
│   ├── models.py        # MealAnalysis / FoodItem schemas
│   ├── vision.py        # Gemini / OpenAI vision adapter
│   ├── fitbit.py        # OAuth PKCE + food logging
│   └── telegram_bot.py  # Handlers (commands, photo, callbacks)
├── scripts/run_dev.sh
├── requirements.txt
├── .env.example
└── README.md
```

## Roadmap

- [ ] Per-meal classification (breakfast/lunch/dinner from time-of-day)
- [ ] Edit-before-log flow (inline keyboard to tweak numbers)
- [ ] Daily summary command (`/today`)
- [ ] Barcode support (for packaged food)
- [ ] Multi-user persistence with Postgres
