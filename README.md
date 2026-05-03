# Fooder

A Telegram bot that turns a meal photo into a nutrition log entry in Google Sheets.

Snap → LLM estimates calories + macros → you confirm → row appended to your sheet.

## Stack

- **Telegram Bot API** (python-telegram-bot) — chat UX, no mobile app needed
- **Vision LLM** — Gemini 2.0 Flash (default, cheap) or OpenAI GPT-4o-mini
- **Google Sheets** — service-account auth, append-only row writes
- **FastAPI** — webhook receiver (optional; polling works fine for dev)
- **SQLite** — short-lived pending-meal buffer (between photo + confirm)

## Architecture

```
Phone (Telegram)
    │ photo + optional caption
    ▼
Fooder
    │
    ├──▶ Vision LLM  →  MealAnalysis JSON
    │
    └──▶ Google Sheets  →  append row
```

## Setup

### 1. Telegram bot

- Message `@BotFather` on Telegram → `/newbot` → copy the token.

### 2. Vision LLM key

Pick one:
- Gemini: https://aistudio.google.com/apikey (has a free tier — recommended)
- OpenAI: https://platform.openai.com/api-keys

### 3. Google Sheet + service account

1. Create a Google Sheet. Copy its ID from the URL:
   `https://docs.google.com/spreadsheets/d/` **`<SPREADSHEET_ID>`** `/edit`
2. Go to https://console.cloud.google.com → create/select a project.
3. Enable two APIs:
   - Google Sheets API
   - Google Drive API
4. Create a service account: IAM & Admin → Service Accounts → Create.
5. Create a JSON key for it: *Keys* tab → *Add key* → *JSON*. Download it.
6. Save the key as `service-account.json` in the project root.
7. Open the service account's JSON file, find the `client_email` value
   (looks like `fooder-bot@your-project.iam.gserviceaccount.com`),
   and **share your Google Sheet with that email as Editor**.

### 4. Configure

```bash
cp .env.example .env
$EDITOR .env
```

Fill in:
- `TELEGRAM_BOT_TOKEN`
- `GEMINI_API_KEY` (or `OPENAI_API_KEY` + set `VISION_PROVIDER=openai`)
- `GOOGLE_SHEETS_SPREADSHEET_ID`
- optionally `TELEGRAM_ALLOWED_USER_IDS` to restrict who can use the bot

### 5. Run

```bash
./scripts/run_dev.sh
```

This uses polling — no webhook / public URL required. For production, set
`TELEGRAM_WEBHOOK_URL` and run:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Usage

1. Message `/start` in Telegram
2. Send a meal photo (optionally with a caption like "large portion, with butter")
3. Review the estimate → tap **Log it**
4. A new row appears in your sheet:

| timestamp_utc | telegram_user_id | telegram_username | description | total_calories | protein_g | carbs_g | fat_g | confidence | items_detail | notes |

## Project layout

```
fooder/
├── app/
│   ├── main.py          # FastAPI + polling entrypoint
│   ├── config.py        # Pydantic settings (loads .env)
│   ├── db.py            # SQLite (pending meals buffer)
│   ├── models.py        # MealAnalysis / FoodItem schemas
│   ├── vision.py        # Gemini / OpenAI vision adapter
│   ├── sheets.py        # Google Sheets logger (gspread)
│   └── telegram_bot.py  # Handlers (commands, photo, callbacks)
├── scripts/run_dev.sh
├── requirements.txt
├── .env.example
└── README.md
```

## Roadmap

- [ ] `/today` command — daily totals from the sheet
- [ ] Edit-before-log flow (tweak numbers inline)
- [ ] Barcode support for packaged food
- [ ] Reminder scheduling (nudge if you skip a meal)
- [ ] Fitbit / Google Health API sync when food-log support lands
