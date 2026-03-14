"""
services/radar-service/app/workers/radar_worker.py
====================================================
Radar Worker — event-driven compute node.

Trigger: consumes stream:candle-events (published by Market Data Service)
Pipeline per event:
  1. Load OHLCV indicators from Redis candle cache (NEVER external API)
  2. Feature Engine (Layer 1)
  3. Composite Score Engine (Layer 2)
  4. Transition Detector (Layer 3)
  5. Market State Machine (Layer 4, Redis-backed)
  6. Portfolio Regime Detector (Layer 5, aggregated)
  7. Write radar_map to Redis
  8. Publish stream:radar-updates

Multiple workers can run in parallel — each consumes different events.
Workers use consumer groups: each event processed by exactly one worker.

Worker assignment example:
  radar_worker_1 → handles M5 events
  radar_worker_2 → handles M15 events
  radar_worker_3 → handles H1 events (primary)
  radar_worker_4 → overflow / backup
"""

import os
import json
import time
import threading
import logging
from datetime import datetime, timezone

from shared.libs.messaging.redis_streams import (
    create_consumer_group, consume_messages, publish,
)
from shared.libs.cache.candle_cache import read_indicators
from shared.libs.cache.redis_store import cache_set, cache_get

logger = logging.getLogger("zarmor.radar.worker")

CANDLE_STREAM   = "stream:candle-events"
RADAR_STREAM    = "stream:radar-updates"
CONSUMER_GROUP  = "radar-workers"
RADAR_MAP_KEY   = "radar_map:{symbol}:{tf}"
PORTFOLIO_KEY   = "radar_portfolio_regime"
MAX_RETRY       = 3


# ══════════════════════════════════════════════════════════════════
# WORKER MAIN LOOP
# ══════════════════════════════════════════════════════════════════

def run_worker(worker_id: str, tf_filter: list[str] = None, shutdown_event: threading.Event = None):
    """
    Run radar worker loop.
    tf_filter: if set, only process events for those timeframes.
    Example: tf_filter=["H1"] → worker only processes H1 candle events.
    """
    consumer_name = f"{worker_id}-pid{os.getpid()}"
    logger.info(f"[WORKER:{worker_id}] Starting. TF filter: {tf_filter or 'ALL'}")

    create_consumer_group(CANDLE_STREAM, CONSUMER_GROUP, start_id="$")

    while not (shutdown_event and shutdown_event.is_set()):
        try:
            consume_messages(
                stream=CANDLE_STREAM,
                group=CONSUMER_GROUP,
                consumer=consumer_name,
                handler=lambda etype, payload: _handle_candle_event(
                    etype, payload, worker_id, tf_filter
                ),
                batch_size=20,
                block_ms=2000,
                max_retry=MAX_RETRY,
            )
        except Exception as e:
            logger.error(f"[WORKER:{worker_id}] Loop error: {e}")
            time.sleep(1)

    logger.info(f"[WORKER:{worker_id}] Stopped.")


