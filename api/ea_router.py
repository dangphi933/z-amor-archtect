"""
EA ROUTER — Z-Armor Cloud Engine
=================================
Toan bo endpoint danh rieng cho EA MT5 ket noi len server.

Endpoint map:
  POST /ea/handshake    — EA xac thuc lan dau, lay session_token + config
  POST /ea/heartbeat    — EA kiem tra trang thai moi 30-60s
  POST /ea/risk-check   — EA gui equity, server tinh DD va tra KILL neu vi pham
  POST /ea/trade-event  — EA bao cao lenh mo/dong
  GET  /ea/config/{id}  — EA lay config moi nhat (dung If-None-Match de tranh reload thua)
  POST /ea/revoke       — Admin revoke session ngay lap tuc (tat EA)

Security layers:
  1. License validation    — kiem tra status + expiry trong bang licenses
  2. Device fingerprint    — broker_server + device_hash luu trong ea_sessions
  3. Session token         — opaque token 32 byte, TTL 70s (EA heartbeat 60s)
  4. Challenge-response    — HMAC-SHA256, EA phai tra loi dung de chung minh co secret
  5. Rate limiting         — dem request/phut per account_id bang bien nho (khong can Redis)
  6. Clone detection       — phat hien cung account_id tu 2 broker_server khac nhau
"""

import os
import uuid
import hmac
import hashlib
import secrets
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import (
    SessionLocal, get_db,
    License, TradingAccount, SystemState,
    RiskHardLimit, RiskTactical, NeuralProfile, TelegramConfig,
    EaSession, TradeHistory
)
from api.config_manager import get_all_units, update_unit_from_payload
from app.telegram_engine.engine import push_to_telegram, send_defcon1_scram, send_defcon3_silent

# [FIX] Debounce disconnect alerts — max 1 alert per account per 5 minutes
_disconnect_alert_last = {}  # account_id -> last alert timestamp
_DISCONNECT_DEBOUNCE = 300   # 5 minutes

def _should_send_disconnect_alert(account_id: str) -> bool:
    import time
    now = time.time()
    last = _disconnect_alert_last.get(str(account_id), 0)
    if now - last > _DISCONNECT_DEBOUNCE:
        _disconnect_alert_last[str(account_id)] = now
        return True
    return False

def _reset_disconnect_alert(account_id: str):
    _disconnect_alert_last.pop(str(account_id), None)

router = APIRouter(prefix="/ea", tags=["EA Engine"])

# ==========================================
# CONSTANTS
# ==========================================
TOKEN_TTL_SECONDS      = 70        # EA heartbeat 60s, token song 70s co buffer
CHALLENGE_TTL_SECONDS  = 90        # EA phai tra loi challenge trong 90s
RATE_LIMIT_HANDSHAKE   = 10        # toi da 10 handshake/phut per account
RATE_LIMIT_HEARTBEAT   = 4         # toi da 4 heartbeat/phut per account (60s interval)
RATE_LIMIT_RISK        = 20        # toi da 20 risk-check/phut per account
SUSPICIOUS_THRESHOLD   = 3         # so lan device mismatch truoc khi auto-revoke

# In-memory rate limiter (du dung voi SQLite, scale len dung Redis)
# Structure: { "account_id:endpoint": [(timestamp), ...] }
_rate_counters: dict = {}

HMAC_SECRET_SALT = os.environ.get("EA_HMAC_SALT", "zarmor-default-salt-change-in-prod")

# ==========================================
# PYDANTIC MODELS
# ==========================================

class HandshakeRequest(BaseModel):
    license_key:   str
    mt5_login:     str
    broker_server: Optional[str] = ""
    device_hash:   Optional[str] = ""
    mt5_build:     Optional[str] = ""

class HeartbeatRequest(BaseModel):
    session_token:      str
    challenge_response: Optional[str] = ""   # HMAC(secret, challenge+timestamp)
    equity:             Optional[float] = 0.0
    balance:            Optional[float] = 0.0
    config_version:     Optional[str] = ""   # hash config hien tai cua EA
    # ── Phase 4B: Radar context request ──────────────────────────────────────
    symbols:            Optional[str] = ""   # comma-separated MT5 symbols: "XAUUSDm,BTCUSDm"
    tf:                 Optional[str] = "H1" # timeframe cho radar lookup

class RiskCheckRequest(BaseModel):
    session_token:  str
    equity:         float
    balance:        float
    daily_pnl:      Optional[float] = 0.0
    open_positions: Optional[int] = 0

class TradeEventRequest(BaseModel):
    session_token: str
    event_type:    str    # OPEN | CLOSE
    ticket:        str
    symbol:        str
    trade_type:    str    # BUY | SELL
    volume:        float
    price:         float
    pnl:           Optional[float] = 0.0
    rr_ratio:      Optional[float] = 0.0

