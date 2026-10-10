from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.database import get_db
from backend.app.models import TranscriptSegmentModel, SessionModel
from backend.app.schemas import PaginatedSegmentsResponse, TranscriptSegmentResponse

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


@router.get("/{session_id}", response_model=PaginatedSegmentsResponse)
async def get_transcript_segments(
    session_id: str,
    search: Optional[str] = Query(None, description="Search term in Hebrew"),
    speaker_id: Optional[str] = Query(None, description="Filter by speaker ID"),
    flagged_only: bool = Query(False, description="Filter flagged/crying segments"),
    start_time_ge: Optional[float] = Query(None, description="Filter segments with start_time >= value"),
    end_time_le: Optional[float] = Query(None, description="Filter segments with start_time <= value"),
    page: int = Query(1, ge=1),
    page_size: int = Query(250, ge=1, le=10000),
    db: AsyncSession = Depends(get_db)
):
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    conditions = [TranscriptSegmentModel.session_id == session_id]

    if speaker_id:
        conditions.append(TranscriptSegmentModel.speaker_id == speaker_id)

    if flagged_only:
        conditions.append(TranscriptSegmentModel.is_flagged == True)

    if start_time_ge is not None:
        conditions.append(TranscriptSegmentModel.start_time >= start_time_ge)

    if end_time_le is not None:
        conditions.append(TranscriptSegmentModel.start_time <= end_time_le)

    if search:
        search_term = f"%{search.strip()}%"
        conditions.append(TranscriptSegmentModel.text.ilike(search_term))

    # Count total
    count_query = select(func.count(TranscriptSegmentModel.id)).where(and_(*conditions))
    total_count = (await db.execute(count_query)).scalar() or 0

    total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count > 0 else 1

    # Fetch items
    offset = (page - 1) * page_size
    query = (
        select(TranscriptSegmentModel)
        .where(and_(*conditions))
        .order_by(TranscriptSegmentModel.start_time.asc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    items = result.scalars().all()

    return PaginatedSegmentsResponse(
        total=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=items
    )


@router.get("/{session_id}/page-for-time")
async def get_page_for_time(
    session_id: str,
    time_seconds: float = Query(..., description="Timestamp in seconds"),
    page_size: int = Query(250, ge=1, le=10000),
    speaker_id: Optional[str] = Query(None),
    flagged_only: bool = Query(False),
    db: AsyncSession = Depends(get_db)
):
    """
    Given a timestamp in seconds (e.g. from an audio jump or citation),
    determines which page contains that moment so the UI can navigate straight to it.
    """
    conditions = [TranscriptSegmentModel.session_id == session_id]
    if speaker_id:
        conditions.append(TranscriptSegmentModel.speaker_id == speaker_id)
    if flagged_only:
        conditions.append(TranscriptSegmentModel.is_flagged == True)

    # Count segments before time_seconds
    cnt_stmt = select(func.count(TranscriptSegmentModel.id)).where(
        and_(*conditions, TranscriptSegmentModel.start_time <= time_seconds)
    )
    count_before = (await db.execute(cnt_stmt)).scalar() or 0
    page = max(1, (count_before // page_size) + 1)
    return {"page": page, "count_before": count_before}
