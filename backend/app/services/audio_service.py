import os
import re
import json
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from fastapi import Request
from fastapi.responses import StreamingResponse
from backend.app.config import settings

logger = logging.getLogger(__name__)


class AudioService:
    def __init__(self):
        self.ffmpeg_bin = settings.FFMPEG_PATH
        self.ffprobe_bin = settings.FFPROBE_PATH

    async def probe_audio(self, file_path: str) -> Dict[str, Any]:
        """Probes audio file using ffprobe and returns metadata."""
        cmd = [
            self.ffprobe_bin,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            file_path
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"FFprobe failed: {stderr.decode('utf-8', errors='ignore')}")
            
        data = json.loads(stdout.decode('utf-8'))
        format_info = data.get("format", {})
        duration = float(format_info.get("duration", 0.0))
        size_bytes = int(format_info.get("size", 0))
        bit_rate = int(format_info.get("bit_rate", 0)) if format_info.get("bit_rate") else 0
        
        streams = data.get("streams", [])
        sample_rate = 44100
        channels = 1
        codec = "mp3"
        for st in streams:
            if st.get("codec_type") == "audio":
                sample_rate = int(st.get("sample_rate", 44100))
                channels = int(st.get("channels", 1))
                codec = st.get("codec_name", "mp3")
                break
                
        return {
            "duration": duration,
            "size_bytes": size_bytes,
            "bit_rate": bit_rate,
            "sample_rate": sample_rate,
            "channels": channels,
            "codec": codec
        }

    async def optimize_audio(self, input_path: str, output_path: str) -> str:
        """
        Downsamples audio to 16kHz mono 32k MP3 for optimal STT upload & accuracy.
        Reduces ~1GB files down to ~100MB while keeping speech crystal clear.
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", input_path,
            "-vn",
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "libmp3lame",
            "-b:a", "32k",
            str(output_file)
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg optimization failed: {stderr.decode('utf-8', errors='ignore')}")
            
        return str(output_file)

    async def extract_snippet(self, audio_path: str, start_time: float, duration: float, output_path: str) -> str:
        """
        Extracts a short snippet (e.g. 5-10s) from the audio file.
        Uses fast seek and copy or re-encode for crisp playback.
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Format start time as HH:MM:SS.mmm
        start_str = f"{start_time:.3f}"
        dur_str = f"{duration:.3f}"
        
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-ss", start_str,
            "-i", audio_path,
            "-t", dur_str,
            "-c:a", "libmp3lame",
            "-b:a", "64k",
            str(output_file)
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg snippet extraction failed: {stderr.decode('utf-8', errors='ignore')}")
            
        return str(output_file)

    async def find_natural_pause(
        self,
        audio_path: str,
        target_time: float,
        search_window: float = 15.0,
        min_silence_dur: float = 0.3,
        noise_threshold_db: int = -30,
    ) -> Optional[float]:
        """
        Uses FFmpeg silencedetect to find a natural pause (speech boundary)
        around target_time within [target_time - search_window, target_time + search_window].
        Returns the absolute timestamp (in seconds) of the pause center, or None if no silence found.
        """
        probe_start = max(0.0, target_time - search_window)
        probe_dur = search_window * 2.0

        cmd = [
            self.ffmpeg_bin,
            "-nostdin",
            "-ss", f"{probe_start:.3f}",
            "-t", f"{probe_dur:.3f}",
            "-i", audio_path,
            "-af", f"silencedetect=noise={noise_threshold_db}dB:d={min_silence_dur}",
            "-f", "null",
            "-"
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"FFmpeg silencedetect returned code {proc.returncode}")
                return None

            stderr_text = stderr.decode("utf-8", errors="ignore")
            intervals = []
            current_start = None

            for line in stderr_text.splitlines():
                start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
                if start_match:
                    current_start = float(start_match.group(1))
                end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
                if end_match:
                    s_end = float(end_match.group(1))
                    s_start = current_start if current_start is not None else 0.0
                    intervals.append((s_start, s_end))
                    current_start = None

            if current_start is not None:
                intervals.append((current_start, probe_dur))

            candidates = []
            for s_start, s_end in intervals:
                silence_len = s_end - s_start
                if silence_len >= min_silence_dur:
                    abs_center = probe_start + (s_start + s_end) / 2.0
                    candidates.append({
                        "center": abs_center,
                        "duration": silence_len,
                        "dist": abs(abs_center - target_time)
                    })

            if not candidates:
                return None

            # Prefer candidates with robust pause (>= 0.5s) closest to target_time
            good_candidates = [c for c in candidates if c["duration"] >= 0.5]
            if good_candidates:
                best = min(good_candidates, key=lambda c: c["dist"])
            else:
                best = min(candidates, key=lambda c: c["dist"])

            logger.info(
                f"Found natural pause at {best['center']:.2f}s "
                f"(silence dur {best['duration']:.2f}s, offset from target: {best['center'] - target_time:+.2f}s)"
            )
            return best["center"]
        except Exception as e:
            logger.warning(f"Failed to find natural pause with silencedetect: {e}")
            return None

    async def split_audio_into_chunks(
        self,
        audio_path: str,
        chunk_duration_seconds: float = 7200.0,
        total_duration: Optional[float] = None,
        silence_aware: bool = True,
        overlap_seconds: float = 0.0,
        search_window: float = 15.0,
        min_silence_dur: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Splits an audio file into sequential chunks if duration exceeds chunk_duration_seconds.
        If silence_aware=True, searches for natural speech pauses near chunk boundaries
        to avoid cutting words/sentences in half.
        If overlap_seconds > 0, chunks will have a sliding window overlap at the boundaries.
        Returns a list of dicts:
        [
            {
                "chunk_index": 0,
                "path": "...",
                "start_time": 0.0,
                "end_time": 1800.0,
                "duration": 1800.0,
                "is_original": False
            },
            ...
        ]
        """
        if total_duration is None:
            meta = await self.probe_audio(audio_path)
            total_duration = meta["duration"]

        if total_duration <= chunk_duration_seconds:
            return [{
                "chunk_index": 0,
                "path": audio_path,
                "start_time": 0.0,
                "end_time": total_duration,
                "duration": total_duration,
                "is_original": True
            }]

        chunks = []
        start = 0.0
        idx = 0
        p = Path(audio_path)
        chunk_dir = p.parent / f"{p.stem}_chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        while start < total_duration:
            nominal_end = start + chunk_duration_seconds
            if nominal_end >= total_duration:
                actual_end = total_duration
                next_start = total_duration
            else:
                split_pt = nominal_end
                if silence_aware:
                    pause = await self.find_natural_pause(
                        audio_path,
                        target_time=nominal_end,
                        search_window=search_window,
                        min_silence_dur=min_silence_dur
                    )
                    if pause is not None and (pause - start) >= 30.0 and (total_duration - pause) >= 15.0:
                        split_pt = pause

                actual_end = min(total_duration, split_pt)
                if overlap_seconds > 0.0 and actual_end < total_duration:
                    next_start = max(start + 1.0, actual_end - overlap_seconds)
                else:
                    next_start = actual_end

                # Avoid tiny trailing chunk (< 20 seconds)
                if total_duration - actual_end < 20.0:
                    actual_end = total_duration
                    next_start = total_duration

            dur = actual_end - start
            chunk_path = str(chunk_dir / f"chunk_{idx:03d}.mp3")

            # Cut using fast stream copy if already mp3
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-ss", f"{start:.3f}",
                "-i", audio_path,
                "-t", f"{dur:.3f}",
                "-c", "copy",
                chunk_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                # Fallback to re-encoding if stream copy fails
                cmd_reencode = [
                    self.ffmpeg_bin,
                    "-y",
                    "-ss", f"{start:.3f}",
                    "-i", audio_path,
                    "-t", f"{dur:.3f}",
                    "-c:a", "libmp3lame",
                    "-b:a", "32k",
                    chunk_path
                ]
                proc_re = await asyncio.create_subprocess_exec(
                    *cmd_reencode,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc_re.communicate()

            chunks.append({
                "chunk_index": idx,
                "path": chunk_path,
                "start_time": start,
                "end_time": actual_end,
                "duration": dur,
                "is_original": False
            })
            start = next_start
            idx += 1

        return chunks

    @staticmethod
    def stream_file_range(file_path: str, range_header: Optional[str]) -> StreamingResponse:
        """
        Implements HTTP 206 Partial Content range requests for instant scrubbing
        in large (5-10 hour) audio files.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        file_size = os.path.getsize(file_path)
        start = 0
        end = file_size - 1

        if range_header:
            range_value = range_header.strip().replace("bytes=", "")
            range_parts = range_value.split("-")
            if range_parts[0]:
                start = int(range_parts[0])
            if len(range_parts) > 1 and range_parts[1]:
                end = int(range_parts[1])

        start = max(0, start)
        end = min(file_size - 1, end)
        content_length = (end - start) + 1

        def file_iterator(path: str, offset: int, length: int, chunk_size: int = 65536):
            with open(path, "rb") as f:
                f.seek(offset)
                remaining = length
                while remaining > 0:
                    read_bytes = min(remaining, chunk_size)
                    chunk = f.read(read_bytes)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        status_code = 206 if range_header else 200
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Content-Type": "audio/mpeg",
        }

        return StreamingResponse(
            file_iterator(file_path, start, content_length),
            status_code=status_code,
            headers=headers
        )


audio_service = AudioService()
