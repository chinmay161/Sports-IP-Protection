# app/services/severity.py
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


async def compute_severity(
    match_type: str,
    confidence: float,
    infringing_url: str,
    platform: str | None,
    asset_title: str,
) -> tuple[float, str, str]:
    """
    Score severity using Groq (free) or rule-based fallback.
    Returns (score, label, reasoning)
    """
    if not GROQ_API_KEY:
        return _rule_based_severity(confidence, match_type)

    prompt = f"""You are a copyright infringement severity analyst for a sports media organization.

Analyze this infringement alert and return a JSON object ONLY. No markdown, no extra text, no explanation.

Alert details:
- Asset title: {asset_title}
- Match type: {match_type}
- Confidence score: {confidence:.2f} (0.0 to 1.0)
- Infringing URL: {infringing_url}
- Platform: {platform or "unknown"}

Return ONLY this JSON:
{{
  "score": <float 0.0-1.0>,
  "label": <"low" | "medium" | "high" | "critical">,
  "reasoning": <one sentence max>
}}

Scoring rules:
- critical (0.85-1.0): high confidence on major platform (YouTube, Twitter, Facebook, Instagram)
- high (0.65-0.84): high confidence or major platform
- medium (0.40-0.64): moderate confidence or unknown platform
- low (0.0-0.39): low confidence or audio-only match"""

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 200,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            parsed = json.loads(text)
            return (
                float(parsed["score"]),
                str(parsed["label"]),
                str(parsed["reasoning"]),
            )
    except Exception as exc:
        logger.warning("Groq severity scoring failed, using rules: %s", exc)
        return _rule_based_severity(confidence, match_type)


def _rule_based_severity(
    confidence: float,
    match_type: str,
) -> tuple[float, str, str]:
    if confidence >= 0.85:
        return 0.9, "critical", "High confidence match detected."
    elif confidence >= 0.65:
        return 0.7, "high", "Moderately high confidence match."
    elif confidence >= 0.40:
        return 0.5, "medium", "Moderate confidence match."
    else:
        return 0.2, "low", "Low confidence match."