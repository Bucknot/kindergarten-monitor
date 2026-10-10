import os
import json
import asyncio
import logging
import httpx
from typing import List, Dict, Tuple, Optional, Any
from collections import defaultdict
from backend.app.services.stt.base import (
    BaseSTTProvider, STTResult, STTUtterance, STTSpeaker,
    consolidate_utterances, deduplicate_boundary_utterances
)

logger = logging.getLogger(__name__)


class GladiaSTTProvider(BaseSTTProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.gladia.io/v2"

    async def transcribe(
        self,
        audio_path: str,
        duration_seconds: float,
        progress_callback: Optional[Any] = None,
        context_prompt: Optional[str] = None,
        context_metadata: Optional[Dict[str, Any]] = None
    ) -> STTResult:
        if not self.api_key:
            raise ValueError("Gladia API key is not configured. Please add GLADIA_API_KEY to .env")

        from backend.app.services.audio_service import audio_service

        # Gladia limit is 8100s. Split files into chunks of max 7000s (~1h 56m) with silence awareness
        chunks = await audio_service.split_audio_into_chunks(
            audio_path,
            chunk_duration_seconds=7000.0,
            total_duration=duration_seconds,
            silence_aware=True,
            overlap_seconds=2.0
        )
        total_chunks = len(chunks)
        headers = {"x-gladia-key": self.api_key}

        logger.info(f"Gladia transcription starting for {audio_path}: {total_chunks} chunk(s), total {duration_seconds:.1f}s")

        chunk_results: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

        custom_vocab = None
        if context_metadata:
            from backend.app.services.context_service import extract_custom_vocabulary
            custom_vocab = extract_custom_vocabulary(context_metadata)

        async with httpx.AsyncClient(timeout=300.0) as client:
            for idx, chunk in enumerate(chunks):
                chunk_num = idx + 1
                start_hms = self._seconds_to_hms(chunk["start_time"])
                end_hms = self._seconds_to_hms(chunk["start_time"] + chunk["duration"])

                if progress_callback:
                    await progress_callback(
                        idx,
                        total_chunks,
                        f"מעבד מקטע {chunk_num} מתוך {total_chunks} בעברית (Gladia: {start_hms}-{end_hms})..."
                    )

                logger.info(f"Transcribing Gladia chunk {chunk_num}/{total_chunks}: {chunk['path']} ({chunk['duration']:.1f}s)")
                res = await self._transcribe_single_chunk(client, chunk["path"], headers, custom_vocab=custom_vocab)
                chunk_results.append((chunk, res))

        if progress_callback:
            await progress_callback(total_chunks, total_chunks, "מאחד מקטעי תמלול ודוברים...")

        return self._merge_chunk_results(chunk_results)

    async def _transcribe_single_chunk(
        self,
        client: httpx.AsyncClient,
        file_path: str,
        headers: Dict[str, str],
        custom_vocab: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Uploads and transcribes a single audio chunk (<= 7000s)."""
        # 1. Upload audio file
        with open(file_path, "rb") as f:
            files = {"audio": (os.path.basename(file_path), f, "audio/mpeg")}
            upload_res = await client.post(
                f"{self.base_url}/upload",
                headers=headers,
                files=files
            )

        if upload_res.status_code not in (200, 201):
            raise RuntimeError(f"Gladia upload failed: {upload_res.status_code} - {upload_res.text}")

        upload_data = upload_res.json()
        audio_url = upload_data.get("audio_url")
        if not audio_url:
            raise RuntimeError(f"Missing audio_url from Gladia response: {upload_data}")

        # 2. Initiate transcription with Hebrew + Diarization
        job_payload: Dict[str, Any] = {
            "audio_url": audio_url,
            "diarization": True,
            "language_config": {
                "languages": ["he"]
            }
        }
        if custom_vocab:
            job_payload["custom_vocabulary"] = custom_vocab

        job_res = await client.post(
            f"{self.base_url}/pre-recorded",
            headers={**headers, "Content-Type": "application/json"},
            json=job_payload
        )

        if job_res.status_code not in (200, 201):
            raise RuntimeError(f"Gladia job creation failed: {job_res.status_code} - {job_res.text}")

        job_data = job_res.json()
        result_url = job_data.get("result_url") or f"{self.base_url}/pre-recorded/{job_data['id']}"

        # 3. Poll for completion
        max_attempts = 180  # up to 30 mins polling
        poll_interval = 10
        for attempt in range(max_attempts):
            await asyncio.sleep(poll_interval)
            poll_res = await client.get(result_url, headers=headers)

            if poll_res.status_code != 200:
                continue

            poll_json = poll_res.json()
            status = poll_json.get("status")

            if status == "done":
                return poll_json
            elif status in ("error", "failed"):
                error_msg = poll_json.get("error", "Unknown error")
                raise RuntimeError(f"Gladia transcription failed: {error_msg}")

        raise TimeoutError("Gladia transcription job timed out.")

    def _merge_chunk_results(
        self,
        chunk_results: List[Tuple[Dict[str, Any], Dict[str, Any]]]
    ) -> STTResult:
        """Merges multiple chunk transcription responses into a single continuous STTResult."""
        utterances: List[STTUtterance] = []
        speaker_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "best_snippet": None})
        is_multi_chunk = len(chunk_results) > 1

        for chunk_info, poll_json in chunk_results:
            offset = float(chunk_info["start_time"])
            c_idx = chunk_info["chunk_index"]

            result = poll_json.get("result", {})
            transcription = result.get("transcription", {})
            raw_utterances = transcription.get("utterances", [])

            for u in raw_utterances:
                spk_num = u.get("speaker", 0)
                spk_tag = f"c{c_idx}_spk_{spk_num}" if is_multi_chunk else f"speaker_{spk_num}"
                rel_start = float(u.get("start", 0.0))
                rel_end = float(u.get("end", 0.0))
                abs_start = offset + rel_start
                abs_end = offset + rel_end
                dur = max(0.1, abs_end - abs_start)
                text = u.get("text", "").strip()
                conf = float(u.get("confidence", 0.95))

                if not text:
                    continue

                utterances.append(STTUtterance(
                    speaker_tag=spk_tag,
                    start_time=abs_start,
                    end_time=abs_end,
                    text=text,
                    confidence=conf
                ))

                stats = speaker_stats[spk_tag]
                stats["duration"] += dur
                stats["count"] += 1
                if 4.0 <= dur <= 12.0 and stats["best_snippet"] is None:
                    stats["best_snippet"] = (abs_start, dur)
                elif stats["best_snippet"] is None and dur >= 2.5:
                    stats["best_snippet"] = (abs_start, min(10.0, dur))

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

        # Sort speakers by speech duration descending (most active first)
        speakers.sort(key=lambda s: s.total_speech_seconds, reverse=True)

        # If there are many micro-speakers, keep top 12 or those with > 6s
        if len(speakers) > 12:
            prominent = [s for s in speakers if s.total_speech_seconds >= 6.0]
            speakers = prominent if len(prominent) >= 3 else speakers[:12]

        # Deduplicate boundary overlap utterances across chunks
        deduped = deduplicate_boundary_utterances(utterances)

        return STTResult(
            utterances=consolidate_utterances(deduped, max_gap_seconds=3.0),
            speakers=speakers,
            provider_name="gladia"
        )

    @staticmethod
    def _seconds_to_hms(seconds: float) -> str:
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
