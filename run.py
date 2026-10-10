import uvicorn
from backend.app.config import settings

if __name__ == "__main__":
    print(f"=======================================================")
    print(f"🚀 Starting Kindergarten Monitor Server")
    print(f"🌐 Access Web UI at: http://localhost:{settings.PORT}")
    print(f"🎙️ STT Provider: {settings.STT_PROVIDER}")
    print(f"🧠 LLM Provider: {settings.LLM_PROVIDER}")
    print(f"🎬 FFmpeg Path: {settings.FFMPEG_PATH}")
    print(f"=======================================================")
    uvicorn.run(
        "backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )
