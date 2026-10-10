import os
import json
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.config import settings
from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    SessionModel, SpeakerModel, TranscriptSegmentModel, DailyReportModel, AudioEventModel
)
from backend.app.services.audio_service import audio_service
from backend.app.services.stt import get_stt_provider
from backend.app.services.stt.base import consolidate_utterance_dicts
from backend.app.services.llm.report_service import llm_report_service
from backend.app.services.cache_service import cache_service
from backend.app.services.acoustic import acoustic_service
from backend.app.services.llm.audio_analyst import audio_analyst

logger = logging.getLogger(__name__)


class JobPipeline:
    async def process_initial_audio(self, session_id: str):
        """
        Background task:
        1. Probes & downsamples audio
        2. Transcribes & diarizes (or loads from fast cache)
        3. Extracts speaker audio snippets (strictly from session audio)
        4. Runs Acoustic Layer & Audio LLM candidate listening
        5. Sets state to 'ready_for_tagging'
        """
        async with AsyncSessionLocal() as db:
            session = await db.get(SessionModel, session_id)
            if not session:
                return

            try:
                # 1. Update status to preprocessing
                session.status = "preprocessing"
                session.progress_percent = 15
                session.status_message = "בודק וממטב קובץ שמע לטובת זיהוי דיבור..."
                await db.commit()

                # 2. Probe audio file
                meta = await audio_service.probe_audio(session.raw_file_path)
                session.duration_seconds = meta["duration"]
                session.file_size_bytes = meta["size_bytes"]
                await db.commit()

                # Compute fast 3-chunk hash to check STT cache
                file_hash = cache_service.compute_file_hash(session.raw_file_path)

                # Check cache hit (isolated by STT provider and model)
                cached = cache_service.get_stt_cache(
                    file_hash,
                    stt_provider=session.stt_provider,
                    stt_model=session.stt_model
                )
                if cached:
                    logger.info(f"Reusing cached transcription for {session.source_filename} (hash: {file_hash})")
                    session.progress_percent = 50
                    session.status_message = "נמצא תמליל וזיהוי קולות שמורים במערכת! טוען נתונים באופן מיידי ללא עלות נוספת..."
                    await db.commit()

                    speaker_id_map = {}
                    for idx, spk in enumerate(cached.get("speakers", [])):
                        spk_tag = spk["diarization_tag"]

                        # Ensure snippet file exists for this session
                        snippet_filename = f"{session.id}_spk_{spk_tag}.mp3"
                        target_snippet_path = settings.snippet_dir / snippet_filename
                        sample_snippet_path = None
                        if target_snippet_path.exists() and target_snippet_path.stat().st_size > 500:
                            sample_snippet_path = str(target_snippet_path)
                        else:
                            # Extract directly from current session audio - NEVER copy from unrelated sessions
                            sample_start = float(spk.get("sample_start_time", 0.0))
                            if sample_start == 0.0:
                                for u in cached.get("utterances", []):
                                    if u.get("speaker_tag") == spk_tag:
                                        sample_start = float(u.get("start_time", 0.0))
                                        break
                            try:
                                audio_src = session.optimized_file_path or session.raw_file_path
                                await audio_service.extract_snippet(
                                    audio_src, sample_start, 5.0, str(target_snippet_path)
                                )
                                if target_snippet_path.exists() and target_snippet_path.stat().st_size > 500:
                                    sample_snippet_path = str(target_snippet_path)
                            except Exception as se:
                                logger.warning(f"Could not extract snippet for {spk_tag}: {se}")

                        sample_snippet_url = f"/api/audio/snippet/{session.id}/{spk_tag}"

                        speaker_model = SpeakerModel(
                            session_id=session.id,
                            diarization_tag=spk_tag,
                            assigned_name=spk.get("assigned_name") or f"דובר {idx + 1}",
                            role=spk.get("role") or f"דובר {idx + 1}",
                            is_child_in_focus=bool(spk.get("is_child_in_focus", False)),
                            total_speech_seconds=float(spk.get("total_speech_seconds", 0.0)),
                            utterance_count=int(spk.get("utterance_count", 0)),
                            sample_snippet_path=sample_snippet_path,
                            sample_snippet_url=sample_snippet_url
                        )
                        db.add(speaker_model)
                        await db.flush()
                        speaker_id_map[spk_tag] = (speaker_model.id, speaker_model.assigned_name)

                    consolidated_utts = consolidate_utterance_dicts(cached.get("utterances", []), max_gap_seconds=3.0)
                    cached_segments = []
                    for u in consolidated_utts:
                        spk_tag = u.get("speaker_tag", "")
                        spk_info = speaker_id_map.get(spk_tag)
                        spk_id = spk_info[0] if spk_info else None
                        spk_name = spk_info[1] if spk_info else (u.get("speaker_name") or spk_tag)

                        seg = TranscriptSegmentModel(
                            session_id=session.id,
                            speaker_id=spk_id,
                            speaker_tag=spk_tag,
                            speaker_name=spk_name,
                            start_time=float(u.get("start_time", 0.0)),
                            end_time=float(u.get("end_time", 0.0)),
                            text=u.get("text", ""),
                            confidence=float(u.get("confidence", 0.95)),
                            is_flagged=bool(u.get("is_flagged", False))
                        )
                        db.add(seg)
                        cached_segments.append({
                            "start_time": seg.start_time,
                            "end_time": seg.end_time,
                            "text": seg.text
                        })

                    # Run Acoustic Layer
                    await self._run_acoustic_and_audio_llm_layer(
                        session=session,
                        file_hash=file_hash,
                        segments_data=cached_segments,
                        db=db
                    )

                    session.status = "ready_for_tagging"
                    session.progress_percent = 70
                    session.status_message = "הנתונים נטענו מהמטמון בהצלחה! יש לתייג את שמות הדוברים ולהגדיר את הילד במוקד."
                    await db.commit()
                    return

                # 3. Downsample to 16kHz mono 32k MP3 for lightning-fast STT upload
                optimized_path = str(settings.processed_dir / f"{session.id}_optimized.mp3")
                session.progress_percent = 30
                session.status_message = "ממטב שמע ל-16kHz ומסנן רעשים..."
                await db.commit()

                await audio_service.optimize_audio(session.raw_file_path, optimized_path)
                session.optimized_file_path = optimized_path
                await db.commit()

                # 4. Transcribe and diarize audio
                session.status = "transcribing"
                session.progress_percent = 45
                session.status_message = "מבצע תמלול וזיהוי דוברים בעברית..."
                await db.commit()

                async def on_stt_progress(current_chunk: int, total_chunks: int, msg: str):
                    try:
                        async with AsyncSessionLocal() as p_db:
                            p_sess = await p_db.get(SessionModel, session_id)
                            if p_sess:
                                pct = 45 + int((current_chunk / max(1, total_chunks)) * 14)
                                p_sess.progress_percent = min(59, pct)
                                p_sess.status_message = msg
                                await p_db.commit()
                    except Exception as pe:
                        logger.warning(f"Error in STT progress callback: {pe}")

                provider = get_stt_provider(session.stt_provider, model=session.stt_model)
                stt_result = await provider.transcribe(
                    optimized_path,
                    session.duration_seconds,
                    progress_callback=on_stt_progress,
                    context_metadata=session.context_metadata
                )

                # 5. Save speaker clusters and extract snippets
                session.progress_percent = 60
                session.status_message = "מפיק דגימות קול מבודדות לכל דובר..."
                await db.commit()

                speaker_id_map = {}
                for idx, spk in enumerate(stt_result.speakers):
                    speaker_num = idx + 1
                    assigned_name = f"דובר {speaker_num}"
                    role = f"דובר {speaker_num}"

                    # Extract 5-10s sample snippet for user verification
                    snippet_filename = f"{session.id}_spk_{spk.speaker_tag}.mp3"
                    snippet_path = str(settings.snippet_dir / snippet_filename)
                    snippet_url = f"/api/audio/snippet/{session.id}/{spk.speaker_tag}"

                    try:
                        await audio_service.extract_snippet(
                            optimized_path,
                            spk.sample_start_time,
                            spk.sample_duration,
                            snippet_path
                        )
                    except Exception as e:
                        logger.warning(f"Could not extract snippet for {spk.speaker_tag}: {e}")
                        snippet_path = None
                        snippet_url = None

                    speaker_model = SpeakerModel(
                        session_id=session.id,
                        diarization_tag=spk.speaker_tag,
                        assigned_name=assigned_name,
                        role=role,
                        is_child_in_focus=False,
                        total_speech_seconds=spk.total_speech_seconds,
                        utterance_count=spk.utterance_count,
                        sample_snippet_path=snippet_path,
                        sample_snippet_url=snippet_url
                    )
                    db.add(speaker_model)
                    await db.flush()
                    speaker_id_map[spk.speaker_tag] = (speaker_model.id, assigned_name)

                # 6. Save transcript segments
                created_segments = []
                for u in stt_result.utterances:
                    spk_info = speaker_id_map.get(u.speaker_tag)
                    spk_id = spk_info[0] if spk_info else None
                    spk_name = spk_info[1] if spk_info else u.speaker_tag

                    seg = TranscriptSegmentModel(
                        session_id=session.id,
                        speaker_id=spk_id,
                        speaker_tag=u.speaker_tag,
                        speaker_name=spk_name,
                        start_time=u.start_time,
                        end_time=u.end_time,
                        text=u.text,
                        confidence=u.confidence,
                        is_flagged=False
                    )
                    db.add(seg)
                    created_segments.append({
                        "start_time": u.start_time,
                        "end_time": u.end_time,
                        "text": u.text
                    })

                # Save to persistent STT cache for instant future reruns
                try:
                    speakers_cache = [
                        {
                            "diarization_tag": spk.speaker_tag,
                            "assigned_name": speaker_id_map.get(spk.speaker_tag, (None, f"דובר {idx+1}"))[1],
                            "role": f"דובר {idx+1}",
                            "is_child_in_focus": False,
                            "total_speech_seconds": spk.total_speech_seconds,
                            "utterance_count": spk.utterance_count,
                            "sample_snippet_url": f"/api/audio/snippet/{session.id}/{spk.speaker_tag}"
                        }
                        for idx, spk in enumerate(stt_result.speakers)
                    ]
                    utterances_cache = [
                        {
                            "speaker_tag": u.speaker_tag,
                            "speaker_name": speaker_id_map.get(u.speaker_tag, (None, u.speaker_tag))[1],
                            "start_time": u.start_time,
                            "end_time": u.end_time,
                            "text": u.text,
                            "confidence": u.confidence,
                            "is_flagged": False
                        }
                        for u in stt_result.utterances
                    ]
                    cache_service.save_stt_cache(
                        file_hash=file_hash,
                        source_filename=session.source_filename,
                        duration_seconds=session.duration_seconds,
                        file_size_bytes=session.file_size_bytes,
                        stt_provider=session.stt_provider,
                        stt_model=session.stt_model,
                        speakers=speakers_cache,
                        utterances=utterances_cache
                    )
                except Exception as ce:
                    logger.warning(f"Error saving STT cache: {ce}")

                # 7. Run Acoustic Layer & Audio LLM
                await self._run_acoustic_and_audio_llm_layer(
                    session=session,
                    file_hash=file_hash,
                    segments_data=created_segments,
                    db=db
                )

                # 8. Update session status to ready_for_tagging
                session.status = "ready_for_tagging"
                session.progress_percent = 70
                session.status_message = "העיבוד הראשוני והניתוח האקוסטי הסתיימו. יש לתייג את שמות הדוברים ולהגדיר את הילד במוקד."
                await db.commit()

            except Exception as e:
                logger.error(f"Error processing session {session_id}: {e}", exc_info=True)
                session.status = "failed"
                session.error_message = str(e)
                session.status_message = f"שגיאה בעיבוד: {e}"
                await db.commit()

    async def _run_acoustic_and_audio_llm_layer(
        self,
        session: SessionModel,
        file_hash: Optional[str],
        segments_data: List[Dict[str, Any]],
        db: AsyncSession
    ):
        """
        Runs acoustic loudness & cry-band profiling, un-transcribed gap analysis,
        and audio-native LLM (Gemini) listening on top candidate distress windows.
        Persists detected events to the AudioEventModel table.
        """
        if not settings.ENABLE_ACOUSTIC_ANALYSIS:
            return

        try:
            audio_path = session.optimized_file_path or session.raw_file_path
            if not audio_path or not os.path.exists(audio_path):
                return

            session.status_message = "מנתח פרופיל אקוסטי, זיהוי בכי ופערי תמלול..."
            session.progress_percent = 65
            await db.commit()

            acoustic_res = await acoustic_service.analyze_audio(
                audio_path=audio_path,
                duration_seconds=session.duration_seconds,
                transcript_segments=segments_data,
                file_hash=file_hash
            )

            # Audio-native LLM inspection on candidate windows (concurrent batching)
            if settings.ENABLE_AUDIO_LLM_ANALYSIS and (settings.OPENROUTER_API_KEY or settings.GEMINI_API_KEY):
                windows = acoustic_res.candidate_windows
                if windows:
                    logger.info(f"Analyzing {len(windows)} candidate audio windows concurrently with {settings.AUDIO_LLM_MODEL}")
                    sem = asyncio.Semaphore(4)

                    async def analyze_win(win):
                        async with sem:
                            try:
                                return await audio_analyst.analyze_candidate_window(
                                    audio_path=audio_path,
                                    start_seconds=win["start_seconds"],
                                    duration_seconds=win["duration_seconds"],
                                    target_child_name=session.target_child_name,
                                    focus_prompt=session.focus_prompt
                                )
                            except Exception as le:
                                logger.warning(f"Audio LLM candidate window analysis failed for {win['start_seconds']}s: {le}")
                                return []

                    results = await asyncio.gather(*[analyze_win(w) for w in windows])
                    for llm_events in results:
                        if llm_events:
                            acoustic_res.events.extend(llm_events)

            # Persist AudioEventModel records
            for ev in acoustic_res.events:
                db_event = AudioEventModel(
                    session_id=session.id,
                    event_type=ev.event_type,
                    start_time=ev.start_time,
                    end_time=ev.end_time,
                    peak_score=ev.peak_score,
                    mean_db=ev.mean_db,
                    source=ev.source,
                    intensity=ev.intensity,
                    description=ev.description,
                    adult_response=ev.adult_response,
                    quotes_json=json.dumps(ev.quotes, ensure_ascii=False) if ev.quotes else None
                )
                db.add(db_event)
            await db.flush()
        except Exception as e:
            logger.warning(f"Error in acoustic layer for session {session.id}: {e}", exc_info=True)

    async def generate_final_report(self, session_id: str):
        """
        Background task:
        1. Maps speaker names to segments
        2. Retrieves audio events & coverage data
        3. Generates pedagogical Hebrew report (Map-Reduce & deterministic markdown)
        4. Persists report and marks session completed
        """
        async with AsyncSessionLocal() as db:
            session = await db.get(SessionModel, session_id)
            if not session:
                return

            try:
                session.status = "generating_report"
                session.progress_percent = 80
                session.status_message = "מנתח את מהלך היום ומפיק דוח פדגוגי בעברית..."
                await db.commit()

                # Fetch all speakers
                spk_query = select(SpeakerModel).where(SpeakerModel.session_id == session.id)
                speakers = (await db.execute(spk_query)).scalars().all()
                speakers_data = [
                    {
                        "diarization_tag": s.diarization_tag,
                        "assigned_name": s.assigned_name,
                        "role": s.role,
                        "is_child_in_focus": s.is_child_in_focus
                    }
                    for s in speakers
                ]

                # Fetch all segments
                seg_query = select(TranscriptSegmentModel).where(
                    TranscriptSegmentModel.session_id == session.id
                ).order_by(TranscriptSegmentModel.start_time.asc())
                segments = (await db.execute(seg_query)).scalars().all()
                segments_data = [
                    {
                        "start_time": seg.start_time,
                        "end_time": seg.end_time,
                        "speaker_name": seg.speaker_name,
                        "text": seg.text
                    }
                    for seg in segments
                ]

                # Fetch all audio events
                ev_query = select(AudioEventModel).where(
                    AudioEventModel.session_id == session.id
                ).order_by(AudioEventModel.start_time.asc())
                audio_events_db = (await db.execute(ev_query)).scalars().all()
                audio_events_data = [
                    {
                        "event_type": e.event_type,
                        "start_time": e.start_time,
                        "end_time": e.end_time,
                        "intensity": e.intensity,
                        "description": e.description,
                        "adult_response": e.adult_response,
                        "quotes": json.loads(e.quotes_json) if e.quotes_json else []
                    }
                    for e in audio_events_db
                ]

                # Fetch coverage info
                acoustic_res = await acoustic_service.analyze_audio(
                    audio_path=session.optimized_file_path or session.raw_file_path,
                    duration_seconds=session.duration_seconds,
                    transcript_segments=segments_data,
                    file_hash=None
                )
                coverage_info = {
                    "coverage_percent": acoustic_res.coverage_percent,
                    "transcribed_seconds": acoustic_res.transcribed_seconds,
                    "gaps": [
                        {
                            "start_seconds": g.start_seconds,
                            "end_seconds": g.end_seconds,
                            "duration_seconds": g.duration_seconds,
                            "start_formatted": g.start_formatted,
                            "end_formatted": g.end_formatted,
                            "mean_db": g.mean_db,
                            "note": g.note
                        }
                        for g in acoustic_res.gaps
                    ]
                }

                # Generate report
                session.progress_percent = 90
                session.status_message = "מגבש תובנות, ציר זמן כרונולוגי ונורות אזהרה..."
                await db.commit()

                report_data = await llm_report_service.generate_report(
                    child_name=session.target_child_name,
                    focus_prompt=session.focus_prompt,
                    speakers=speakers_data,
                    segments=segments_data,
                    audio_events=audio_events_data,
                    coverage_info=coverage_info,
                    total_duration_seconds=session.duration_seconds,
                    context_metadata=session.context_metadata
                )

                # Persist DailyReportModel (Upsert)
                rep_stmt = select(DailyReportModel).where(DailyReportModel.session_id == session.id)
                report_model = (await db.execute(rep_stmt)).scalar_one_or_none()

                if report_model:
                    report_model.executive_summary = report_data.get("executive_summary", "")
                    report_model.focus_inquiry_response = report_data.get("focus_inquiry_response", "")
                    report_model.timeline_json = json.dumps(report_data.get("timeline", []), ensure_ascii=False)
                    report_model.emotional_analysis = report_data.get("emotional_analysis", "")
                    report_model.staff_evaluation = report_data.get("staff_evaluation", "")
                    report_model.red_flags_json = json.dumps(report_data.get("red_flags", []), ensure_ascii=False)
                    report_model.recommendations = report_data.get("recommendations", "")
                    report_model.full_markdown = report_data.get("full_markdown", "")
                    report_model.coverage_percent = report_data.get("coverage_percent", 0.0)
                    report_model.transcribed_seconds = report_data.get("transcribed_seconds", 0.0)
                    report_model.coverage_gaps_json = report_data.get("coverage_gaps_json")
                    report_model.audio_events_summary = report_data.get("audio_events_summary")
                else:
                    report_model = DailyReportModel(
                        session_id=session.id,
                        executive_summary=report_data.get("executive_summary", ""),
                        focus_inquiry_response=report_data.get("focus_inquiry_response", ""),
                        timeline_json=json.dumps(report_data.get("timeline", []), ensure_ascii=False),
                        emotional_analysis=report_data.get("emotional_analysis", ""),
                        staff_evaluation=report_data.get("staff_evaluation", ""),
                        red_flags_json=json.dumps(report_data.get("red_flags", []), ensure_ascii=False),
                        recommendations=report_data.get("recommendations", ""),
                        full_markdown=report_data.get("full_markdown", ""),
                        coverage_percent=report_data.get("coverage_percent", 0.0),
                        transcribed_seconds=report_data.get("transcribed_seconds", 0.0),
                        coverage_gaps_json=report_data.get("coverage_gaps_json"),
                        audio_events_summary=report_data.get("audio_events_summary")
                    )
                    db.add(report_model)

                session.status = "completed"
                session.progress_percent = 100
                session.status_message = "הניתוח הושלם בהצלחה!"
                await db.commit()

            except Exception as e:
                logger.error(f"Error generating report for session {session_id}: {e}", exc_info=True)
                session.status = "failed"
                session.error_message = str(e)
                session.status_message = f"שגיאה בהפקת הדוח: {e}"
                await db.commit()


job_pipeline = JobPipeline()
