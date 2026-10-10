import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.database import get_db
from backend.app.models import SessionModel, SpeakerModel
from backend.app.services.audio_service import audio_service

router = APIRouter(prefix="/audio", tags=["audio"])


@router.get("/stream/{session_id}")
async def stream_session_audio(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Streams session audio with HTTP Range support for instant seeking
    in full-day recordings.
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    file_to_stream = session.optimized_file_path or session.raw_file_path
    if not file_to_stream or not os.path.exists(file_to_stream):
        raise HTTPException(status_code=404, detail="Audio file not found on disk")

    range_header = request.headers.get("range")
    return audio_service.stream_file_range(file_to_stream, range_header)


from pathlib import Path
from backend.app.config import settings

@router.get("/snippet/{session_id}/{speaker_tag}")
async def get_speaker_snippet(
    session_id: str,
    speaker_tag: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns the isolated 5-10 second audio snippet for a specific speaker.
    Resilient to cache-reused sessions by falling back to disk search.
    """
    snippet_path = None
    query = (
        SpeakerModel.session_id == session_id,
        SpeakerModel.diarization_tag == speaker_tag
    )
    result = await db.execute(
        SpeakerModel.__table__.select().where(*query)
    )
    speaker = result.first()
    if speaker and speaker.sample_snippet_path and os.path.exists(speaker.sample_snippet_path):
        snippet_path = speaker.sample_snippet_path

    # Fallback 1: check direct session snippet file
    if not snippet_path or not os.path.exists(snippet_path):
        candidate = settings.snippet_dir / f"{session_id}_spk_{speaker_tag}.mp3"
        if candidate.exists() and candidate.stat().st_size > 500:
            snippet_path = str(candidate)

    # Fallback 2: check any matching snippet for this speaker_tag in snippets directory
    if not snippet_path or not os.path.exists(snippet_path):
        candidates = list(settings.snippet_dir.glob(f"*_spk_{speaker_tag}.mp3"))
        valid = [c for c in candidates if c.exists() and c.stat().st_size > 500]
        if valid:
            snippet_path = str(valid[0])

    if not snippet_path or not os.path.exists(snippet_path):
        raise HTTPException(status_code=404, detail="Snippet audio file not found on disk")

    return FileResponse(snippet_path, media_type="audio/mpeg")
