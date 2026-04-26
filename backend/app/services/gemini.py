"""Thin wrapper around the Gemini API for DMCA notice generation.

Why this lives in services/, not workers/: the API call is fast (1-3 sec) and
the operator is waiting for the response in the UI. Going through Celery would
add complexity without benefit.
"""
import logging
from datetime import datetime
from typing import Any

from app.core.config import get_settings


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GeminiError(Exception):
    """Base error for Gemini integration."""


class GeminiNotConfigured(GeminiError):
    """No API key set. Caller should fall back to template."""


class GeminiRateLimited(GeminiError):
    """Hit the free-tier rate limit. Caller should show a transient error."""


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

DMCA_PROMPT = """You are a legal assistant drafting a DMCA takedown notice for a sports media
rights holder. Generate a complete, professional takedown notice based on the
infringement details below.

Infringement details:
- Platform: {platform}
- Source URL: {source_url}
- Detected at: {detected_at}
- Severity: {severity}
- Confidence score: {confidence_pct}%
- Match type: {match_type}
- Original asset title: {asset_title}
{description_block}{view_count_block}

Format requirements:
- Address the platform's designated DMCA agent
- State the copyrighted work and ownership clearly
- Identify the infringing material with the URL
- Include the standard "good faith belief" language
- Include the required perjury statement (17 U.S.C. § 512(c)(3))
- Sign off with placeholder "[Rights Holder Name]" and "[Contact Email]" so the
  operator can fill them in
- Output plain text only. No markdown, no commentary, no preamble.

Draft the notice now."""


def _build_dmca_prompt(
    *,
    platform: str | None,
    source_url: str,
    detected_at: datetime,
    severity: str | None,
    confidence: float | None,
    match_type: str | None,
    asset_title: str,
    asset_description: str | None = None,
    view_count: int | None = None,
) -> str:
    description_block = (
        f"- Description: {asset_description}\n" if asset_description else ""
    )
    view_count_block = (
        f"- Observed view count on infringing copy: {view_count:,}\n" if view_count else ""
    )
    confidence_pct = f"{confidence * 100:.1f}" if confidence is not None else "n/a"

    return DMCA_PROMPT.format(
        platform=platform or "unknown",
        source_url=source_url,
        detected_at=detected_at.strftime("%B %d, %Y at %H:%M UTC"),
        severity=severity or "unspecified",
        confidence_pct=confidence_pct,
        match_type=match_type or "unspecified",
        asset_title=asset_title,
        description_block=description_block,
        view_count_block=view_count_block,
    )


# ---------------------------------------------------------------------------
# Fallback template (used when Gemini is unreachable)
# ---------------------------------------------------------------------------

FALLBACK_TEMPLATE = """DMCA TAKEDOWN NOTICE
====================
Date: {date}

TO WHOM IT MAY CONCERN,

I, [Rights Holder Name], am the copyright owner of the media content titled:
"{asset_title}"

I have discovered that the following URL is hosting or distributing this
content without authorization:

Infringing URL: {source_url}
Platform: {platform}
Match Type: {match_type}
Detection Confidence: {confidence_pct}%

This content is protected under copyright law. I hereby request that you
immediately remove or disable access to the infringing material.

I have a good faith belief that the use of the material described above
is not authorized by the copyright owner, its agent, or the law.

I declare under penalty of perjury that the information in this notification
is accurate, and that I am the copyright owner or am authorized to act on
behalf of the owner of an exclusive right that is allegedly infringed.

Signed,
[Rights Holder Name]
[Contact Email]
"""


def _build_fallback_notice(
    *,
    platform: str | None,
    source_url: str,
    confidence: float | None,
    match_type: str | None,
    asset_title: str,
) -> str:
    return FALLBACK_TEMPLATE.format(
        date=datetime.utcnow().strftime("%B %d, %Y"),
        asset_title=asset_title,
        source_url=source_url,
        platform=platform or "Unknown",
        match_type=match_type or "Unspecified",
        confidence_pct=f"{confidence * 100:.1f}" if confidence is not None else "n/a",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def draft_dmca_notice(
    *,
    platform: str | None,
    source_url: str,
    detected_at: datetime,
    severity: str | None = None,
    confidence: float | None = None,
    match_type: str | None = None,
    asset_title: str,
    asset_description: str | None = None,
    view_count: int | None = None,
) -> dict[str, Any]:
    """Draft a DMCA takedown notice. Returns dict with `notice` text and `provider`.

    Provider is 'gemini' on success, 'fallback' if we degraded to the template.
    Caller should never have to handle "we have no notice" — we always return one.
    """
    settings = get_settings()

    fallback_notice = _build_fallback_notice(
        platform=platform,
        source_url=source_url,
        confidence=confidence,
        match_type=match_type,
        asset_title=asset_title,
    )

    if not settings.gemini_api_key:
        logger.info("gemini_not_configured falling_back_to_template")
        return {"notice": fallback_notice, "provider": "fallback", "model": None}

    try:
        from google import genai
        from google.genai import errors as genai_errors
    except ImportError:
        logger.warning("gemini_sdk_missing falling_back_to_template")
        return {"notice": fallback_notice, "provider": "fallback", "model": None}

    prompt = _build_dmca_prompt(
        platform=platform,
        source_url=source_url,
        detected_at=detected_at,
        severity=severity,
        confidence=confidence,
        match_type=match_type,
        asset_title=asset_title,
        asset_description=asset_description,
        view_count=view_count,
    )

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        text = (response.text or "").strip()
        if not text:
            logger.warning("gemini_empty_response falling_back_to_template")
            return {"notice": fallback_notice, "provider": "fallback", "model": settings.gemini_model}

        return {"notice": text, "provider": "gemini", "model": settings.gemini_model}
    except genai_errors.ClientError as exc:
        # Includes 429 rate-limit and 4xx errors
        msg = str(exc).lower()
        if "429" in msg or "quota" in msg or "rate" in msg:
            raise GeminiRateLimited("Gemini rate limit exceeded") from exc
        logger.warning("gemini_client_error %s", exc)
        return {"notice": fallback_notice, "provider": "fallback", "model": settings.gemini_model}
    except Exception as exc:
        logger.exception("gemini_unexpected_error %s", exc)
        return {"notice": fallback_notice, "provider": "fallback", "model": settings.gemini_model}