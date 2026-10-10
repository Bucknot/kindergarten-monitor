import os
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport

from backend.app.main import app
from backend.app.config import settings
from backend.app.database import init_db, AsyncSessionLocal
from backend.app.models import SessionModel, AudioEventModel, TranscriptSegmentModel
from backend.app.services.audio_service import audio_service
from backend.app.services.acoustic import acoustic_service
from backend.app.services.llm.audio_analyst import audio_analyst
from backend.app.services.llm.chat_agent import chat_agent_service

SAMPLE_AUDIO_PATH = os.getenv("SAMPLE_AUDIO_PATH", "/mnt/c/Users/Adar/Documents/savion-08-10-26-part-1.mp3")


@pytest.mark.asyncio
async def test_acoustic_profiling_ground_truth_crying():
    """
    Validates that the acoustic layer profiles loudness and identifies
    high-energy cry-band activity at the ground-truth crying timestamp (~2820s / 00:47:00).
    """
    if not os.path.exists(SAMPLE_AUDIO_PATH):
        pytest.skip(f"Ground truth audio {SAMPLE_AUDIO_PATH} not found; skipping")
    
    # Extract a 40-second clip centered on the 00:47:00 crying peak
    test_clip = "/tmp/test_crying_47min.mp3"
    await audio_service.extract_snippet(SAMPLE_AUDIO_PATH, 2820.0, 40.0, test_clip)
    assert os.path.exists(test_clip)

    res = await acoustic_service.analyze_audio(
        audio_path=test_clip,
        duration_seconds=40.0,
        transcript_segments=[]
    )

    assert len(res.loudness_points) > 0, "Loudness profile should have sample points"
    assert res.baseline_db < 0, "Baseline dB should be negative"

    # Verify peak energy exists and is significant
    peak_full = max(p["full_db"] for p in res.loudness_points)
    peak_cry = max(p["cry_db"] for p in res.loudness_points)
    print(f"Acoustic peak in 00:47 crying clip: full={peak_full:.1f} dB, cry-band={peak_cry:.1f} dB")
    assert peak_full > -20.0, "Crying peak should be loud (above -20 dB)"
    assert peak_cry > -25.0, "Cry-band peak (1.5-4kHz) should be elevated"

    if os.path.exists(test_clip):
        os.remove(test_clip)


@pytest.mark.asyncio
async def test_audio_analyst_multimodal_crying_detection():
    """
    Validates that the multimodal Audio LLM (Gemini 2.5 Flash via OpenRouter)
    listens to the 00:47:00 clip and identifies crying/distress and adult response.
    """
    if not settings.OPENROUTER_API_KEY and not settings.GEMINI_API_KEY:
        pytest.skip("No API key available for live audio LLM test")
    if not os.path.exists(SAMPLE_AUDIO_PATH):
        pytest.skip(f"Ground truth audio {SAMPLE_AUDIO_PATH} not found; skipping")

    events = await audio_analyst.analyze_candidate_window(
        audio_path=SAMPLE_AUDIO_PATH,
        start_seconds=2820.0,
        duration_seconds=20.0,
        target_child_name="סביון",
        focus_prompt="האם הילד בכה או חווה מצוקה?"
    )

    print(f"Audio LLM detected {len(events)} events in 20s clip at 00:47:00:")
    for ev in events:
        print(f"  [{ev.start_time:.1f}s - {ev.end_time:.1f}s] {ev.event_type} ({ev.intensity}): {ev.description} | response: {ev.adult_response}")

    assert len(events) >= 1, "Audio analyst should detect at least one event in the crying segment"
    crying_event = next((e for e in events if e.event_type in ("crying", "screaming", "soothing")), None)
    assert crying_event is not None, "At least one crying or soothing event should be identified"


@pytest.mark.asyncio
async def test_coverage_and_gap_calculation():
    """
    Validates calculation of coverage percentage and identification of >60s silence/gap periods.
    """
    total_duration = 3600.0  # 1 hour
    # 2 speech blocks: 0-300s (5 min) and 1200-1500s (5 min) -> total 600s = 16.7% coverage
    mock_segments = [
        {"start_time": 0.0, "end_time": 300.0},
        {"start_time": 1200.0, "end_time": 1500.0}
    ]

    gaps, transcribed_sec, cov_pct = acoustic_service._compute_coverage_gaps(
        duration_seconds=total_duration,
        segments=mock_segments,
        loudness_points=[]
    )

    assert abs(cov_pct - 16.7) < 0.2
    assert transcribed_sec == 600.0
    # Should identify gap 1 (1200-300 = 900s) and gap 2 (3600-1500 = 2100s)
    assert len(gaps) == 2
    assert gaps[0].duration_seconds == 900.0
    assert gaps[1].duration_seconds == 2100.0
    print(f"Coverage test passed: {cov_pct}% coverage, {len(gaps)} gaps")


