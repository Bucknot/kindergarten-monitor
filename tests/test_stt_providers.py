import pytest
from backend.app.services.cache_service import cache_service
from backend.app.services.stt import get_stt_provider, OpenRouterSTTProvider, OpenAICompatibleSTTProvider, GladiaSTTProvider, MockSTTProvider
from backend.app.services.stt.base import STTResult, STTUtterance, STTSpeaker


def test_cache_isolation_by_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_service, "cache_dir", tmp_path)
    test_hash = "fakehash123456789"
    
    # Save cache for gladia
    gladia_utts = [{"start_time": 0.0, "end_time": 2.0, "speaker_tag": "spk_0", "text": "שלום מגלאדיה", "confidence": 0.9}]
    gladia_spks = [{"speaker_tag": "spk_0", "total_speech_seconds": 2.0, "utterance_count": 1, "sample_start_time": 0.0, "sample_duration": 2.0}]
    
    cache_service.save_stt_cache(
        file_hash=test_hash,
        source_filename="test.mp3",
        duration_seconds=120.0,
        file_size_bytes=1000,
        stt_provider="gladia",
        speakers=gladia_spks,
        utterances=gladia_utts
    )
    
    # Query with gladia -> hit
    cached_gladia = cache_service.get_stt_cache(test_hash, stt_provider="gladia")
    assert cached_gladia is not None
    assert cached_gladia["utterances"][0]["text"] == "שלום מגלאדיה"
    
    # Query with whisper / openai_compatible -> miss! (no cross-pollution)
    cached_whisper = cache_service.get_stt_cache(test_hash, stt_provider="openai_compatible")
    assert cached_whisper is None

    # Query with openrouter -> miss!
    cached_openrouter = cache_service.get_stt_cache(test_hash, stt_provider="openrouter")
    assert cached_openrouter is None

    # Save cache for whisper
    whisper_utts = [{"start_time": 0.0, "end_time": 2.0, "speaker_tag": "spk_0", "text": "שלום מוויספר", "confidence": 0.9}]
    whisper_spks = [{"speaker_tag": "spk_0", "total_speech_seconds": 2.0, "utterance_count": 1, "sample_start_time": 0.0, "sample_duration": 2.0}]
    
    cache_service.save_stt_cache(
        file_hash=test_hash,
        source_filename="test.mp3",
        duration_seconds=120.0,
        file_size_bytes=1000,
        stt_provider="openai_compatible",
        speakers=whisper_spks,
        utterances=whisper_utts
    )

    # Now whisper hits whisper result and gladia hits gladia result
    assert cache_service.get_stt_cache(test_hash, stt_provider="openai_compatible")["utterances"][0]["text"] == "שלום מוויספר"
    assert cache_service.get_stt_cache(test_hash, stt_provider="gladia")["utterances"][0]["text"] == "שלום מגלאדיה"


def test_stt_provider_factory():
    p_or = get_stt_provider("openrouter")
    assert isinstance(p_or, (OpenRouterSTTProvider, MockSTTProvider))

    p_or_mai = get_stt_provider("openrouter", model="microsoft/mai-transcribe-2")
    if isinstance(p_or_mai, OpenRouterSTTProvider):
        assert p_or_mai.model == "microsoft/mai-transcribe-2"

    p_or_whisper = get_stt_provider("openrouter_whisper")
    assert isinstance(p_or_whisper, (OpenAICompatibleSTTProvider, MockSTTProvider))
    if isinstance(p_or_whisper, OpenAICompatibleSTTProvider):
        assert "openrouter.ai" in p_or_whisper.base_url
        assert p_or_whisper.model == "openai/whisper-large-v3"
    
    p_groq = get_stt_provider("openai_compatible")
    assert isinstance(p_groq, (OpenAICompatibleSTTProvider, MockSTTProvider))

    p_mock = get_stt_provider("mock")
    assert isinstance(p_mock, MockSTTProvider)


def test_cache_isolation_by_model(tmp_path, monkeypatch):
    """Verify that switching models within the same provider bypasses the cache."""
    monkeypatch.setattr(cache_service, "cache_dir", tmp_path)
    test_hash = "modelhash987654321"

    # Save cache for elevenlabs/scribe-v2
    eleven_utts = [{"start_time": 0.0, "end_time": 3.0, "speaker_tag": "spk_0", "text": "שלום מסקרייב", "confidence": 0.98}]
    eleven_spks = [{"speaker_tag": "spk_0", "total_speech_seconds": 3.0, "utterance_count": 1, "sample_start_time": 0.0, "sample_duration": 3.0}]

    cache_service.save_stt_cache(
        file_hash=test_hash,
        source_filename="test.mp3",
        duration_seconds=120.0,
        file_size_bytes=1000,
        stt_provider="openrouter",
        stt_model="elevenlabs/scribe-v2",
        speakers=eleven_spks,
        utterances=eleven_utts
    )

    # Query with elevenlabs/scribe-v2 -> HIT
    hit = cache_service.get_stt_cache(test_hash, stt_provider="openrouter", stt_model="elevenlabs/scribe-v2")
    assert hit is not None
    assert hit["utterances"][0]["text"] == "שלום מסקרייב"

    # Query with microsoft/mai-transcribe-2 -> MISS!
    miss = cache_service.get_stt_cache(test_hash, stt_provider="openrouter", stt_model="microsoft/mai-transcribe-2")
    assert miss is None

    # Query with openai/whisper-large-v3 -> MISS!
    miss_whisper = cache_service.get_stt_cache(test_hash, stt_provider="openrouter", stt_model="openai/whisper-large-v3")
    assert miss_whisper is None
