"""Telegram bot handlers."""
import io
import logging
import uuid
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import settings
from app import db, sheets, vision
from app.models import MealAnalysis

log = logging.getLogger(__name__)


def _authorized(update: Update) -> bool:
    allowed = settings.allowed_user_ids
    if not allowed:
        return True  # open to everyone
    return update.effective_user and update.effective_user.id in allowed


async def _reject(update: Update) -> None:
    await update.message.reply_text(
        "🔒 This bot is private. Your Telegram ID is not on the allow-list."
    )


# --- Command handlers ---

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return await _reject(update)
    await update.message.reply_text(
        "👋 Welcome to Fooder.\n\n"
        "Send me a photo of your meal and I'll estimate the calories + macros "
        "and log it to your Google Sheet.\n\n"
        "Tip: add a caption with extra context, e.g. 'large portion with butter'.\n\n"
        "Commands: /help  /ping"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return await _reject(update)
    await update.message.reply_text(
        "How to use:\n"
        "1. Send a photo of your meal (optionally with a caption)\n"
        "2. Review the estimate\n"
        "3. Tap *Log it* → a new row is appended to the spreadsheet\n\n"
        "The sheet records timestamp, calories, macros, item breakdown, and your notes.",
        parse_mode="Markdown",
    )


async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return await _reject(update)
    await update.message.reply_text("pong ✅")


# --- Photo handler ---

async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return await _reject(update)

    chat_id = update.effective_chat.id
    user = update.effective_user
    caption = (update.message.caption or "").strip()

    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    buf = io.BytesIO()
    await file.download_to_memory(out=buf)
    image_bytes = buf.getvalue()

    thinking = await update.message.reply_text("🔎 Analyzing meal…")

    try:
        analysis = await vision.analyze_meal(image_bytes, caption)
    except Exception as e:
        log.exception("vision failed")
        await thinking.edit_text(f"⚠️ Vision analysis failed: {e}")
        return

    if not analysis.items or analysis.confidence < 0.2:
        await thinking.edit_text(
            "🤔 I don't see a clear meal in that photo. Try again with better lighting?"
        )
        return

    meal_id = uuid.uuid4().hex[:12]
    db.save_pending_meal(
        meal_id=meal_id,
        chat_id=chat_id,
        user_id=user.id,
        username=user.username,
        analysis=analysis.model_dump(),
    )

    lines = [f"🍽 *{analysis.description}*", ""]
    for it in analysis.items:
        lines.append(f"• {it.name} ({it.portion}) — {int(it.calories)} kcal")
    lines += [
        "",
        f"Totals: *{int(analysis.total_calories)} kcal*  "
        f"P {int(analysis.total_protein_g)}g · C {int(analysis.total_carbs_g)}g · F {int(analysis.total_fat_g)}g",
        f"_confidence {int(analysis.confidence * 100)}%_",
    ]
    if analysis.notes:
        lines.append(f"_note: {analysis.notes}_")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Log it", callback_data=f"log:{meal_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{meal_id}"),
    ]])

    await thinking.edit_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=kb
    )


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    action, _, meal_id = q.data.partition(":")

    if action == "cancel":
        db.consume_pending_meal(meal_id)
        await q.edit_message_text("❌ Canceled — nothing logged.")
        return

    if action == "log":
        pending = db.consume_pending_meal(meal_id)
        if not pending:
            await q.edit_message_text("⚠️ That meal expired. Send the photo again.")
            return
        analysis = MealAnalysis.model_validate(pending["analysis"])
        try:
            await sheets.log_meal(
                user_id=pending["user_id"],
                username=pending["username"],
                analysis=analysis,
            )
        except Exception as e:
            log.exception("sheets log failed")
            await q.edit_message_text(f"⚠️ Sheets error: {e}")
            return
        await q.edit_message_text(
            f"✅ Logged to your sheet: {analysis.description} — "
            f"{int(analysis.total_calories)} kcal"
        )


# --- Application factory ---

def build_application() -> Application:
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app
