import uuid
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from backend.app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def run_sqlite_migrations(sync_conn):
            try:
                res = sync_conn.exec_driver_sql("PRAGMA table_info(daily_reports)").fetchall()
                cols = [r[1] for r in res]
                new_cols = [
                    ("coverage_percent", "FLOAT DEFAULT 0.0"),
                    ("transcribed_seconds", "FLOAT DEFAULT 0.0"),
                    ("coverage_gaps_json", "TEXT"),
                    ("audio_events_summary", "TEXT")
                ]
                for col, col_type in new_cols:
                    if col not in cols:
                        sync_conn.exec_driver_sql(f"ALTER TABLE daily_reports ADD COLUMN {col} {col_type}")

                # Migrations for sessions table
                res_sess = sync_conn.exec_driver_sql("PRAGMA table_info(sessions)").fetchall()
                sess_cols = [r[1] for r in res_sess]
                if "context_metadata" not in sess_cols:
                    sync_conn.exec_driver_sql("ALTER TABLE sessions ADD COLUMN context_metadata JSON")
                if "stt_model" not in sess_cols:
                    sync_conn.exec_driver_sql("ALTER TABLE sessions ADD COLUMN stt_model VARCHAR(100)")
            except Exception:
                pass

        await conn.run_sync(run_sqlite_migrations)