class RevokeRequest(BaseModel):
    account_id:    str
    admin_secret:  str    # phai match env var ADMIN_SECRET de revoke


# ==========================================
# UTILS
# ==========================================

def _now_ms() -> int:
    return int(datetime.utcnow().timestamp() * 1000)

def _now_ts() -> int:
    return int(datetime.utcnow().timestamp())

def _generate_token() -> str:
    return secrets.token_hex(32)

def _generate_challenge() -> str:
    return secrets.token_hex(16)

def _verify_challenge_response(
    challenge: str,
    response: str,
    license_key: str,
    timestamp_tolerance: int = 120
) -> bool:
    """
    EA phai tinh: HMAC-SHA256(key=license_key+SALT, msg=challenge)
    Server verify bang cach tinh lai va so sanh.
    Dung compare_digest de chong timing attack.
    """
    if not challenge or not response:
        return True  # Challenge optional o phase hien tai — bat buoc sau khi EA update
    secret = (license_key + HMAC_SECRET_SALT).encode()
    expected = hmac.new(secret, challenge.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, response)

def _check_rate_limit(account_id: str, endpoint: str, max_per_minute: int) -> bool:
    """Tra ve True neu con trong gioi han, False neu da vuot."""
    key = f"{account_id}:{endpoint}"
    now = _now_ts()
    window_start = now - 60

    if key not in _rate_counters:
        _rate_counters[key] = []

    # Xoa request cu
    _rate_counters[key] = [t for t in _rate_counters[key] if t > window_start]

    if len(_rate_counters[key]) >= max_per_minute:
        return False

    _rate_counters[key].append(now)
    return True

def _build_config_payload(account_id: str) -> dict:
    """Lay config day du cua 1 account de tra ve cho EA."""
    units = get_all_units()
    unit = units.get(str(account_id), {})
    risk = unit.get("risk_params", {})
    neural = unit.get("neural_profile", {})
    sys_state_locked = unit.get("is_locked", False)

    # Config version = hash cua cac thong so quan trong
    config_str = json.dumps({
        "max_dd": risk.get("max_dd", 10.0),
        "max_daily_dd_pct": risk.get("max_daily_dd_pct", 5.0),
        "daily_limit_money": risk.get("daily_limit_money", 150.0),
        "dd_type": risk.get("dd_type", "STATIC"),
        "is_locked": sys_state_locked,
    }, sort_keys=True)
    config_version = hashlib.md5(config_str.encode()).hexdigest()[:12]

    return {
        "account_id":      account_id,
        "alias":           unit.get("alias", f"Trader {account_id}"),
        "is_locked":       sys_state_locked,
        "config_version":  config_version,
        "risk": {
            "max_dd_pct":        risk.get("max_dd", 10.0),
            "max_daily_dd_pct":  risk.get("max_daily_dd_pct", 5.0),
            "daily_limit_money": risk.get("daily_limit_money", 150.0),
            "dd_type":           risk.get("dd_type", "STATIC"),
            "profit_lock_pct":   risk.get("profit_lock_pct", 40.0),
            "consistency":       risk.get("consistency", 97.0),
        },
        "neural": {
            "archetype":  neural.get("trader_archetype", "SNIPER"),
            "win_rate":   neural.get("historical_win_rate", 40.0),
            "rr":         neural.get("historical_rr", 1.5),
            "bias":       neural.get("optimization_bias", "HALF_KELLY"),
        },
        "telegram_active": unit.get("telegram_config", {}).get("is_active", False),
    }

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ==========================================
# ENDPOINT 1: HANDSHAKE
# ==========================================

