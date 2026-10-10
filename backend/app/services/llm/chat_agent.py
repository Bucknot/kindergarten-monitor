import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
import httpx
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.models import SessionModel, SpeakerModel, TranscriptSegmentModel, DailyReportModel, AudioEventModel
from backend.app.schemas import ChatMessage, ChatToolExecution, ChatCitation, ChatResponse
from backend.app.services.llm.audio_analyst import audio_analyst

logger = logging.getLogger(__name__)


def format_seconds_to_hms(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def parse_hms_to_seconds(hms_str: str) -> float:
    parts = hms_str.replace("[", "").replace("]", "").strip().split(":")
    if len(parts) == 3:
        return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
    elif len(parts) == 2:
        return float(int(parts[0]) * 60 + int(parts[1]))
    return 0.0


AGENT_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_transcription",
            "description": "מחפש מילות מפתח או ביטויים בתוך תמליל ההקלטה המלא של כל שעות היום בגן. מחזיר מקטעים תואמים עם חותמות זמן מדויקות, שמות הדוברים והטקסט שנאמר.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "מילת חיפוש או ביטוי בעברית (לדוגמה: 'בכי', 'אוכל', 'חצר', 'אסור', 'חיבוק', 'אמא')"
                    },
                    "speaker_name": {
                        "type": "string",
                        "description": "שם דובר ספציפי לסינון (אופציונלי, למשל: 'אדם', 'גננת מיכל')"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_audio_events",
            "description": "שולף אירועים אקוסטיים וקוליים שזוהו ישירות מקובץ השמע (בכי, צעקות, מצוקה, ניסיונות הרגעה, רעש חריג, פערי תמלול). חיוני ביותר למענה על שאלות כגון 'האם הילד בכה?', 'מתי היו צעקות?', 'מי הרגיע?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": ["all", "crying", "screaming", "shouting", "laughing", "loud_span", "speech_gap", "soothing"],
                        "description": "סוג האירוע לסינון (ברירת מחדל 'all')"
                    },
                    "start_seconds": {
                        "type": "number",
                        "description": "זמן התחלה בשניות לסינון טווח (אופציונלי)"
                    },
                    "end_seconds": {
                        "type": "number",
                        "description": "זמן סיום בשניות לסינון טווח (אופציונלי)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "listen_to_clip",
            "description": "מאזין ישירות לקטע שמע מההקלטה באמצעות מודל שמע רב-מודאלי (Gemini) ומשיב על שאלתך בהתבסס על מה שנשמע בקול (טון דיבור, בכי, צחוק, רעשי רקע).",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_seconds": {
                        "type": "number",
                        "description": "שניות מתחילת ההקלטה לתחילת הקטע"
                    },
                    "end_seconds": {
                        "type": "number",
                        "description": "שניות מתחילת ההקלטה לסיום הקטע (עד 90 שניות)"
                    },
                    "question": {
                        "type": "string",
                        "description": "שאלה ספציפית לגבי מה שנשמע בקטע"
                    }
                },
                "required": ["start_seconds", "end_seconds", "question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_coverage_summary",
            "description": "מחזיר נתוני כיסוי תמלול של ההקלטה: אחוז הזמן שתומלל, סך שעות הדיבור, ורשימת פערי תמלול ממושכים (>60 שנ') המעידים על שקט או רעש ללא דיבור מזוהה.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_context_around_time",
            "description": "שולף את מהלך השיחה המלא והרציף (דיאלוג לפני ואחרי) סביב חותמת זמן מסוימת בשניות. שימושי ביותר להבנת ההקשר המלא של אירוע, מה הוביל אליו ואיך הצוות הגיב.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timestamp_seconds": {
                        "type": "number",
                        "description": "נקודת הזמן בשניות מתחילת ההקלטה (למשל: 3600 לשעה 01:00:00)"
                    },
                    "window_seconds": {
                        "type": "number",
                        "description": "רוחב חלון הזמן בשניות לקריאה (ברירת מחדל: 120 שניות, 60 שניות לפני ו-60 שניות אחרי)"
                    }
                },
                "required": ["timestamp_seconds"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_report_section",
            "description": "שולף פרק ספציפי מתוך הדוח הפדגוגי המקיף שהופק על יום זה (נורות אזהרה, הערכת צוות, ניתוח רגשי, ציר זמנים, סיכום מנהלים, המלצות).",
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": ["summary", "focus", "timeline", "emotional_analysis", "staff_evaluation", "red_flags", "recommendations", "all"],
                        "description": "שם הפרק המבוקש מתוך הדוח"
                    }
                },
                "required": ["section"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_speakers",
            "description": "מחזיר את רשימת כל הדוברים שזוהו ותויגו בהקלטה, תפקידם (גננת, סייעת, ילד), זמני הדיבור שלהם ומי הילד במוקד.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


class ChatAgentService:
    async def execute_tool(
        self,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Executes a specific tool against the database for the given session."""
        if tool_name == "search_transcription":
            query = tool_args.get("query", "").strip()
            speaker_name = tool_args.get("speaker_name", "").strip()
            return await self._tool_search_transcription(session_id, query, speaker_name, db)

        elif tool_name == "get_context_around_time":
            ts = float(tool_args.get("timestamp_seconds", 0.0))
            window = float(tool_args.get("window_seconds", 120.0))
            return await self._tool_get_context_around_time(session_id, ts, window, db)

        elif tool_name == "get_audio_events":
            ev_type = tool_args.get("event_type", "all")
            st = tool_args.get("start_seconds")
            et = tool_args.get("end_seconds")
            return await self._tool_get_audio_events(session_id, ev_type, st, et, db)

        elif tool_name == "listen_to_clip":
            st = float(tool_args.get("start_seconds", 0.0))
            et = float(tool_args.get("end_seconds", st + 30.0))
            q = tool_args.get("question", "")
            return await self._tool_listen_to_clip(session_id, st, et, q, db)

        elif tool_name == "get_coverage_summary":
            return await self._tool_get_coverage_summary(session_id, db)

        elif tool_name == "get_report_section":
            section = tool_args.get("section", "all").strip().lower()
            return await self._tool_get_report_section(session_id, section, db)

        elif tool_name == "get_session_speakers":
            return await self._tool_get_session_speakers(session_id, db)

        return {"error": f"Tool '{tool_name}' is not recognized"}

    async def _tool_search_transcription(
        self,
        session_id: str,
        query: str,
        speaker_name: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        if not query:
            return {"results": [], "count": 0, "message": "שאילתת חיפוש ריקה"}

        # Search direct query
        search_pattern = f"%{query}%"
        stmt = select(TranscriptSegmentModel).where(
            TranscriptSegmentModel.session_id == session_id,
            TranscriptSegmentModel.text.ilike(search_pattern)
        )
        if speaker_name:
            stmt = stmt.where(TranscriptSegmentModel.speaker_name.ilike(f"%{speaker_name}%"))

        stmt = stmt.order_by(TranscriptSegmentModel.start_time.asc()).limit(15)
        res = await db.execute(stmt)
        segments = res.scalars().all()

        # If few results and multi-word query, split words
        if len(segments) < 3 and " " in query:
            words = [w.strip() for w in query.split() if len(w.strip()) >= 2]
            if words:
                or_clauses = [TranscriptSegmentModel.text.ilike(f"%{w}%") for w in words]
                stmt_split = select(TranscriptSegmentModel).where(
                    TranscriptSegmentModel.session_id == session_id,
                    or_(*or_clauses)
                )
                if speaker_name:
                    stmt_split = stmt_split.where(TranscriptSegmentModel.speaker_name.ilike(f"%{speaker_name}%"))
                stmt_split = stmt_split.order_by(TranscriptSegmentModel.start_time.asc()).limit(15)
                res_split = await db.execute(stmt_split)
                segments = res_split.scalars().all()

        results = []
        for s in segments:
            results.append({
                "timestamp": format_seconds_to_hms(s.start_time),
                "timestamp_seconds": round(s.start_time, 1),
                "speaker": s.speaker_name,
                "text": s.text
            })

        return {
            "query": query,
            "speaker_filter": speaker_name or None,
            "count": len(results),
            "results": results
        }

    async def _tool_get_context_around_time(
        self,
        session_id: str,
        timestamp_seconds: float,
        window_seconds: float,
        db: AsyncSession
    ) -> Dict[str, Any]:
        half = window_seconds / 2.0
        start = max(0.0, timestamp_seconds - half)
        end = timestamp_seconds + half

        stmt = select(TranscriptSegmentModel).where(
            TranscriptSegmentModel.session_id == session_id,
            TranscriptSegmentModel.start_time >= start,
            TranscriptSegmentModel.start_time <= end
        ).order_by(TranscriptSegmentModel.start_time.asc())

        res = await db.execute(stmt)
        segments = res.scalars().all()

        dialogue_lines = []
        for s in segments:
            hms = format_seconds_to_hms(s.start_time)
            dialogue_lines.append(f"[{hms}] {s.speaker_name}: {s.text}")

        return {
            "center_timestamp": format_seconds_to_hms(timestamp_seconds),
            "window_range": f"{format_seconds_to_hms(start)} - {format_seconds_to_hms(end)}",
            "dialogue_count": len(dialogue_lines),
            "dialogue": dialogue_lines
        }

    async def _tool_get_report_section(
        self,
        session_id: str,
        section: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        stmt = select(DailyReportModel).where(DailyReportModel.session_id == session_id)
        res = await db.execute(stmt)
        report = res.scalar_one_or_none()
        if not report:
            return {"error": "טרם הופק דוח פדגוגי עבור הקלטה זו. יש להפיק דוח תחילה."}

        mapping = {
            "summary": report.executive_summary,
            "focus": report.focus_inquiry_response or "לא הוגדרה שאלת מיקוד ספציפית.",
            "timeline": report.timeline_json or "אין נתוני ציר זמן.",
            "emotional_analysis": report.emotional_analysis,
            "staff_evaluation": report.staff_evaluation,
            "red_flags": report.red_flags_json or "אין נורות אזהרה שנמצאו.",
            "recommendations": report.recommendations,
            "all": report.full_markdown
        }

        content = mapping.get(section, report.full_markdown)
        return {
            "section": section,
            "content": content
        }

    async def _tool_get_session_speakers(
        self,
        session_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        stmt = select(SpeakerModel).where(SpeakerModel.session_id == session_id).order_by(SpeakerModel.total_speech_seconds.desc())
        res = await db.execute(stmt)
        speakers = res.scalars().all()

        speaker_list = []
        for s in speakers:
            speaker_list.append({
                "tag": s.diarization_tag,
                "assigned_name": s.assigned_name,
                "role": s.role,
                "is_child_in_focus": s.is_child_in_focus,
                "speech_seconds": round(s.total_speech_seconds, 1),
                "speech_minutes": round(s.total_speech_seconds / 60.0, 1),
                "utterances": s.utterance_count
            })

        return {"speakers": speaker_list, "total_speakers": len(speaker_list)}

    async def _tool_get_audio_events(
        self,
        session_id: str,
        event_type: str,
        start_seconds: Optional[float],
        end_seconds: Optional[float],
        db: AsyncSession
    ) -> Dict[str, Any]:
        stmt = select(AudioEventModel).where(AudioEventModel.session_id == session_id)
        if event_type and event_type != "all":
            stmt = stmt.where(AudioEventModel.event_type == event_type)
        if start_seconds is not None:
            stmt = stmt.where(AudioEventModel.end_time >= float(start_seconds))
        if end_seconds is not None:
            stmt = stmt.where(AudioEventModel.start_time <= float(end_seconds))

        stmt = stmt.order_by(AudioEventModel.start_time.asc())
        res = await db.execute(stmt)
        events = res.scalars().all()

        results = []
        for e in events:
            results.append({
                "timestamp": format_seconds_to_hms(e.start_time),
                "timestamp_end": format_seconds_to_hms(e.end_time),
                "start_seconds": e.start_time,
                "end_seconds": e.end_time,
                "event_type": e.event_type,
                "intensity": e.intensity,
                "description": e.description,
                "adult_response": e.adult_response,
                "source": e.source
            })
        return {
            "total_events": len(results),
            "filter_type": event_type,
            "events": results
        }

    async def _tool_listen_to_clip(
        self,
        session_id: str,
        start_seconds: float,
        end_seconds: float,
        question: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        session = await db.get(SessionModel, session_id)
        if not session:
            return {"error": "Session not found"}
        audio_file = session.optimized_file_path or session.raw_file_path
        if not audio_file or not os.path.exists(audio_file):
            return {"error": "קובץ השמע אינו זמין בדיסק להאזנה ישירה."}

        ans = await audio_analyst.listen_to_clip(
            audio_path=audio_file,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            question=question
        )
        return {
            "clip_range": f"{format_seconds_to_hms(start_seconds)} - {format_seconds_to_hms(end_seconds)}",
            "question": question,
            "hearing_result": ans
        }

    async def _tool_get_coverage_summary(
        self,
        session_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        session = await db.get(SessionModel, session_id)
        if not session:
            return {"error": "Session not found"}
        stmt = select(DailyReportModel).where(DailyReportModel.session_id == session_id)
        report = (await db.execute(stmt)).scalar_one_or_none()
        cov_pct = report.coverage_percent if report else 0.0
        trans_sec = report.transcribed_seconds if report else 0.0
        gaps = json.loads(report.coverage_gaps_json) if (report and report.coverage_gaps_json) else []

        return {
            "total_duration": format_seconds_to_hms(session.duration_seconds),
            "transcribed_duration": format_seconds_to_hms(trans_sec),
            "coverage_percent": cov_pct,
            "gaps_count": len(gaps),
            "gaps": gaps[:8]
        }

    async def chat(
        self,
        session_id: str,
        user_message: str,
        history: List[ChatMessage],
        db: AsyncSession,
        openrouter_api_key: Optional[str] = None,
        openrouter_model: Optional[str] = None
    ) -> ChatResponse:
        """
        Runs the full agentic loop:
        1. Prepares system prompt with session context.
        2. Calls OpenRouter with function tools.
        3. Loops up to 4 times while tool_calls are requested.
        4. Synthesizes a factual, empathetic Hebrew answer with timestamps.
        5. Extracts citations.
        """
        session = await db.get(SessionModel, session_id)
        if not session:
            return ChatResponse(reply="שגיאה: הקלטה זו לא נמצאה במערכת.", tool_executions=[], citations=[])

        api_key = openrouter_api_key or settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY
        chosen_model = openrouter_model or settings.OPENROUTER_MODEL or "google/gemini-2.5-flash"

        system_prompt = f"""אתה סוכן AI מומחה לניתוח פדגוגי ואקוסטי של שמע והתנהלות בגן ילדים ("גן מוניטור").
אתה עונה על שאלות הורים ואנשי חינוך לגבי ההקלטה: "{session.title}" (קובץ: {session.source_filename}, משך זמן כולל: {format_seconds_to_hms(session.duration_seconds)}).
שם הילד/ה במוקד: {session.target_child_name or 'לא הוגדר'}.

לרשותך כלים מתקדמים:
1. `get_audio_events(event_type)` - בדיקת אירועים אקוסטיים (בכי, צעקות, מצוקה, הרגעה) ישירות מהאודיו! חובה להשתמש בו כששואלים "האם הוא בכה?", "מתי הוא בכה?", "היו צעקות?" כי מודלי תמלול רגילים משמיטים בכי.
2. `listen_to_clip(start_seconds, end_seconds, question)` - מאזין ישירות לשמע באמצעות מודל שמע Gemini ומשיב על בסיס הטון, הניואנסים והבכי האמיתיים!
3. `get_coverage_summary()` - בדיקת כיסוי התמלול ופערי שקט/רעש ללא תמלול לאורך היום.
4. `search_transcription(query)` - חיפוש מילות מפתח בתמליל הדיבור (חצר, אוכל, חיבוק, אסור, אמא).
5. `get_context_around_time(timestamp_seconds)` - קריאת דיאלוג מלא סביב חותמת זמן.
6. `get_report_section(section)` - קריאת פרקי הדוח הפדגוגי (red_flags, emotional_analysis, staff_evaluation, timeline, summary, recommendations).
7. `get_session_speakers()` - בדיקת רשימת הדוברים והתפקידים.

הנחיות חובה:
- בסס תמיד את התשובה על עובדות אמיתיות מההקלטה והדוח באמצעות הכלים. אל תנחש.
- אם ההורה שואל על בכי או מצוקה, התחל תמיד ב-`get_audio_events(event_type='crying')`!
- ציין תמיד חותמות זמן של ההקלטה בפורמט [HH:MM:SS] (למשל [00:47:20]) כדי שהמשתמש יוכל להקליק ולהאזין.
- ענה בעברית רהוטה, אמפתית, בהירה ומקצועית.
"""

        tool_executions: List[ChatToolExecution] = []

        # If no external API key is available, run smart local retrieval fallback
        if not api_key:
            return await self._run_smart_local_retrieval(session, user_message, db)

        # Build messages for LLM
        messages = [{"role": "system", "content": system_prompt}]
        for h in history[-8:]:  # keep last 8 turns
            messages.append({"role": h.role, "content": h.content})
        messages.append({"role": "user", "content": user_message})

        candidate_models = [chosen_model]
        for fallback in ["qwen/qwen-2.5-72b-instruct", "meta-llama/llama-3.3-70b-instruct"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        max_loops = 4
        final_reply = ""

        try:
            for loop_idx in range(max_loops):
                call_res = await self._call_llm_with_tools(
                    api_key=api_key,
                    models=candidate_models,
                    messages=messages,
                    tools=AGENT_TOOLS_SCHEMA
                )

                if not call_res:
                    break

                message_obj = call_res.get("message", {})
                tool_calls = message_obj.get("tool_calls")
                content = message_obj.get("content")

                if tool_calls:
                    # Append assistant's tool-call request to messages
                    messages.append(message_obj)

                    for tc in tool_calls:
                        func_info = tc.get("function", {})
                        t_name = func_info.get("name", "")
                        t_call_id = tc.get("id", f"call_{loop_idx}")
                        try:
                            t_args = json.loads(func_info.get("arguments", "{}"))
                        except Exception:
                            t_args = {}

                        logger.info(f"[Agent Loop {loop_idx}] Calling tool {t_name} with args {t_args}")
                        tool_output = await self.execute_tool(session_id, t_name, t_args, db)

                        # Create human summary for UI
                        summary = self._summarize_tool_execution(t_name, t_args, tool_output)
                        tool_executions.append(ChatToolExecution(
                            tool=t_name,
                            args=t_args,
                            summary=summary
                        ))

                        # Append tool response
                        messages.append({
                            "role": "tool",
                            "tool_call_id": t_call_id,
                            "name": t_name,
                            "content": json.dumps(tool_output, ensure_ascii=False)
                        })
                else:
                    final_reply = content or ""
                    break

            if not final_reply and messages:
                # Last ditch check if content was provided in earlier turn
                last_msg = messages[-1]
                if last_msg.get("role") == "assistant" and last_msg.get("content"):
                    final_reply = last_msg.get("content")

        except Exception as e:
            logger.error(f"Error in chat agent loop: {e}", exc_info=True)
            return await self._run_smart_local_retrieval(session, user_message, db, error_notice=str(e))

        if not final_reply:
            final_reply = "לא הצלחתי למצוא מידע מספק בתמליל או בדוח עבור שאלה זו. אנא נסה לשאול מחדש בניסוח אחר."

        # Extract citations
        citations = await self._extract_citations_from_reply(session_id, final_reply, db)

        return ChatResponse(
            reply=final_reply,
            tool_executions=tool_executions,
            citations=citations
        )

    async def _call_llm_with_tools(
        self,
        api_key: str,
        models: List[str],
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://kindergarten-monitor.local",
            "X-Title": "Kindergarten Monitor",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            for model_name in models:
                payload = {
                    "model": model_name,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "max_tokens": 2048,
                    "temperature": 0.2
                }
                try:
                    res = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=payload
                    )
                    if res.status_code == 200:
                        data = res.json()
                        choices = data.get("choices", [])
                        if choices:
                            return choices[0]
                    else:
                        logger.warning(f"OpenRouter model {model_name} failed with status {res.status_code}: {res.text[:200]}")
                except Exception as e:
                    logger.warning(f"Error calling {model_name}: {e}")

        return None

    def _summarize_tool_execution(self, tool_name: str, args: Dict[str, Any], output: Dict[str, Any]) -> str:
        if tool_name == "search_transcription":
            q = args.get("query", "")
            cnt = output.get("count", 0)
            return f"חיפש בתמליל: \"{q}\" (נמצאו {cnt} תוצאות)"
        elif tool_name == "get_context_around_time":
            ts = args.get("timestamp_seconds", 0)
            hms = format_seconds_to_hms(ts)
            cnt = output.get("dialogue_count", 0)
            return f"שלף מהלך שיחה מלא סביב {hms} ({cnt} שורות דיאלוג)"
        elif tool_name == "get_report_section":
            sec = args.get("section", "all")
            return f"קרא פרק מהדוח הפדגוגי: {sec}"
        elif tool_name == "get_session_speakers":
            cnt = output.get("total_speakers", 0)
            return f"בדק רשימת דוברים ותפקידים ({cnt} דוברים זוהו)"
        return f"הפעיל כלי {tool_name}"

    async def _extract_citations_from_reply(
        self,
        session_id: str,
        text: str,
        db: AsyncSession
    ) -> List[ChatCitation]:
        citations = []
        # Find timestamps in format [HH:MM:SS] or HH:MM:SS
        matches = re.findall(r"\[?(\d{1,2}:\d{2}:\d{2})\]?", text)
        seen_seconds = set()

        for hms in matches:
            secs = parse_hms_to_seconds(hms)
            if secs in seen_seconds:
                continue
            seen_seconds.add(secs)

            # Find closest segment within +/- 15 seconds
            stmt = select(TranscriptSegmentModel).where(
                TranscriptSegmentModel.session_id == session_id,
                TranscriptSegmentModel.start_time >= max(0.0, secs - 15.0),
                TranscriptSegmentModel.start_time <= secs + 15.0
            ).order_by(func.abs(TranscriptSegmentModel.start_time - secs)).limit(1)

            res = await db.execute(stmt)
            seg = res.scalar_one_or_none()
            if seg:
                citations.append(ChatCitation(
                    timestamp_seconds=seg.start_time,
                    timestamp_formatted=format_seconds_to_hms(seg.start_time),
                    speaker_name=seg.speaker_name,
                    text=seg.text
                ))
            else:
                citations.append(ChatCitation(
                    timestamp_seconds=secs,
                    timestamp_formatted=hms,
                    speaker_name="הקלטת יום בגן",
                    text=""
                ))

        return citations[:8]

    async def _run_smart_local_retrieval(
        self,
        session: SessionModel,
        user_message: str,
        db: AsyncSession,
        error_notice: Optional[str] = None
    ) -> ChatResponse:
        """Fallback when no external LLM API is available: keyword search + report lookup."""
        query_words = [w.strip() for w in user_message.split() if len(w.strip()) >= 2]
        matched_segments = []

        if query_words:
            clauses = [TranscriptSegmentModel.text.ilike(f"%{w}%") for w in query_words]
            stmt = select(TranscriptSegmentModel).where(
                TranscriptSegmentModel.session_id == session.id,
                or_(*clauses)
            ).order_by(TranscriptSegmentModel.start_time.asc()).limit(8)
            res = await db.execute(stmt)
            matched_segments = res.scalars().all()

        tool_execs = [
            ChatToolExecution(
                tool="search_transcription",
                args={"query": user_message},
                summary=f"חיפוש ישיר בתמליל המלא (נמצאו {len(matched_segments)} תוצאות רלוונטיות)"
            )
        ]

        # Fetch report summary
        stmt_rep = select(DailyReportModel).where(DailyReportModel.session_id == session.id)
        rep = (await db.execute(stmt_rep)).scalar_one_or_none()

        reply_parts = []
        if error_notice:
            reply_parts.append(f"> [!NOTE]\n> שירות ה-LLM החיצוני החזיר התראה ({error_notice[:100]}). המערכת שולפת ממצאים ישירים מהתמליל והדוח השמורים:\n")

        reply_parts.append(f"### ממצאים מתוך ההקלטה לגבי השאלה:")
        if matched_segments:
            reply_parts.append("\n**קטעים רלוונטיים שנמצאו בתמליל:**")
            for seg in matched_segments:
                hms = format_seconds_to_hms(seg.start_time)
                reply_parts.append(f"- `[{hms}]` **{seg.speaker_name}**: \"{seg.text}\"")
        else:
            reply_parts.append("\nלא נמצאו מילות מפתח תואמות ישירות במקטעי התמליל.")

        if rep:
            reply_parts.append(f"\n**מתוך הדוח הפדגוגי:**")
            reply_parts.append(rep.executive_summary[:500] + ("..." if len(rep.executive_summary) > 500 else ""))

        citations = [
            ChatCitation(
                timestamp_seconds=s.start_time,
                timestamp_formatted=format_seconds_to_hms(s.start_time),
                speaker_name=s.speaker_name,
                text=s.text
            )
            for s in matched_segments
        ]

        return ChatResponse(
            reply="\n".join(reply_parts),
            tool_executions=tool_execs,
            citations=citations
        )


chat_agent_service = ChatAgentService()
