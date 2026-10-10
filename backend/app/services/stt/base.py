from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class STTUtterance(BaseModel):
    speaker_tag: str       # e.g., "speaker_0"
    start_time: float      # in seconds
    end_time: float        # in seconds
    text: str              # Hebrew transcription
    confidence: float = 1.0


class STTSpeaker(BaseModel):
    speaker_tag: str
    total_speech_seconds: float
    utterance_count: int
    sample_start_time: float  # best moment to extract snippet
    sample_duration: float


class STTResult(BaseModel):
    utterances: List[STTUtterance]
    speakers: List[STTSpeaker]
    provider_name: str


class BaseSTTProvider(ABC):
    @abstractmethod
    async def transcribe(
        self,
        audio_path: str,
        duration_seconds: float,
        progress_callback: Optional[object] = None,
        context_prompt: Optional[str] = None,
        context_metadata: Optional[Dict[str, Any]] = None
    ) -> STTResult:
        """Transcribes and diarizes the audio file into speaker utterances."""
        pass


def consolidate_utterances(
    utterances: List[STTUtterance],
    max_gap_seconds: float = 3.0
) -> List[STTUtterance]:
    """
    Consolidates consecutive fragmented utterances from the same speaker
    within a reasonable conversational gap into fluent, coherent speech turns.
    """
    if not utterances:
        return []

    consolidated: List[STTUtterance] = []
    current: Optional[STTUtterance] = None

    for u in utterances:
        text = (u.text or "").strip()
        if not text:
            continue

        if current is None:
            current = u.model_copy()
            current.text = text
        elif current.speaker_tag == u.speaker_tag and (u.start_time - current.end_time) <= max_gap_seconds:
            current.end_time = max(current.end_time, u.end_time)
            current.text += " " + text
            current.confidence = min(current.confidence, u.confidence)
        else:
            consolidated.append(current)
            current = u.model_copy()
            current.text = text

    if current is not None:
        consolidated.append(current)

    return consolidated


def consolidate_utterance_dicts(
    utterances: List[dict],
    max_gap_seconds: float = 3.0
) -> List[dict]:
    """
    Consolidates consecutive dictionary utterances from the same speaker.
    """
    if not utterances:
        return []

    consolidated: List[dict] = []
    current: Optional[dict] = None

    for u in utterances:
        text = (u.get("text") or "").strip()
        if not text:
            continue

        spk_tag = u.get("speaker_tag")
        start = float(u.get("start_time", 0.0))
        end = float(u.get("end_time", 0.0))
        conf = float(u.get("confidence", 1.0))
        is_flagged = bool(u.get("is_flagged", False))

        if current is None:
            current = dict(u)
            current["text"] = text
            current["start_time"] = start
            current["end_time"] = end
        elif current.get("speaker_tag") == spk_tag and (start - current["end_time"]) <= max_gap_seconds:
            current["end_time"] = max(current["end_time"], end)
            current["text"] += " " + text
            current["confidence"] = min(float(current.get("confidence", 1.0)), conf)
            if is_flagged:
                current["is_flagged"] = True
        else:
            consolidated.append(current)
            current = dict(u)
            current["text"] = text
            current["start_time"] = start
            current["end_time"] = end

    if current is not None:
        consolidated.append(current)

    return consolidated


def deduplicate_boundary_utterances(
    utterances: List[STTUtterance],
    time_tolerance_seconds: float = 4.0,
    similarity_threshold: float = 0.6,
) -> List[STTUtterance]:
    """
    Deduplicates and merges speech turns that overlap across audio chunk boundaries.
    Handles:
    1. Exact or near-exact identical transcriptions in the boundary overlap window.
    2. Subsumed utterances (where one chunk captured a truncated fragment and the other captured the full phrase).
    3. Partial suffix-prefix word overlap where speech crossed the boundary seam.
    4. Fuzzy word-token matching (Jaccard / sequence similarity >= threshold).
    """
    if not utterances or len(utterances) <= 1:
        return utterances

    import difflib

    sorted_utts = sorted(utterances, key=lambda u: (u.start_time, u.end_time))
    deduped: List[STTUtterance] = []

    for u in sorted_utts:
        text = (u.text or "").strip()
        if not text:
            continue

        if not deduped:
            clean_u = u.model_copy()
            clean_u.text = text
            deduped.append(clean_u)
            continue

        merged = False
        # Look back through recent utterances that might overlap
        for i in range(len(deduped) - 1, -1, -1):
            prev = deduped[i]
            if prev.end_time + time_tolerance_seconds < u.start_time:
                break

            time_overlap = max(0.0, min(prev.end_time, u.end_time) - max(prev.start_time, u.start_time))
            time_proximity = abs(prev.start_time - u.start_time) <= time_tolerance_seconds or time_overlap > 0.0

            if not time_proximity:
                continue

            prev_text = prev.text.strip()
            if not prev_text:
                continue

            # 1. Exact match
            if prev_text == text:
                prev.start_time = min(prev.start_time, u.start_time)
                prev.end_time = max(prev.end_time, u.end_time)
                prev.confidence = max(prev.confidence, u.confidence)
                merged = True
                break

            # 2. Subsumed: u is inside prev
            if text in prev_text:
                prev.start_time = min(prev.start_time, u.start_time)
                prev.end_time = max(prev.end_time, u.end_time)
                merged = True
                break

            # 3. Subsumed: prev is inside u
            if prev_text in text:
                prev.text = text
                prev.start_time = min(prev.start_time, u.start_time)
                prev.end_time = max(prev.end_time, u.end_time)
                prev.confidence = max(prev.confidence, u.confidence)
                merged = True
                break

            # 4. Suffix/Prefix seam join
            prev_words = prev_text.split()
            u_words = text.split()
            max_check = min(len(prev_words), len(u_words))
            seam_merged = False
            for k in range(max_check, 1, -1):
                if prev_words[-k:] == u_words[:k]:
                    combined_words = prev_words + u_words[k:]
                    prev.text = " ".join(combined_words)
                    prev.start_time = min(prev.start_time, u.start_time)
                    prev.end_time = max(prev.end_time, u.end_time)
                    prev.confidence = max(prev.confidence, u.confidence)
                    seam_merged = True
                    break
            if seam_merged:
                merged = True
                break

            # 5. Fuzzy match / Jaccard token similarity
            words_p = set(prev_words)
            words_u = set(u_words)
            inter = words_p.intersection(words_u)
            union = words_p.union(words_u)
            jaccard = len(inter) / max(1, len(union))
            seq_sim = difflib.SequenceMatcher(None, prev_text, text).ratio()
            similarity = max(jaccard, seq_sim)

            if similarity >= similarity_threshold and (time_overlap > 0.3 or abs(prev.start_time - u.start_time) <= 1.5):
                if len(text) > len(prev_text):
                    prev.text = text
                prev.start_time = min(prev.start_time, u.start_time)
                prev.end_time = max(prev.end_time, u.end_time)
                prev.confidence = max(prev.confidence, u.confidence)
                merged = True
                break

        if not merged:
            clean_u = u.model_copy()
            clean_u.text = text
            deduped.append(clean_u)

    return deduped


