import os
import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.database import AsyncSessionLocal
from backend.app.models import SessionModel, SpeakerModel, TranscriptSegmentModel
from backend.app.services.speaker_service import speaker_service, format_seconds_to_time


def test_format_seconds_to_time():
    assert format_seconds_to_time(45.0) == "00:45"
    assert format_seconds_to_time(90.0) == "01:30"
    assert format_seconds_to_time(3665.0) == "01:01:05"


@pytest.mark.asyncio
async def test_speaker_samples_selection():
    async with AsyncSessionLocal() as db:
        # Create a test session
        test_session = SessionModel(
            title="בדיקת דגימות קול",
            source_filename="test_audio.mp3",
            raw_file_path="/tmp/test_audio.mp3",
            status="ready_for_tagging",
            duration_seconds=1200.0
        )
        db.add(test_session)
        await db.flush()

        spk1 = SpeakerModel(
            session_id=test_session.id,
            diarization_tag="speaker_0",
            assigned_name="גננת",
            total_speech_seconds=150.0,
            sample_snippet_url=f"/api/audio/snippet/{test_session.id}/speaker_0"
        )
        spk2 = SpeakerModel(
            session_id=test_session.id,
            diarization_tag="speaker_1",
            assigned_name="ילד",
            total_speech_seconds=50.0,
            sample_snippet_url=f"/api/audio/snippet/{test_session.id}/speaker_1"
        )
        db.add_all([spk1, spk2])
        await db.flush()

        # Add segments with different durations and gaps
        # Seg 1: isolated 5s segment for spk1
        s1 = TranscriptSegmentModel(
            session_id=test_session.id,
            speaker_id=spk1.id,
            speaker_tag="speaker_0",
            speaker_name="גננת",
            start_time=10.0,
            end_time=15.0,
            text="בוקר טוב לכל הילדים החמודים שבאו לגן",
            confidence=0.98
        )
        # Seg 2: isolated 4s segment for spk2
        s2 = TranscriptSegmentModel(
            session_id=test_session.id,
            speaker_id=spk2.id,
            speaker_tag="speaker_1",
            speaker_name="ילד",
            start_time=20.0,
            end_time=24.0,
            text="אני רוצה לשחק בבובות",
            confidence=0.95
        )
        # Seg 3: rapid banter (overlapping / non-isolated) between spk1 and spk2
        s3 = TranscriptSegmentModel(
            session_id=test_session.id,
            speaker_id=spk1.id,
            speaker_tag="speaker_0",
            speaker_name="גננת",
            start_time=24.2,
            end_time=25.0,
            text="יופי",
            confidence=0.8
        )
        s4 = TranscriptSegmentModel(
            session_id=test_session.id,
            speaker_id=spk2.id,
            speaker_tag="speaker_1",
            speaker_name="ילד",
            start_time=25.1,
            end_time=26.0,
            text="כן",
            confidence=0.7
        )
        # Seg 5: another isolated segment for spk1 at later time
        s5 = TranscriptSegmentModel(
            session_id=test_session.id,
            speaker_id=spk1.id,
            speaker_tag="speaker_0",
            speaker_name="גננת",
            start_time=300.0,
            end_time=307.0,
            text="בואו כולנו לשבת ליד השולחן לאכול פירות",
            confidence=0.99
        )

        db.add_all([s1, s2, s3, s4, s5])
        await db.commit()

        # Test sample retrieval
        samples_map = await speaker_service.get_all_speakers_samples(test_session.id, db)
        assert spk1.id in samples_map
        assert spk2.id in samples_map

        spk1_samples = samples_map[spk1.id]
        assert len(spk1_samples) >= 2
        # Check that isolated, longer segments scored higher and are included
        texts = [s.text for s in spk1_samples]
        assert "בוקר טוב לכל הילדים החמודים שבאו לגן" in texts
        assert "בואו כולנו לשבת ליד השולחן לאכול פירות" in texts

        # Verify SpeakerSampleItem properties
        sample0 = spk1_samples[0]
        assert sample0.start_time > 0
        assert sample0.duration > 0
        assert sample0.formatted_time != ""
        assert sample0.audio_url.startswith(f"/api/audio/snippet/{test_session.id}/speaker_0")

        # Test single speaker sample method
        spk2_samples = await speaker_service.get_speaker_sample_clips(test_session.id, spk2.id, db)
        assert len(spk2_samples) >= 1
        assert any("בובות" in s.text for s in spk2_samples)

        # Cleanup
        await db.delete(test_session)
        await db.commit()


@pytest.mark.asyncio
async def test_speaker_samples_api_endpoints():
    async with AsyncSessionLocal() as db:
        test_session = SessionModel(
            title="בדיקת API דגימות",
            source_filename="test_api.mp3",
            raw_file_path="/tmp/test_api.mp3",
            status="ready_for_tagging",
            duration_seconds=600.0
        )
        db.add(test_session)
        await db.flush()

        spk = SpeakerModel(
            session_id=test_session.id,
            diarization_tag="speaker_0",
            assigned_name="גננת שרה",
            total_speech_seconds=60.0
        )
        db.add(spk)
        await db.flush()

        seg = TranscriptSegmentModel(
            session_id=test_session.id,
            speaker_id=spk.id,
            speaker_tag="speaker_0",
            speaker_name="גננת שרה",
            start_time=12.0,
            end_time=18.0,
            text="מי רוצה לקרוא סיפור?",
            confidence=0.99
        )
        db.add(seg)
        await db.commit()
        session_id = test_session.id
        speaker_id = spk.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. GET /api/speakers/{session_id}/samples
        res_all = await client.get(f"/api/speakers/{session_id}/samples")
        assert res_all.status_code == 200
        data_all = res_all.json()
        assert speaker_id in data_all
        assert len(data_all[speaker_id]) >= 1
        assert "סיפור" in data_all[speaker_id][0]["text"]

        # 2. GET /api/speakers/{session_id}/{speaker_id}/samples
        res_single = await client.get(f"/api/speakers/{session_id}/{speaker_id}/samples")
        assert res_single.status_code == 200
        data_single = res_single.json()
        assert len(data_single) >= 1
        assert data_single[0]["sample_index"] == 0
        assert data_single[0]["formatted_time"] == "00:12"

        # 3. GET /api/sessions/{session_id} includes samples in speaker
        res_session = await client.get(f"/api/sessions/{session_id}")
        assert res_session.status_code == 200
        session_data = res_session.json()
        assert len(session_data["speakers"]) >= 1
        assert "samples" in session_data["speakers"][0]
        assert len(session_data["speakers"][0]["samples"]) >= 1

    # Cleanup
    async with AsyncSessionLocal() as db:
        s = await db.get(SessionModel, session_id)
        if s:
            await db.delete(s)
            await db.commit()
