"""Vision LLM adapter — pluggable Gemini / OpenAI backends.

Both return a validated MealAnalysis. Keep the prompt in one place so we can
A/B providers without drift.
"""
import base64
import json
from typing import Union

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
    "ground truth that overrides your visual guesses.\n\nUser caption: {caption}"
)


def _build_user_prompt(caption: str) -> str:
    return USER_INSTRUCTION.format(caption=caption or "(none)")


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

    schema = MealAnalysis.model_json_schema()
    # Gemini wants a response_schema, not a response_format
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
            response_mime_type="application/json",
            response_schema=MealAnalysis,
            temperature=0.2,
        ),
    )
    # google-genai may return the parsed object directly
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, MealAnalysis):
        return parsed
    return MealAnalysis.model_validate_json(response.text)


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
