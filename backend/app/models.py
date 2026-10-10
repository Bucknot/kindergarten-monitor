import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from backend.app.database import Base


def get_utc_now():
    return datetime.now(timezone.utc)


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False, default="הקלטת יום בגן")
    source_filename = Column(String(255), nullable=False)
    raw_file_path = Column(String(1024), nullable=False)
    optimized_file_path = Column(String(1024), nullable=True)
    duration_seconds = Column(Float, default=0.0)
    file_size_bytes = Column(Integer, default=0)

    # pending, preprocessing, transcribing, ready_for_tagging, generating_report, completed, failed
    status = Column(String(50), nullable=False, default="pending")
    progress_percent = Column(Integer, default=0)
    status_message = Column(String(255), default="ממתין לעיבוד")
    error_message = Column(Text, nullable=True)

    stt_provider = Column(String(50), default="gladia")
    stt_model = Column(String(100), nullable=True)
    focus_prompt = Column(Text, nullable=True)
    target_child_name = Column(String(255), nullable=True)
    context_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=get_utc_now)
    updated_at = Column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)

    # Relationships
    speakers = relationship("SpeakerModel", back_populates="session", cascade="all, delete-orphan", order_by="SpeakerModel.total_speech_seconds.desc()")
    segments = relationship("TranscriptSegmentModel", back_populates="session", cascade="all, delete-orphan", order_by="TranscriptSegmentModel.start_time.asc()")
    audio_events = relationship("AudioEventModel", back_populates="session", cascade="all, delete-orphan", order_by="AudioEventModel.start_time.asc()")
    report = relationship("DailyReportModel", back_populates="session", uselist=False, cascade="all, delete-orphan")


class SpeakerModel(Base):
    __tablename__ = "speakers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)

    diarization_tag = Column(String(50), nullable=False)  # e.g., "speaker_0"
    assigned_name = Column(String(100), nullable=False)   # e.g., "גננת מיכל" or "דובר 1"
    role = Column(String(100), default="אחר")             # גננת ראשית, סייעת, ילד/ה, ילד במוקד, רקע
    is_child_in_focus = Column(Boolean, default=False)
    total_speech_seconds = Column(Float, default=0.0)
    utterance_count = Column(Integer, default=0)

    sample_snippet_path = Column(String(1024), nullable=True)
    sample_snippet_url = Column(String(255), nullable=True)

    session = relationship("SessionModel", back_populates="speakers")
    segments = relationship("TranscriptSegmentModel", back_populates="speaker")


class TranscriptSegmentModel(Base):
    __tablename__ = "transcript_segments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    speaker_id = Column(String(36), ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True)

    speaker_tag = Column(String(50), nullable=False)
    speaker_name = Column(String(100), nullable=False)
    start_time = Column(Float, nullable=False)  # seconds
    end_time = Column(Float, nullable=False)    # seconds
    text = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0)
    is_flagged = Column(Boolean, default=False)

    session = relationship("SessionModel", back_populates="segments")
    speaker = relationship("SpeakerModel", back_populates="segments")


class DailyReportModel(Base):
    __tablename__ = "daily_reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)

    executive_summary = Column(Text, nullable=False)
    focus_inquiry_response = Column(Text, nullable=True)
    timeline_json = Column(Text, nullable=True)       # JSON string
    emotional_analysis = Column(Text, nullable=False)
    staff_evaluation = Column(Text, nullable=False)
    red_flags_json = Column(Text, nullable=True)      # JSON string
    recommendations = Column(Text, nullable=False)
    full_markdown = Column(Text, nullable=False)

    # Coverage & Acoustic metrics
    coverage_percent = Column(Float, default=0.0)
    transcribed_seconds = Column(Float, default=0.0)
    coverage_gaps_json = Column(Text, nullable=True)
    audio_events_summary = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    session = relationship("SessionModel", back_populates="report")


class AudioEventModel(Base):
    __tablename__ = "audio_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)

    # crying | screaming | shouting | laughing | loud_span | speech_gap | soothing | conflict
    event_type = Column(String(50), nullable=False)
    start_time = Column(Float, nullable=False)  # seconds
    end_time = Column(Float, nullable=False)    # seconds
    peak_score = Column(Float, default=1.0)
    mean_db = Column(Float, nullable=True)
    # "loudness" | "gemini" | "classifier" | "stt_tag"
    source = Column(String(50), default="loudness")
    attributed_speaker_id = Column(String(36), ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True)
    attributed_speaker_name = Column(String(100), nullable=True)
    intensity = Column(String(50), nullable=True)  # low | medium | high
    description = Column(Text, nullable=True)
    adult_response = Column(Text, nullable=True)
    quotes_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    session = relationship("SessionModel", back_populates="audio_events")
    attributed_speaker = relationship("SpeakerModel")