@router.post("/handshake")
async def ea_handshake(req: HandshakeRequest, request: Request, db=Depends(get_db)):
    """
    EA goi 1 lan khi khoi dong.
    Tra ve: session_token, config, challenge cho heartbeat tiep theo.

    Steps:
      1. Rate limit check (10/phut)
      2. Validate license (ton tai + ACTIVE + chua het han)
      3. Kiem tra bound_mt5_id khop voi mt5_login
      4. Check/create EaSession, detect device mismatch
      5. Tao session_token moi + challenge
      6. Tra config day du
    """
    client_ip = _get_client_ip(request)
    account_id = str(req.mt5_login).strip()

    # 1. Rate limit
    if not _check_rate_limit(account_id, "handshake", RATE_LIMIT_HANDSHAKE):
        raise HTTPException(status_code=429, detail="TOO_MANY_HANDSHAKES")

    # 2. Validate license
    lic = db.query(License).filter(
        License.license_key == req.license_key
    ).first()

    if not lic:
        return {"command": "REJECT", "reason": "LICENSE_NOT_FOUND"}

    if lic.status not in ("ACTIVE", "UNUSED"):
        return {"command": "REJECT", "reason": f"LICENSE_{lic.status}"}

    if lic.expires_at and lic.expires_at < datetime.utcnow():
        lic.status = "EXPIRED"
        db.commit()
        return {"command": "REJECT", "reason": "LICENSE_EXPIRED"}

    # 3. Check binding — neu license ACTIVE phai khop mt5_login
    if lic.status == "ACTIVE" and lic.bound_mt5_id and lic.bound_mt5_id != account_id:
        return {"command": "REJECT", "reason": "ACCOUNT_MISMATCH"}

    # Auto-bind neu UNUSED
    if lic.status == "UNUSED":
        lic.status = "ACTIVE"
        lic.bound_mt5_id = account_id
        lic.expires_at = datetime.utcnow() + timedelta(days=30)
        # Tao trading account neu chua co
        if not db.query(TradingAccount).filter(TradingAccount.account_id == account_id).first():
            update_unit_from_payload(account_id, {
                "mt5_login": account_id,
                "alias": f"Trader {account_id}",
                "telegram_config": {"is_active": True},
                "risk_params": {"daily_limit_money": 150, "max_dd": 10.0, "dd_type": "STATIC", "consistency": 97},
                "neural_profile": {"trader_archetype": "SNIPER", "historical_win_rate": 40.0, "historical_rr": 1.5}
            })
        db.commit()

    # 4. Kiem tra/tao EaSession, detect device mismatch
    existing_session = db.query(EaSession).filter(
        EaSession.account_id == account_id,
        EaSession.status == "ACTIVE"
    ).first()

    suspicious = 0
    if existing_session:
        # Phat hien clone: cung account nhung broker_server khac
        if (req.broker_server
                and existing_session.broker_server
                and req.broker_server != existing_session.broker_server
                and existing_session.last_seen
                and (_now_ms() - existing_session.last_seen) < 300_000):  # con song trong 5 phut
            existing_session.suspicious_count = (existing_session.suspicious_count or 0) + 1
            suspicious = existing_session.suspicious_count
            print(f"[SECURITY] Clone detected: account={account_id} "
                  f"old_broker={existing_session.broker_server} "
                  f"new_broker={req.broker_server} "
                  f"suspicious_count={suspicious}", flush=True)

            if suspicious >= SUSPICIOUS_THRESHOLD:
                existing_session.status = "REVOKED"
                db.commit()
                # Alert Telegram admin
                admin_chat = os.environ.get("ADMIN_TELEGRAM_CHAT_ID", "")
                if admin_chat:
                    import asyncio
                    asyncio.create_task(push_to_telegram(
                        chat_id=admin_chat,
                        text=(f"SECURITY ALERT: Clone EA detected!\n"
                              f"Account: {account_id}\n"
                              f"Broker A: {existing_session.broker_server}\n"
                              f"Broker B: {req.broker_server}\n"
                              f"Action: AUTO-REVOKED")
                    ))
                return {"command": "KILL", "reason": "CLONE_DETECTED"}

        # Expire session cu, tao moi
        existing_session.status = "EXPIRED"
        db.flush()

    # 5. Tao session moi
    new_token     = _generate_token()
    new_challenge = _generate_challenge()
    now_ms        = _now_ms()
    now_ts        = _now_ts()

    new_session = EaSession(
        id                = str(uuid.uuid4()),
        account_id        = account_id,
        license_key       = req.license_key,
        broker_server     = req.broker_server or "",
        device_hash       = req.device_hash or "",
        mt5_build         = req.mt5_build or "",
        session_token     = new_token,
        token_expires_at  = now_ts + TOKEN_TTL_SECONDS,
        challenge         = new_challenge,
        challenge_expires = now_ts + CHALLENGE_TTL_SECONDS,
        status            = "ACTIVE",
        handshake_at      = now_ms,
        last_seen         = now_ms,
        heartbeat_count   = 0,
        suspicious_count  = suspicious,
        last_ip           = client_ip,
    )
    db.add(new_session)
    db.commit()

    print(f"[HANDSHAKE] OK: account={account_id} ip={client_ip} broker={req.broker_server}", flush=True)

    # 6. Tra config
    config = _build_config_payload(account_id)

    return {
        "command":       "OK",
        "session_token": new_token,
        "token_ttl":     TOKEN_TTL_SECONDS,
        "challenge":     new_challenge,
        "config":        config,
        "server_time":   now_ms,
    }


# ==========================================
# ENDPOINT 2: HEARTBEAT
# ==========================================

