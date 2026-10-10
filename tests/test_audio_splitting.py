import pytest
import os
import asyncio
from backend.app.services.audio_service import audio_service
from backend.app.services.stt.base import (
    STTUtterance,
    STTSpeaker,
    deduplicate_boundary_utterances,
    deduplicate_boundary_utterance_dicts,
    consolidate_utterances
)
from backend.app.services.stt.openrouter_stt import OpenRouterSTTProvider


def test_deduplicate_exact_duplicates():
    """Identical utterances produced in the boundary overlap window should be deduplicated."""
    u1 = STTUtterance(speaker_tag="spk_0", start_time=1798.5, end_time=1801.0, text="שלום לכל הילדים", confidence=0.88)
    u2 = STTUtterance(speaker_tag="spk_1", start_time=1798.6, end_time=1801.2, text="שלום לכל הילדים", confidence=0.96)
    
    deduped = deduplicate_boundary_utterances([u1, u2])
    assert len(deduped) == 1
    assert deduped[0].text == "שלום לכל הילדים"
    assert deduped[0].confidence == 0.96
    assert deduped[0].start_time == 1798.5
    assert deduped[0].end_time == 1801.2


def test_deduplicate_subsumed_fragment():
    """When one chunk gets cut mid-sentence and the next chunk has the complete sentence, keep the complete one."""
    u1 = STTUtterance(speaker_tag="spk_0", start_time=1798.0, end_time=1799.5, text="בוקר טוב", confidence=0.8)
    u2 = STTUtterance(speaker_tag="spk_0", start_time=1798.2, end_time=1802.0, text="בוקר טוב ילדים חמודים", confidence=0.92)

    deduped = deduplicate_boundary_utterances([u1, u2])
    assert len(deduped) == 1
    assert deduped[0].text == "בוקר טוב ילדים חמודים"
    assert deduped[0].end_time == 1802.0


def test_deduplicate_seam_word_overlap():
    """When speech crosses the seam and words are repeated at the boundary, seamlessly join the seam."""
    u1 = STTUtterance(speaker_tag="spk_0", start_time=1796.0, end_time=1799.5, text="הגננת אמרה לשבת יפה", confidence=0.9)
    u2 = STTUtterance(speaker_tag="spk_0", start_time=1798.5, end_time=1802.0, text="לשבת יפה ונקרא סיפור", confidence=0.9)

    deduped = deduplicate_boundary_utterances([u1, u2])
    assert len(deduped) == 1
    assert deduped[0].text == "הגננת אמרה לשבת יפה ונקרא סיפור"
    assert deduped[0].start_time == 1796.0
    assert deduped[0].end_time == 1802.0


def test_deduplicate_fuzzy_variation():
    """When slight transcription variance occurs in the overlap region, merge them."""
    u1 = STTUtterance(speaker_tag="spk_0", start_time=1798.0, end_time=1801.0, text="בואו נשב במעגל", confidence=0.85)
    u2 = STTUtterance(speaker_tag="spk_0", start_time=1798.2, end_time=1801.2, text="בואו נשב כולנו במעגל", confidence=0.92)

    deduped = deduplicate_boundary_utterances([u1, u2])
    assert len(deduped) == 1
    assert deduped[0].text == "בואו נשב כולנו במעגל"


def test_deduplicate_dict_variant():
    """Verify dictionary variant behaves identically for cached or DB segments."""
    raw = [
        {"speaker_tag": "spk_0", "start_time": 10.0, "end_time": 13.0, "text": "בוקר טוב לכולם", "confidence": 0.9},
        {"speaker_tag": "spk_1", "start_time": 10.1, "end_time": 13.2, "text": "בוקר טוב לכולם", "confidence": 0.95},
        {"speaker_tag": "spk_1", "start_time": 20.0, "end_time": 25.0, "text": "שקט בבקשה", "confidence": 0.9},
    ]
    deduped = deduplicate_boundary_utterance_dicts(raw)
    assert len(deduped) == 2
    assert deduped[0]["text"] == "בוקר טוב לכולם"
    assert deduped[1]["text"] == "שקט בבקשה"


def test_deduplicate_preserves_distinct_utterances():
    """Distinct, non-overlapping utterances must not be merged."""
    u1 = STTUtterance(speaker_tag="spk_0", start_time=100.0, end_time=105.0, text="אני רוצה מים", confidence=0.9)
    u2 = STTUtterance(speaker_tag="spk_1", start_time=110.0, end_time=115.0, text="הנה הבקבוק שלך", confidence=0.9)

    deduped = deduplicate_boundary_utterances([u1, u2])
    assert len(deduped) == 2
    assert deduped[0].text == "אני רוצה מים"
    assert deduped[1].text == "הנה הבקבוק שלך"


@pytest.mark.asyncio
async def test_find_natural_pause_on_processed_sample():
    """Test find_natural_pause finds a silence point in real audio."""
    sample_file = "storage/processed/ed8cbc25-f7a0-404e-bd2c-b41266d1cc8c_optimized.mp3"
    if not os.path.exists(sample_file):
        pytest.skip("Sample audio file not available in test environment")

    pause = await audio_service.find_natural_pause(
        sample_file,
        target_time=600.0,
        search_window=15.0,
        min_silence_dur=0.3
    )
    assert pause is not None
    # Pause should be within 15 seconds of target
    assert 585.0 <= pause <= 615.0


@pytest.mark.asyncio
async def test_split_audio_into_chunks_silence_and_overlap():
    """Test chunk splitting with silence awareness and boundary overlap."""
    sample_file = "storage/processed/ed8cbc25-f7a0-404e-bd2c-b41266d1cc8c_optimized.mp3"
    if not os.path.exists(sample_file):
        pytest.skip("Sample audio file not available in test environment")

    chunks = await audio_service.split_audio_into_chunks(
        sample_file,
        chunk_duration_seconds=600.0,
        total_duration=1300.0,
        silence_aware=True,
        overlap_seconds=2.0
    )
    assert len(chunks) >= 2
    # Verify first chunk
    c0 = chunks[0]
    c1 = chunks[1]
    assert c0["chunk_index"] == 0
    assert c0["start_time"] == 0.0
    assert c0["end_time"] > 550.0

    # Verify overlap: chunk 1 should start overlap_seconds before chunk 0 ends
    assert c1["chunk_index"] == 1
    assert abs(c1["start_time"] - (c0["end_time"] - 2.0)) < 0.1
