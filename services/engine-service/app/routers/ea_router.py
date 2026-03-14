"""
app/routers/ea_router.py  (v2 — 3 bug fixes)
=============================================
BUG FIX 1: EA session store → Redis (multi-worker safe)
BUG FIX 2: Trade events → XADD stream:trade-events (không ghi DB trực tiếp)
BUG FIX 3: License validation → Redis cache 30s (không query DB mỗi request)

Rate limit → Redis sliding window (multi-worker safe)
Risk config → Redis cache 300s
"""

import os
import uuid
import hmac
import hashlib
import secrets
import json
import time
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from ..core.database import (
    SessionLocal,
    License, TradingAccount,
    RiskHardLimit, RiskTactical, NeuralProfile, TelegramConfig,
    EaSession,
)
from shared.libs.messaging.redis_streams import (
    publish_notification, publish,
    STREAM_NOTIFICATIONS,
)
from shared.libs.cache.redis_store import (
    ea_session_set, ea_session_get,
    ea_session_refresh_ttl, ea_session_delete,
    ea_sessions_for_account,
    rate_check,
    license_cache_get, license_cache_set,
    risk_config_get, risk_config_set,
    cache_set, cache_get,
)

logger = logging.getLogger("zarmor.engine")

# ── Constants ────────────────────────────────────────────────────
TOKEN_TTL_SECONDS     = 70
CHALLENGE_TTL_SECONDS = 90
HMAC_SECRET_SALT = os.environ.get("EA_HMAC_SALT", "zarmor-default-salt-change-in-prod")
ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY", "CHANGE_ME")
RADAR_SERVICE_URL = os.environ.get("RADAR_SERVICE_URL", "http://radar-service:8004")

# Stream names
STREAM_TRADE_EVENTS = "stream:trade-events"
STREAM_RISK_ALERTS  = "stream:risk-alerts"

router = APIRouter(tags=["EA Engine"])


# ══════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ══════════════════════════════════════════════════════════════════

class HandshakeRequest(BaseModel):
    license_key:   str
    mt5_login:     str
    broker_server: Optional[str] = ""
    device_hash:   Optional[str] = ""
    mt5_build:     Optional[str] = ""

class HeartbeatRequest(BaseModel):
    session_token:      str
    challenge_response: Optional[str] = ""
    equity:             Optional[float] = 0.0
    balance:            Optional[float] = 0.0
    config_version:     Optional[str] = ""
    symbols:            Optional[str] = ""
    tf:                 Optional[str] = "H1"

class RiskCheckRequest(BaseModel):
    session_token:  str
    equity:         float
    balance:        float
    daily_pnl:      Optional[float] = 0.0
    open_positions: Optional[int] = 0

class TradeEventRequest(BaseModel):
    session_token: str
    event_type:    str
    ticket:        str
    symbol:        str
    trade_type:    str
    volume:        float
    price:         float
    pnl:           Optional[float] = 0.0
    rr_ratio:      Optional[float] = 0.0

class RevokeRequest(BaseModel):
    account_id:   str
    admin_secret: str


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _generate_challenge(session_token: str) -> str:
    challenge = secrets.token_hex(16)
    cache_set(f"challenge:{session_token}", challenge, ttl=CHALLENGE_TTL_SECONDS)
    return challenge