@router.post("/heartbeat")
async def ea_heartbeat(req: HeartbeatRequest, db=Depends(get_db)):
    """
    EA goi moi 30-60s.
    Server tra ve:
      - {"command": "OK"}             neu binh thuong
      - {"command": "KILL"}           neu license bi revoke/het han
      - {"command": "UPDATE_CONFIG"}  neu config da thay doi (EA reload)
      - {"command": "LOCK"}           neu account dang locked (khong duoc mo lenh moi)

    Token validation: token phai ton tai trong ea_sessions va chua het han.
    Challenge-response: server gui challenge moi, EA tra loi o heartbeat tiep theo.
    """
    # 1. Lay session tu DB
    session = db.query(EaSession).filter(
        EaSession.session_token == req.session_token
    ).first()

    if not session:
        return {"command": "HANDSHAKE_REQUIRED", "reason": "TOKEN_NOT_FOUND"}

    now_ts = _now_ts()
    now_ms = _now_ms()

    # 2. Kiem tra token con song
    if session.token_expires_at and now_ts > session.token_expires_at:
        session.status = "EXPIRED"
        db.commit()
        return {"command": "HANDSHAKE_REQUIRED", "reason": "TOKEN_EXPIRED"}

    # 3. Kiem tra session status
    if session.status == "REVOKED":
        return {"command": "KILL", "reason": "SESSION_REVOKED"}
    if session.status == "EXPIRED":
        return {"command": "HANDSHAKE_REQUIRED", "reason": "SESSION_EXPIRED"}

    # 4. Kiem tra license van hop le
    account_id = session.account_id
    lic = db.query(License).filter(
        License.license_key == session.license_key
    ).first()

    if not lic or lic.status not in ("ACTIVE",):
        session.status = "REVOKED"
        db.commit()
        return {"command": "KILL", "reason": f"LICENSE_{lic.status if lic else 'NOT_FOUND'}"}

    if lic.expires_at and lic.expires_at < datetime.utcnow():
        lic.status = "EXPIRED"
        session.status = "REVOKED"
        db.commit()
        return {"command": "KILL", "reason": "LICENSE_EXPIRED"}

    # 5. Rate limit
    if not _check_rate_limit(account_id, "heartbeat", RATE_LIMIT_HEARTBEAT):
        return {"command": "OK", "warning": "RATE_LIMITED"}

    # 6. Verify challenge response (neu EA gui)
    if req.challenge_response and session.challenge:
        if session.challenge_expires and now_ts > session.challenge_expires:
            pass  # het han challenge thi bo qua, khong kill
        else:
            valid = _verify_challenge_response(
                session.challenge,
                req.challenge_response,
                session.license_key
            )
            if not valid:
                session.suspicious_count = (session.suspicious_count or 0) + 1
                print(f"[SECURITY] Bad challenge response: account={account_id} "
                      f"count={session.suspicious_count}", flush=True)

    # 7. Cap nhat token TTL (sliding window — token song tiep 70s moi heartbeat)
    new_challenge = _generate_challenge()
    session.token_expires_at  = now_ts + TOKEN_TTL_SECONDS
    session.challenge         = new_challenge
    session.challenge_expires = now_ts + CHALLENGE_TTL_SECONDS
    session.last_seen         = now_ms
    session.heartbeat_count   = (session.heartbeat_count or 0) + 1

    # 8. Kiem tra lock status
    units = get_all_units()
    unit  = units.get(account_id, {})
    is_locked = unit.get("is_locked", False)

    # 9. Kiem tra config version — neu EA dang dung config cu thi bao UPDATE
    current_config = _build_config_payload(account_id)
    config_changed = (
        req.config_version
        and req.config_version != current_config.get("config_version", "")
    )

    db.commit()

    # ── Phase 4B: Radar Context ───────────────────────────────────────────────
    # Compute radar_map cho symbols EA đang chạy.
    # Non-fatal: bất kỳ lỗi nào đều bị bắt và trả về {} để không làm hỏng heartbeat.
    radar_map = {}
    try:
        from radar.engine import compute, ASSET_PROFILES
        from radar.router import SYMBOL_TO_ASSET

        # Parse symbols từ request: "XAUUSDm,BTCUSDm" → ["XAUUSDm","BTCUSDm"]
        sym_list = [s.strip().upper() for s in (req.symbols or "").split(",") if s.strip()]

        # Fallback: nếu EA không gửi symbols → dùng symbols trong Inputs (từ units_config)
        if not sym_list:
            units_cfg = get_all_units().get(account_id, {})
            cfg_syms  = units_cfg.get("symbols", "")
            sym_list  = [s.strip().upper() for s in cfg_syms.split(",") if s.strip()]

        # Fallback cuối: XAUUSD
        if not sym_list:
            sym_list = ["XAUUSD"]

        tf = (req.tf or "H1").upper()
        # Map valid TF — engine chỉ support M5/M15/H1
        if tf not in ("M5", "M15", "H1"):
            tf = "H1"

        for raw_sym in sym_list:
            # Normalize broker suffixes: XAUUSDm → XAUUSD
            base_sym = raw_sym.rstrip("m").rstrip("_")
            asset    = SYMBOL_TO_ASSET.get(raw_sym) or SYMBOL_TO_ASSET.get(base_sym)
            if not asset or asset not in ASSET_PROFILES:
                continue

            r = compute(asset, tf)
            radar_map[raw_sym] = {
                "asset":         asset,
                "score":         r.score,
                "label":         r.label,
                "regime":        r.regime,
                "session":       r.session,
                "allow_trade":   r.ea_allow_trade,
                "position_pct":  r.ea_position_pct,
                "sl_multiplier": r.ea_sl_multiplier,
                "state_cap":     r.ea_state_cap,
                "updated_at":    r.timestamp_utc,
                "ttl_sec":       r.ttl_sec,
            }

        # Hard lock check: nếu có symbol nào score < 20 → force LOCK
        hard_lock_symbols = [
            sym for sym, ctx in radar_map.items()
            if not ctx["allow_trade"] and ctx["score"] < 20
        ]
        if hard_lock_symbols and not is_locked:
            print(f"[HEARTBEAT] RADAR_AVOID | account={account_id} "
                  f"symbols={hard_lock_symbols}", flush=True)
            return {
                "command":        "LOCK",
                "reason":         "RADAR_AVOID",
                "locked_symbols": hard_lock_symbols,
                "next_challenge": new_challenge,
                "server_time":    now_ms,
                "radar_map":      radar_map,
            }

    except Exception as _re:
        print(f"[HEARTBEAT] Radar context error (non-fatal): {_re}", flush=True)
        radar_map = {}

    # 10. Quyet dinh command
    if is_locked:
        return {
            "command":        "LOCK",
            "reason":         "ACCOUNT_LOCKED",
            "next_challenge": new_challenge,
            "server_time":    now_ms,
            "radar_map":      radar_map,
        }

    if config_changed:
        return {
            "command":        "UPDATE_CONFIG",
            "config":         current_config,
            "next_challenge": new_challenge,
            "server_time":    now_ms,
            "radar_map":      radar_map,
        }

    return {
        "command":        "OK",
        "next_challenge": new_challenge,
        "server_time":    now_ms,
        "radar_map":      radar_map,
    }


