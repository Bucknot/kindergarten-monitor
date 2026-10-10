import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.app.config import settings
from backend.app.database import init_db
from backend.app.api.sessions import router as sessions_router
from backend.app.api.audio import router as audio_router
from backend.app.api.speakers import router as speakers_router
from backend.app.api.transcripts import router as transcripts_router
from backend.app.api.reports import router as reports_router
from backend.app.api.settings import router as settings_router
from backend.app.api.chat import router as chat_router
from backend.app.api.audio_events import router as audio_events_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database schemas
    await init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="מערכת לניתוח הקלטות יום בגן ילדים, תמלול ודוחות פדגוגיים",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(sessions_router, prefix="/api")
app.include_router(audio_router, prefix="/api")
app.include_router(speakers_router, prefix="/api")
app.include_router(transcripts_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(audio_events_router, prefix="/api")


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "stt_provider": settings.STT_PROVIDER,
        "llm_provider": settings.LLM_PROVIDER,
        "ffmpeg": bool(settings.FFMPEG_PATH)
    }


# Mount Frontend static files
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(str(frontend_dir / "index.html"))
