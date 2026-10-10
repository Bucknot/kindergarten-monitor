import os
import re
import json
import logging
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from backend.app.config import settings
from backend.app.services.cache_service import cache_service

logger = logging.getLogger(__name__)


@dataclass
class DetectedAudioEvent:
    event_type: str  # crying | screaming | shouting | laughing | loud_span | speech_gap | soothing | conflict
    start_time: float
    end_time: float
    peak_score: float = 1.0
    mean_db: Optional[float] = None
    peak_db: Optional[float] = None
    source: str = "loudness"  # loudness | gemini | classifier
    intensity: Optional[str] = "medium"  # low | medium | high
    description: Optional[str] = None
    adult_response: Optional[str] = None
    quotes: List[str] = field(default_factory=list)


@dataclass
class CoverageGap:
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    start_formatted: str
    end_formatted: str
    mean_db: Optional[float] = None
    note: Optional[str] = None


@dataclass
class AcousticProfileResult:
    total_duration_seconds: float
    transcribed_seconds: float
    coverage_percent: float
    baseline_db: float
    loudness_points: List[Dict[str, float]]  # [{"time": t, "full_db": f, "cry_db": c}]
    events: List[DetectedAudioEvent]
    gaps: List[CoverageGap]
    candidate_windows: List[Dict[str, Any]]  # Top windows for Audio-LLM inspection