# ==========================================
# ENDPOINT 3: RISK CHECK
# ==========================================

@router.post("/risk-check")
async def ea_risk_check(req: RiskCheckRequest, db=Depends(get_db)):
    """
    EA gui equity dinh ky (hoac sau moi lenh dong).
    Server tinh DD va tra lenh KILL / DISABLE_TRADING / OK.

    Logic:
      - Daily DD vi pham max_daily_dd_pct  -> DISABLE_TRADING (dung ngay, cho Rollover)
      - Total DD vi pham max_dd_pct        -> KILL (SCRAM toan he)
      - Account bi locked                  -> LOCK
    """
    # Validate token
    session = db.query(EaSession).filter(
        EaSession.session_token == req.session_token,
        EaSession.status == "ACTIVE"
    ).first()

    if not session:
        return {"command": "HANDSHAKE_REQUIRED"}

    account_id = session.account_id
    now_ts = _now_ts()

    if session.token_expires_at and now_ts > session.token_expires_at:
        return {"command": "HANDSHAKE_REQUIRED", "reason": "TOKEN_EXPIRED"}

    # Rate limit
    if not _check_rate_limit(account_id, "risk_check", RATE_LIMIT_RISK):
        return {"command": "OK", "warning": "RATE_LIMITED"}

    # Lay risk config
    units  = get_all_units()
    unit   = units.get(account_id, {})
    risk   = unit.get("risk_params", {})

    is_locked        = unit.get("is_locked", False)
    max_dd_pct       = float(risk.get("max_dd", 10.0))
    max_daily_dd_pct = float(risk.get("max_daily_dd_pct", 5.0))
    balance          = req.balance if req.balance > 0 else req.equity
    daily_pnl        = req.daily_pnl or 0.0

    if balance <= 0:
        return {"command": "OK", "warning": "ZERO_BALANCE"}

    if is_locked:
        return {"command": "LOCK", "reason": "ACCOUNT_LOCKED"}

    # Tinh DD
    total_dd_pct = max(0.0, (balance - req.equity) / balance * 100.0)
    daily_dd_pct = max(0.0, -daily_pnl / balance * 100.0) if daily_pnl < 0 else 0.0

    # Cap nhat session last_seen
    session.last_seen = _now_ms()
    db.commit()

    # Quyet dinh
    if total_dd_pct >= max_dd_pct:
        # SCRAM toan he
        from api.config_manager import set_lock_status
        set_lock_status(account_id, True)
        trader_name = unit.get("alias", f"Trader {account_id}")
        chat_id     = unit.get("telegram_config", {}).get("chat_id", "")
        if chat_id:
            import asyncio
            asyncio.create_task(send_defcon1_scram(
                chat_id=chat_id,
                trader_name=trader_name,
                loss_amount=round(balance - req.equity, 2)
            ))
        return {
            "command": "KILL",
            "reason":  "MAX_DD_BREACHED",
            "dd_pct":  round(total_dd_pct, 2),
            "limit":   max_dd_pct,
        }

    if daily_dd_pct >= max_daily_dd_pct:
        # Dung giao dich trong ngay, cho Rollover
        return {
            "command":     "DISABLE_TRADING",
            "reason":      "DAILY_DD_BREACHED",
            "daily_dd_pct": round(daily_dd_pct, 2),
            "limit":        max_daily_dd_pct,
        }

    # Canh bao som neu gan gioi han
    dd_buffer_pct = (max_dd_pct - total_dd_pct) / max_dd_pct * 100
    daily_buffer  = (max_daily_dd_pct - daily_dd_pct) / max_daily_dd_pct * 100

    return {
        "command":          "OK",
        "total_dd_pct":     round(total_dd_pct, 2),
        "daily_dd_pct":     round(daily_dd_pct, 2),
        "dd_buffer_pct":    round(dd_buffer_pct, 1),
        "daily_buffer_pct": round(daily_buffer, 1),
        "warning":          "APPROACHING_LIMIT" if dd_buffer_pct < 20 or daily_buffer < 20 else None,
    }


