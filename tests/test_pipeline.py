import os
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.config import settings
from backend.app.database import init_db
from backend.app.services.audio_service import audio_service

SAMPLE_AUDIO_PATH = os.getenv("SAMPLE_AUDIO_PATH", "/mnt/c/Users/Adar/Documents/savion-08-10-26-part-1.mp3")


@pytest.mark.asyncio
async def test_audio_probing():
    if not os.path.exists(SAMPLE_AUDIO_PATH):
        pytest.skip(f"Local audio file {SAMPLE_AUDIO_PATH} not found; skipping probe test")
    meta = await audio_service.probe_audio(SAMPLE_AUDIO_PATH)
    assert meta["duration"] > 0, "Duration should be positive"
    assert meta["channels"] == 1 or meta["channels"] == 2
    print(f"Verified sample audio: duration={meta['duration']}s, size={meta['size_bytes']} bytes")


@pytest.mark.asyncio
async def test_snippet_extraction():
    test_out = "/tmp/test_snippet_extracted.mp3"
    temp_source = None
    if os.path.exists(SAMPLE_AUDIO_PATH):
        src_path = SAMPLE_AUDIO_PATH
    else:
        temp_source = "/tmp/test_source_synth.mp3"
        import subprocess
        subprocess.run(
            [settings.FFMPEG_PATH, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=10", "-ar", "16000", "-ac", "1", temp_source],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        src_path = temp_source

    snippet_path = await audio_service.extract_snippet(src_path, 1.0, 3.0, test_out)
    assert os.path.exists(snippet_path)
    assert os.path.getsize(snippet_path) > 500
    if os.path.exists(test_out):
        os.remove(test_out)
    if temp_source and os.path.exists(temp_source):
        os.remove(temp_source)


@pytest.mark.asyncio
async def test_openai_compatible_stt_parsing():
    from backend.app.services.stt.openai_compatible import OpenAICompatibleSTTProvider
    provider = OpenAICompatibleSTTProvider(api_key="test-key", base_url="https://api.openai.com/v1")
    dummy_data = {
        "segments": [
            {"start": 0.0, "end": 4.5, "text": "בוקר טוב ילדים חמודים"},
            {"start": 4.8, "end": 9.2, "text": "בואו נשב כולנו במעגל"},
            {"start": 12.0, "end": 16.5, "text": "אני רוצה לשחק בקוביות"}
        ]
    }
    res = provider._parse_verbose_json(dummy_data)
    assert len(res.utterances) == 3
    assert len(res.speakers) >= 2
    assert res.provider_name == "openai_compatible"
    print("OpenAI-compatible / OpenRouter STT parsing verified successfully!")


@pytest.mark.asyncio
async def test_full_pipeline_flow():
    await init_db()
    # Create a 15-second mini clip for test execution
    mini_audio = "/tmp/test_mini_kindergarten.mp3"
    if os.path.exists(SAMPLE_AUDIO_PATH):
        await audio_service.extract_snippet(SAMPLE_AUDIO_PATH, 0.0, 15.0, mini_audio)
    else:
        import subprocess
        subprocess.run(
            [settings.FFMPEG_PATH, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=15", "-ar", "16000", "-ac", "1", mini_audio],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health check
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"

        # 2. Create session from local path
        payload = {
            "local_file_path": mini_audio,
            "title": "בדיקת מערכת אוטומטית - יום בגן",
            "target_child_name": "סביון",
            "focus_prompt": "בדיקת אירועי בכי בחצר ויחס הגננת בארוחת עשר",
            "stt_provider": "mock"
        }
        res = await client.post("/api/sessions", json=payload)
        assert res.status_code == 200
        session_data = res.json()
        session_id = session_data["id"]
        assert session_data["status"] == "pending"

        # 3. Wait for initial processing (probe, optimize, transcribe, extract snippets)
        max_wait = 20
        while max_wait > 0:
            await asyncio.sleep(1.0)
            res = await client.get(f"/api/sessions/{session_id}")
            assert res.status_code == 200
            session = res.json()
            if session["status"] == "ready_for_tagging":
                break
            max_wait -= 1

        assert session["status"] == "ready_for_tagging"
        assert len(session["speakers"]) > 0
        print(f"Session reached ready_for_tagging with {len(session['speakers'])} speakers")

        # 4. Verify snippet audio endpoint works
        first_spk = session["speakers"][0]
        snippet_res = await client.get(f"/api/audio/snippet/{session_id}/{first_spk['diarization_tag']}")
        assert snippet_res.status_code == 200
        assert len(snippet_res.content) > 0

        # 5. Configure speakers & focus child
        speaker_updates = []
        for idx, spk in enumerate(session["speakers"]):
            speaker_updates.append({
                "speaker_id": spk["id"],
                "assigned_name": "גננת מיכל" if idx == 0 else ("סייעת רותי" if idx == 1 else "סביון"),
                "role": "גננת ראשית" if idx == 0 else ("סייעת" if idx == 1 else "ילד/ה במוקד"),
                "is_child_in_focus": (idx == 2)
            })

        config_payload = {
            "speakers": speaker_updates,
            "focus_prompt": "בדיקת אירועי בכי בחצר ויחס הגננת בארוחת עשר",
            "target_child_name": "סביון"
        }

        res = await client.post(f"/api/speakers/{session_id}/configure", json=config_payload)
        assert res.status_code == 200

        # 6. Wait for report generation to complete
        max_wait = 60
        while max_wait > 0:
            await asyncio.sleep(1.0)
            res = await client.get(f"/api/sessions/{session_id}")
            session = res.json()
            if session["status"] == "completed":
                break
            max_wait -= 1

        assert session["status"] == "completed"
        assert session["report"] is not None
        assert "דוח יומי מקיף" in session["report"]["full_markdown"] or len(session["report"]["executive_summary"]) > 0
        print("Session report generated successfully!")

        # 7. Check transcripts query and search
        res = await client.get(f"/api/transcripts/{session_id}?search=שלום")
        assert res.status_code == 200
        trans_data = res.json()
        assert trans_data["total"] >= 1

        # 8. Check range streaming
        stream_res = await client.get(
            f"/api/audio/stream/{session_id}",
            headers={"Range": "bytes=0-1023"}
        )
        assert stream_res.status_code in (200, 206)
        assert len(stream_res.content) > 0

        # 9. Check markdown download endpoint
        md_res = await client.get(f"/api/reports/{session_id}/markdown")
        assert md_res.status_code == 200
        assert "דוח יומי מקיף" in md_res.text

        # 10. Clean up test session
        del_res = await client.delete(f"/api/sessions/{session_id}")
        assert del_res.status_code == 200
        print("Pipeline test completed with 100% success!")
