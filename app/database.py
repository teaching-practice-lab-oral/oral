from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

# Pool sizing is bounded by PostgreSQL's max_connections (=100, see docker-compose.yml),
# shared across ALL gunicorn workers. Each worker holds its own pool, so the ceiling is
#   workers * (pool_size + max_overflow)  <=  max_connections - superuser_reserved(3).
# With 4 workers: 4 * (10 + 10) = 80 < 97 — comfortable headroom. The old 20/30 allowed
# 4 * 50 = 200 connections, which under load would blow past max_connections and surface
# as "FATAL: too many clients" or pool_timeout stalls. Steady-state demand is low because
# the slow AI endpoints release their connection before each OpenAI/Whisper/TTS await.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