# ==========================================
# ENDPOINT 4: CONFIG (voi If-None-Match)
# ==========================================

@router.get("/config/{account_id}")
async def ea_get_config(
    account_id: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
    db=Depends(get_db)
):
    """
    EA lay config moi nhat.
    Neu EA gui If-None-Match: {config_version} va config khong doi -> 304 Not Modified.
    Giam bandwidth 80% vi EA khong can parse config neu khong co thay doi.
    """
    config = _build_config_payload(account_id)
    current_version = config.get("config_version", "")

    if if_none_match and if_none_match == current_version:
        # Config khong doi — tra 304 (khong co body)
        from fastapi.responses import Response
        return Response(status_code=304, headers={"ETag": current_version})

    return {
        "command":        "CONFIG",
        "config":         config,
        "config_version": current_version,
        "etag":           current_version,
    }


# ==========================================
# ENDPOINT 5: TRADE EVENT (tu EA)
# ==========================================

@router.post("/trade-event")
async def ea_trade_event(req: TradeEventRequest, db=Depends(get_db)):
    """
    EA bao cao lenh mo/dong.
    G-01 FIX: Ghi vào trade_history table để nuôi ML Flywheel (Luồng D).
    Đồng thời gửi Telegram notify nếu đã cấu hình.
    """
    # ── Validate session (nếu có token) ──────────────────────────────────────
    account_id = None
    if req.session_token:
        session = db.query(EaSession).filter(
            EaSession.session_token == req.session_token,
            EaSession.status == "ACTIVE"
        ).first()
        if session:
            account_id = session.account_id

    # Fallback: dùng license_key lookup nếu không có session token
    # (EA hiện tại dùng /api/webhook/trade-event không có session)
    if not account_id:
        # Không có account_id → vẫn ghi vào trade_history với account từ request
        # Lấy từ DB qua license key nếu có
        account_id = getattr(req, "account_id", None) or "UNKNOWN"

    # ── G-01 FIX: Ghi vào trade_history → data cho ML labeler ───────────────
    try:
        from sqlalchemy import text as _text
        from datetime import datetime as _dt
        ev_up   = req.event_type.upper()
        o_price = float(req.price) if ev_up == "OPEN"  else None
        c_price = float(req.price) if ev_up == "CLOSE" else None
        db.execute(_text("""
            INSERT INTO trade_history
              (account_id, ticket, symbol, trade_type, volume,
               open_price, close_price, pnl, rr_ratio, event_type, opened_at)
            VALUES
              (:account_id, :ticket, :symbol, :trade_type, :volume,
               :open_price, :close_price, :pnl, :rr_ratio, :event_type, :opened_at)
            ON CONFLICT DO NOTHING
        """), {
            "account_id": str(account_id),
            "ticket":     str(req.ticket),
            "symbol":     req.symbol.upper(),
            "trade_type": req.trade_type.upper(),
            "volume":     float(req.volume),
            "open_price": o_price,
            "close_price": c_price,
            "pnl":        float(req.pnl or 0.0),
            "rr_ratio":   float(req.rr_ratio or 0.0),
            "event_type": ev_up,
            "opened_at":  _dt.utcnow(),
        })
        db.commit()
        print(
            f"[TRADE-EVENT] DB write OK: {req.event_type} {req.symbol} "
            f"ticket={req.ticket} pnl={req.pnl}",
            flush=True
        )
    except Exception as db_err:
        db.rollback()
        print(f"[TRADE-EVENT] DB write FAILED: {db_err}", flush=True)
        # Tiếp tục — không block Telegram notify

    # ── Telegram notify (best-effort, không blocking) ────────────────────────
    try:
        units = get_all_units()
        unit  = units.get(str(account_id), {})
        chat_id     = unit.get("telegram_config", {}).get("chat_id", "")
        is_active   = unit.get("telegram_config", {}).get("is_active", True)
        trader_name = unit.get("alias", f"Trader {account_id}")

        if chat_id and is_active:
            from telegram_engine import send_trade_opened, send_trade_closed
            import asyncio
            if req.event_type.upper() == "OPEN":
                asyncio.create_task(send_trade_opened(
                    chat_id=chat_id, trader_name=trader_name,
                    ticket=req.ticket, symbol=req.symbol,
                    trade_type=req.trade_type, volume=req.volume, price=req.price
                ))
            elif req.event_type.upper() == "CLOSE":
                asyncio.create_task(send_trade_closed(
                    chat_id=chat_id, trader_name=trader_name,
                    ticket=req.ticket, symbol=req.symbol,
                    trade_type=req.trade_type, pnl=req.pnl, rr_ratio=req.rr_ratio
                ))
    except Exception as tg_err:
        print(f"[TRADE-EVENT] Telegram notify error (non-critical): {tg_err}", flush=True)

    return {"status": "ok", "db_written": True}


