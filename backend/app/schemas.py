from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SpeakerBase(BaseModel):
    diarization_tag: str
    assigned_name: str
    role: str = "אחר"
    is_child_in_focus: bool = False
    total_speech_seconds: float = 0.0
    utterance_count: int = 0
    sample_snippet_url: Optional[str] = None


class SpeakerResponse(SpeakerBase):
    id: str
    session_id: str

    model_config = {"from_attributes": True}


class SpeakerUpdateItem(BaseModel):
    speaker_id: str
    assigned_name: str
    role: str
    is_child_in_focus: bool = False


class TaggingConfigRequest(BaseModel):
    speakers: List[SpeakerUpdateItem]
    focus_prompt: Optional[str] = None
    target_child_name: Optional[str] = None


class TranscriptSegmentResponse(BaseModel):
    id: str
    speaker_id: Optional[str]
    speaker_tag: str
    speaker_name: str
    start_time: float
    end_time: float
    text: str
    confidence: float
    is_flagged: bool

    model_config = {"from_attributes": True}


class DailyReportResponse(BaseModel):
    id: str
    session_id: str
    executive_summary: str
    focus_inquiry_response: Optional[str] = None
    timeline_json: Optional[str] = None
    emotional_analysis: str
    staff_evaluation: str
    red_flags_json: Optional[str] = None
    recommendations: str
    full_markdown: str
    coverage_percent: Optional[float] = 0.0
    transcribed_seconds: Optional[float] = 0.0
    coverage_gaps_json: Optional[str] = None
    audio_events_summary: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AudioEventResponse(BaseModel):
    id: str
    session_id: str
    event_type: str
    start_time: float
    end_time: float
    peak_score: float = 1.0
    mean_db: Optional[float] = None
    source: str = "loudness"
    attributed_speaker_id: Optional[str] = None
    attributed_speaker_name: Optional[str] = None
    intensity: Optional[str] = None
    description: Optional[str] = None
    adult_response: Optional[str] = None
    quotes_json: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CoverageGapItem(BaseModel):
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    start_formatted: str
    end_formatted: str
    mean_db: Optional[float] = None
    note: Optional[str] = None


class CoverageResponse(BaseModel):
    total_duration_seconds: float
    transcribed_seconds: float
    coverage_percent: float
    gaps_count: int
    gaps: List[CoverageGapItem] = []


class SessionCreateRequest(BaseModel):
    title: Optional[str] = "הקלטת יום בגן"
    local_file_path: Optional[str] = None
    stt_provider: Optional[str] = None
    focus_prompt: Optional[str] = None
    target_child_name: Optional[str] = None
    gladia_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None
    openrouter_stt_model: Optional[str] = None
    audio_llm_model: Optional[str] = None
    deepgram_api_key: Optional[str] = None
    openai_stt_base_url: Optional[str] = None
    openai_stt_api_key: Optional[str] = None
    openai_stt_model: Optional[str] = None
    context_metadata: Optional[Dict[str, Any]] = None


class RegenerateReportRequest(BaseModel):
    focus_prompt: Optional[str] = None
    target_child_name: Optional[str] = None
    openrouter_model: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    context_metadata: Optional[Dict[str, Any]] = None


class SettingsUpdateRequest(BaseModel):
    stt_provider: Optional[str] = None
    gladia_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None
    llm_provider: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None
    openrouter_stt_model: Optional[str] = None
    audio_llm_model: Optional[str] = None
    openai_api_key: Optional[str] = None


class SettingsResponse(BaseModel):
    stt_provider: str
    gladia_key_set: bool
    deepgram_key_set: bool
    llm_provider: str
    openrouter_key_set: bool
    openrouter_model: str
    openrouter_stt_model: str = "elevenlabs/scribe-v2"
    audio_llm_model: str = "google/gemini-2.5-flash"
    openai_key_set: bool


class SessionDetailResponse(BaseModel):
    id: str
    title: str
    source_filename: str
    duration_seconds: float
    file_size_bytes: int
    status: str
    progress_percent: int
    status_message: str
    error_message: Optional[str] = None
    stt_provider: str
    stt_model: Optional[str] = None
    focus_prompt: Optional[str] = None
    target_child_name: Optional[str] = None
    context_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    speakers: List[SpeakerResponse] = []
    audio_events: List[AudioEventResponse] = []
    report: Optional[DailyReportResponse] = None

    model_config = {"from_attributes": True}


class SessionSummaryResponse(BaseModel):
    id: str
    title: str
    source_filename: str
    duration_seconds: float
    status: str
    progress_percent: int
    status_message: str
    stt_model: Optional[str] = None
    target_child_name: Optional[str] = None
    context_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedSegmentsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int = 1
    items: List[TranscriptSegmentResponse]


class ChatMessage(BaseModel):
    role: str  # "user", "assistant", "system"
    content: str


class ChatCitation(BaseModel):
    timestamp_seconds: float
    timestamp_formatted: str
    speaker_name: str
    text: str


class ChatToolExecution(BaseModel):
    tool: str
    args: Dict[str, Any] = {}
    summary: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    tool_executions: List[ChatToolExecution] = []
    citations: List[ChatCitation] = []
