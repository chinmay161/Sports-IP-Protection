from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
from dataclasses import dataclass

from app.core.config import get_settings


logger = logging.getLogger(__name__)

KNOWN_BRANDS = [
    "UEFA Champions League",
    "Premier League",
    "LaLiga",
    "Serie A",
    "Bundesliga",
    "Ligue 1",
    "MLS Official",
    "NBA",
    "NFL",
    "ICC Cricket",
    "FIFA World Cup",
    "Formula 1",
    "Wimbledon",
    "US Open Tennis",
    "Olympics",
    "ESPN",
    "Sky Sports",
    "BeIN Sports",
    "DAZN",
    "TNT Sports",
]


@dataclass(slots=True)
class LookalikeResult:
    channel_name: str
    is_impersonator: bool
    matched_brand: str | None
    fuzzy_score: float
    gemini_verdict: bool | None
    gemini_reasoning: str | None
    confidence: float


def _truncate(value: str, max_length: int = 100) -> str:
    return value if len(value) <= max_length else value[: max_length - 3] + "..."


def _strip_json_fences(text: str) -> str:
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return fenced.group(1).strip() if fenced else cleaned


def _fuzzy_score(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _best_fuzzy_match(channel: str) -> tuple[str, float]:
    return max(
        ((brand, _fuzzy_score(channel, brand)) for brand in KNOWN_BRANDS),
        key=lambda item: item[1],
    )


async def _gemini_impersonation_check(channel: str, matched_brand: str) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.gemini_enabled:
        return False, "AI disabled"

    prompt = f"""You are a brand protection analyst.

Determine if this channel name is impersonating the official brand.

Channel name: "{channel}"
Official brand: "{matched_brand}"

Common impersonation techniques:
- Unicode substitution (l->I, o->0, rn->m)
- Added words (HD, Official, TV, Live, Clips)
- Slight misspellings
- Reordered words

Reply in this exact JSON format with no other text:
{{
  "is_impersonator": true or false,
  "reasoning": "one sentence explanation"
}}
"""
    try:
        from app.core.ai import get_gemini_flash

        gemini_flash = get_gemini_flash()
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, lambda: gemini_flash.generate_content(prompt))
        payload = json.loads(_strip_json_fences((getattr(response, "text", None) or "").strip()))
        return bool(payload.get("is_impersonator", False)), str(payload.get("reasoning", ""))
    except Exception as exc:
        logger.warning("gemini_lookalike_check_failed channel=%s error=%s", channel, _truncate(str(exc)))
        return False, f"check failed: {exc}"


async def check(channel_name: str) -> LookalikeResult:
    brand, score = _best_fuzzy_match(channel_name)
    if score < 0.4:
        return LookalikeResult(
            channel_name=channel_name,
            is_impersonator=False,
            matched_brand=None,
            fuzzy_score=score,
            gemini_verdict=None,
            gemini_reasoning=None,
            confidence=0.0,
        )

    gemini_verdict, gemini_reasoning = await _gemini_impersonation_check(channel_name, brand)
    if gemini_verdict is True and score >= 0.6:
        confidence = min(1.0, score * 0.5 + 0.6)
    elif gemini_verdict is True:
        confidence = 0.65
    elif gemini_reasoning == "AI disabled":
        confidence = score * 0.5
    elif score >= 0.85:
        confidence = score
    else:
        confidence = score * 0.5

    return LookalikeResult(
        channel_name=channel_name,
        is_impersonator=confidence >= 0.6,
        matched_brand=brand,
        fuzzy_score=score,
        gemini_verdict=gemini_verdict,
        gemini_reasoning=gemini_reasoning,
        confidence=confidence,
    )


async def check_batch(channel_names: list[str]) -> list[LookalikeResult]:
    return await asyncio.gather(*[check(name) for name in channel_names])
