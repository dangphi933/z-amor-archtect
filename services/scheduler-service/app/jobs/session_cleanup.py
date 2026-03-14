"""app/jobs/session_cleanup.py — Cleanup expired EA sessions mỗi 1 giờ."""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from shared.libs.database.models import SessionLocal

logger = logging.getLogger("zarmor.scheduler.session_cleanup")

SESSION_TTL_MINUTES = 10   # EA session considered zombie sau 10 phút không ping


def run_session_cleanup():
    db = SessionLocal()
    try:
        stale_before = datetime.now(timezone.utc) - timedelta(minutes=SESSION_TTL_MINUTES)

        result = db.execute(text("""
            UPDATE ea_sessions
            SET status    = 'TIMEOUT',
                ended_at  = NOW()
            WHERE status  = 'ACTIVE'
              AND last_ping < :cutoff
        """), {"cutoff": stale_before})

        n_cleaned = result.rowcount
        db.commit()

        if n_cleaned:
            logger.info(f"[SESSION_CLEANUP] Cleaned {n_cleaned} stale EA sessions")
        else:
            logger.debug("[SESSION_CLEANUP] No stale sessions found")

    except Exception as e:
        db.rollback()
        logger.error(f"[SESSION_CLEANUP] Failed: {e}")
    finally:
        db.close()
