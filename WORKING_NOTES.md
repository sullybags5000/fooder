# Fooder Working Notes

Last updated: 2026-05-04 (UTC)

## Current status
- Telegram bot is running in polling mode.
- Vision provider is Gemini.
- Gemini model default is now `gemini-2.5-flash`.
- Vision parsing was hardened to normalize non-conforming Gemini JSON before Pydantic validation.

## Recent fixes shipped
1. Replaced deprecated Gemini model ID (`gemini-2.0-flash-exp`) with `gemini-2.5-flash`.
2. Added robust normalization in `app/vision.py` to map key drift (e.g. `food_item -> name`) and fill missing totals/description.
3. Fixed prompt templating bug caused by JSON braces and `str.format`.

## Files changed in this debugging cycle
- `app/config.py`
- `app/vision.py`

## Runtime notes
- Current launch mode is manual polling (`python -m app.main --polling`).
- Not reboot-persistent yet.
- Next infra task: convert to a `systemd` service (auto-start on boot, restart on failure).

## Recommended next session checklist
1. Create `systemd --user` or system-level service for Fooder bot.
2. Verify service survives reboot.
3. Rotate exposed secrets:
   - Gemini API key
   - Telegram bot token
4. Confirm `.env` and credential files are excluded from git.
5. Add a lightweight regression test for normalization behavior in `app/vision.py`.

## Security note
Secrets were exposed in terminal/log context during debugging. Rotate credentials and redeploy.
