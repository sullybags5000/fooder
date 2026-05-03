"""Fitbit OAuth 2.0 (PKCE) + food logging.

Docs:
  - OAuth:   https://dev.fitbit.com/build/reference/web-api/authorization/
  - Foods:   https://dev.fitbit.com/build/reference/web-api/nutrition/create-food-log/
"""
import base64
import hashlib
import secrets
import time
from datetime import date as _date
from typing import Optional

import httpx

from app.config import settings
from app import db

AUTH_URL = "https://www.fitbit.com/oauth2/authorize"
TOKEN_URL = "https://api.fitbit.com/oauth2/token"
API_BASE = "https://api.fitbit.com"
SCOPES = "nutrition"


# --- PKCE helpers ---

def _gen_verifier() -> str:
    # 43-128 chars per RFC 7636
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")


def _challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_auth_url(chat_id: int) -> str:
    state = secrets.token_urlsafe(24)
    verifier = _gen_verifier()
    challenge = _challenge_for(verifier)
    db.save_oauth_state(state, chat_id, verifier)
    params = {
        "response_type": "code",
        "client_id": settings.fitbit_client_id,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "redirect_uri": settings.fitbit_redirect_uri,
    }
    from urllib.parse import urlencode
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, state: str) -> int:
    """Exchange auth code for tokens and persist. Returns the chat_id."""
    row = db.consume_oauth_state(state)
    if not row:
        raise ValueError("Unknown or expired state")
    chat_id = row["chat_id"]
    verifier = row["verifier"]

    auth = base64.b64encode(
        f"{settings.fitbit_client_id}:{settings.fitbit_client_secret}".encode()
    ).decode()

    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "client_id": settings.fitbit_client_id,
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": settings.fitbit_redirect_uri,
            },
        )
        r.raise_for_status()
        tok = r.json()

    db.save_fitbit_tokens(
        chat_id=chat_id,
        fitbit_user_id=tok.get("user_id", ""),
        access=tok["access_token"],
        refresh=tok["refresh_token"],
        expires_in=int(tok.get("expires_in", 28800)),
    )
    return chat_id


async def _refresh(chat_id: int, refresh_token: str) -> dict:
    auth = base64.b64encode(
        f"{settings.fitbit_client_id}:{settings.fitbit_client_secret}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        r.raise_for_status()
        tok = r.json()
    db.save_fitbit_tokens(
        chat_id=chat_id,
        fitbit_user_id=tok.get("user_id", ""),
        access=tok["access_token"],
        refresh=tok["refresh_token"],
        expires_in=int(tok.get("expires_in", 28800)),
    )
    return tok


async def _access_token(chat_id: int) -> Optional[str]:
    row = db.get_fitbit_tokens(chat_id)
    if not row:
        return None
    if row["expires_at"] - 60 <= int(time.time()):
        tok = await _refresh(chat_id, row["refresh_token"])
        return tok["access_token"]
    return row["access_token"]


async def log_meal(chat_id: int, *, name: str, calories: int,
                   protein_g: float = 0, carbs_g: float = 0, fat_g: float = 0,
                   meal_type: int = 7, when: Optional[_date] = None) -> dict:
    """Log a custom food to Fitbit.

    meal_type codes (per Fitbit API):
        1=Breakfast 2=Morning Snack 3=Lunch 4=Afternoon Snack 5=Dinner
        7=Anytime (default)
    """
    token = await _access_token(chat_id)
    if not token:
        raise RuntimeError("Fitbit not connected — run /connect first")

    log_date = (when or _date.today()).isoformat()

    # Fitbit's "log food" endpoint accepts a foodName + calories for custom
    # entries (no foodId lookup needed).
    params = {
        "foodName": name,
        "mealTypeId": str(meal_type),
        "unitId": "147",  # 147 = "serving"
        "amount": "1",
        "calories": str(int(round(calories))),
        "date": log_date,
        # Fitbit accepts nutritionalValues JSON alongside calories
        "favorite": "false",
    }

    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{API_BASE}/1/user/-/foods/log.json",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        # If token expired mid-flight, retry once
        if r.status_code == 401:
            row = db.get_fitbit_tokens(chat_id)
            if row:
                tok = await _refresh(chat_id, row["refresh_token"])
                r = await c.post(
                    f"{API_BASE}/1/user/-/foods/log.json",
                    headers={"Authorization": f"Bearer {tok['access_token']}"},
                    params=params,
                )
        r.raise_for_status()
        return r.json()
