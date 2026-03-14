"""
app/jobs/radar_warm.py
========================
Job: Warm radar cache mỗi 15 phút.
Trigger radar-service /radar/scan cho tất cả assets + timeframes.
Extract từ radar/scheduler.py monolith.
"""

import os
import logging
import httpx

logger = logging.getLogger("zarmor.scheduler.radar_warm")

RADAR_SERVICE_URL = os.getenv("RADAR_SERVICE_URL", "http://radar-service:8004")
ASSETS     = ["GOLD", "EURUSD", "BTC", "NASDAQ"]
TIMEFRAMES = ["M15", "H1"]


def run_radar_warm():
    """HTTP POST /radar/scan cho từng asset/timeframe combo."""
    success = 0
    errors  = 0
    for asset in ASSETS:
        for tf in TIMEFRAMES:
            try:
                resp = httpx.post(
                    f"{RADAR_SERVICE_URL}/radar/scan",
                    json={"asset": asset, "timeframe": tf},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    score = data.get("score", "?")
                    state = data.get("market_state", "?")
                    logger.info(f"[RADAR_WARM] {asset}/{tf}: score={score}, state={state}")
                    success += 1
                else:
                    logger.warning(f"[RADAR_WARM] {asset}/{tf}: HTTP {resp.status_code}")
                    errors += 1
            except Exception as e:
                logger.error(f"[RADAR_WARM] {asset}/{tf} failed: {e}")
                errors += 1

    logger.info(f"[RADAR_WARM] Done: {success} ok, {errors} errors")
