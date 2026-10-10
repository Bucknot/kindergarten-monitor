from typing import Optional
from backend.app.config import settings
from backend.app.services.stt.base import BaseSTTProvider, STTResult, STTUtterance, STTSpeaker
from backend.app.services.stt.gladia import GladiaSTTProvider
from backend.app.services.stt.deepgram import DeepgramSTTProvider
from backend.app.services.stt.openai_compatible import OpenAICompatibleSTTProvider
from backend.app.services.stt.openrouter_stt import OpenRouterSTTProvider
from backend.app.services.stt.mock import MockSTTProvider


def get_stt_provider(provider_name: Optional[str] = None, model: Optional[str] = None) -> BaseSTTProvider:
    name = (provider_name or settings.STT_PROVIDER or "mock").lower()
    
    if name == "gladia":
        if settings.GLADIA_API_KEY:
            return GladiaSTTProvider(api_key=settings.GLADIA_API_KEY)
        return MockSTTProvider()
    elif name == "openrouter":
        key = settings.OPENROUTER_API_KEY or settings.GEMINI_API_KEY
        if key:
            stt_model = model or getattr(settings, "OPENROUTER_STT_MODEL", "elevenlabs/scribe-v2") or "elevenlabs/scribe-v2"
            return OpenRouterSTTProvider(
                api_key=key,
                model=stt_model,
                base_url=settings.OPENROUTER_BASE_URL
            )
        return MockSTTProvider()
    elif name == "deepgram":
        if settings.DEEPGRAM_API_KEY:
            return DeepgramSTTProvider(api_key=settings.DEEPGRAM_API_KEY)
        return MockSTTProvider()
    elif name in ("openai_compatible", "openai", "groq", "whisper"):
        key = settings.OPENAI_COMPATIBLE_STT_API_KEY or settings.OPENAI_API_KEY
        if key:
            return OpenAICompatibleSTTProvider(
                api_key=key,
                base_url=settings.OPENAI_COMPATIBLE_STT_BASE_URL,
                model=settings.OPENAI_COMPATIBLE_STT_MODEL
            )
        return MockSTTProvider()
    elif name in ("openrouter_whisper", "openrouter/whisper", "whisper_openrouter"):
        key = settings.OPENROUTER_API_KEY
        if key:
            return OpenAICompatibleSTTProvider(
                api_key=key,
                base_url="https://openrouter.ai/api/v1",
                model="openai/whisper-large-v3"
            )
        return MockSTTProvider()
    elif name == "mock":
        return MockSTTProvider()
    
    return MockSTTProvider()