def deduplicate_boundary_utterance_dicts(
    utterances: List[dict],
    time_tolerance_seconds: float = 4.0,
    similarity_threshold: float = 0.6,
) -> List[dict]:
    """
    Dictionary variant of deduplicate_boundary_utterances.
    """
    if not utterances or len(utterances) <= 1:
        return utterances

    import difflib

    sorted_utts = sorted(utterances, key=lambda u: (float(u.get("start_time", 0.0)), float(u.get("end_time", 0.0))))
    deduped: List[dict] = []

    for u in sorted_utts:
        text = (u.get("text") or "").strip()
        if not text:
            continue

        start = float(u.get("start_time", 0.0))
        end = float(u.get("end_time", 0.0))
        conf = float(u.get("confidence", 1.0))

        if not deduped:
            item = dict(u)
            item["text"] = text
            item["start_time"] = start
            item["end_time"] = end
            deduped.append(item)
            continue

        merged = False
        for i in range(len(deduped) - 1, -1, -1):
            prev = deduped[i]
            prev_end = float(prev.get("end_time", 0.0))
            prev_start = float(prev.get("start_time", 0.0))

            if prev_end + time_tolerance_seconds < start:
                break

            time_overlap = max(0.0, min(prev_end, end) - max(prev_start, start))
            time_proximity = abs(prev_start - start) <= time_tolerance_seconds or time_overlap > 0.0

            if not time_proximity:
                continue

            prev_text = (prev.get("text") or "").strip()
            if not prev_text:
                continue

            # 1. Exact match
            if prev_text == text:
                prev["start_time"] = min(prev_start, start)
                prev["end_time"] = max(prev_end, end)
                prev["confidence"] = max(float(prev.get("confidence", 1.0)), conf)
                merged = True
                break

            # 2. Subsumed: u in prev
            if text in prev_text:
                prev["start_time"] = min(prev_start, start)
                prev["end_time"] = max(prev_end, end)
                merged = True
                break

            # 3. Subsumed: prev in u
            if prev_text in text:
                prev["text"] = text
                prev["start_time"] = min(prev_start, start)
                prev["end_time"] = max(prev_end, end)
                prev["confidence"] = max(float(prev.get("confidence", 1.0)), conf)
                merged = True
                break

            # 4. Suffix/prefix seam
            prev_words = prev_text.split()
            u_words = text.split()
            max_check = min(len(prev_words), len(u_words))
            seam_merged = False
            for k in range(max_check, 1, -1):
                if prev_words[-k:] == u_words[:k]:
                    combined_words = prev_words + u_words[k:]
                    prev["text"] = " ".join(combined_words)
                    prev["start_time"] = min(prev_start, start)
                    prev["end_time"] = max(prev_end, end)
                    prev["confidence"] = max(float(prev.get("confidence", 1.0)), conf)
                    seam_merged = True
                    break
            if seam_merged:
                merged = True
                break

            # 5. Fuzzy match
            words_p = set(prev_words)
            words_u = set(u_words)
            inter = words_p.intersection(words_u)
            union = words_p.union(words_u)
            jaccard = len(inter) / max(1, len(union))
            seq_sim = difflib.SequenceMatcher(None, prev_text, text).ratio()
            similarity = max(jaccard, seq_sim)

            if similarity >= similarity_threshold and (time_overlap > 0.3 or abs(prev_start - start) <= 1.5):
                if len(text) > len(prev_text):
                    prev["text"] = text
                prev["start_time"] = min(prev_start, start)
                prev["end_time"] = max(prev_end, end)
                prev["confidence"] = max(float(prev.get("confidence", 1.0)), conf)
                merged = True
                break

        if not merged:
            item = dict(u)
            item["text"] = text
            item["start_time"] = start
            item["end_time"] = end
            deduped.append(item)

    return deduped
