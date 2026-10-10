import os
import json
import base64
import logging
import asyncio
import tempfile
import subprocess
from typing import List, Dict, Any, Optional
from collections import defaultdict
import httpx

from backend.app.config import settings
from backend.app.services.stt.base import (
    BaseSTTProvider, STTResult, STTUtterance, STTSpeaker,
    consolidate_utterances, deduplicate_boundary_utterances
)
from backend.app.services.context_service import build_stt_biasing_prompt

logger = logging.getLogger(__name__)


class OpenRouterSTTProvider(BaseSTTProvider):
    """
    STT Provider using OpenRouter's Multimodal Audio models (e.g., google/gemini-2.5-flash).
    Transcribes Hebrew audio directly from raw sound with native diarization and emotional context.
    Auto-chunks long audio into 600s (10-minute) windows to ensure high precision.
    """
    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        self.api_key = api_key
        self.model = model or getattr(settings, "OPENROUTER_STT_MODEL", "elevenlabs/scribe-v2") or "elevenlabs/scribe-v2"
        self.base_url = (base_url or settings.OPENROUTER_BASE_URL).rstrip("/")

    async def transcribe(
        self,
        audio_path: str,
        duration_seconds: float,
        progress_callback: Optional[Any] = None,
        context_prompt: Optional[str] = None,
        context_metadata: Optional[Dict[str, Any]] = None
    ) -> STTResult:
        if not self.api_key:
            raise ValueError("OpenRouter API key is not configured for STT transcription.")

        from backend.app.services.audio_service import audio_service

        biasing_prompt = context_prompt or build_stt_biasing_prompt(context_metadata)

        # 30 minutes per chunk (Enhancement 3: larger chunk duration for OpenRouter)
        chunk_len = 1800.0
        chunks = await audio_service.split_audio_into_chunks(
            audio_path,
            chunk_duration_seconds=chunk_len,
            total_duration=duration_seconds,
            silence_aware=True,
            overlap_seconds=2.0
        )
        total_chunks = len(chunks)
        logger.info(f"OpenRouter STT starting for {audio_path}: {total_chunks} chunk(s) using model {self.model}")

        all_utterances: List[STTUtterance] = []
        speaker_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "best_snippet": None})

        # Process chunks with concurrency semaphore (3 concurrent requests)
        sem = asyncio.Semaphore(3)

        async def process_chunk(idx: int, chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
            chunk_num = idx + 1
            offset = float(chunk["start_time"])
            c_dur = float(chunk["duration"])

            if progress_callback:
                await progress_callback(
                    idx,
                    total_chunks,
                    f"מתמלל מקטע {chunk_num} מתוך {total_chunks} דרך OpenRouter ({self.model})..."
                )

            async with sem:
                chunk_utts = await self._transcribe_single_chunk(chunk["path"], offset, c_dur, idx, biasing_prompt=biasing_prompt)
                return chunk_utts

        chunk_results = await asyncio.gather(*[process_chunk(i, c) for i, c in enumerate(chunks)])

        # Flatten utterances from all chunks
        for chunk_utts in chunk_results:
            for u in chunk_utts:
                all_utterances.append(u)

        # Deduplicate boundary overlap utterances across chunks (Enhancement 2)
        deduped_utterances = deduplicate_boundary_utterances(all_utterances)

        # Build speaker stats from deduplicated utterances
        for u in deduped_utterances:
            spk = u.speaker_tag
            dur = max(0.2, u.end_time - u.start_time)
            speaker_stats[spk]["duration"] += dur
            speaker_stats[spk]["count"] += 1
            if 3.0 <= dur <= 10.0 and speaker_stats[spk]["best_snippet"] is None:
                speaker_stats[spk]["best_snippet"] = (u.start_time, dur)

        # Build speakers list
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
            await progress_callback(total_chunks, total_chunks, "מאחד תמליל ודוברים מ-OpenRouter...")

        return STTResult(
            utterances=consolidate_utterances(deduped_utterances, max_gap_seconds=3.0),
            speakers=speakers,
            provider_name="openrouter"
        )

    async def _transcribe_single_chunk(
        self,
        chunk_path: str,
        offset_seconds: float,
        duration_seconds: float,
        chunk_idx: int,
        biasing_prompt: Optional[str] = None
    ) -> List[STTUtterance]:
        """Sends single audio chunk to OpenRouter using either dedicated STT endpoint or multimodal LLM."""
        # Convert to 32kbps mono MP3 for compact transfer
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            compressed_path = tmp.name

        try:
            cmd = [
                settings.FFMPEG_PATH, "-y", "-nostdin", "-loglevel", "error",
                "-i", chunk_path,
                "-ac", "1", "-ar", "16000", "-b:a", "32k",
                compressed_path
            ]
            await asyncio.to_thread(subprocess.run, cmd, check=True)

            with open(compressed_path, "rb") as f:
                b64_audio = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"Error compressing chunk for OpenRouter STT: {e}")
            return []
        finally:
            if os.path.exists(compressed_path):
                try:
                    os.remove(compressed_path)
                except Exception:
                    pass

        # Check if the model is an Audio STT model (e.g. microsoft/mai-transcribe-2, elevenlabs/scribe-v2, openai/whisper-large-v3)
        # or a multimodal Chat LLM (e.g. google/gemini-2.5-flash).
        is_audio_stt_model = any(
            k in self.model.lower() for k in ["mai-", "transcribe", "whisper", "scribe", "speech"]
        )

        if is_audio_stt_model:
            return await self._transcribe_via_audio_endpoint(
                b64_audio, offset_seconds, duration_seconds, chunk_idx, biasing_prompt=biasing_prompt
            )
        else:
            return await self._transcribe_via_chat_completion(
                b64_audio, offset_seconds, duration_seconds, chunk_idx, biasing_prompt=biasing_prompt
            )

    async def _transcribe_via_audio_endpoint(
        self,
        b64_audio: str,
        offset_seconds: float,
        duration_seconds: float,
        chunk_idx: int,
        biasing_prompt: Optional[str] = None
    ) -> List[STTUtterance]:
        """Calls OpenRouter /api/v1/audio/transcriptions with Azure/ElevenLabs diarization support."""
        is_elevenlabs = "elevenlabs" in self.model.lower() or "scribe" in self.model.lower()

        provider_options = {}
        if is_elevenlabs:
            provider_options = {"elevenlabs": {"diarize": True}}
        else:
            provider_options = {"azure": {"diarization": {"enabled": True}}}

        payload: Dict[str, Any] = {
            "model": self.model,
            "input_audio": {"data": b64_audio, "format": "mp3"},
            "language": "he",
            "response_format": "verbose_json",
            "provider": {
                "options": provider_options
            }
        }

        if is_elevenlabs:
            payload["timestamp_granularities"] = ["word", "segment"]

        if biasing_prompt:
            payload["prompt"] = biasing_prompt
        elif is_elevenlabs:
            payload["prompt"] = "גן ילדים, גננת, סייעת, מוצץ, בקבוק, חצר, בכי, מפגש, ארוחת עשר"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                res = await client.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers=headers,
                    json=payload
                )

            if res.status_code != 200:
                logger.error(f"OpenRouter audio/transcriptions error ({res.status_code}): {res.text[:300]}")
                # Fallback to chat completions if audio endpoint fails
                return await self._transcribe_via_chat_completion(b64_audio, offset_seconds, duration_seconds, chunk_idx)

            data = res.json()
            words = data.get("words", [])
            segments = data.get("segments", [])

            # 1. If word-level diarization is returned (ElevenLabs Scribe v2)
            has_word_speakers = any(w.get("speaker") is not None or w.get("speaker_label") for w in words)
            if words and has_word_speakers:
                return self._parse_words_into_utterances(words, offset_seconds, chunk_idx)

            # 2. If segment-level diarization or plain segments returned (MAI-Transcribe 2 / Whisper)
            if not segments and data.get("text"):
                return [STTUtterance(
                    speaker_tag=f"c{chunk_idx}_speaker_0" if chunk_idx > 0 else "speaker_0",
                    start_time=offset_seconds,
                    end_time=offset_seconds + duration_seconds,
                    text=data["text"].strip(),
                    confidence=0.9
                )]

            result_utts: List[STTUtterance] = []
            curr_spk_idx = 0
            last_end = 0.0

            for seg in segments:
                rel_st = float(seg.get("start", 0.0))
                rel_et = float(seg.get("end", rel_st + 1.0))
                abs_st = round(offset_seconds + rel_st, 2)
                abs_et = round(offset_seconds + rel_et, 2)
                text = str(seg.get("text", "")).strip()
                if not text:
                    continue

                spk_val = seg.get("speaker")
                if spk_val is not None:
                    tag = f"c{chunk_idx}_speaker_{spk_val}" if chunk_idx > 0 else f"speaker_{spk_val}"
                else:
                    # Turn-taking clustering by silence gap
                    if rel_st - last_end > 1.8:
                        curr_spk_idx = (curr_spk_idx + 1) % 4
                    tag = f"c{chunk_idx}_speaker_{curr_spk_idx}" if chunk_idx > 0 else f"speaker_{curr_spk_idx}"

                last_end = rel_et
                result_utts.append(STTUtterance(
                    speaker_tag=tag,
                    start_time=abs_st,
                    end_time=abs_et,
                    text=text,
                    confidence=0.95
                ))

            return result_utts
        except Exception as e:
            logger.error(f"Exception during OpenRouter audio endpoint transcription: {e}")
            return []

    def _parse_words_into_utterances(
        self,
        words: List[Dict[str, Any]],
        offset_seconds: float,
        chunk_idx: int
    ) -> List[STTUtterance]:
        """Groups word-level diarization (e.g. ElevenLabs) into coherent speaker conversational turns."""
        turns: List[STTUtterance] = []
        curr_speaker = None
        curr_words: List[str] = []
        turn_start = 0.0
        turn_end = 0.0

        for w in words:
            word_txt = str(w.get("word", "")).strip()
            if not word_txt:
                continue

            spk_raw = w.get("speaker")
            spk_label = w.get("speaker_label")
            if spk_label:
                spk = f"c{chunk_idx}_{spk_label}" if chunk_idx > 0 else spk_label
            elif spk_raw is not None:
                spk = f"c{chunk_idx}_speaker_{spk_raw}" if chunk_idx > 0 else f"speaker_{spk_raw}"
            else:
                spk = f"c{chunk_idx}_speaker_0" if chunk_idx > 0 else "speaker_0"

            w_start = float(w.get("start", 0.0))
            w_end = float(w.get("end", w_start + 0.3))

            if curr_speaker is None:
                curr_speaker = spk
                turn_start = w_start

            # Speaker transition or natural pause (>2.0s)
            if spk != curr_speaker or (w_start - turn_end > 2.0 and turn_end > 0):
                if curr_words:
                    turns.append(STTUtterance(
                        speaker_tag=curr_speaker,
                        start_time=round(offset_seconds + turn_start, 2),
                        end_time=round(offset_seconds + turn_end, 2),
                        text=" ".join(curr_words),
                        confidence=0.95
                    ))
                curr_speaker = spk
                curr_words = []
                turn_start = w_start

            curr_words.append(word_txt)
            turn_end = w_end

        if curr_words and curr_speaker:
            turns.append(STTUtterance(
                speaker_tag=curr_speaker,
                start_time=round(offset_seconds + turn_start, 2),
                end_time=round(offset_seconds + turn_end, 2),
                text=" ".join(curr_words),
                confidence=0.95
            ))

        return turns

    async def _transcribe_via_chat_completion(
        self,
        b64_audio: str,
        offset_seconds: float,
        duration_seconds: float,
        chunk_idx: int,
        biasing_prompt: Optional[str] = None
    ) -> List[STTUtterance]:
        """Calls OpenRouter /api/v1/chat/completions with multimodal audio and diarization prompt."""
        system_prompt = (
            "You are an expert Hebrew speech-to-text transcriber with speaker diarization. "
            "Transcribe every spoken Hebrew utterance with exact timestamps and distinguish speakers (speaker_0, speaker_1, etc.). "
            "Output strictly valid JSON with no markdown formatting."
        )

        extra_ctx = f"\n\nמידע רקע ושמות משתתפים לדיוק התמלול:\n{biasing_prompt}\n" if biasing_prompt else ""

        user_prompt = f"""תמלל את כל הדיבור בעברית בקטע השמע הנוכחי (משך: {int(duration_seconds)} שניות).
הפרד בין דוברים שונים (גננת, סייעת, ילדים).{extra_ctx}
החזר אך ורק מבנה JSON תקין:
{{
  "utterances": [
    {{
      "start": 0.0,
      "end": 3.8,
      "speaker": "speaker_0",
      "text": "טקסט התמלול בעברית מדויקת",
      "confidence": 0.95
    }}
  ]
}}
הערה: זמני start ו-end נמדדים בשניות מתחילת הקטע הנוכחי (0 עד {int(duration_seconds)})."""

        payload = {
            "model": self.model if not any(k in self.model.lower() for k in ["mai-", "whisper"]) else "google/gemini-2.5-flash",
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "input_audio", "input_audio": {"data": b64_audio, "format": "mp3"}}
                    ]
                }
            ],
            "max_tokens": 4000
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                res = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )

            if res.status_code != 200:
                logger.error(f"OpenRouter multimodal chat STT error ({res.status_code}): {res.text[:300]}")
                return []

            data = res.json()
            content = data["choices"][0]["message"]["content"]
            parsed = self._safe_parse_json(content)
            if not parsed or "utterances" not in parsed:
                return []

            result_utts: List[STTUtterance] = []
            for item in parsed.get("utterances", []):
                rel_st = float(item.get("start", 0.0))
                rel_et = float(item.get("end", rel_st + 1.0))
                abs_st = round(offset_seconds + rel_st, 2)
                abs_et = round(offset_seconds + rel_et, 2)
                text = str(item.get("text", "")).strip()
                spk_id = item.get("speaker", "speaker_0")
                tag = f"c{chunk_idx}_{spk_id}"

                if text:
                    result_utts.append(STTUtterance(
                        speaker_tag=tag,
                        start_time=abs_st,
                        end_time=abs_et,
                        text=text,
                        confidence=float(item.get("confidence", 0.95))
                    ))

            return result_utts
        except Exception as e:
            logger.error(f"Exception during OpenRouter multimodal transcription: {e}")
            return []

    def _safe_parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        if not content:
            return None
        text = content.strip()
        if "<think>" in text and "</think>" in text:
            text = text.split("</think>")[-1].strip()
        if "```json" in text:
            text = text.split("```json", 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1].strip()
        try:
            return json.loads(text)
        except Exception:
            return None
