"""Telegram bot handlers. Works in both polling (dev) and webhook (prod) modes."""
import io
import logging
import uuid

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
from app import db, fitbit, vision

log = logging.getLogger(__name__)


# --- Command handlers ---

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Welcome to Fooder.\n\n"
        "Send me a photo of your meal and I'll estimate the calories + macros "
        "and log it to Fitbit.\n\n"
        "First: /connect to link your Fitbit account.\n"
        "Other commands: /status  /disconnect  /help"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "How to use:\n"
        "1. /connect — link Fitbit (one-time)\n"
        "2. Send a photo (add a caption like 'large portion' for better accuracy)\n"
        "3. Confirm the estimate → logged to Fitbit\n\n"
        "/status — check Fitbit connection\n"
        "/disconnect — remove Fitbit tokens"
    )


async def cmd_connect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not settings.fitbit_client_id:
        await update.message.reply_text("⚠️ Fitbit not configured on the server.")
        return
    url = fitbit.build_auth_url(update.effective_chat.id)
    await update.message.reply_text(
        f"Connect Fitbit:\n{url}\n\nAfter approving, you'll be redirected and can come back here."
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    row = db.get_fitbit_tokens(update.effective_chat.id)
    if row:
        await update.message.reply_text("✅ Fitbit connected.")
    else:
        await update.message.reply_text("❌ Fitbit not connected. Run /connect")


async def cmd_disconnect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db.delete_fitbit_tokens(update.effective_chat.id)
    await update.message.reply_text("🔌 Fitbit disconnected.")


# --- Photo handler ---

async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    caption = (update.message.caption or "").strip()

    # Grab highest-resolution photo
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

    # Stash for confirmation callback
    meal_id = uuid.uuid4().hex[:12]
    db.save_pending_meal(meal_id, chat_id, analysis.model_dump())

    lines = [f"🍽 *{analysis.description}*", ""]
    for it in analysis.items:
        lines.append(
            f"• {it.name} ({it.portion}) — {int(it.calories)} kcal"
        )
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
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    action, _, meal_id = q.data.partition(":")
    chat_id = q.message.chat_id

    if action == "cancel":
        db.consume_pending_meal(meal_id)
        await q.edit_message_text("❌ Canceled — nothing logged.")
        return

    if action == "log":
        data = db.consume_pending_meal(meal_id)
        if not data:
            await q.edit_message_text("⚠️ That meal expired. Send the photo again.")
            return
        try:
            await fitbit.log_meal(
                chat_id=chat_id,
                name=data["description"],
                calories=int(round(data["total_calories"])),
                protein_g=data["total_protein_g"],
                carbs_g=data["total_carbs_g"],
                fat_g=data["total_fat_g"],
            )
        except RuntimeError as e:
            await q.edit_message_text(f"⚠️ {e}")
            return
        except Exception as e:
            log.exception("fitbit log failed")
            await q.edit_message_text(f"⚠️ Fitbit error: {e}")
            return
        await q.edit_message_text(
            f"✅ Logged to Fitbit: {data['description']} — "
            f"{int(data['total_calories'])} kcal"
        )


# --- Application factory ---

def build_application() -> Application:
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("connect", cmd_connect))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("disconnect", cmd_disconnect))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app
