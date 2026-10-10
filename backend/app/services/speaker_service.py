import logging
from typing import List, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import SpeakerModel, TranscriptSegmentModel
from backend.app.schemas import SpeakerSampleItem

logger = logging.getLogger(__name__)


def format_seconds_to_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


class SpeakerService:
    @staticmethod
    def _select_best_samples(
        speaker: SpeakerModel,
        speaker_segments: List[TranscriptSegmentModel],
        all_segments: List[TranscriptSegmentModel],
        seg_index_map: Dict[str, int],
        session_id: str,
        limit: int = 5
    ) -> List[SpeakerSampleItem]:
        """
        Picks up to `limit` high-quality, diverse audio samples for a speaker.
        Prioritizes:
        1. Isolated speech (no other speakers talking immediately before/after).
        2. Optimal duration (3.0s - 10.0s).
        3. Clear text (multiple words, high STT confidence).
        4. Temporal spread across the entire recording day.
        """
        if not speaker_segments:
            if speaker.sample_snippet_url:
                return [
                    SpeakerSampleItem(
                        sample_index=0,
                        segment_id=None,
                        start_time=0.0,
                        end_time=5.0,
                        duration=5.0,
                        formatted_time="00:00",
                        text="(דגימת קול ברירת מחדל)",
                        is_isolated=False,
                        audio_url=speaker.sample_snippet_url
                    )
                ]
            return []

        scored = []
        for seg in speaker_segments:
            seg_idx = seg_index_map.get(seg.id, -1)
            prev_seg = all_segments[seg_idx - 1] if seg_idx > 0 else None
            next_seg = all_segments[seg_idx + 1] if 0 <= seg_idx < len(all_segments) - 1 else None

            # Calculate gap to previous/next speaker
            prev_gap = 999.0
            if prev_seg and (prev_seg.speaker_id != seg.speaker_id or prev_seg.speaker_tag != seg.speaker_tag):
                prev_gap = max(0.0, seg.start_time - prev_seg.end_time)

            next_gap = 999.0
            if next_seg and (next_seg.speaker_id != seg.speaker_id or next_seg.speaker_tag != seg.speaker_tag):
                next_gap = max(0.0, next_seg.start_time - seg.end_time)

            dur = max(0.1, seg.end_time - seg.start_time)
            text_clean = (seg.text or "").strip()
            words = text_clean.split()
            word_count = len(words)

            # Isolation threshold: 0.8s gap before and after
            is_isolated = (prev_gap >= 0.8 and next_gap >= 0.8)

            score = 0.0
            # Duration score
            if 3.0 <= dur <= 10.0:
                score += 6.0
            elif 2.0 <= dur <= 15.0:
                score += 3.5
            elif dur >= 1.0:
                score += 1.5
            else:
                score += 0.2

            # Word count & text quality
            if word_count >= 5:
                score += 5.0
            elif word_count >= 3:
                score += 3.5
            elif word_count >= 2:
                score += 2.0
            else:
                score += 0.5

            # Isolation bonus
            if is_isolated:
                score += 6.0
            elif prev_gap >= 0.4 and next_gap >= 0.4:
                score += 2.5

            # Confidence bonus
            score += float(seg.confidence or 0.9) * 2.5

            scored.append((score, seg, is_isolated, dur))

        # Sort candidate segments by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Select diverse candidates spread across time
        # Try to find candidates at least 45 seconds apart
        top_pool = scored[: max(25, limit * 5)]
        top_pool.sort(key=lambda x: x[1].start_time)

        chosen = []
        min_spacing_seconds = 45.0
        for item in top_pool:
            cand_seg = item[1]
            if not chosen or all(abs(cand_seg.start_time - c[1].start_time) >= min_spacing_seconds for c in chosen):
                chosen.append(item)
            if len(chosen) >= limit:
                break

        # If not enough spaced candidates, fill from remaining top scored
        if len(chosen) < limit:
            for item in scored:
                if item not in chosen:
                    chosen.append(item)
                if len(chosen) >= limit:
                    break

        # Sort the chosen samples chronologically
        chosen.sort(key=lambda x: x[1].start_time)

        samples: List[SpeakerSampleItem] = []
        for idx, (_, s, is_iso, dur) in enumerate(chosen):
            # Cap snippet duration to 10.0s for snappy playback
            sample_dur = round(min(10.0, max(2.5, dur)), 1)
            audio_url = f"/api/audio/snippet/{session_id}/{s.speaker_tag}?start={s.start_time:.2f}&duration={sample_dur}&sample_idx={idx}"
            samples.append(
                SpeakerSampleItem(
                    sample_index=idx,
                    segment_id=s.id,
                    start_time=round(s.start_time, 2),
                    end_time=round(s.end_time, 2),
                    duration=sample_dur,
                    formatted_time=format_seconds_to_time(s.start_time),
                    text=s.text.strip(),
                    is_isolated=is_iso,
                    audio_url=audio_url
                )
            )

        return samples

    async def get_all_speakers_samples(
        self,
        session_id: str,
        db: AsyncSession,
        limit_per_speaker: int = 5
    ) -> Dict[str, List[SpeakerSampleItem]]:
        """
        Retrieves multiple diverse voice sample clips for all speakers in a session in a single DB query.
        Returns a dict mapping speaker_id to List[SpeakerSampleItem].
        """
        # Fetch all segments in chronological order
        seg_stmt = (
            select(TranscriptSegmentModel)
            .where(TranscriptSegmentModel.session_id == session_id)
            .order_by(TranscriptSegmentModel.start_time.asc())
        )
        res_segs = await db.execute(seg_stmt)
        all_segments = res_segs.scalars().all()

        # Build fast index lookup
        seg_index_map = {seg.id: i for i, seg in enumerate(all_segments)}

        # Group segments by speaker_id and by speaker_tag
        spk_segs_map: Dict[str, List[TranscriptSegmentModel]] = {}
        for s in all_segments:
            if s.speaker_id:
                spk_segs_map.setdefault(s.speaker_id, []).append(s)
            if s.speaker_tag:
                spk_segs_map.setdefault(s.speaker_tag, []).append(s)

        # Fetch speakers
        spk_stmt = (
            select(SpeakerModel)
            .where(SpeakerModel.session_id == session_id)
            .order_by(SpeakerModel.total_speech_seconds.desc())
        )
        res_spks = await db.execute(spk_stmt)
        speakers = res_spks.scalars().all()

        samples_map: Dict[str, List[SpeakerSampleItem]] = {}
        for spk in speakers:
            spk_segs = spk_segs_map.get(spk.id) or spk_segs_map.get(spk.diarization_tag) or []
            samples_map[spk.id] = self._select_best_samples(
                speaker=spk,
                speaker_segments=spk_segs,
                all_segments=all_segments,
                seg_index_map=seg_index_map,
                session_id=session_id,
                limit=limit_per_speaker
            )

        return samples_map

    async def get_speaker_sample_clips(
        self,
        session_id: str,
        speaker_id: str,
        db: AsyncSession,
        limit: int = 5
    ) -> List[SpeakerSampleItem]:
        """
        Returns multiple sample clips for a specific speaker.
        """
        all_samples = await self.get_all_speakers_samples(session_id, db, limit_per_speaker=limit)
        return all_samples.get(speaker_id, [])


speaker_service = SpeakerService()
