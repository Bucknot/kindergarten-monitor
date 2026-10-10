import os
import shutil
from pathlib import Path
from pydantic_settings import BaseSettings

# Auto-detect ffmpeg & ffprobe or fallback to static_ffmpeg
def get_ffmpeg_binary() -> str:
    bin_path = shutil.which("ffmpeg")
    if bin_path:
        return bin_path
    home_local = os.path.expanduser("~/.local/bin/ffmpeg")
    if os.path.exists(home_local):
        return home_local
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        return shutil.which("ffmpeg") or "ffmpeg"
    except Exception:
        return "ffmpeg"

def get_ffprobe_binary() -> str:
    bin_path = shutil.which("ffprobe")
    if bin_path:
        return bin_path
    home_local = os.path.expanduser("~/.local/bin/ffprobe")
    if os.path.exists(home_local):
        return home_local
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        return shutil.which("ffprobe") or "ffprobe"
    except Exception:
        return "ffprobe"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Kindergarten Monitor"
    VERSION: str = "1.0.0"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # STT Services: gladia | deepgram | openai_compatible | mock
    STT_PROVIDER: str = "gladia"
    GLADIA_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""
    OPENAI_COMPATIBLE_STT_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_COMPATIBLE_STT_API_KEY: str = ""
    OPENAI_COMPATIBLE_STT_MODEL: str = "whisper-1"

    # LLM Services: openrouter | openai | anthropic | gemini | mock
    LLM_PROVIDER: str = "openrouter"
    LLM_MODEL: str = "google/gemini-2.5-flash"
    OPENAI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "google/gemini-2.5-flash"
    OPENROUTER_STT_MODEL: str = "elevenlabs/scribe-v2"
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    # Acoustic Analysis & Audio LLM Settings
    ENABLE_ACOUSTIC_ANALYSIS: bool = True
    ENABLE_AUDIO_LLM_ANALYSIS: bool = True
    AUDIO_LLM_MODEL: str = "google/gemini-2.5-flash"
    MAX_AUDIO_LLM_WINDOWS: int = 100
    ACOUSTIC_LOUD_THRESHOLD_DB: float = -14.0
    ACOUSTIC_CRY_BAND_THRESHOLD_DB: float = -18.0
    ACOUSTIC_BASELINE_DIFF_DB: float = 10.0

    # Storage Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    STORAGE_PATH: str = str(Path(__file__).resolve().parent.parent.parent / "storage")

    DATABASE_URL: str = ""

    FFMPEG_PATH: str = get_ffmpeg_binary()
    FFPROBE_PATH: str = get_ffprobe_binary()

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        base_storage = Path(self.STORAGE_PATH)
        (base_storage / "uploads").mkdir(parents=True, exist_ok=True)
        (base_storage / "processed").mkdir(parents=True, exist_ok=True)
        (base_storage / "snippets").mkdir(parents=True, exist_ok=True)
        (base_storage / "db").mkdir(parents=True, exist_ok=True)

        if not self.DATABASE_URL:
            db_file = base_storage / "db" / "kindergarten_monitor.db"
            self.DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"

        # Smart defaults if keys provided
        if self.GLADIA_API_KEY and self.STT_PROVIDER == "mock":
            self.STT_PROVIDER = "gladia"
        elif self.DEEPGRAM_API_KEY and self.STT_PROVIDER == "mock":
            self.STT_PROVIDER = "deepgram"
        elif self.OPENAI_COMPATIBLE_STT_API_KEY and self.STT_PROVIDER == "mock":
            self.STT_PROVIDER = "openai_compatible"

        if self.OPENROUTER_API_KEY and self.LLM_PROVIDER == "mock":
            self.LLM_PROVIDER = "openrouter"
        elif self.OPENAI_API_KEY and self.LLM_PROVIDER == "mock":
            self.LLM_PROVIDER = "openai"
        elif self.ANTHROPIC_API_KEY and self.LLM_PROVIDER == "mock":
            self.LLM_PROVIDER = "anthropic"
        elif self.GEMINI_API_KEY and self.LLM_PROVIDER == "mock":
            self.LLM_PROVIDER = "gemini"

    @property
    def upload_dir(self) -> Path:
        return Path(self.STORAGE_PATH) / "uploads"

    @property
    def processed_dir(self) -> Path:
        return Path(self.STORAGE_PATH) / "processed"

    @property
    def snippet_dir(self) -> Path:
        return Path(self.STORAGE_PATH) / "snippets"

    @property
    def cache_dir(self) -> Path:
        p = Path(self.STORAGE_PATH) / "cache"
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