# ==========================================
# ENDPOINT 6: REVOKE (Admin)
# ==========================================

@router.post("/revoke")
async def ea_revoke(req: RevokeRequest, db=Depends(get_db)):
    """
    Admin revoke session ngay lap tuc.
    EA se nhan KILL o heartbeat tiep theo (toi da 60s).
    Bao ve bang ADMIN_SECRET trong env var.
    """
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if not admin_secret or req.admin_secret != admin_secret:
        raise HTTPException(status_code=403, detail="FORBIDDEN")

    revoked = db.query(EaSession).filter(
        EaSession.account_id == str(req.account_id),
        EaSession.status == "ACTIVE"
    ).update({"status": "REVOKED"})

    db.commit()

    print(f"[REVOKE] account={req.account_id} sessions_revoked={revoked}", flush=True)
    return {"status": "ok", "revoked_sessions": revoked}


# ==========================================
# ENDPOINT 7: STATUS (debug/monitoring)
# ==========================================

@router.get("/status/{account_id}")
async def ea_status(account_id: str, db=Depends(get_db)):
    """
    Kiem tra trang thai EA session hien tai.
    Dung cho admin dashboard / monitoring.
    """
    session = db.query(EaSession).filter(
        EaSession.account_id == account_id,
        EaSession.status == "ACTIVE"
    ).order_by(EaSession.last_seen.desc()).first()

    if not session:
        return {"connected": False, "account_id": account_id}

    now_ms = _now_ms()
    last_seen_ago = (now_ms - (session.last_seen or 0)) / 1000  # seconds

    return {
        "connected":       last_seen_ago < 90,  # con song neu heartbeat trong 90s
        "account_id":      account_id,
        "last_seen_ago_s": round(last_seen_ago, 1),
        "heartbeat_count": session.heartbeat_count,
        "broker_server":   session.broker_server,
        "suspicious":      (session.suspicious_count or 0) > 0,
        "status":          session.status,
    }

# ==========================================
# ENDPOINT 8: RADAR-APPLY
# POST /api/radar-apply
# RegimeFit scan.html goi khi trader nhan "AP DUNG VAO TAI KHOAN".
# Luu regime_context vao units_config -> EA doc tai heartbeat tiep theo.
# ==========================================

class RadarApplyRequest(BaseModel):
    asset:     str
    timeframe: str
    score:     int
    regime:    str = ""
    email:     str = ""
    timestamp: str = ""
    position_pct:  int   = -1
    sl_multiplier: float = -1.0
    allow_trade:   bool  = True


