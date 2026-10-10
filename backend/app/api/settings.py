from fastapi import APIRouter
from backend.app.config import settings
from backend.app.schemas import SettingsUpdateRequest, SettingsResponse

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings():
    return SettingsResponse(
        stt_provider=settings.STT_PROVIDER,
        gladia_key_set=bool(settings.GLADIA_API_KEY),
        deepgram_key_set=bool(settings.DEEPGRAM_API_KEY),
        llm_provider=settings.LLM_PROVIDER,
        openrouter_key_set=bool(settings.OPENROUTER_API_KEY),
        openrouter_model=settings.OPENROUTER_MODEL,
        openrouter_stt_model=getattr(settings, "OPENROUTER_STT_MODEL", "elevenlabs/scribe-v2"),
        audio_llm_model=settings.AUDIO_LLM_MODEL,
        openai_key_set=bool(settings.OPENAI_API_KEY)
    )


@router.post("", response_model=SettingsResponse)
async def update_settings(req: SettingsUpdateRequest):
    if req.stt_provider:
        settings.STT_PROVIDER = req.stt_provider
    if req.gladia_api_key:
        settings.GLADIA_API_KEY = req.gladia_api_key.strip()
        settings.STT_PROVIDER = "gladia"
    if req.deepgram_api_key:
        settings.DEEPGRAM_API_KEY = req.deepgram_api_key.strip()
    if req.llm_provider:
        settings.LLM_PROVIDER = req.llm_provider
    if req.openrouter_api_key:
        settings.OPENROUTER_API_KEY = req.openrouter_api_key.strip()
        settings.LLM_PROVIDER = "openrouter"
    if req.openrouter_model:
        settings.OPENROUTER_MODEL = req.openrouter_model.strip()
    if req.openrouter_stt_model:
        settings.OPENROUTER_STT_MODEL = req.openrouter_stt_model.strip()
    if req.audio_llm_model:
        settings.AUDIO_LLM_MODEL = req.audio_llm_model.strip()
    if req.openai_api_key:
        settings.OPENAI_API_KEY = req.openai_api_key.strip()

    return await get_settings()
