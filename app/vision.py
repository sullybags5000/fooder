"""Vision LLM adapter — pluggable Gemini / OpenAI backends.

Both return a validated MealAnalysis. Keep the prompt in one place so we can
A/B providers without drift.
"""
import base64
import json
import re
from typing import Any, Union

from app.config import settings
from app.models import MealAnalysis


SYSTEM_PROMPT = """You are a careful nutritionist analyzing a meal photo.

Estimate calories and macros for each visible food item, then totals.
If portion sizes are ambiguous, assume typical restaurant/home portions and
note it. If the photo isn't a meal, respond with items=[] and confidence=0.

Be realistic — don't underestimate oils, dressings, or hidden ingredients.
Return ONLY valid JSON matching the provided schema. No prose, no markdown.
"""

USER_INSTRUCTION = (
    "Analyze this meal photo. If the user provided a caption, treat it as "
    "ground truth that overrides your visual guesses.\n\n"
    "Return STRICT JSON with EXACT keys:\n"
    "{\n"
    '  "description": "short one-line meal description",\n'
    '  "items": [\n'
    "    {\n"
    '      "name": "food name",\n'
    '      "portion": "estimated portion string",\n'
    '      "calories": 0,\n'
    '      "protein_g": 0,\n'
    '      "carbs_g": 0,\n'
    '      "fat_g": 0\n'
    "    }\n"
    "  ],\n"
    '  "total_calories": 0,\n'
    '  "total_protein_g": 0,\n'
    '  "total_carbs_g": 0,\n'
    '  "total_fat_g": 0,\n'
    '  "confidence": 0.0,\n'
    '  "notes": "optional caveats or null"\n'
    "}\n"
    "Do NOT use alternate keys like food_item or kcal_total.\n\n"
    "User caption: {caption}"
)


def _build_user_prompt(caption: str) -> str:
    # Use plain string replacement so JSON braces in USER_INSTRUCTION are not
    # interpreted as str.format placeholders.
    return USER_INSTRUCTION.replace("{caption}", caption or "(none)")


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return default
    return default


def _normalize_meal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize common LLM key drift into MealAnalysis schema."""
    data = dict(payload or {})

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raw_items = []

    norm_items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue

        name = (
            raw.get("name")
            or raw.get("food_item")
            or raw.get("food")
            or raw.get("item")
            or "unknown item"
        )
        portion = (
            raw.get("portion")
            or raw.get("serving")
            or raw.get("amount")
            or raw.get("quantity")
            or "estimated portion"
        )

        calories = _to_float(raw.get("calories", raw.get("kcal", raw.get("energy_kcal", 0))))
        protein_g = _to_float(raw.get("protein_g", raw.get("protein", 0)))
        carbs_g = _to_float(raw.get("carbs_g", raw.get("carbs", raw.get("carbohydrates", 0))))
        fat_g = _to_float(raw.get("fat_g", raw.get("fat", 0)))

        norm_items.append(
            {
                "name": str(name),
                "portion": str(portion),
                "calories": calories,
                "protein_g": protein_g,
                "carbs_g": carbs_g,
                "fat_g": fat_g,
            }
        )

    data["items"] = norm_items

    if not data.get("description"):
        if norm_items:
            top_names = ", ".join(it["name"] for it in norm_items[:3])
            data["description"] = f"Meal with {top_names}"
        else:
            data["description"] = "No meal detected"

    sum_cal = sum(_to_float(it.get("calories")) for it in norm_items)
    sum_pro = sum(_to_float(it.get("protein_g")) for it in norm_items)
    sum_carbs = sum(_to_float(it.get("carbs_g")) for it in norm_items)
    sum_fat = sum(_to_float(it.get("fat_g")) for it in norm_items)

    data["total_calories"] = _to_float(
        data.get("total_calories", data.get("kcal_total", data.get("calories_total", sum_cal))),
        default=sum_cal,
    )
    data["total_protein_g"] = _to_float(
        data.get("total_protein_g", data.get("protein_total", sum_pro)),
        default=sum_pro,
    )
    data["total_carbs_g"] = _to_float(
        data.get("total_carbs_g", data.get("carbs_total", data.get("carbohydrates_total", sum_carbs))),
        default=sum_carbs,
    )
    data["total_fat_g"] = _to_float(
        data.get("total_fat_g", data.get("fat_total", sum_fat)),
        default=sum_fat,
    )

    data["confidence"] = _to_float(data.get("confidence", 0.7), default=0.7)
    data["confidence"] = max(0.0, min(1.0, data["confidence"]))

    if "notes" not in data:
        data["notes"] = None

    return data


async def analyze_meal(image_bytes: bytes, caption: str = "") -> MealAnalysis:
    provider = settings.vision_provider.lower()
    if provider == "gemini":
        return await _analyze_gemini(image_bytes, caption)
    if provider == "openai":
        return await _analyze_openai(image_bytes, caption)
    raise ValueError(f"Unknown VISION_PROVIDER: {provider}")


# --- Gemini ---

async def _analyze_gemini(image_bytes: bytes, caption: str) -> MealAnalysis:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    types.Part.from_text(text=_build_user_prompt(caption)),
                ],
            ),
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            # NOTE: Do NOT pass response_schema here.
            # google-genai==0.3.0 can fail converting nested Pydantic JSON schema
            # ($defs/$ref + null union) into Gemini Schema.
            # We request JSON output and validate ourselves with Pydantic.
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )

    text = (response.text or "").strip()

    # Defensive cleanup in case model returns fenced JSON despite instruction.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    payload = json.loads(text)
    normalized = _normalize_meal_payload(payload)
    return MealAnalysis.model_validate(normalized)


# --- OpenAI ---

async def _analyze_openai(image_bytes: bytes, caption: str) -> MealAnalysis:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "MealAnalysis",
                "schema": MealAnalysis.model_json_schema(),
                "strict": False,
            },
        },
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _build_user_prompt(caption)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            },
        ],
    )
    return MealAnalysis.model_validate_json(resp.choices[0].message.content)
