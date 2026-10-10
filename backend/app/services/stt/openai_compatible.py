import os
import json
import httpx
from typing import List, Dict, Optional, Any
from collections import defaultdict
from backend.app.config import settings
from backend.app.services.stt.base import (
    BaseSTTProvider, STTResult, STTUtterance, STTSpeaker,
    consolidate_utterances, deduplicate_boundary_utterances
)
from backend.app.services.context_service import build_stt_biasing_prompt


class OpenAICompatibleSTTProvider(BaseSTTProvider):
    """
    STT Provider for any OpenAI-compatible speech-to-text API
    (OpenAI Whisper, Groq, LemonFox, Local Whisper, RunPod, etc.)
    """
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "whisper-1"
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or (settings.OPENROUTER_API_KEY if "openrouter.ai" in self.base_url else "")

    async def transcribe(
        self,
        audio_path: str,
        duration_seconds: float,
        progress_callback: Optional[Any] = None,
        context_prompt: Optional[str] = None,
        context_metadata: Optional[Dict[str, Any]] = None
    ) -> STTResult:
        if not self.api_key:
            raise ValueError(f"STT API key is not configured for {self.base_url}.")

        from backend.app.services.audio_service import audio_service

        biasing_prompt = context_prompt or build_stt_biasing_prompt(context_metadata)

        # If file duration > 900s or size > 20MB, chunk it to respect OpenAI/Groq 25MB limits
        file_size = os.path.getsize(audio_path) if os.path.exists(audio_path) else 0
        if duration_seconds > 900.0 or file_size > 20 * 1024 * 1024:
            return await self._transcribe_chunked(audio_path, duration_seconds, progress_callback, biasing_prompt=biasing_prompt)

        return await self._transcribe_single_file(audio_path, 0.0, 0, biasing_prompt=biasing_prompt)

    async def _transcribe_single_file(
        self,
        audio_path: str,
        offset_seconds: float,
        chunk_idx: int,
        biasing_prompt: Optional[str] = None
    ) -> STTResult:
        url = f"{self.base_url}/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(audio_path, "rb") as f:
                files = {
                    "file": (os.path.basename(audio_path), f, "audio/mpeg")
                }
                data = {
                    "model": self.model,
                    "language": "he",
                    "response_format": "verbose_json"
                }
                if biasing_prompt:
                    data["prompt"] = biasing_prompt

                res = await client.post(url, headers=headers, files=files, data=data)

            if res.status_code != 200:
                raise RuntimeError(f"OpenAI/Groq STT error ({res.status_code}): {res.text[:300]}")

            result_json = res.json()
            return self._parse_verbose_json(result_json, offset_seconds, chunk_idx)

    async def _transcribe_chunked(
        self,
        audio_path: str,
        duration_seconds: float,
        progress_callback: Optional[Any] = None,
        biasing_prompt: Optional[str] = None
    ) -> STTResult:
        from backend.app.services.audio_service import audio_service

        chunks = await audio_service.split_audio_into_chunks(
            audio_path,
            chunk_duration_seconds=900.0,
            total_duration=duration_seconds,
            silence_aware=True,
            overlap_seconds=2.0
        )
        total_chunks = len(chunks)
        all_utterances: List[STTUtterance] = []
        speaker_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "best_snippet": None})

        for idx, chunk in enumerate(chunks):
            offset = float(chunk["start_time"])
            if progress_callback:
                await progress_callback(
                    idx,
                    total_chunks,
                    f"מתמלל מקטע {idx + 1} מתוך {total_chunks} (Whisper/Groq)..."
                )

            chunk_res = await self._transcribe_single_file(chunk["path"], offset, idx, biasing_prompt=biasing_prompt)
            for u in chunk_res.utterances:
                all_utterances.append(u)

        # Deduplicate boundary overlap utterances across chunks
        deduped = deduplicate_boundary_utterances(all_utterances)

        for u in deduped:
            spk = u.speaker_tag
            dur = max(0.2, u.end_time - u.start_time)
            speaker_stats[spk]["duration"] += dur
            speaker_stats[spk]["count"] += 1
            if 3.0 <= dur <= 10.0 and speaker_stats[spk]["best_snippet"] is None:
                speaker_stats[spk]["best_snippet"] = (u.start_time, dur)

        speakers: List[STTSpeaker] = []
        for spk_tag, stats in speaker_stats.items():
            best = stats["best_snippet"] or (0.0, 5.0)
            speakers.append(STTSpeaker(
                speaker_tag=spk_tag,
                total_speech_seconds=stats["duration"],
                utterance_count=stats["count"],
                sample_start_time=best[0],
                sample_duration=min(10.0, max(4.0, best[1]))
            ))

        speakers.sort(key=lambda s: s.total_speech_seconds, reverse=True)
        if len(speakers) > 12:
            prominent = [s for s in speakers if s.total_speech_seconds >= 6.0]
            speakers = prominent if len(prominent) >= 3 else speakers[:12]

        if progress_callback:
            await progress_callback(total_chunks, total_chunks, "מאחד תמלילי מקטעים...")

        return STTResult(
            utterances=consolidate_utterances(deduped, max_gap_seconds=3.0),
            speakers=speakers,
            provider_name="openai_compatible"
        )

    def _parse_verbose_json(self, data: Dict, offset_seconds: float = 0.0, chunk_idx: int = 0) -> STTResult:
        segments = data.get("segments", [])
        if not segments:
            # Fallback if only text was returned
            full_text = data.get("text", "")
            return STTResult(
                utterances=[
                    STTUtterance(
                        speaker_tag=f"c{chunk_idx}_speaker_0" if chunk_idx > 0 else "speaker_0",
                        start_time=offset_seconds,
                        end_time=offset_seconds + 10.0,
                        text=full_text,
                        confidence=0.9
                    )
                ],
                speakers=[
                    STTSpeaker(
                        speaker_tag=f"c{chunk_idx}_speaker_0" if chunk_idx > 0 else "speaker_0",
                        total_speech_seconds=10.0,
                        utterance_count=1,
                        sample_start_time=offset_seconds,
                        sample_duration=6.0
                    )
                ],
                provider_name="openai_compatible"
            )

        utterances: List[STTUtterance] = []
        speaker_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "best_snippet": None})

        # Turn-taking clustering:
        # Long pauses (>1.8s) or conversational shifts indicate speaker changes.
        current_speaker_idx = 0
        last_end = 0.0

        for seg in segments:
            rel_start = float(seg.get("start", 0.0))
            rel_end = float(seg.get("end", 0.0))
            dur = max(0.1, rel_end - rel_start)
            abs_start = offset_seconds + rel_start
            abs_end = offset_seconds + rel_end
            text = seg.get("text", "").strip()

            if not text:
                continue

            # Switch speaker turn if pause > 1.8 seconds
            if rel_start - last_end > 1.8:
                current_speaker_idx = (current_speaker_idx + 1) % 4

            last_end = rel_end
            spk_tag = f"c{chunk_idx}_speaker_{current_speaker_idx}" if chunk_idx > 0 else f"speaker_{current_speaker_idx}"

            utterances.append(STTUtterance(
                speaker_tag=spk_tag,
                start_time=abs_start,
                end_time=abs_end,
                text=text,
                confidence=0.95
            ))

            stats = speaker_stats[spk_tag]
            stats["duration"] += dur
            stats["count"] += 1
            if 4.0 <= dur <= 12.0 and stats["best_snippet"] is None:
                stats["best_snippet"] = (abs_start, dur)
            elif stats["best_snippet"] is None and dur >= 2.0:
                stats["best_snippet"] = (abs_start, min(10.0, dur))

        speakers: List[STTSpeaker] = []
        for spk_tag, stats in speaker_stats.items():
            best = stats["best_snippet"] or (0.0, 5.0)
            speakers.append(STTSpeaker(
                speaker_tag=spk_tag,
                total_speech_seconds=round(stats["duration"], 1),
                utterance_count=stats["count"],
                sample_start_time=best[0],
                sample_duration=min(10.0, max(4.0, best[1]))
            ))

        speakers.sort(key=lambda s: s.total_speech_seconds, reverse=True)

        return STTResult(
            utterances=utterances,
            speakers=speakers,
            provider_name="openai_compatible"
        )
