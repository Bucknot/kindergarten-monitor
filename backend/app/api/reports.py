from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.database import get_db
from backend.app.models import DailyReportModel, SessionModel
from backend.app.schemas import DailyReportResponse

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{session_id}", response_model=DailyReportResponse)
async def get_report(session_id: str, db: AsyncSession = Depends(get_db)):
    query = select(DailyReportModel).where(DailyReportModel.session_id == session_id)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet for this session")
    return report


@router.get("/{session_id}/markdown")
async def download_report_markdown(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    query = select(DailyReportModel).where(DailyReportModel.session_id == session_id)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet")

    filename = f"kindergarten_report_{session_id[:8]}.md"
    return Response(
        content=report.full_markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
