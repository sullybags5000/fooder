"""Google Sheets logger.

Uses a service account (JSON key) so there's no OAuth dance — you just need to
share the target spreadsheet with the service account's email, once.

The worksheet is created on first write with a header row; subsequent writes
append rows.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from app.config import settings
from app.models import MealAnalysis

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

HEADER = [
    "timestamp_utc",
    "telegram_user_id",
    "telegram_username",
    "description",
    "total_calories",
    "protein_g",
    "carbs_g",
    "fat_g",
    "confidence",
    "items_detail",
    "notes",
]


_client: Optional[gspread.Client] = None
_worksheet: Optional[gspread.Worksheet] = None
_lock = asyncio.Lock()


def _load_client() -> gspread.Client:
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            settings.google_sheets_credentials_file, scopes=SCOPES
        )
        _client = gspread.authorize(creds)
    return _client


def _load_worksheet() -> gspread.Worksheet:
    global _worksheet
    if _worksheet is not None:
        return _worksheet
    client = _load_client()
    sh = client.open_by_key(settings.google_sheets_spreadsheet_id)
    name = settings.google_sheets_worksheet_name
    try:
        ws = sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=1000, cols=len(HEADER))
        ws.append_row(HEADER, value_input_option="USER_ENTERED")
    else:
        # Ensure header row exists
        first_row = ws.row_values(1)
        if not first_row:
            ws.append_row(HEADER, value_input_option="USER_ENTERED")
    _worksheet = ws
    return ws


def _format_items(analysis: MealAnalysis) -> str:
    parts = []
    for it in analysis.items:
        parts.append(
            f"{it.name} ({it.portion}): {int(it.calories)}kcal "
            f"P{int(it.protein_g)}/C{int(it.carbs_g)}/F{int(it.fat_g)}"
        )
    return " | ".join(parts)


async def log_meal(
    *,
    user_id: int,
    username: Optional[str],
    analysis: MealAnalysis,
) -> None:
    """Append one row per meal. gspread is sync — run in a thread."""
    row = [
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        str(user_id),
        username or "",
        analysis.description,
        round(analysis.total_calories, 1),
        round(analysis.total_protein_g, 1),
        round(analysis.total_carbs_g, 1),
        round(analysis.total_fat_g, 1),
        round(analysis.confidence, 2),
        _format_items(analysis),
        analysis.notes or "",
    ]

    async with _lock:
        await asyncio.to_thread(_append_row_sync, row)


def _append_row_sync(row: list) -> None:
    ws = _load_worksheet()
    ws.append_row(row, value_input_option="USER_ENTERED")
