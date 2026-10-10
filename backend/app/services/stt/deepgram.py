import json
import httpx
from typing import List, Dict, Optional, Any
from collections import defaultdict
from backend.app.services.stt.base import BaseSTTProvider, STTResult, STTUtterance, STTSpeaker


class DeepgramSTTProvider(BaseSTTProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://api.deepgram.com/v1/listen?model=nova-3&language=he&diarize_model=latest&punctuate=true&utterances=true"

    async def transcribe(
        self,
        audio_path: str,
        duration_seconds: float,
        progress_callback: Optional[Any] = None,
        context_prompt: Optional[str] = None,
        context_metadata: Optional[Dict[str, Any]] = None
    ) -> STTResult:
        if not self.api_key:
            raise ValueError("Deepgram API key is not configured. Please add DEEPGRAM_API_KEY to .env")

        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/mpeg"
        }

        async with httpx.AsyncClient(timeout=600.0) as client:
            with open(audio_path, "rb") as f:
                res = await client.post(self.url, headers=headers, content=f.read())

            if res.status_code != 200:
                raise RuntimeError(f"Deepgram transcription failed: {res.status_code} - {res.text}")

            data = res.json()
            return self._parse_deepgram_result(data)

    def _parse_deepgram_result(self, data: Dict) -> STTResult:
        results = data.get("results", {})
        raw_utterances = results.get("utterances", [])

        utterances: List[STTUtterance] = []
        speaker_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "best_snippet": None})

        for u in raw_utterances:
            spk_num = u.get("speaker", 0)
            spk_tag = f"speaker_{spk_num}"
            start = float(u.get("start", 0.0))
            end = float(u.get("end", 0.0))
            dur = max(0.1, end - start)
            text = u.get("transcript", "").strip()
            conf = float(u.get("confidence", 0.95))

            if not text:
                continue

            utterances.append(STTUtterance(
                speaker_tag=spk_tag,
                start_time=start,
                end_time=end,
                text=text,
                confidence=conf
            ))

            stats = speaker_stats[spk_tag]
            stats["duration"] += dur
            stats["count"] += 1
            if 4.0 <= dur <= 12.0 and stats["best_snippet"] is None:
                stats["best_snippet"] = (start, dur)
            elif stats["best_snippet"] is None and dur >= 2.5:
                stats["best_snippet"] = (start, min(10.0, dur))

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

        return STTResult(
            utterances=utterances,
            speakers=speakers,
            provider_name="deepgram"
        )
