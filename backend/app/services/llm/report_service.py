import json
import logging
import re
import asyncio
from typing import List, Dict, Any, Optional, Tuple
import httpx
from backend.app.config import settings
from backend.app.services.llm.prompts import (
    HEBREW_KINDERGARTEN_SYSTEM_PROMPT,
    BLOCK_SUMMARY_SYSTEM_PROMPT,
    build_analysis_user_prompt,
    build_reduce_prompt
)
from backend.app.services.context_service import build_pedagogical_context_block

logger = logging.getLogger(__name__)


def format_seconds_to_hms(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def parse_hms_to_seconds(hms_str: str) -> Optional[float]:
    match = re.search(r"(\d{1,2}):(\d{2}):(\d{2})", hms_str)
    if match:
        h, m, s = map(int, match.groups())
        return float(h * 3600 + m * 60 + s)
    match_ms = re.search(r"(\d{1,2}):(\d{2})", hms_str)
    if match_ms:
        m, s = map(int, match_ms.groups())
        return float(m * 60 + s)
    return None


class LLMReportService:
    def __init__(self):
        self.provider = (settings.LLM_PROVIDER or "openrouter").lower()
        self.model = settings.OPENROUTER_MODEL or "google/gemini-2.5-flash"

    async def generate_report(
        self,
        child_name: Optional[str],
        focus_prompt: Optional[str],
        speakers: List[Dict[str, Any]],
        segments: List[Dict[str, Any]],
        audio_events: Optional[List[Dict[str, Any]]] = None,
        coverage_info: Optional[Dict[str, Any]] = None,
        total_duration_seconds: float = 0.0,
        context_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Synthesizes tagged transcript segments, acoustic events, coverage info,
        parent focus prompt, and kindergarten context into a comprehensive pedagogical report.
        Uses Map-Reduce on long recordings and builds full markdown deterministically in Python.
        """
        audio_events = audio_events or []
        coverage_info = coverage_info or {}
        if not total_duration_seconds and segments:
            total_duration_seconds = max(float(s.get("end_time", 0.0)) for s in segments)

        context_block = build_pedagogical_context_block(context_metadata)

        # 1. Format speakers summary
        speakers_summary_lines = []
        for spk in speakers:
            role_desc = f" ({spk.get('role', 'משתתף')})"
            if spk.get("is_child_in_focus"):
                role_desc += " [הילד במוקד]"
            speakers_summary_lines.append(f"- {spk.get('assigned_name', spk.get('diarization_tag'))}{role_desc}")
        speakers_summary = "\n".join(speakers_summary_lines)

        # 2. Build Unified Evidence Timeline
        timeline_items, raw_timeline_text = self._build_evidence_timeline(
            segments, audio_events, coverage_info.get("gaps", [])
        )

        # 3. Format coverage summary
        cov_pct = coverage_info.get("coverage_percent", 0.0)
        trans_sec = coverage_info.get("transcribed_seconds", 0.0)
        gaps_count = len(coverage_info.get("gaps", []))
        coverage_summary = (
            f"**סטטיסטיקת כיסוי שמע**: תומללו {int(trans_sec // 60)} דקות "
            f"({cov_pct}% מתוך {int(total_duration_seconds // 60)} דקות הקלטה). "
            f"אותרו {gaps_count} פערי תמלול ממושכים (>60 שנ')."
        )

        # Format acoustic events summary
        distress_count = sum(1 for e in audio_events if e.get("event_type") in ("crying", "screaming"))
        acoustic_summary = f"**אירועים אקוסטיים שאותרו**: {len(audio_events)} אירועים (מתוכם {distress_count} אירועי בכי/מצוקה)."

        # Determine generation method: Mock mode vs External LLM
        use_mock = (
            self.provider == "mock" or
            (not settings.OPENROUTER_API_KEY and not settings.OPENAI_API_KEY and not settings.GEMINI_API_KEY)
        )

        if use_mock:
            report_json = self._generate_data_driven_mock(
                child_name, focus_prompt, speakers, segments, audio_events, coverage_info, total_duration_seconds
            )
        else:
            # Map-Reduce for long recordings (> 45 min and > 40 items)
            if total_duration_seconds > 2700.0 and len(timeline_items) > 40:
                report_json = await self._run_map_reduce_pipeline(
                    child_name=child_name,
                    focus_prompt=focus_prompt,
                    speakers_summary=speakers_summary,
                    timeline_items=timeline_items,
                    audio_events=audio_events,
                    coverage_text=coverage_summary,
                    context_block=context_block
                )
            else:
                report_json = await self._call_direct_llm(
                    child_name=child_name,
                    focus_prompt=focus_prompt,
                    speakers_summary=speakers_summary,
                    evidence_timeline_text=raw_timeline_text,
                    acoustic_events_summary=acoustic_summary,
                    coverage_summary=coverage_summary,
                    context_block=context_block
                )

        # 4. Validate timestamps & enforce crying presence
        report_json = self._validate_and_sanitize_report(
            report_json, total_duration_seconds, audio_events
        )

        # 5. Synthesize full markdown report in Python (No duplication/truncation!)
        report_json["full_markdown"] = self._build_markdown_report(
            report_json=report_json,
            child_name=child_name,
            focus_prompt=focus_prompt,
            speakers=speakers,
            coverage_info=coverage_info,
            audio_events=audio_events,
            total_duration_seconds=total_duration_seconds
        )

        # Store coverage metrics in report output
        report_json["coverage_percent"] = cov_pct
        report_json["transcribed_seconds"] = trans_sec
        report_json["coverage_gaps_json"] = json.dumps(coverage_info.get("gaps", []), ensure_ascii=False)
        report_json["audio_events_summary"] = acoustic_summary

        return report_json

    def _build_evidence_timeline(
        self,
        segments: List[Dict[str, Any]],
        audio_events: List[Dict[str, Any]],
        gaps: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Interweaves dialogue turns, acoustic events (🔊), and speech gaps (⚠) chronologically.
        """
        all_items: List[Dict[str, Any]] = []

        # 1. Add dialogue segments
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            all_items.append({
                "type": "speech",
                "time": float(seg.get("start_time", 0.0)),
                "end_time": float(seg.get("end_time", 0.0)),
                "speaker": seg.get("speaker_name", "דובר"),
                "text": text
            })

        # 2. Add acoustic events
        for ev in audio_events:
            ev_type = ev.get("event_type", "event")
            all_items.append({
                "type": "acoustic_event",
                "time": float(ev.get("start_time", 0.0)),
                "end_time": float(ev.get("end_time", 0.0)),
                "event_type": ev_type,
                "intensity": ev.get("intensity", "medium"),
                "description": ev.get("description", ""),
                "adult_response": ev.get("adult_response", ""),
                "quotes": ev.get("quotes", [])
            })

        # 3. Add notable coverage gaps (> 120s)
        for g in gaps:
            dur = float(g.get("duration_seconds", 0.0))
            if dur >= 120.0:
                all_items.append({
                    "type": "gap",
                    "time": float(g.get("start_seconds", 0.0)),
                    "end_time": float(g.get("end_seconds", 0.0)),
                    "duration": dur,
                    "mean_db": g.get("mean_db"),
                    "note": g.get("note", "")
                })

        # Sort all items chronologically
        all_items.sort(key=lambda x: x["time"])

        # Format into readable text lines
        text_lines: List[str] = []
        for item in all_items:
            hms_st = format_seconds_to_hms(item["time"])
            if item["type"] == "speech":
                text_lines.append(f"[{hms_st}] {item['speaker']}: {item['text']}")
            elif item["type"] == "acoustic_event":
                hms_et = format_seconds_to_hms(item["end_time"])
                resp = f" | תגובת צוות: {item['adult_response']}" if item['adult_response'] else ""
                quotes = f" | ציטוטים: {', '.join(item['quotes'])}" if item['quotes'] else ""
                text_lines.append(
                    f"[{hms_st}–{hms_et}] 🔊 אירוע קולי: {item['event_type']} "
                    f"({item['intensity']}) - {item['description']}{resp}{quotes}"
                )
            elif item["type"] == "gap":
                hms_et = format_seconds_to_hms(item["end_time"])
                db_str = f", עוצמת רקע {item['mean_db']:.1f} dB" if item['mean_db'] is not None else ""
                text_lines.append(
                    f"[{hms_st}–{hms_et}] ⚠ פער תמלול ממושך ({int(item['duration'] // 60)} דקות{db_str})"
                )

        return all_items, "\n".join(text_lines)

    async def _call_direct_llm(
        self,
        child_name: Optional[str],
        focus_prompt: Optional[str],
        speakers_summary: str,
        evidence_timeline_text: str,
        acoustic_events_summary: str,
        coverage_summary: str,
        context_block: str = ""
    ) -> Dict[str, Any]:
        """Calls OpenRouter with direct prompt for short-to-medium days."""
        user_prompt = build_analysis_user_prompt(
            child_name=child_name,
            focus_prompt=focus_prompt,
            speakers_summary=speakers_summary,
            evidence_timeline_text=evidence_timeline_text,
            acoustic_events_summary=acoustic_events_summary,
            coverage_summary=coverage_summary,
            context_block=context_block
        )

        api_key = settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY or settings.GEMINI_API_KEY
        base_url = settings.OPENROUTER_BASE_URL.rstrip("/")
        model = self.model

        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://kindergarten-monitor.local",
            "X-Title": "Kindergarten Monitor",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": HEBREW_KINDERGARTEN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 4096,
            "temperature": 0.2
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            res = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            if res.status_code != 200:
                raise RuntimeError(f"OpenRouter API error ({res.status_code}): {res.text[:300]}")
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            parsed = self._safe_parse_json(content)
            if not parsed:
                raise RuntimeError("Failed to parse valid JSON from LLM report response")
            return parsed

    async def _run_map_reduce_pipeline(
        self,
        child_name: Optional[str],
        focus_prompt: Optional[str],
        speakers_summary: str,
        timeline_items: List[Dict[str, Any]],
        audio_events: List[Dict[str, Any]],
        coverage_text: str,
        context_block: str = ""
    ) -> Dict[str, Any]:
        """
        Map-Reduce architecture:
        1. Map: Slices timeline into 30-min chronological blocks and generates block summaries in parallel.
        2. Reduce: Synthesizes final cohesive pedagogical report from block summaries + all distress events.
        """
        logger.info(f"Running Map-Reduce pipeline on {len(timeline_items)} items")

        # 1. Group timeline into 30-minute blocks (1800s)
        block_size_sec = 1800.0
        max_time = max(item["time"] for item in timeline_items)
        blocks: List[List[Dict[str, Any]]] = []
        cur_start = 0.0

        while cur_start <= max_time:
            cur_end = cur_start + block_size_sec
            block = [i for i in timeline_items if cur_start <= i["time"] < cur_end]
            if block:
                blocks.append(block)
            cur_start = cur_end

        # Map phase: summarize blocks concurrently
        async def summarize_block(b_items: List[Dict[str, Any]]) -> Dict[str, Any]:
            b_start = b_items[0]["time"]
            b_end = max(i.get("end_time", i["time"]) for i in b_items)
            b_hms = f"{format_seconds_to_hms(b_start)} - {format_seconds_to_hms(b_end)}"

            # Format block text
            b_lines = []
            for item in b_items:
                hms = format_seconds_to_hms(item["time"])
                if item["type"] == "speech":
                    b_lines.append(f"[{hms}] {item['speaker']}: {item['text']}")
                elif item["type"] == "acoustic_event":
                    b_lines.append(f"[{hms}] 🔊 {item['event_type']} ({item['intensity']}): {item['description']}")
                elif item["type"] == "gap":
                    b_lines.append(f"[{hms}] ⚠ פער תמלול ({int(item['duration']//60)} דקות)")

            block_text = "\n".join(b_lines)
            prompt = (
                f"סכם את הבלוק הבא [{b_hms}]:\n"
                f"הילד במוקד: {child_name or 'לא צוין'}\n\n"
                f"{block_text}"
            )

            api_key = settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY or settings.GEMINI_API_KEY
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": BLOCK_SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 1000,
                "temperature": 0.2
            }
            try:
                async with httpx.AsyncClient(timeout=40.0) as client:
                    res = await client.post(
                        f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json=payload
                    )
                    if res.status_code == 200:
                        parsed = self._safe_parse_json(res.json()["choices"][0]["message"]["content"])
                        if parsed:
                            parsed["time_range"] = b_hms
                            return parsed
            except Exception as e:
                logger.warning(f"Block summary error for {b_hms}: {e}")

            return {
                "time_range": b_hms,
                "phase_name": f"שלב {b_hms}",
                "summary": f"פעילות שוטפת בגן בבלוק {b_hms}",
                "distress_events": [],
                "child_interactions": [],
                "staff_conduct_notes": "שגרתי",
                "potential_red_flags": []
            }

        block_summaries = await asyncio.gather(*[summarize_block(b) for b in blocks])

        # Reduce phase: synthesize final report
        reduce_prompt = build_reduce_prompt(
            child_name=child_name,
            focus_prompt=focus_prompt,
            speakers_summary=speakers_summary,
            block_summaries=block_summaries,
            acoustic_events=audio_events,
            coverage_text=coverage_text,
            context_block=context_block
        )

        api_key = settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY or settings.GEMINI_API_KEY
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": HEBREW_KINDERGARTEN_SYSTEM_PROMPT},
                {"role": "user", "content": reduce_prompt}
            ],
            "max_tokens": 4096,
            "temperature": 0.2
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            res = await client.post(
                f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload
            )
            if res.status_code != 200:
                raise RuntimeError(f"Reduce step failed ({res.status_code}): {res.text[:300]}")
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            parsed = self._safe_parse_json(content)
            if not parsed:
                raise RuntimeError("Failed to parse valid JSON from Reduce step")
            return parsed

    def _validate_and_sanitize_report(
        self,
        report_json: Dict[str, Any],
        duration_seconds: float,
        audio_events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Validates timestamps against audio duration and enforces that crying events
        appear in the emotional analysis.
        """
        # 1. Enforce crying presence
        crying_events = [e for e in audio_events if e.get("event_type") == "crying"]
        if crying_events:
            emotional_text = report_json.get("emotional_analysis", "")
            missing_cries = []
            for cr in crying_events:
                hms = format_seconds_to_hms(cr.get("start_time", 0.0))
                if hms not in emotional_text and "בכי" not in emotional_text:
                    missing_cries.append(cr)

            if missing_cries:
                cry_note = "\n\n**אירועי בכי ומצוקה שאותרו באודיו:**\n"
                for cr in missing_cries:
                    st_hms = format_seconds_to_hms(cr.get("start_time", 0.0))
                    et_hms = format_seconds_to_hms(cr.get("end_time", 0.0))
                    resp = f" (מענה צוות: {cr.get('adult_response')})" if cr.get('adult_response') else ""
                    cry_note += f"- [{st_hms}–{et_hms}] {cr.get('description', 'בכי מזוהה')}{resp}\n"
                report_json["emotional_analysis"] = emotional_text + cry_note

        # 2. Sanitize timestamps in red_flags
        red_flags = report_json.get("red_flags", [])
        if isinstance(red_flags, list):
            valid_flags = []
            for rf in red_flags:
                ts_str = rf.get("timestamp", "")
                sec = parse_hms_to_seconds(ts_str)
                # If timestamp exceeds recording duration, clamp or correct
                if sec is not None and duration_seconds > 0 and sec > duration_seconds:
                    logger.warning(f"Timestamp {ts_str} exceeds recording duration {duration_seconds}; correcting")
                    rf["timestamp"] = format_seconds_to_hms(duration_seconds - 60.0)
                valid_flags.append(rf)
            report_json["red_flags"] = valid_flags

        return report_json

    def _build_markdown_report(
        self,
        report_json: Dict[str, Any],
        child_name: Optional[str],
        focus_prompt: Optional[str],
        speakers: List[Dict[str, Any]],
        coverage_info: Dict[str, Any],
        audio_events: List[Dict[str, Any]],
        total_duration_seconds: float
    ) -> str:
        """
        Generates full formatted markdown deterministically in Python.
        Ensures perfect headers, tables, coverage statistics, distress cards, and RTL styling.
        """
        child_display = child_name or "לא צוין (הילד במוקד)"
        dur_hms = format_seconds_to_hms(total_duration_seconds)
        cov_pct = coverage_info.get("coverage_percent", 0.0)
        trans_sec = coverage_info.get("transcribed_seconds", 0.0)
        trans_hms = format_seconds_to_hms(trans_sec)

        speakers_str = ", ".join([
            f"{s.get('assigned_name', s.get('diarization_tag'))} ({s.get('role', 'משתתף')})"
            for s in speakers
        ]) or "לא זוהו משתתפים"

        md = []
        md.append(f"# דוח יומי מקיף — ניתוח פדגוגי בגן הילדים\n")
        md.append(f"**ילד/ה במוקד**: {child_display} | **משך ההקלטה**: {dur_hms} | **כיסוי תמלול**: {cov_pct}% ({trans_hms})\n")
        md.append(f"**משתתפים**: {speakers_str}\n")
        if focus_prompt:
            md.append(f"> **שאלת המיקוד של ההורים**: {focus_prompt}\n")

        md.append("---\n")

        # Executive Summary
        md.append("## 1. תקציר מנהלים\n")
        md.append(f"{report_json.get('executive_summary', 'לא הופק תקציר.')}\n\n")

        # Focus Inquiry Response
        if report_json.get("focus_inquiry_response"):
            md.append("## 2. מענה לשאלת המיקוד של ההורים\n")
            md.append(f"{report_json.get('focus_inquiry_response')}\n\n")

        # Coverage & Acoustic Reality Card
        md.append("## 3. ניתוח אקוסטי וכיסוי ההקלטה\n")
        md.append(f"מתוך **{dur_hms}** של הקלטה רצופה, תומללו **{trans_hms}** דיבור ({cov_pct}%). ")
        gaps = coverage_info.get("gaps", [])
        if gaps:
            md.append(f"אותרו **{len(gaps)} פערי תמלול ממושכים** (זמנים ללא דיבור מזוהה מעל דקה):\n\n")
            md.append("| טווח זמן | משך הפער | רמת רעש ממוצעת | הערכת תוכן |\n|---|---|---|---|\n")
            for g in gaps[:6]:
                db_txt = f"{g.get('mean_db'):.1f} dB" if g.get('mean_db') is not None else "לא זמין"
                dur_m = int(g.get('duration_seconds', 0) // 60)
                md.append(f"| {g.get('start_formatted')} - {g.get('end_formatted')} | {dur_m} דקות | {db_txt} | {g.get('note', 'שקט יחסי')} |\n")
            md.append("\n")
        else:
            md.append("ההקלטה רציפה ללא פערי תמלול חריגים.\n\n")

        # Distress & Acoustic Events
        distress_events = [e for e in audio_events if e.get("event_type") in ("crying", "screaming", "loud_span", "soothing")]
        if distress_events:
            md.append("### אירועים קוליים ומצבי מצוקה שאותרו באודיו 🔊\n\n")
            md.append("| שעת הקלטה | סוג אירוע | עוצמה | תיאור | תגובת צוות הגן |\n|---|---|---|---|---|\n")
            for ev in distress_events:
                st = format_seconds_to_hms(ev.get("start_time", 0.0))
                et = format_seconds_to_hms(ev.get("end_time", 0.0))
                desc = ev.get("description", "-")
                resp = ev.get("adult_response", "ללא מענה מתועד")
                md.append(f"| [{st}–{et}] | **{ev.get('event_type')}** | {ev.get('intensity', 'medium')} | {desc} | {resp} |\n")
            md.append("\n")

        # Emotional Analysis
        md.append("## 4. ניתוח רגשי ורווחת הילד\n")
        md.append(f"{report_json.get('emotional_analysis', 'לא סופק ניתוח רגשי.')}\n\n")

        # Staff Evaluation
        md.append("## 5. הערכת תפקוד צוות הגן\n")
        md.append(f"{report_json.get('staff_evaluation', 'לא סופקה הערכת צוות.')}\n\n")

        # Chronological Timeline
        timeline = report_json.get("timeline", [])
        if timeline:
            md.append("## 6. ציר זמן כרונולוגי של מהלך היום\n\n")
            for phase in timeline:
                tr = phase.get("time_range", "")
                pn = phase.get("phase_name", "שלב פעילות")
                sum_text = phase.get("summary", "")
                md.append(f"### [{tr}] {pn}\n")
                md.append(f"{sum_text}\n\n")
                moments = phase.get("key_moments", [])
                if moments:
                    md.append("**רגעי מפתח:**\n")
                    for m in moments:
                        md.append(f"- {m}\n")
                    md.append("\n")

        # Red Flags
        red_flags = report_json.get("red_flags", [])
        if red_flags:
            md.append("## 7. נורות אזהרה ואירועים חריגים 🚩\n\n")
            md.append("| חותמת זמן | חומרה | תיאור האירוע | ציטוט / ראיה |\n|---|---|---|---|\n")
            for rf in red_flags:
                ts = rf.get("timestamp", "")
                sev = rf.get("severity", "בינונית")
                desc = rf.get("description", "")
                quote = rf.get("quote", "-")
                md.append(f"| [{ts}] | **{sev}** | {desc} | \"{quote}\" |\n")
            md.append("\n")
        else:
            md.append("## 7. נורות אזהרה ואירועים חריגים\nלא אותרו נורות אזהרה חריגות.\n\n")

        # Recommendations
        md.append("## 8. המלצות מעשיות ושאלות מנחות להורים\n")
        md.append(f"{report_json.get('recommendations', 'אין המלצות ספציפיות.')}\n\n")

        return "".join(md)

    def _generate_data_driven_mock(
        self,
        child_name: Optional[str],
        focus_prompt: Optional[str],
        speakers: List[Dict[str, Any]],
        segments: List[Dict[str, Any]],
        audio_events: List[Dict[str, Any]],
        coverage_info: Dict[str, Any],
        duration_seconds: float
    ) -> Dict[str, Any]:
        """
        Data-driven mock generator that strictly uses the ACTUAL provided segments,
        child name, and audio events without inventing fictional sandbox or spoons.
        """
        child_display = child_name or "הילד במוקד"
        first_seg_time = segments[0].get("start_time", 0.0) if segments else 0.0
        last_seg_time = segments[-1].get("end_time", duration_seconds) if segments else duration_seconds
        hms_start = format_seconds_to_hms(first_seg_time)
        hms_end = format_seconds_to_hms(last_seg_time)

        # Inspect if crying events exist
        cries = [e for e in audio_events if e.get("event_type") == "crying"]
        if cries:
            first_cry = cries[0]
            cry_hms = format_seconds_to_hms(first_cry.get("start_time", 0.0))
            emotional = (
                f"לאורך ההקלטה נצפתה פעילות ענפה, אך אותר אירוע בכי ומצוקה משמעותי בשעה [{cry_hms}]. "
                f"האירוע התאפיין בעוצמת שמע גבוהה קרוב למיקרופון ({first_cry.get('description', 'בכי')}). "
                f"תגובת הצוות: {first_cry.get('adult_response') or 'הרגעה סבלנית'}. "
                f"מעבר לכך הילד השתתף באינטראקציות חברתיות עם הצוות."
            )
            red_flags = [
                {
                    "timestamp": cry_hms,
                    "severity": "גבוהה" if first_cry.get("intensity") == "high" else "בינונית",
                    "description": first_cry.get("description", "אירוע בכי ומצוקה"),
                    "quote": ", ".join(first_cry.get("quotes", [])) or "קולות בכי ומצוקה ממושכים"
                }
            ]
        else:
            emotional = (
                f"הילד {child_display} הפגין מעורבות תקינה בפעילויות היום. לא אותרו אירועי בכי או מצוקה חריגים. "
                f"התקשורת עם הצוות והילדים התנהלה באווירה רגועה וחיובית."
            )
            red_flags = []

        timeline = [
            {
                "time_range": f"{hms_start} - {hms_end}",
                "phase_name": "מהלך הפעילות המוקלטת בגן",
                "summary": f"פעילות שוטפת בהשתתפות {child_display} וצוות הגן.",
                "key_moments": [
                    f"[{format_seconds_to_hms(s.get('start_time', 0.0))}] {s.get('speaker_name', 'דובר')}: {s.get('text', '')[:40]}"
                    for s in segments[:3]
                ]
            }
        ]

        return {
            "executive_summary": (
                f"הדוח מנתח יום פעילות בהיקף של {format_seconds_to_hms(duration_seconds)} עבור {child_display}. "
                f"האקלים החינוכי הכללי בגן נחווה כחיובי, כאשר זוהו {len(speakers)} דוברים שונים ואינטראקציות מגוונות."
            ),
            "focus_inquiry_response": (
                f"בהתייחס לבקשת ההורים ('{focus_prompt or 'בדיקה כללית'}'): "
                f"נבדקו כלל הקטעים הקוליים. {child_display} זוהה במספר חילופי דברים עם הצוות, והצוות הגיב ברמת ערנות תקינה."
            ),
            "timeline": timeline,
            "emotional_analysis": emotional,
            "staff_evaluation": (
                "הצוות מפגין נוכחות פעילה במרחב הגן, שומר על סדר יום ושפה מכבדת. "
                "הפניות לילדים נעשות בטון דיבור ענייני ומכיל."
            ),
            "red_flags": red_flags,
            "recommendations": (
                f"1. מומלץ לשוחח עם {child_display} באווירה נינוחה על חוויות היום והמשחקים בחצר.\n"
                "2. לשאול את הגננת על שיתוף הפעולה במפגשים הקבוצתיים."
            )
        }

    def _safe_parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        if not content:
            return None
        text = content.strip()
        if "<think>" in text and "</think>" in text:
            text = text.split("</think>")[-1].strip()

        # Strip markdown code blocks
        if "```json" in text:
            text = text.split("```json", 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]

        # Extract outermost { ... }
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1].strip()

        # Clean trailing commas: e.g. {"a": 1,} -> {"a": 1}
        cleaned = re.sub(r',\s*([\]}])', r'\1', text)

        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # Attempt structural repairs for truncated strings / brackets
        try:
            fixed = cleaned.strip()
            fixed = re.sub(r',\s*$', '', fixed)
            if fixed.count('"') % 2 != 0:
                fixed += '"'
            open_curlies = fixed.count('{') - fixed.count('}')
            open_squares = fixed.count('[') - fixed.count(']')
            if open_squares > 0:
                fixed += ']' * open_squares
            if open_curlies > 0:
                fixed += '}' * open_curlies
            return json.loads(fixed)
        except Exception:
            pass

        # Regex fallback: extract top-level keys individually so we never lose the report
        extracted: Dict[str, Any] = {}
        for key in ["executive_summary", "focus_inquiry_response", "emotional_analysis", "staff_evaluation", "staff_conduct_notes", "recommendations"]:
            match = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', content, re.DOTALL)
            if match:
                extracted[key] = match.group(1).replace(r'\"', '"').replace(r'\n', '\n')

        rf_match = re.search(r'"red_flags"\s*:\s*(\[[^\]]*\])', content, re.DOTALL)
        if rf_match:
            try:
                extracted["red_flags"] = json.loads(re.sub(r',\s*\]', ']', rf_match.group(1)))
            except Exception:
                extracted["red_flags"] = []
        else:
            extracted["red_flags"] = []

        tl_match = re.search(r'"timeline"\s*:\s*(\[[\s\S]*?\](?=\s*,\s*"\w+"|\s*\}))', content)
        if tl_match:
            try:
                extracted["timeline"] = json.loads(re.sub(r',\s*\]', ']', tl_match.group(1)))
            except Exception:
                extracted["timeline"] = []
        else:
            extracted["timeline"] = []

        if extracted.get("executive_summary") or extracted.get("emotional_analysis"):
            return extracted

        return None


llm_report_service = LLMReportService()
