from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.database import get_db
from backend.app.models import SessionModel, SpeakerModel, TranscriptSegmentModel
from backend.app.schemas import TaggingConfigRequest, SessionDetailResponse
from backend.app.services.job_pipeline import job_pipeline

router = APIRouter(prefix="/speakers", tags=["speakers"])


@router.post("/{session_id}/configure", response_model=SessionDetailResponse)
async def configure_speakers_and_focus(
    session_id: str,
    req: TaggingConfigRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Submits user speaker tagging, selects the child in focus,
    and sets custom focus prompt. Then triggers final AI report generation.
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    target_child_name = req.target_child_name

    # 1. Update speakers
    for spk_in in req.speakers:
        spk = await db.get(SpeakerModel, spk_in.speaker_id)
        if spk and spk.session_id == session.id:
            spk.assigned_name = spk_in.assigned_name.strip()
            spk.role = spk_in.role.strip()
            spk.is_child_in_focus = spk_in.is_child_in_focus

            if spk_in.is_child_in_focus:
                target_child_name = spk.assigned_name

            # Update all segments spoken by this speaker
            await db.execute(
                update(TranscriptSegmentModel)
                .where(TranscriptSegmentModel.speaker_id == spk.id)
                .values(speaker_name=spk.assigned_name)
            )

    # 2. Update session metadata
    if req.focus_prompt:
        session.focus_prompt = req.focus_prompt.strip()
    if target_child_name:
        session.target_child_name = target_child_name.strip()

    await db.commit()

    # Re-query with selectinload
    stmt = (
        select(SessionModel)
        .where(SessionModel.id == session.id)
        .options(
            selectinload(SessionModel.speakers),
            selectinload(SessionModel.audio_events),
            selectinload(SessionModel.report)
        )
    )
    res = await db.execute(stmt)
    loaded_session = res.scalar_one()

    # 3. Trigger final AI report generation
    background_tasks.add_task(job_pipeline.generate_final_report, session.id)

    return loaded_session


from backend.app.schemas import SpeakerSampleItem
from backend.app.services.speaker_service import speaker_service
from typing import Dict


@router.get("/{session_id}/samples", response_model=Dict[str, List[SpeakerSampleItem]])
async def get_all_speakers_samples(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns multiple candidate speech sample clips for all speakers in the session.
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return await speaker_service.get_all_speakers_samples(session_id, db)


@router.get("/{session_id}/{speaker_id}/samples", response_model=List[SpeakerSampleItem])
async def get_speaker_samples(
    session_id: str,
    speaker_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns multiple candidate speech sample clips for a single speaker.
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return await speaker_service.get_speaker_sample_clips(session_id, speaker_id, db)
