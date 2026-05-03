"""FastAPI entrypoint.

Two run modes:

  1. Polling (dev):
       python -m app.main --polling
     No public URL needed; the bot pulls updates from Telegram.

  2. Webhook (prod):
       uvicorn app.main:app --host 0.0.0.0 --port 8000
     Requires TELEGRAM_WEBHOOK_URL to be set to a public HTTPS URL.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update

from app import db
from app.config import settings
from app.telegram_bot import build_application

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("fooder")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    tg = build_application()
    await tg.initialize()
    await tg.bot.set_webhook(
        url=f"{settings.telegram_webhook_url.rstrip('/')}/telegram/webhook",
        secret_token=settings.telegram_webhook_secret,
        drop_pending_updates=True,
    )
    await tg.start()
    app.state.tg = tg
    log.info("Webhook set to %s", settings.telegram_webhook_url)
    try:
        yield
    finally:
        await tg.bot.delete_webhook()
        await tg.stop()
        await tg.shutdown()


app = FastAPI(title="Fooder", lifespan=lifespan)


@app.get("/")
async def root():
    return {"ok": True, "service": "fooder"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="bad secret")
    tg = request.app.state.tg
    update = Update.de_json(await request.json(), tg.bot)
    await tg.process_update(update)
    return {"ok": True}


# ---------- Polling mode ----------

async def _run_polling() -> None:
    db.init_db()
    tg = build_application()
    log.info("Starting Telegram polling (dev mode)…")
    await tg.initialize()
    await tg.start()
    await tg.updater.start_polling(drop_pending_updates=True)
    try:
        await asyncio.Event().wait()
    finally:
        await tg.updater.stop()
        await tg.stop()
        await tg.shutdown()


if __name__ == "__main__":
    if "--polling" in sys.argv:
        try:
            asyncio.run(_run_polling())
        except KeyboardInterrupt:
            pass
    else:
        import uvicorn
        uvicorn.run(
            "app.main:app",
            host=settings.app_host,
            port=settings.app_port,
            reload=False,
        )
