import asyncio
import logging
from sqlalchemy import select, delete, func
from backend.app.database import AsyncSessionLocal
from backend.app.models import SessionModel, SpeakerModel, TranscriptSegmentModel
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("consolidate_sessions")


async def consolidate_session(db, session_id: str, max_gap_seconds: float = 3.0):
    res = await db.execute(
        select(TranscriptSegmentModel)
        .where(TranscriptSegmentModel.session_id == session_id)
        .order_by(TranscriptSegmentModel.start_time.asc())
    )
    segs = res.scalars().all()
    if not segs:
        logger.info(f"Session {session_id}: no segments found.")
        return 0, 0

    groups = []
    for s in segs:
        if not groups:
            groups.append([s])
            continue
        prev_group = groups[-1]
        prev = prev_group[-1]
        same_speaker = (s.speaker_id == prev.speaker_id) if (s.speaker_id or prev.speaker_id) else (s.speaker_tag == prev.speaker_tag)
        gap = s.start_time - prev.end_time
        if same_speaker and gap <= max_gap_seconds:
            prev_group.append(s)
        else:
            groups.append([s])

    if len(groups) == len(segs):
        logger.info(f"Session {session_id}: segments already consolidated ({len(segs)} segments).")
        return len(segs), len(groups)

    logger.info(f"Session {session_id}: consolidating {len(segs)} segments -> {len(groups)} speech turns.")

    new_segments = []
    for g in groups:
        joined_text = " ".join(x.text.strip() for x in g if x.text.strip())
        avg_conf = sum(x.confidence for x in g) / len(g)
        any_flagged = any(x.is_flagged for x in g)
        new_seg = TranscriptSegmentModel(
            id=str(uuid.uuid4()),
            session_id=session_id,
            speaker_id=g[0].speaker_id,
            speaker_tag=g[0].speaker_tag,
            speaker_name=g[0].speaker_name,
            start_time=g[0].start_time,
            end_time=g[-1].end_time,
            text=joined_text,
            confidence=round(avg_conf, 4),
            is_flagged=any_flagged
        )
        new_segments.append(new_seg)

    # Delete old segments
    await db.execute(
        delete(TranscriptSegmentModel).where(TranscriptSegmentModel.session_id == session_id)
    )
    # Add new consolidated segments
    db.add_all(new_segments)
    await db.flush()

    # Update utterance_count in SpeakerModel
    speakers = (await db.execute(
        select(SpeakerModel).where(SpeakerModel.session_id == session_id)
    )).scalars().all()

    for spk in speakers:
        cnt = (await db.execute(
            select(func.count(TranscriptSegmentModel.id))
            .where(TranscriptSegmentModel.session_id == session_id, TranscriptSegmentModel.speaker_id == spk.id)
        )).scalar() or 0
        spk.utterance_count = cnt

    await db.commit()
    logger.info(f"Session {session_id}: successfully saved {len(new_segments)} consolidated segments.")
    return len(segs), len(new_segments)


async def main():
    async with AsyncSessionLocal() as db:
        sessions = (await db.execute(select(SessionModel))).scalars().all()
        for s in sessions:
            old_cnt, new_cnt = await consolidate_session(db, s.id)
            if old_cnt != new_cnt:
                print(f"Session {s.id} consolidated: {old_cnt} -> {new_cnt}")


if __name__ == "__main__":
    asyncio.run(main())