@pytest.mark.asyncio
async def test_audio_events_api_and_loudness_endpoints():
    """
    Validates the REST API endpoints for audio events, coverage, and loudness profile.
    """
    await init_db()

    # Create dummy session with acoustic events in DB
    session_id = "test-acoustic-session-999"
    async with AsyncSessionLocal() as db:
        session = SessionModel(
            id=session_id,
            title="בדיקת אירועים אקוסטיים",
            source_filename="test_audio.mp3",
            raw_file_path="/tmp/test_audio.mp3",
            status="completed",
            duration_seconds=1800.0,
            target_child_name="סביון"
        )
        db.add(session)

        ev1 = AudioEventModel(
            session_id=session_id,
            event_type="crying",
            start_time=120.0,
            end_time=145.0,
            peak_score=0.95,
            intensity="high",
            source="gemini",
            description="בכי חזק וממושך",
            adult_response="הגננת ניגשה והרגיעה"
        )
        ev2 = AudioEventModel(
            session_id=session_id,
            event_type="speech_gap",
            start_time=600.0,
            end_time=900.0,
            peak_score=0.5,
            intensity="low",
            source="loudness",
            description="פער תמלול ממושך (5 דקות)"
        )
        db.add_all([ev1, ev2])
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fetch all audio events
        res = await client.get(f"/api/audio-events/{session_id}")
        assert res.status_code == 200
        events = res.json()
        assert len(events) == 2
        assert events[0]["event_type"] == "crying"
        assert events[0]["intensity"] == "high"

        # 2. Filter by event_type=crying
        res_filter = await client.get(f"/api/audio-events/{session_id}?event_type=crying")
        assert res_filter.status_code == 200
        filtered = res_filter.json()
        assert len(filtered) == 1
        assert filtered[0]["event_type"] == "crying"

        # 3. Coverage endpoint
        cov_res = await client.get(f"/api/audio-events/{session_id}/coverage")
        assert cov_res.status_code == 200
        cov_data = cov_res.json()
        assert "coverage_percent" in cov_data

        # 4. Loudness endpoint
        loud_res = await client.get(f"/api/audio-events/{session_id}/loudness")
        assert loud_res.status_code == 200
        loud_data = loud_res.json()
        assert "baseline_db" in loud_data

        # Clean up test session
        del_res = await client.delete(f"/api/sessions/{session_id}")
        assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_chat_agent_acoustic_tool_execution():
    """
    Validates that the Chat Agent's acoustic tools (get_audio_events, get_coverage_summary)
    execute cleanly and return structured data for the LLM.
    """
    await init_db()

    session_id = "test-chat-acoustic-888"
    async with AsyncSessionLocal() as db:
        session = SessionModel(
            id=session_id,
            title="בדיקת צ'אט אקוסטי",
            source_filename="test_chat.mp3",
            raw_file_path="/tmp/test_chat.mp3",
            status="completed",
            duration_seconds=3600.0,
            target_child_name="סביון"
        )
        db.add(session)
        ev = AudioEventModel(
            session_id=session_id,
            event_type="crying",
            start_time=2820.0,
            end_time=2850.0,
            peak_score=0.9,
            intensity="high",
            source="gemini",
            description="בכי חזק בחצר",
            adult_response="סייעת חיבקה ונתנה מים"
        )
        db.add(ev)
        await db.commit()

    # Test get_audio_events tool
    async with AsyncSessionLocal() as db:
        ev_tool_output = await chat_agent_service.execute_tool(
            session_id=session_id,
            tool_name="get_audio_events",
            tool_args={"event_type": "all"},
            db=db
        )
        assert "events" in ev_tool_output
        assert len(ev_tool_output["events"]) == 1
        assert ev_tool_output["events"][0]["event_type"] == "crying"

        # Test get_coverage_summary tool
        cov_tool_output = await chat_agent_service.execute_tool(
            session_id=session_id,
            tool_name="get_coverage_summary",
            tool_args={},
            db=db
        )
        assert "coverage_percent" in cov_tool_output

        # Cleanup
        sess = await db.get(SessionModel, session_id)
        if sess:
            await db.delete(sess)
            await db.commit()
            await db.commit()
