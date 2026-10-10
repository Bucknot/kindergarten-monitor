import os
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import SessionModel, AudioEventModel, DailyReportModel
from backend.app.schemas import AudioEventResponse, CoverageResponse, CoverageGapItem
from backend.app.services.acoustic import acoustic_service
from backend.app.services.cache_service import cache_service

router = APIRouter(prefix="/audio-events", tags=["audio-events"])


@router.get("/{session_id}", response_model=List[AudioEventResponse])
async def get_session_audio_events(
    session_id: str,
    event_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns detected acoustic events (crying, screaming, loud spans, speech gaps)
    for a given session.
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    stmt = select(AudioEventModel).where(AudioEventModel.session_id == session_id)
    if event_type and event_type != "all":
        stmt = stmt.where(AudioEventModel.event_type == event_type)

    stmt = stmt.order_by(AudioEventModel.start_time.asc())
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get("/{session_id}/coverage", response_model=CoverageResponse)
async def get_session_coverage(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns coverage statistics (% transcribed, duration) and unanalyzed gaps > 60s.
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Probe or load from acoustic service
    audio_path = session.optimized_file_path or session.raw_file_path
    if not audio_path or not os.path.exists(audio_path):
        return CoverageResponse(
            total_duration_seconds=session.duration_seconds or 0.0,
            transcribed_seconds=0.0,
            coverage_percent=0.0,
            gaps_count=0,
            gaps=[]
        )

    file_hash = cache_service.compute_file_hash(audio_path)

    # Load segments from DB
    from backend.app.models import TranscriptSegmentModel
    seg_stmt = select(TranscriptSegmentModel).where(
        TranscriptSegmentModel.session_id == session.id
    ).order_by(TranscriptSegmentModel.start_time.asc())
    segs = (await db.execute(seg_stmt)).scalars().all()
    seg_dicts = [{"start_time": s.start_time, "end_time": s.end_time} for s in segs]

    acoustic_res = await acoustic_service.analyze_audio(
        audio_path=audio_path,
        duration_seconds=session.duration_seconds,
        transcript_segments=seg_dicts,
        file_hash=file_hash
    )

    gaps_items = [
        CoverageGapItem(
            start_seconds=g.start_seconds,
            end_seconds=g.end_seconds,
            duration_seconds=g.duration_seconds,
            start_formatted=g.start_formatted,
            end_formatted=g.end_formatted,
            mean_db=g.mean_db,
            note=g.note
        )
        for g in acoustic_res.gaps
    ]

    return CoverageResponse(
        total_duration_seconds=session.duration_seconds,
        transcribed_seconds=acoustic_res.transcribed_seconds,
        coverage_percent=acoustic_res.coverage_percent,
        gaps_count=len(gaps_items),
        gaps=gaps_items
    )


@router.get("/{session_id}/loudness")
async def get_session_loudness_profile(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns downsampled RMS loudness points (full_db, cry_db) for waveform rendering.
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    audio_path = session.optimized_file_path or session.raw_file_path
    if not audio_path or not os.path.exists(audio_path):
        return {"points": [], "baseline_db": -28.0}

    file_hash = cache_service.compute_file_hash(audio_path)
    acoustic_res = await acoustic_service.analyze_audio(
        audio_path=audio_path,
        duration_seconds=session.duration_seconds,
        file_hash=file_hash
    )

    return {
        "baseline_db": acoustic_res.baseline_db,
        "points": acoustic_res.loudness_points
    }