def _verify_challenge_response(session_token: str, response: str, account_id: str) -> bool:
    if not response:
        return True
    challenge = cache_get(f"challenge:{session_token}")
    if not challenge:
        return False
    expected = hmac.new(
        HMAC_SECRET_SALT.encode(),
        f"{challenge}{account_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, response)


def _get_session(token: str) -> Optional[dict]:
    """Redis-backed session lookup (FIX 1: multi-worker safe)."""
    return ea_session_get(token)


def _get_license(license_key: str) -> Optional[dict]:
    """
    FIX 3: Kiểm tra Redis cache trước (30s TTL), chỉ query DB khi cache miss.
    Giảm DB load khi nhiều EA heartbeat đồng thời.
    """
    cached = license_cache_get(license_key)
    if cached:
        return cached

    db = SessionLocal()
    try:
        lic = db.query(License).filter(License.license_key == license_key).first()
        if not lic:
            return None
        data = {
            "license_key":  lic.license_key,
            "status":       lic.status,
            "tier":         lic.tier,
            "bound_mt5_id": lic.bound_mt5_id,
            "expires_at":   lic.expires_at.isoformat() if lic.expires_at else None,
            "strategy_id":  lic.strategy_id or "S1",
        }
        license_cache_set(license_key, data)
        return data
    finally:
        db.close()


def _get_risk_config(account_id: str) -> dict:
    """Redis cache 300s. Query DB khi miss."""
    cached = risk_config_get(account_id)
    if cached:
        return cached

    db = SessionLocal()
    try:
        rl  = db.query(RiskHardLimit).filter(RiskHardLimit.account_id == account_id).first()
        rt  = db.query(RiskTactical).filter(RiskTactical.account_id  == account_id).first()
        np_ = db.query(NeuralProfile).filter(NeuralProfile.account_id == account_id).first()
        tg  = db.query(TelegramConfig).filter(TelegramConfig.account_id == account_id).first()
        ta  = db.query(TradingAccount).filter(TradingAccount.account_id == account_id).first()

        config = {
            "account_id":          account_id,
            "is_locked":           ta.is_locked if ta else False,
            "arm":                 ta.arm       if ta else False,
            "daily_limit_money":   rl.daily_limit_money if rl else 150.0,
            "max_dd":              rl.max_dd            if rl else 10.0,
            "dd_type":             rl.dd_type           if rl else "STATIC",
            "consistency":         rl.consistency       if rl else 97.0,
            "risk_params":         json.loads(rt.params_json) if rt and rt.params_json else {},
            "trader_archetype":    np_.trader_archetype    if np_ else "SNIPER",
            "historical_win_rate": np_.historical_win_rate if np_ else 40.0,
            "historical_rr":       np_.historical_rr       if np_ else 1.5,
            "optimization_bias":   np_.optimization_bias   if np_ else "HALF_KELLY",
            "telegram_chat_id":    tg.chat_id if tg and tg.is_active else "",
        }
        risk_config_set(account_id, config)
        return config
    finally:
        db.close()


async def _get_radar_context(symbols: str, tf: str) -> Optional[dict]:
    if not symbols or not RADAR_SERVICE_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{RADAR_SERVICE_URL}/radar/latest",
                params={"symbols": symbols, "tf": tf},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.debug(f"[ENGINE] Radar fetch failed: {e}")
    return None


def _notify(event_type: str, payload: dict):
    publish_notification(event_type, payload, source="engine-service")


def _publish_trade_event(event_type: str, payload: dict):
    """
    FIX 2: Trade events → stream:trade-events (không ghi DB trực tiếp).
    event_persister consumer trong engine pod sẽ consume và ghi DB.
    """
    publish(STREAM_TRADE_EVENTS, event_type, payload, source="engine-service")


def _publish_risk_alert(payload: dict):
    publish(STREAM_RISK_ALERTS, "RISK_KILL", payload, source="engine-service")


# ══════════════════════════════════════════════════════════════════
# POST /ea/handshake
# ══════════════════════════════════════════════════════════════════

@router.post("/handshake")
async def ea_handshake(req: HandshakeRequest, request: Request):
    account_id = str(req.mt5_login).strip()

    # Rate limit: Redis sliding window (multi-worker safe)
    if not rate_check("handshake", account_id, limit=10, window=60):
        raise HTTPException(429, "Rate limit exceeded.")

    # License validation (Redis cache → DB fallback)
    lic_data = _get_license(req.license_key)
    if not lic_data:
        raise HTTPException(403, "License key không tồn tại.")
    if lic_data["status"] not in ("ACTIVE",):
        raise HTTPException(403, f"License status: {lic_data['status']}. Liên hệ admin.")
    if lic_data["bound_mt5_id"] and lic_data["bound_mt5_id"] != account_id:
        _notify("DEFCON1_ALERT", {
            "account_id": account_id,
            "message": f"⚠️ Clone attempt: {account_id} dùng license của {lic_data['bound_mt5_id']}",
        })
        raise HTTPException(403, "License đã bind cho account khác.")
    if lic_data.get("expires_at"):
        from datetime import datetime, timezone
        if datetime.fromisoformat(lic_data["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(403, "License đã hết hạn.")

    # Issue session token
    session_token = secrets.token_hex(32)
    challenge     = _generate_challenge(session_token)

    # Store session vào Redis (FIX 1)
    session_data = {
        "account_id":    account_id,
        "license_key":   req.license_key,
        "broker_server": req.broker_server,
        "device_hash":   req.device_hash,
        "tier":          lic_data["tier"],
        "strategy_id":   lic_data["strategy_id"],
        "created_at":    time.time(),
    }
    ea_session_set(session_token, session_data, ttl=TOKEN_TTL_SECONDS)

    # Upsert EaSession record trong DB (audit trail)
    db = SessionLocal()
    try:
        existing = db.query(EaSession).filter(EaSession.account_id == account_id).first()
        if existing:
            existing.session_id  = session_token
            existing.license_key = req.license_key
            existing.status      = "ACTIVE"
            existing.last_ping   = datetime.now(timezone.utc)
            existing.meta_json   = json.dumps({
                "broker_server": req.broker_server,
                "device_hash":   req.device_hash,
                "mt5_build":     req.mt5_build,
            })
        else:
            db.add(EaSession(
                account_id=account_id,
                session_id=session_token,
                license_key=req.license_key,
                status="ACTIVE",
                meta_json=json.dumps({
                    "broker_server": req.broker_server,
                    "device_hash":   req.device_hash,
                    "mt5_build":     req.mt5_build,
                }),
            ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"[ENGINE] EaSession DB error: {e}")
    finally:
        db.close()

    config = _get_risk_config(account_id)

    _notify("DEFCON3_SILENT", {
        "account_id": account_id,
        "message":    f"🟢 EA connected: {account_id} [{lic_data['tier']}]",
    })
    logger.info(f"[ENGINE] Handshake OK: {account_id}")

    return {
        "status":        "ok",
        "session_token": session_token,
        "challenge":     challenge,
        "config":        config,
        "tier":          lic_data["tier"],
        "strategy_id":   lic_data["strategy_id"],
        "server_time":   datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════
# POST /ea/heartbeat
# ══════════════════════════════════════════════════════════════════

@router.post("/heartbeat")
async def ea_heartbeat(req: HeartbeatRequest, request: Request):
    session = _get_session(req.session_token)
    if not session:
        raise HTTPException(401, "Session expired. Gọi lại /ea/handshake.")

    account_id = session["account_id"]
    if not rate_check("heartbeat", account_id, limit=4, window=60):
        raise HTTPException(429, "Heartbeat quá nhanh.")

    if req.challenge_response:
        if not _verify_challenge_response(req.session_token, req.challenge_response, account_id):
            raise HTTPException(401, "Challenge response không hợp lệ.")

    # Sliding window refresh (FIX 1: Redis EXPIRE reset)
    ea_session_refresh_ttl(req.session_token)
    new_challenge = _generate_challenge(req.session_token)

    # Update equity trong session cache
    session.update({"equity": req.equity, "balance": req.balance})
    ea_session_set(req.session_token, session, ttl=TOKEN_TTL_SECONDS)

    # Update DB last_ping (async — không block response)
    _update_session_ping(req.session_token, req.equity, req.balance)

    config = _get_risk_config(account_id)
    config_hash = hashlib.md5(json.dumps(config, sort_keys=True).encode()).hexdigest()[:8]
    config_changed = bool(req.config_version and req.config_version != config_hash)

    radar_context = None
    if req.symbols:
        radar_context = await _get_radar_context(req.symbols, req.tf or "H1")

    response = {
        "status":         "ok",
        "challenge":      new_challenge,
        "server_time":    datetime.now(timezone.utc).isoformat(),
        "config_version": config_hash,
        "config_changed": config_changed,
        "is_locked":      config.get("is_locked", False),
        "arm":            config.get("arm", False),
    }
    if config_changed:
        response["config"] = config
    if radar_context:
        response["radar"] = radar_context

    return response


def _update_session_ping(session_token: str, equity: float, balance: float):
    """DB update trong thread pool — không block heartbeat response."""
    import threading
    def _do():
        db = SessionLocal()
        try:
            ea = db.query(EaSession).filter(EaSession.session_id == session_token).first()
            if ea:
                ea.equity    = equity
                ea.balance   = balance
                ea.last_ping = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    threading.Thread(target=_do, daemon=True).start()


# ══════════════════════════════════════════════════════════════════
# POST /ea/risk-check
# ══════════════════════════════════════════════════════════════════

@router.post("/risk-check")
async def ea_risk_check(req: RiskCheckRequest, request: Request):
    session = _get_session(req.session_token)
    if not session:
        raise HTTPException(401, "Session expired. Gọi lại /ea/handshake.")

    account_id = session["account_id"]
    if not rate_check("risk", account_id, limit=20, window=60):
        raise HTTPException(429, "Risk check quá nhanh.")

    config = _get_risk_config(account_id)
    action = "ALLOW"
    kill_reason = None

    if config.get("is_locked"):
        action = "KILL"
        kill_reason = "Account đã bị lock bởi admin."
    elif req.equity > 0 and req.balance > 0:
        daily_limit = config.get("daily_limit_money", 150.0)
        max_dd_pct  = config.get("max_dd", 10.0)
        dd_type     = config.get("dd_type", "STATIC")

        if req.daily_pnl < 0 and abs(req.daily_pnl) >= daily_limit:
            action = "KILL"
            kill_reason = f"Daily loss limit: ${abs(req.daily_pnl):.2f} >= ${daily_limit:.2f}"
            _notify("DEFCON1_ALERT", {
                "account_id": account_id,
                "message":    f"🚨 KILL {account_id} — Daily ${abs(req.daily_pnl):.2f}",
                "kill_reason": kill_reason,
            })
            _publish_risk_alert({"account_id": account_id, "reason": kill_reason,
                                  "equity": req.equity, "daily_pnl": req.daily_pnl})

        elif dd_type == "STATIC":
            dd_pct = (req.balance - req.equity) / req.balance * 100 if req.balance > 0 else 0
            if dd_pct >= max_dd_pct:
                action = "KILL"
                kill_reason = f"Max DD: {dd_pct:.1f}% >= {max_dd_pct:.1f}%"
                _notify("DEFCON1_ALERT", {
                    "account_id": account_id,
                    "message":    f"🚨 KILL {account_id} — DD {dd_pct:.1f}%",
                    "kill_reason": kill_reason,
                })
                _publish_risk_alert({"account_id": account_id, "reason": kill_reason,
                                      "equity": req.equity, "dd_pct": dd_pct})

    return {
        "action":      action,
        "kill_reason": kill_reason,
        "equity":      req.equity,
        "balance":     req.balance,
        "daily_pnl":   req.daily_pnl,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════
# POST /ea/trade-event
# ══════════════════════════════════════════════════════════════════

@router.post("/trade-event")
async def ea_trade_event(req: TradeEventRequest, request: Request):
    """
    FIX 2: KHÔNG ghi DB trực tiếp nữa.
    Publish vào stream:trade-events → event_persister consumer ghi DB.
    EA nhận 200 OK ngay lập tức, không chờ DB write.
    """
    session = _get_session(req.session_token)
    if not session:
        raise HTTPException(401, "Session expired. Gọi lại /ea/handshake.")

    account_id = session["account_id"]
    ts = datetime.now(timezone.utc).isoformat()

    if req.event_type == "OPEN":
        _publish_trade_event("TRADE_OPENED", {
            "account_id": account_id,
            "ticket":     req.ticket,
            "symbol":     req.symbol,
            "trade_type": req.trade_type,
            "volume":     req.volume,
            "open_price": req.price,
            "opened_at":  ts,
        })
        # Also notify Telegram
        _notify("TRADE_OPENED", {
            "account_id": account_id,
            "ticket":     req.ticket,
            "symbol":     req.symbol,
            "trade_type": req.trade_type,
            "volume":     req.volume,
            "price":      req.price,
        })

    elif req.event_type == "CLOSE":
        _publish_trade_event("TRADE_CLOSED", {
            "account_id":  account_id,
            "ticket":      req.ticket,
            "symbol":      req.symbol,
            "close_price": req.price,
            "pnl":         req.pnl,
            "rr_ratio":    req.rr_ratio,
            "closed_at":   ts,
        })
        _notify("TRADE_CLOSED", {
            "account_id": account_id,
            "ticket":     req.ticket,
            "symbol":     req.symbol,
            "pnl":        req.pnl,
            "rr_ratio":   req.rr_ratio,
        })

    return {"status": "ok", "event_type": req.event_type, "ticket": req.ticket}


# ══════════════════════════════════════════════════════════════════
# GET /ea/config/{account_id}
# ══════════════════════════════════════════════════════════════════

@router.get("/config/{account_id}")
async def ea_get_config(account_id: str, version: Optional[str] = None):
    config = _get_risk_config(account_id)
    config_hash = hashlib.md5(json.dumps(config, sort_keys=True).encode()).hexdigest()[:8]
    if version and version == config_hash:
        from fastapi.responses import Response
        return Response(status_code=304)
    return {"config": config, "version": config_hash}


# ══════════════════════════════════════════════════════════════════
# POST /ea/revoke
# ══════════════════════════════════════════════════════════════════

@router.post("/revoke")
async def ea_revoke(req: RevokeRequest):
    if req.admin_secret != ADMIN_SECRET_KEY:
        raise HTTPException(403, "Admin secret không đúng.")

    account_id = req.account_id
    tokens = ea_sessions_for_account(account_id)
    for token in tokens:
        ea_session_delete(token)

    # Update DB
    db = SessionLocal()
    try:
        db.query(EaSession).filter(
            EaSession.account_id == account_id,
            EaSession.status == "ACTIVE",
        ).update({"status": "REVOKED", "ended_at": datetime.now(timezone.utc)})
        db.commit()
    finally:
        db.close()

    _notify("DEFCON3_SILENT", {
        "account_id": account_id,
        "message":    f"🔴 EA revoked: {account_id} by admin",
    })

    return {"status": "ok", "account_id": account_id, "sessions_revoked": len(tokens)}
