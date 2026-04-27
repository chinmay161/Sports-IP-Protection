from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_gemini_flash():
    import google.generativeai as genai

    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key or "")
    return genai.GenerativeModel("gemini-1.5-flash")


@lru_cache(maxsize=1)
def get_gemini_pro():
    import google.generativeai as genai

    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key or "")
    return genai.GenerativeModel("gemini-1.5-pro")


@lru_cache(maxsize=1)
def get_video_client():
    from google.cloud import videointelligence

    return videointelligence.VideoIntelligenceServiceClient()