def _handle_candle_event(event_type: str, payload: dict, worker_id: str, tf_filter) -> bool:
    """
    Process one candle-close event.
    event_type is always "CANDLE_CLOSE" here (sent by market-data-service).
    payload: {symbol, tf, timestamp, score_hint}
    """
    symbol = payload.get("symbol", "")
    tf     = payload.get("tf", "H1")

    # Skip if this worker doesn't handle this TF
    if tf_filter and tf not in tf_filter:
        return True  # ACK — not our job, another worker handles it

    logger.debug(f"[WORKER:{worker_id}] Processing {symbol}/{tf}")

    try:
        radar_map_entry = _compute_radar_map(symbol, tf)
        if radar_map_entry:
            _write_radar_map(symbol, tf, radar_map_entry)
            _publish_radar_update(symbol, tf, radar_map_entry)
            _update_portfolio_regime()
            return True
        else:
            logger.warning(f"[WORKER:{worker_id}] No result for {symbol}/{tf} — cache miss?")
            return False   # Will retry
    except Exception as e:
        logger.error(f"[WORKER:{worker_id}] Compute error {symbol}/{tf}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
# RADAR PIPELINE (5 layers)
# ══════════════════════════════════════════════════════════════════

def _compute_radar_map(symbol: str, tf: str) -> dict | None:
    """
    Run the 5-layer Radar Intelligence Stack.
    Reads ONLY from Redis candle cache — never external API.
    Returns radar_map entry dict or None if data unavailable.
    """
    # ── Load from candle cache (NEVER external API) ───────────────
    indicators = read_indicators(symbol, tf)
    if not indicators:
        logger.debug(f"[PIPELINE] Cache miss {symbol}/{tf} — skip")
        return None

    # ── Import engine (lazy — avoids circular imports) ─────────────
    from app.intelligence.engine import (
        compute_features, compute_score, detect_transition,
        update_market_state, compute_portfolio_regime,
        SCORE_LABELS, _ea_params,
    )
    from shared.libs.cache.redis_store import cache_get

    # ── Layer 1: Feature Engine ───────────────────────────────────
    features = compute_features(symbol, indicators)

    # ── Layer 2: Score Engine ─────────────────────────────────────
    score, breakdown, regime, confidence, session = compute_score(symbol, tf, features)

    # ── Layer 3: Transition Detector ─────────────────────────────
    prev_score = cache_get(f"radar_prev_score:{symbol}:{tf}")
    transition_type, transition_score = detect_transition(score, prev_score, features)

    # Persist prev_score for next cycle
    cache_set(f"radar_prev_score:{symbol}:{tf}", score, ttl=7200)

    # ── Layer 4: State Machine (Redis-backed) ─────────────────────
    symbol_key = f"{symbol}:{tf}"
    market_state, bars_in_state, _ = update_market_state(symbol_key, score, features)

    # ── EA params (gate + sizing guidance) ────────────────────────
    gate = next((gt for lo, hi, _, _, _, _, gt in SCORE_LABELS if lo <= score < hi), "CAUTION")
    ea   = _ea_params(score, gate, regime)

    now = datetime.now(timezone.utc).isoformat()

    return {
        "symbol":           symbol,
        "tf":               tf,
        "score":            score,
        "regime":           regime,
        "gate":             gate,
        "confidence":       confidence,
        "session":          session,
        "transition_type":  transition_type,
        "transition_score": round(transition_score, 1),
        "market_state":     market_state,
        "bars_in_state":    bars_in_state,
        "ea_allow_trade":   ea["allow_trade"],
        "ea_position_pct":  ea["position_pct"],
        "ea_sl_multiplier": ea["sl_multiplier"],
        "ea_state_cap":     ea["state_cap"],
        "feature_vector": {
            "adx":              round(features.adx, 1),
            "atr_pct":          round(features.atr_pct, 4),
            "rsi":              round(getattr(features, "rsi", 50.0), 1),
            "volatility_ratio": round(features.volatility_ratio, 3),
            "ema_slope":        round(features.ema_slope, 4),
            "range_compression":round(features.range_compression, 3),
        },
        "breakdown":    breakdown,
        "computed_at":  now,
    }


# ══════════════════════════════════════════════════════════════════
# WRITE / PUBLISH
# ══════════════════════════════════════════════════════════════════

def _write_radar_map(symbol: str, tf: str, entry: dict):
    """Write radar_map entry to Redis. TTL matches timeframe bar duration × 1.5."""
    ttl_map = {"M5": 450, "M15": 1350, "H1": 5400}
    ttl = ttl_map.get(tf, 5400)
    key = RADAR_MAP_KEY.format(symbol=symbol, tf=tf)
    cache_set(key, entry, ttl=ttl)


def _publish_radar_update(symbol: str, tf: str, entry: dict):
    """Publish radar update event to stream:radar-updates for downstream consumers."""
    publish(
        stream=RADAR_STREAM,
        event_type="RADAR_SCAN_COMPLETE",
        payload={
            "symbol":          symbol,
            "tf":              tf,
            "score":           entry["score"],
            "regime":          entry["regime"],
            "market_state":    entry["market_state"],
            "transition_type": entry["transition_type"],
            "ea_allow_trade":  entry["ea_allow_trade"],
            "computed_at":     entry["computed_at"],
        },
        source="radar-worker",
    )


def _update_portfolio_regime():
    """
    Layer 5: Recompute portfolio_regime after any symbol scan completes.
    Reads all current radar_map entries from Redis.
    """
    try:
        from shared.libs.cache.redis_store import _get_redis
        from app.intelligence.engine import compute_portfolio_regime, RadarResult
        from dataclasses import dataclass

        r = _get_redis()
        if not r:
            return

        keys = list(r.scan_iter("radar_map:*"))
        results = {}
        for k in keys:
            try:
                data = cache_get(k)
                if data and isinstance(data, dict):
                    results[k] = data
            except Exception:
                pass

        if not results:
            return

        # Compute portfolio regime from all active radar_maps
        scores = [v["score"] for v in results.values()]
        shock_count = sum(1 for v in results.values() if v.get("market_state") == "VOLATILITY_SHOCK")
        avg_score = sum(scores) / len(scores)
        shock_pct = shock_count / len(results)

        if shock_pct > 0.5:
            portfolio_regime = "VOLATILITY_SHOCK"
        elif avg_score >= 70 and shock_pct <= 0.10:
            portfolio_regime = "RISK_ON"
        elif avg_score >= 50 and shock_pct <= 0.30:
            portfolio_regime = "RISK_MIXED"
        else:
            portfolio_regime = "RISK_OFF"

        cache_set(PORTFOLIO_KEY, {
            "portfolio_regime": portfolio_regime,
            "avg_score":        round(avg_score, 1),
            "symbol_count":     len(results),
            "shock_pct":        round(shock_pct, 3),
            "computed_at":      datetime.now(timezone.utc).isoformat(),
        }, ttl=7200)

    except Exception as e:
        logger.debug(f"[WORKER] Portfolio regime update failed: {e}")


# ══════════════════════════════════════════════════════════════════
# THREAD LAUNCHER
# ══════════════════════════════════════════════════════════════════

def start_worker_threads(n_workers: int = 2) -> list[threading.Event]:
    """
    Start N radar worker threads.
    Worker assignment:
      - worker-1: H1 (primary, most important)
      - worker-2: M15
      - worker-3+: M5 or ALL (overflow)
    """
    tf_assignments = {
        1: ["H1"],
        2: ["M15"],
        3: ["M5"],
    }
    shutdowns = []
    for i in range(1, n_workers + 1):
        shutdown = threading.Event()
        tf_filter = tf_assignments.get(i, None)  # None = all TFs
        t = threading.Thread(
            target=run_worker,
            args=(f"worker-{i}", tf_filter, shutdown),
            daemon=True,
            name=f"radar-worker-{i}",
        )
        t.start()
        shutdowns.append(shutdown)
        logger.info(f"[RADAR] Worker {i} started (TF: {tf_filter or 'ALL'})")
    return shutdowns
