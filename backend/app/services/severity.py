# app/services/severity.py
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


async def compute_severity(
    match_type: str,
    confidence: float,
    infringing_url: str,
    platform: str | None,
    asset_title: str,
) -> tuple[float, str, str]:
    """
    Call Claude to score severity of a copyright infringement alert.
    Returns (score: float, label: str, reasoning: str)
    """
    if not ANTHROPIC_API_KEY:
        return _rule_based_severity(confidence, match_type)

    prompt = f"""You are a copyright infringement severity analyst for a sports media organization.

Analyze this infringement alert and return a JSON object only, no other text.

Alert details:
- Asset title: {asset_title}
- Match type: {match_type}
- Confidence score: {confidence:.2f} (0.0 to 1.0)
- Infringing URL: {infringing_url}
- Platform: {platform or "unknown"}

Return ONLY this JSON structure:
{{
  "score": <float between 0.0 and 1.0>,
  "label": <"low" | "medium" | "high" | "critical">,
  "reasoning": <one sentence explanation>
}}

Rules:
- critical (0.85-1.0): high confidence match on major platform (YouTube, Twitter, Facebook)
- high (0.65-0.84): high confidence or major platform
- medium (0.40-0.64): moderate confidence or unknown platform
- low (0.0-0.39): low confidence or audio-only match"""

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
            text = data["content"][0]["text"].strip()
            parsed = json.loads(text)
            return (
                float(parsed["score"]),
                str(parsed["label"]),
                str(parsed["reasoning"]),
            )
    except Exception as exc:
        logger.warning("AI severity scoring failed, falling back to rules: %s", exc)
        score, label, _ = _rule_based_severity(confidence, match_type)
        return score, label, "Scored by rule-based fallback."


def _rule_based_severity(
    confidence: float, match_type: str
) -> tuple[float, str, str]:
    if confidence >= 0.85:
        return 0.9, "critical", "High confidence match detected."
    elif confidence >= 0.65:
        return 0.7, "high", "Moderately high confidence match."
    elif confidence >= 0.40:
        return 0.5, "medium", "Moderate confidence match."
    else:
        return 0.2, "low", "Low confidence match."