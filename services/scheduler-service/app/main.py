"""
scheduler-service/app/main.py
================================
Service: Scheduler — background cron jobs, no HTTP port.

Jobs:
  radar_warm          — warm radar cache mỗi 15 phút
  performance_batch   — performance attribution batch mỗi 1 giờ
  remarketing         — remarketing emails mỗi 24 giờ
  license_expiry_check— check & notify license sắp hết hạn mỗi 6 giờ
  session_cleanup     — cleanup expired EA sessions mỗi 1 giờ

Extract từ monolith:
  - remarketing_scheduler.py  → remarketing job
  - radar/scheduler.py        → radar warm job
  - performance/scheduler.py  → performance batch
"""

import os
import sys
import time
import signal
import logging
import threading
import schedule

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("zarmor.scheduler")

from .jobs.radar_warm import run_radar_warm
from .jobs.performance_batch import run_performance_batch
from .jobs.remarketing import run_remarketing
from .jobs.license_expiry import run_license_expiry_check
from .jobs.session_cleanup import run_session_cleanup

_shutdown = threading.Event()


def _handle_signal(sig, frame):
    logger.info(f"[SCHEDULER] Signal {sig} — shutting down")
    _shutdown.set()


def _run_job(name: str, fn):
    """Wrapper: log + catch exceptions per job."""
    def wrapper():
        logger.info(f"[SCHEDULER] Starting job: {name}")
        try:
            fn()
            logger.info(f"[SCHEDULER] Job done: {name}")
        except Exception as e:
            logger.error(f"[SCHEDULER] Job FAILED: {name} — {e}")
    return wrapper


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    logger.info("[SCHEDULER-SERVICE] Starting. Registering jobs...")

    # Register jobs
    schedule.every(15).minutes.do(_run_job("radar_warm",        run_radar_warm))
    schedule.every(1).hours.do(   _run_job("performance_batch", run_performance_batch))
    schedule.every(24).hours.at("00:05").do(_run_job("remarketing", run_remarketing))
    schedule.every(6).hours.do(   _run_job("license_expiry",    run_license_expiry_check))
    schedule.every(1).hours.do(   _run_job("session_cleanup",   run_session_cleanup))

    # Run all jobs immediately on startup
    for job in schedule.jobs:
        job.run()

    logger.info("[SCHEDULER-SERVICE] All jobs registered. Entering main loop.")

    while not _shutdown.is_set():
        schedule.run_pending()
        time.sleep(30)

    logger.info("[SCHEDULER-SERVICE] Stopped.")


if __name__ == "__main__":
    main()
