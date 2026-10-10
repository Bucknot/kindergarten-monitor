import os
import json
import shutil
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.config import settings
from backend.app.database import get_db
from backend.app.models import SessionModel
from backend.app.schemas import (
    SessionCreateRequest,
    SessionDetailResponse,
    SessionSummaryResponse,
    RegenerateReportRequest
)
from backend.app.services.job_pipeline import job_pipeline

router = APIRouter(prefix="/sessions", tags=["sessions"])


def normalize_audio_path(path: str) -> str:
    if not path:
        return ""
    p = path.strip().strip('"').strip("'")
    p = p.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
        drive = p[0].lower()
        p = f"/mnt/{drive}{p[2:]}"
    elif p.startswith("mnt/"):
        p = f"/{p}"
    return p


@router.get("", response_model=List[SessionSummaryResponse])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    query = select(SessionModel).order_by(desc(SessionModel.created_at))
    result = await db.execute(query)
    sessions = result.scalars().all()
    return sessions


@router.post("", response_model=SessionDetailResponse)
async def create_session_from_path(
    req: SessionCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a new analysis session from a local audio file path
    (e.g., /path/to/day_recording.mp3 or C:\recordings\day_recording.mp3)
    """
    normalized_path = normalize_audio_path(req.local_file_path or "")
    if not normalized_path or not os.path.exists(normalized_path):
        raise HTTPException(
            status_code=400,
            detail=f"קובץ השמע לא נמצא בנתיב המבוקש: {req.local_file_path} (נבדק: {normalized_path})"
        )

    file_size = os.path.getsize(normalized_path)
    filename = os.path.basename(normalized_path)

    # Apply Gladia / OpenRouter / OpenAI settings if provided
    if req.gladia_api_key:
        settings.GLADIA_API_KEY = req.gladia_api_key.strip()
        settings.STT_PROVIDER = "gladia"
    if req.deepgram_api_key:
        settings.DEEPGRAM_API_KEY = req.deepgram_api_key.strip()
        settings.STT_PROVIDER = "deepgram"
    if req.openrouter_api_key:
        settings.OPENROUTER_API_KEY = req.openrouter_api_key.strip()
        settings.LLM_PROVIDER = "openrouter"
    if req.openrouter_model:
        settings.OPENROUTER_MODEL = req.openrouter_model.strip()
    if req.openrouter_stt_model:
        settings.OPENROUTER_STT_MODEL = req.openrouter_stt_model.strip()
    if req.audio_llm_model:
        settings.AUDIO_LLM_MODEL = req.audio_llm_model.strip()
    if req.openai_stt_api_key:
        settings.OPENAI_COMPATIBLE_STT_API_KEY = req.openai_stt_api_key.strip()
    if req.openai_stt_base_url:
        settings.OPENAI_COMPATIBLE_STT_BASE_URL = req.openai_stt_base_url.strip()
    if req.openai_stt_model:
        settings.OPENAI_COMPATIBLE_STT_MODEL = req.openai_stt_model.strip()

    target_child = req.target_child_name
    if not target_child and req.context_metadata and req.context_metadata.get("target_child_name"):
        target_child = req.context_metadata.get("target_child_name")

    target_stt_model = None
    effective_provider = req.stt_provider or settings.STT_PROVIDER
    if req.openrouter_stt_model and effective_provider == "openrouter":
        target_stt_model = req.openrouter_stt_model.strip()
    elif req.openai_stt_model and effective_provider == "openai_compatible":
        target_stt_model = req.openai_stt_model.strip()

    ctx_meta = dict(req.context_metadata) if req.context_metadata else {}
    if target_stt_model:
        ctx_meta["stt_model"] = target_stt_model

    session = SessionModel(
        title=req.title or f"הקלטת {filename}",
        source_filename=filename,
        raw_file_path=normalized_path,
        file_size_bytes=file_size,
        status="pending",
        status_message="הקובץ נטען, ממתין לתחילת עיבוד",
        stt_provider=effective_provider,
        stt_model=target_stt_model,
        focus_prompt=req.focus_prompt,
        target_child_name=target_child,
        context_metadata=ctx_meta if ctx_meta else None
    )

    db.add(session)
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

    # Launch background processing pipeline
    background_tasks.add_task(job_pipeline.process_initial_audio, loaded_session.id)

    return loaded_session


@router.post("/upload", response_model=SessionDetailResponse)
async def upload_audio_file(
    background_tasks: BackgroundTasks,
    title: str = Form("הקלטת יום בגן"),
    stt_provider: Optional[str] = Form(None),
    focus_prompt: Optional[str] = Form(None),
    target_child_name: Optional[str] = Form(None),
    gladia_api_key: Optional[str] = Form(None),
    openrouter_api_key: Optional[str] = Form(None),
    openrouter_model: Optional[str] = Form(None),
    openrouter_stt_model: Optional[str] = Form(None),
    audio_llm_model: Optional[str] = Form(None),
    openai_stt_api_key: Optional[str] = Form(None),
    openai_stt_base_url: Optional[str] = Form(None),
    openai_stt_model: Optional[str] = Form(None),
    context_metadata: Optional[str] = Form(None),
    parents_names: Optional[str] = Form(None),
    kindergarten_name: Optional[str] = Form(None),
    staff_names: Optional[str] = Form(None),
    friends_names: Optional[str] = Form(None),
    key_vocabulary: Optional[str] = Form(None),
    custom_notes: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    if gladia_api_key:
        settings.GLADIA_API_KEY = gladia_api_key.strip()
        settings.STT_PROVIDER = "gladia"
    if openrouter_api_key:
        settings.OPENROUTER_API_KEY = openrouter_api_key.strip()
        settings.LLM_PROVIDER = "openrouter"
    if openrouter_model:
        settings.OPENROUTER_MODEL = openrouter_model.strip()
    if openrouter_stt_model:
        settings.OPENROUTER_STT_MODEL = openrouter_stt_model.strip()
    if audio_llm_model:
        settings.AUDIO_LLM_MODEL = audio_llm_model.strip()
    if openai_stt_api_key:
        settings.OPENAI_COMPATIBLE_STT_API_KEY = openai_stt_api_key.strip()
    if openai_stt_base_url:
        settings.OPENAI_COMPATIBLE_STT_BASE_URL = openai_stt_base_url.strip()
    if openai_stt_model:
        settings.OPENAI_COMPATIBLE_STT_MODEL = openai_stt_model.strip()

    # Parse or assemble context metadata
    parsed_context: Dict[str, Any] = {}
    if context_metadata:
        try:
            parsed_context = json.loads(context_metadata) if isinstance(context_metadata, str) else dict(context_metadata)
        except Exception:
            parsed_context = {}

    if target_child_name and not parsed_context.get("target_child_name"):
        parsed_context["target_child_name"] = target_child_name.strip()
    if parents_names and not parsed_context.get("parents_names"):
        parsed_context["parents_names"] = parents_names.strip()
    if kindergarten_name and not parsed_context.get("kindergarten_name"):
        parsed_context["kindergarten_name"] = kindergarten_name.strip()
    if staff_names and not parsed_context.get("staff_names"):
        parsed_context["staff_names"] = staff_names.strip()
    if friends_names and not parsed_context.get("friends_names"):
        parsed_context["friends_names"] = friends_names.strip()
    if key_vocabulary and not parsed_context.get("key_vocabulary"):
        parsed_context["key_vocabulary"] = key_vocabulary.strip()
    if custom_notes and not parsed_context.get("custom_notes"):
        parsed_context["custom_notes"] = custom_notes.strip()

    target_child = target_child_name or parsed_context.get("target_child_name")

    effective_provider = stt_provider or settings.STT_PROVIDER
    target_stt_model = None
    if openrouter_stt_model and effective_provider == "openrouter":
        target_stt_model = openrouter_stt_model.strip()
    elif openai_stt_model and effective_provider == "openai_compatible":
        target_stt_model = openai_stt_model.strip()

    if target_stt_model:
        parsed_context["stt_model"] = target_stt_model

    upload_dest = settings.upload_dir / file.filename
    counter = 1
    base_name = upload_dest.stem
    ext = upload_dest.suffix
    while upload_dest.exists():
        upload_dest = settings.upload_dir / f"{base_name}_{counter}{ext}"
        counter += 1

    with open(upload_dest, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = os.path.getsize(upload_dest)

    session = SessionModel(
        title=title,
        source_filename=file.filename,
        raw_file_path=str(upload_dest),
        file_size_bytes=file_size,
        status="pending",
        status_message="הקובץ הועלה בהצלחה",
        stt_provider=effective_provider,
        stt_model=target_stt_model,
        focus_prompt=focus_prompt,
        target_child_name=target_child,
        context_metadata=parsed_context if parsed_context else None
    )

    db.add(session)
    await db.commit()

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

    background_tasks.add_task(job_pipeline.process_initial_audio, loaded_session.id)

    return loaded_session


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(SessionModel)
        .where(SessionModel.id == session_id)
        .options(
            selectinload(SessionModel.speakers),
            selectinload(SessionModel.audio_events),
            selectinload(SessionModel.report)
        )
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.optimized_file_path and os.path.exists(session.optimized_file_path):
        try:
            os.remove(session.optimized_file_path)
        except Exception:
            pass

    await db.delete(session)
    await db.commit()
    return {"message": "Session deleted successfully"}


@router.post("/{session_id}/regenerate-report")
async def regenerate_report(
    session_id: str,
    background_tasks: BackgroundTasks,
    req: Optional[RegenerateReportRequest] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Reruns the LLM report generation for an existing session without re-running STT.
    Allows testing different prompts, focus questions, or models instantly!
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if req:
        if req.focus_prompt is not None:
            session.focus_prompt = req.focus_prompt
        if req.target_child_name is not None:
            session.target_child_name = req.target_child_name
        if req.context_metadata is not None:
            session.context_metadata = req.context_metadata
        if req.openrouter_model:
            settings.OPENROUTER_MODEL = req.openrouter_model.strip()
        if req.openrouter_api_key:
            settings.OPENROUTER_API_KEY = req.openrouter_api_key.strip()
            settings.LLM_PROVIDER = "openrouter"

    session.status = "generating_report"
    session.progress_percent = 80
    session.status_message = "מפיק דוח פדגוגי מחדש לפי ההנחיות המעודכנות..."
    await db.commit()

    background_tasks.add_task(job_pipeline.generate_final_report, session.id)
    return {"message": "Report regeneration started", "session_id": session.id}