class AcousticService:
    def __init__(self):
        self.cache_dir = settings.cache_dir

    def _get_cache_path(self, file_hash: str) -> Path:
        return self.cache_dir / f"acoustic_{file_hash}.json"

    def _load_cache(self, file_hash: str) -> Optional[Dict[str, Any]]:
        path = self._get_cache_path(file_hash)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read acoustic cache {path}: {e}")
        return None

    def _save_cache(self, file_hash: str, data: Dict[str, Any]):
        path = self._get_cache_path(file_hash)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write acoustic cache {path}: {e}")

    async def analyze_audio(
        self,
        audio_path: str,
        duration_seconds: float,
        transcript_segments: Optional[List[Dict[str, Any]]] = None,
        file_hash: Optional[str] = None
    ) -> AcousticProfileResult:
        """
        Runs acoustic loudness & cry-band profiling on audio file.
        Returns detailed energy points, detected acoustic events, coverage gaps,
        and prioritized candidate windows for the Audio LLM.
        """
        if not file_hash and os.path.exists(audio_path):
            file_hash = cache_service.compute_file_hash(audio_path)

        cached_data = self._load_cache(file_hash) if file_hash else None
        if cached_data:
            logger.info(f"Loaded acoustic profile from cache for hash: {file_hash}")
            return self._deserialize_result(cached_data, transcript_segments, duration_seconds)

        # 1. Compute loudness profile via ffmpeg in a thread
        loudness_points, baseline_db = await asyncio.to_thread(
            self._compute_loudness_profile, audio_path, duration_seconds
        )

        # 2. Detect acoustic events from loudness & cry band
        events = self._detect_events_from_loudness(loudness_points, baseline_db)

        # 3. Analyze coverage & speech gaps against transcript
        gaps, transcribed_sec, cov_pct = self._compute_coverage_gaps(
            duration_seconds, transcript_segments or [], loudness_points
        )

        # Add gap events for noisy untranscribed stretches
        for gap in gaps:
            if gap.duration_seconds >= 60.0:
                is_noisy = gap.mean_db is not None and gap.mean_db > (baseline_db + 6.0)
                note = f"פער תמלול ממושך ({int(gap.duration_seconds // 60)} דקות); "
                note += "רעש רקע ופעילות מוגברת" if is_noisy else "שקט יחסי / מנוחה"
                gap.note = note
                if is_noisy:
                    events.append(DetectedAudioEvent(
                        event_type="speech_gap",
                        start_time=gap.start_seconds,
                        end_time=gap.end_seconds,
                        peak_score=0.7,
                        mean_db=gap.mean_db,
                        peak_db=gap.mean_db,
                        source="loudness",
                        intensity="medium" if gap.mean_db > (baseline_db + 10.0) else "low",
                        description=f"פער תמלול עם רמת רעש פעילות ({gap.mean_db:.1f} dB)"
                    ))

        # 4. Form candidate windows for Audio LLM (including subtle cries and semantic comfort cues)
        candidate_windows = self._select_candidate_windows(events, gaps, loudness_points, duration_seconds, transcript_segments)

        # 5. Serialize and cache
        result_dict = {
            "total_duration_seconds": duration_seconds,
            "transcribed_seconds": transcribed_sec,
            "coverage_percent": cov_pct,
            "baseline_db": baseline_db,
            "loudness_points": loudness_points,
            "events": [
                {
                    "event_type": ev.event_type,
                    "start_time": ev.start_time,
                    "end_time": ev.end_time,
                    "peak_score": ev.peak_score,
                    "mean_db": ev.mean_db,
                    "peak_db": ev.peak_db,
                    "source": ev.source,
                    "intensity": ev.intensity,
                    "description": ev.description,
                    "adult_response": ev.adult_response,
                    "quotes": ev.quotes
                }
                for ev in events
            ],
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
                for g in gaps
            ],
            "candidate_windows": candidate_windows
        }

        if file_hash:
            self._save_cache(file_hash, result_dict)

        return self._deserialize_result(result_dict, transcript_segments, duration_seconds)

    def _compute_loudness_profile(
        self, audio_path: str, duration_seconds: float, step_seconds: int = 5
    ) -> Tuple[List[Dict[str, float]], float]:
        """
        Uses ffmpeg astats to compute full-band and cry-band (1.5kHz-4kHz) RMS levels.
        Runs with step_seconds sample blocks.
        """
        # Samples per block at 16kHz
        samples_per_block = 16000 * step_seconds
        ffmpeg_bin = settings.FFMPEG_PATH

        def run_filter(extra_filter: str) -> List[Tuple[float, float]]:
            af = (
                f"aresample=16000,{extra_filter}"
                f"asetnsamples=n={samples_per_block}:p=0,"
                f"astats=metadata=1:reset=1,"
                f"ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
            )
            cmd = [
                ffmpeg_bin, "-hide_banner", "-nostats", "-i", audio_path,
                "-af", af, "-f", "null", "-"
            ]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, check=False,
                    timeout=max(120.0, duration_seconds * 0.1)
                )
                times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", proc.stdout)]
                vals = [
                    float(x) if x not in ("-inf", "inf") else -90.0
                    for x in re.findall(r"RMS_level=(-?[\w.]+)", proc.stdout)
                ]
                return list(zip(times, vals))
            except Exception as e:
                logger.error(f"ffmpeg loudness filter error: {e}")
                return []

        full_pts = run_filter("")
        cry_pts = run_filter("highpass=f=1500,lowpass=f=4000,")

        combined: List[Dict[str, float]] = []
        cry_map = {round(t, 1): c for t, c in cry_pts}

        full_vals = []
        for t, f_db in full_pts:
            c_db = cry_map.get(round(t, 1), f_db - 8.0)
            combined.append({
                "time": round(t, 1),
                "full_db": round(f_db, 1),
                "cry_db": round(c_db, 1)
            })
            if f_db > -80.0:
                full_vals.append(f_db)

        # Baseline background noise: 20th percentile
        if full_vals:
            full_vals.sort()
            idx = int(len(full_vals) * 0.20)
            baseline_db = full_vals[idx]
        else:
            baseline_db = -28.0

        return combined, round(baseline_db, 1)

    def _detect_events_from_loudness(
        self,
        loudness_points: List[Dict[str, float]],
        baseline_db: float
    ) -> List[DetectedAudioEvent]:
        """
        Detects crying bursts, screaming, and sustained loud spans from RMS profile.
        """
        events: List[DetectedAudioEvent] = []
        if not loudness_points:
            return events

        cry_threshold = settings.ACOUSTIC_CRY_BAND_THRESHOLD_DB  # -18.0 dB
        loud_threshold = baseline_db + settings.ACOUSTIC_BASELINE_DIFF_DB  # baseline + 10dB

        # 1. Detect Cry / Distress Candidates (High cry-band energy + near mic)
        in_cry = False
        cry_start = 0.0
        cry_points: List[Dict[str, float]] = []

        for pt in loudness_points:
            t = pt["time"]
            c_db = pt["cry_db"]
            f_db = pt["full_db"]

            # Cry trigger: strong cry band, elevated energy, or concentrated cry-band ratio for gentle crying/whimpering
            is_cry_hit = (
                (c_db >= cry_threshold) or
                (c_db >= -22.0 and f_db >= -12.0) or
                (c_db >= -28.0 and (c_db - f_db) >= -8.0)  # Gentle crying / quiet whimpering
            )

            if is_cry_hit:
                if not in_cry:
                    in_cry = True
                    cry_start = t
                cry_points.append(pt)
            else:
                if in_cry:
                    dur = t - cry_start
                    if dur >= 6.0:  # Lasted at least 6s
                        peak_c = max(p["cry_db"] for p in cry_points)
                        mean_f = sum(p["full_db"] for p in cry_points) / len(cry_points)
                        if peak_c >= -13.0 or mean_f >= -8.0:
                            intensity = "high"
                        elif peak_c >= -20.0 or mean_f >= -15.0:
                            intensity = "medium"
                        else:
                            intensity = "low"
                        desc = (
                            f"זיהוי אקוסטי: בכי עדין / יבבות (עוצמה {intensity}, שיא {peak_c:.1f} dB)"
                            if intensity == "low"
                            else f"זיהוי אקוסטי: בכי / מצוקה ממושכת (עוצמה {intensity}, שיא תדר בכי {peak_c:.1f} dB)"
                        )
                        events.append(DetectedAudioEvent(
                            event_type="crying",
                            start_time=cry_start,
                            end_time=t,
                            peak_score=min(1.0, max(0.5, (peak_c + 30.0) / 25.0)),
                            mean_db=round(mean_f, 1),
                            peak_db=round(peak_c, 1),
                            source="loudness",
                            intensity=intensity,
                            description=desc
                        ))
                    in_cry = False
                    cry_points = []

        # Flush trailing cry event
        if in_cry and cry_points:
            t = loudness_points[-1]["time"]
            dur = t - cry_start
            if dur >= 6.0:
                peak_c = max(p["cry_db"] for p in cry_points)
                mean_f = sum(p["full_db"] for p in cry_points) / len(cry_points)
                if peak_c >= -13.0 or mean_f >= -8.0:
                    intensity = "high"
                elif peak_c >= -20.0 or mean_f >= -15.0:
                    intensity = "medium"
                else:
                    intensity = "low"
                desc = (
                    f"זיהוי אקוסטי: בכי עדין / יבבות (עוצמה {intensity}, שיא {peak_c:.1f} dB)"
                    if intensity == "low"
                    else f"זיהוי אקוסטי: בכי / מצוקה ממושכת (עוצמה {intensity}, שיא {peak_c:.1f} dB)"
                )
                events.append(DetectedAudioEvent(
                    event_type="crying",
                    start_time=cry_start,
                    end_time=t,
                    peak_score=0.8,
                    mean_db=round(mean_f, 1),
                    peak_db=round(peak_c, 1),
                    source="loudness",
                    intensity=intensity,
                    description=desc
                ))

        # 2. Detect Sustained Loud Spans (Shouting / Noise spikes > baseline + 10dB)
        in_loud = False
        loud_start = 0.0
        loud_pts: List[Dict[str, float]] = []

        for pt in loudness_points:
            t = pt["time"]
            f_db = pt["full_db"]
            is_loud = (f_db >= loud_threshold) or (f_db >= -14.0)

            if is_loud:
                if not in_loud:
                    in_loud = True
                    loud_start = t
                loud_pts.append(pt)
            else:
                if in_loud:
                    dur = t - loud_start
                    # Don't duplicate if already covered by crying
                    already_cry = any(
                        ev.event_type == "crying" and not (t < ev.start_time or loud_start > ev.end_time)
                        for ev in events
                    )
                    if dur >= 20.0 and not already_cry:
                        peak_f = max(p["full_db"] for p in loud_pts)
                        mean_f = sum(p["full_db"] for p in loud_pts) / len(loud_pts)
                        event_type = "screaming" if peak_f >= -7.0 else "loud_span"
                        intensity = "high" if peak_f >= -8.0 else "medium"
                        events.append(DetectedAudioEvent(
                            event_type=event_type,
                            start_time=loud_start,
                            end_time=t,
                            peak_score=0.8,
                            mean_db=round(mean_f, 1),
                            peak_db=round(peak_f, 1),
                            source="loudness",
                            intensity=intensity,
                            description=f"עלייה חדה בעוצמת השמע ({int(dur)} שנ', ממוצע {mean_f:.1f} dB, שיא {peak_f:.1f} dB)"
                        ))
                    in_loud = False
                    loud_pts = []

        return events

    def _compute_coverage_gaps(
        self,
        duration_seconds: float,
        segments: List[Dict[str, Any]],
        loudness_points: List[Dict[str, float]]
    ) -> Tuple[List[CoverageGap], float, float]:
        """
        Calculates transcript coverage % and unanalyzed gaps > 60s.
        """
        if not segments:
            gaps = [
                CoverageGap(
                    start_seconds=0.0,
                    end_seconds=duration_seconds,
                    duration_seconds=duration_seconds,
                    start_formatted="00:00:00",
                    end_formatted=self._format_hms(duration_seconds),
                    mean_db=None,
                    note="אין קטעי תמלול כלל בהקלטה"
                )
            ]
            return gaps, 0.0, 0.0

        # Sort segments by start_time
        sorted_segs = sorted(segments, key=lambda s: s.get("start_time", 0.0))

        # Merge overlapping intervals to get total speech seconds
        merged: List[Tuple[float, float]] = []
        for s in sorted_segs:
            st = float(s.get("start_time", 0.0))
            et = float(s.get("end_time", st + 1.0))
            if not merged:
                merged.append((st, et))
            else:
                last_st, last_et = merged[-1]
                if st <= last_et:
                    merged[-1] = (last_st, max(last_et, et))
                else:
                    merged.append((st, et))

        transcribed_sec = sum(et - st for st, et in merged)
        cov_pct = round((transcribed_sec / max(duration_seconds, 1.0)) * 100.0, 1)

        # Build gaps >= 60s
        gaps: List[CoverageGap] = []
        cur_pos = 0.0

        loudness_map = {pt["time"]: pt["full_db"] for pt in loudness_points}

        for st, et in merged:
            if st - cur_pos >= 60.0:
                gap_dur = st - cur_pos
                gap_dbs = [db for t, db in loudness_map.items() if cur_pos <= t <= st]
                mean_db = round(sum(gap_dbs) / len(gap_dbs), 1) if gap_dbs else None
                gaps.append(CoverageGap(
                    start_seconds=cur_pos,
                    end_seconds=st,
                    duration_seconds=gap_dur,
                    start_formatted=self._format_hms(cur_pos),
                    end_formatted=self._format_hms(st),
                    mean_db=mean_db
                ))
            cur_pos = max(cur_pos, et)

        # Check tail gap
        if duration_seconds - cur_pos >= 60.0:
            gap_dur = duration_seconds - cur_pos
            gap_dbs = [db for t, db in loudness_map.items() if cur_pos <= t <= duration_seconds]
            mean_db = round(sum(gap_dbs) / len(gap_dbs), 1) if gap_dbs else None
            gaps.append(CoverageGap(
                start_seconds=cur_pos,
                end_seconds=duration_seconds,
                duration_seconds=gap_dur,
                start_formatted=self._format_hms(cur_pos),
                end_formatted=self._format_hms(duration_seconds),
                mean_db=mean_db
            ))

        return gaps, round(transcribed_sec, 1), cov_pct

    def _select_candidate_windows(
        self,
        events: List[DetectedAudioEvent],
        gaps: List[CoverageGap],
        loudness_points: List[Dict[str, float]],
        total_duration: float,
        transcript_segments: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Identifies prioritized 25s-45s candidate audio clips for Audio LLM listening.
        Prioritizes:
        1. Crying episodes (both loud bursts and gentle whimpering).
        2. Semantic comfort / distress triggers from Hebrew speech (when teachers say 'why are you crying', etc.).
        3. Screaming / high-energy shouting.
        4. Noisy speech gaps > 120s.
        """
        candidates: List[Dict[str, Any]] = []

        # 1. All crying episodes (loud and gentle whimpers)
        for ev in events:
            if ev.event_type in ("crying", "screaming"):
                center = (ev.start_time + ev.end_time) / 2.0
                win_start = max(0.0, center - 20.0)
                win_dur = min(45.0, total_duration - win_start)
                priority = 1 if ev.event_type == "crying" else 2
                candidates.append({
                    "start_seconds": round(win_start, 1),
                    "duration_seconds": round(win_dur, 1),
                    "reason": f"distress_event_{ev.event_type}_{ev.intensity}",
                    "priority": priority,
                    "peak_db": ev.peak_db or -10.0,
                    "target_time": ev.start_time
                })

        # 2. Semantic Comforting / Distress Cues in speech (detects quiet crying where staff intervened)
        if transcript_segments:
            COMFORT_KEYWORDS = (
                "בוכה", "לבכות", "אל תבכה", "אל תבכי", "למה אתה בוכה", "למה את בוכה",
                "מה קרה", "בוא אליי", "בואי אליי", "רוצה חיבוק", "תירגע", "תירגעי",
                "הכל בסדר", "מי הציק", "מי הרביץ", "מי לקח", "נעלבת", "אתה עצוב", "את עצובה",
                "רוצה מים", "כואב לי", "רוצה הביתה", "איפה אמא", "לא רוצה"
            )
            for seg in transcript_segments:
                txt = seg.get("text", "")
                matched_kw = next((kw for kw in COMFORT_KEYWORDS if kw in txt), None)
                if matched_kw:
                    st = float(seg.get("start_time", 0.0))
                    win_start = max(0.0, st - 15.0)
                    win_dur = min(40.0, total_duration - win_start)
                    candidates.append({
                        "start_seconds": round(win_start, 1),
                        "duration_seconds": round(win_dur, 1),
                        "reason": f"semantic_comfort_cue: {matched_kw}",
                        "priority": 1,
                        "peak_db": -12.0,
                        "target_time": st
                    })

        # 3. Noisy speech gaps > 120s
        for gap in gaps:
            if gap.duration_seconds >= 120.0 and gap.mean_db is not None and gap.mean_db >= -20.0:
                win_start = gap.start_seconds + min(30.0, gap.duration_seconds / 4.0)
                candidates.append({
                    "start_seconds": round(win_start, 1),
                    "duration_seconds": 40.0,
                    "reason": "noisy_speech_gap",
                    "priority": 3,
                    "peak_db": gap.mean_db,
                    "target_time": gap.start_seconds
                })

        # Sort by priority and then peak_db desc
        candidates.sort(key=lambda c: (c["priority"], -c.get("peak_db", -99.0)))

        # Deduplicate overlapping windows (keep window with distance >= 20s)
        unique_windows: List[Dict[str, Any]] = []
        for cand in candidates:
            st = cand["start_seconds"]
            if not any(abs(st - u["start_seconds"]) < 20.0 for u in unique_windows):
                unique_windows.append(cand)
            if len(unique_windows) >= settings.MAX_AUDIO_LLM_WINDOWS:
                break

        return unique_windows

    def _deserialize_result(
        self,
        data: Dict[str, Any],
        segments: Optional[List[Dict[str, Any]]],
        total_duration: float
    ) -> AcousticProfileResult:
        events = [
            DetectedAudioEvent(
                event_type=e.get("event_type", "loud_span"),
                start_time=float(e.get("start_time", 0.0)),
                end_time=float(e.get("end_time", 0.0)),
                peak_score=float(e.get("peak_score", 1.0)),
                mean_db=e.get("mean_db"),
                peak_db=e.get("peak_db"),
                source=e.get("source", "loudness"),
                intensity=e.get("intensity", "medium"),
                description=e.get("description"),
                adult_response=e.get("adult_response"),
                quotes=e.get("quotes", [])
            )
            for e in data.get("events", [])
        ]

        gaps = [
            CoverageGap(
                start_seconds=float(g.get("start_seconds", 0.0)),
                end_seconds=float(g.get("end_seconds", 0.0)),
                duration_seconds=float(g.get("duration_seconds", 0.0)),
                start_formatted=g.get("start_formatted", "00:00:00"),
                end_formatted=g.get("end_formatted", "00:00:00"),
                mean_db=g.get("mean_db"),
                note=g.get("note")
            )
            for g in data.get("gaps", [])
        ]

        return AcousticProfileResult(
            total_duration_seconds=float(data.get("total_duration_seconds", total_duration)),
            transcribed_seconds=float(data.get("transcribed_seconds", 0.0)),
            coverage_percent=float(data.get("coverage_percent", 0.0)),
            baseline_db=float(data.get("baseline_db", -28.0)),
            loudness_points=data.get("loudness_points", []),
            events=events,
            gaps=gaps,
            candidate_windows=data.get("candidate_windows", [])
        )

    @staticmethod
    def _format_hms(seconds: float) -> str:
        s = int(seconds)
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


acoustic_service = AcousticService()