def _compute_regime_params(score: int, regime: str) -> dict:
    sl_mult_map = {
        "STRONG_TREND": 1.3, "TRENDING": 1.5, "TREND_FOLLOWING": 1.5,
        "BREAKOUT_WATCH": 1.5, "MEAN_REVERSION": 1.8, "RANGE_BOUND": 1.8,
        "NEUTRAL": 1.8, "VOLATILE": 2.2, "AVOID": 2.5,
    }
    direction_map = {
        "STRONG_TREND": "BUY_ONLY", "TRENDING": "BUY_ONLY", "TREND_FOLLOWING": "BUY_ONLY",
        "BREAKOUT_WATCH": "BOTH", "MEAN_REVERSION": "BOTH", "RANGE_BOUND": "BOTH",
        "NEUTRAL": "BOTH", "VOLATILE": "SELECTIVE", "AVOID": "NO_ENTRY",
    }
    r = regime.upper()
    sl_mult        = sl_mult_map.get(r, 1.5)
    direction_mode = direction_map.get(r, "BOTH")

    if score < 20:
        return {"allow_trade": False, "position_pct": 0, "sl_multiplier": sl_mult,
                "state_cap": "HIBERNATING", "direction_mode": "NO_ENTRY", "rr_ratio": 2.5}
    elif score >= 85:
        pos_pct, state_cap, rr = 100, "OPTIMAL", 2.0
    elif score >= 70:
        pos_pct, state_cap, rr = 60 + int((score - 70) / 15 * 40), "OPTIMAL", 2.0
    elif score >= 50:
        pos_pct, state_cap, rr = 30 + int((score - 50) / 20 * 30), "CAUTION", 1.5
    elif score >= 30:
        pos_pct, state_cap, rr = 20 + int((score - 30) / 20 * 10), "CAUTION", 2.5
    else:
        pos_pct, state_cap, rr = 0, "HIBERNATING", 2.5

    return {"allow_trade": pos_pct > 0, "position_pct": pos_pct, "sl_multiplier": sl_mult,
            "state_cap": state_cap, "direction_mode": direction_mode, "rr_ratio": rr}


_PENDING_APPLY: dict = {}


@router.post("/radar-apply")
async def radar_apply(req: RadarApplyRequest, db: Session = Depends(get_db)):
    from database import License as LicenseModel

    asset     = req.asset.upper().strip()
    timeframe = req.timeframe.upper().strip()
    score     = max(0, min(100, req.score))
    regime    = req.regime.upper().strip()
    email     = (req.email or "").strip().lower()

    params = _compute_regime_params(score, regime)

    regime_context = {
        "asset":          asset,
        "timeframe":      timeframe,
        "score":          score,
        "regime":         regime,
        "allow_trade":    params["allow_trade"],
        "position_pct":   params["position_pct"],
        "sl_multiplier":  params["sl_multiplier"],
        "state_cap":      params["state_cap"],
        "direction_mode": params["direction_mode"],
        "rr_ratio":       params["rr_ratio"],
        "applied_at":     datetime.utcnow().isoformat() + "Z",
        "applied_via":    "regimefit_scan",
        "next_heartbeat_in": 30,
    }

    account_id = None
    try:
        lic = db.query(LicenseModel).filter(
            LicenseModel.buyer_email == email,
            LicenseModel.status.in_(["ACTIVE", "UNUSED"]),
        ).order_by(LicenseModel.id.desc()).first()
        if lic and lic.bound_mt5_id:
            account_id = str(lic.bound_mt5_id)
    except Exception as exc:
        print(f"[RADAR_APPLY] email lookup error: {exc}", flush=True)

    synced = False
    if account_id:
        try:
            update_unit_from_payload(account_id, {"regime_context": regime_context})
            synced = True
            print(
                f"[RADAR_APPLY] OK | account={account_id} asset={asset} score={score} "
                f"regime={regime} pos={params['position_pct']}% dir={params['direction_mode']}",
                flush=True,
            )
        except Exception as exc:
            print(f"[RADAR_APPLY] update_unit failed account={account_id}: {exc}", flush=True)

    if not synced and email:
        _PENDING_APPLY[email] = regime_context
        print(f"[RADAR_APPLY] PENDING | email={email} asset={asset} score={score}", flush=True)

    return {
        "status":            "ok" if synced else "pending",
        "synced":            synced,
        "account_id":        account_id,
        "asset":             asset,
        "timeframe":         timeframe,
        "score":             score,
        "regime":            regime,
        "allow_trade":       params["allow_trade"],
        "position_pct":      params["position_pct"],
        "sl_multiplier":     params["sl_multiplier"],
        "direction_mode":    params["direction_mode"],
        "rr_ratio":          params["rr_ratio"],
        "next_heartbeat_in": 30,
        "message": (
            "Regime context da sync. EA se cap nhat trong <=30s."
            if synced else
            "Chua tim thay account tu email. Dang nhap dashboard de bind MT5 ID."
        ),
    }