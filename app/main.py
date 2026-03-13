"""
Z-ARMOR CLOUD ENGINE — main.py
================================
Refactor V8.3:
  - Tach EA engine sang api/ea_router.py (mount tai /ea/*)
  - Tach Pydantic models ra khoi route handlers
  - Giu nguyen 100% cac endpoint hien co (backward compatible)
  - Them startup health check + graceful error handling
  - Them periodic rollover task (chay background moi 60s)
  - Phase 4: Radar CRM Growth Loop (email-capture, subscribe-alert, track-share)

V8.3.1 (Multi-Strategy):
  - Mount strategy_router tai /strategy/*
  - Heartbeat inject strategy_profile tu license.strategy_id → EA doc qua g_profile
"""
import os
import json
import uuid
import time
import httpx
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Optional
from datetime import timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import sys
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn
# ── Internal imports ────────────────────────────────────────────
from database import engine, Base, SessionLocal, get_db, License
from api.schemas import LarkWebhookPayload, ZArmorResponse, BindLicensePayload, CheckoutPayload
from api.dashboard_service import (
    fetch_dashboard_state,
    update_webhook_heartbeat,
    update_webhook_positions,
    safe_telegram_send,
    api_log_trade,
    api_close_session,
    api_log_audit,
    api_get_trade_history,
    api_get_session_history,
    api_send_telegram,
    api_sync_history,
    invalidate_units_cache,
)
from api.config_manager import get_all_units, update_unit_from_payload, set_lock_status
from api.ai_guard_logic import api_get_ai_analysis
from telegram_engine import push_to_telegram, send_defcon3_silent, send_trade_opened, send_trade_closed
# ── EA Router ───────────────────────────────────────────────────
from api.ea_router import router as ea_router
# ── Phase 1: Radar + Live OHLCV ─────────────────────────────────
from radar.router import router as radar_router
# ── Phase 2: Performance Attribution + Scheduler ────────────────
from performance.router    import router as perf_router
from performance.scheduler import start_scheduler, stop_scheduler
from api.auth_router import router as auth_router
from api.identity_router import router as identity_router, init_identity
from api.billing_router import router as billing_router, init_billing
from api.radar_identity_router import router as radar_id_router, init_radar_identity
from api.growth_router import router as growth_router
from api.compliance_router import router as compliance_router, init_compliance
from auth import (
    init_auth, require_jwt, optional_jwt, decode_jwt_unsafe,
    set_auth_cookies, clear_auth_cookies,
    set_account_lock_db, check_account_locked_db,
    check_account_access, _upsert_za_user,
    _get_account_ids_for_email,
)
from remarketing_scheduler import start_remarketing_scheduler
# ── Phase 3: ML Regime Classifier ────────────────────────────────
from ml.router  import router as ml_router
from ml.trainer import start_trainer, stop_trainer
# ── Phase 4: Radar CRM — Growth Loop ────────────────────────────
from api.radar_crm_router import router as radar_crm_router
# ── Phase 4B: Radar Scheduler — auto-refresh cache every 30m ────
from radar.scheduler import start_radar_scheduler, stop_radar_scheduler
# ── Multi-Strategy — trader chọn preset, EA nhận qua heartbeat ──
from api.strategy_router import router as strategy_router
load_dotenv()
Base.metadata.create_all(bind=engine)
# ==========================================
# APP SETUP & LIFESPAN (NEW FASTAPI STANDARD)
# ==========================================
async def _rollover_loop():
    from api.config_manager import perform_daily_rollover
    from api.dashboard_service import reset_daily_cache, _mt5_cache
    while True:
        try:
            did_rollover = perform_daily_rollover()
            # BUG 1 FIX: Chỉ reset cache khi rollover thực sự xảy ra (đúng giờ rollover_hour)
            # TRƯỚC: reset_daily_cache() chạy mỗi 60s vô điều kiện → sai daily metrics
            # SAU:   chỉ reset khi perform_daily_rollover() trả về True
            if did_rollover:
                for acc_id in list(_mt5_cache.keys()):
                    try:
                        reset_daily_cache(acc_id)
                    except Exception as ce:
                        print(f"[ROLLOVER] Cache reset lỗi cho {acc_id}: {ce}", flush=True)
        except Exception as e:
            print(f"[ROLLOVER ERROR] {e}", flush=True)
        await asyncio.sleep(60)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Chay khi Server Start ---
    print("[STARTUP] Z-Armor Cloud Engine V8.3 dang khoi dong...", flush=True)
    rollover_task = asyncio.create_task(_rollover_loop())
    start_scheduler()   # Phase 2: Performance auto-compute moi 6h
    start_trainer()     # Phase 3: Weekly ML retrain
    start_radar_scheduler()  # Phase 4B: Radar cache auto-refresh every 30m
    # Sprint 1–6: Identity Platform init
    init_auth()
    init_identity()
    init_billing()
    init_radar_identity()
    init_compliance()
    asyncio.create_task(start_remarketing_scheduler())  # Sprint 5
    print("[STARTUP] OK — san sang nhan ket noi. Phases: EA + Radar + Perf + ML + CRM + RadarScheduler + Identity + Strategy", flush=True)

    yield # Cho o day trong suot qua trinh Server hoat dong

    # --- Chay khi Server Shutdown ---
    rollover_task.cancel()
    stop_scheduler()    # Phase 2: Dung scheduler sach
    stop_trainer()      # Phase 3: Dung ML trainer sach
    stop_radar_scheduler()  # Phase 4B: Dung radar scheduler
    print("[SHUTDOWN] Z-Armor da tat an toan.", flush=True)
app = FastAPI(
    title="Z-Armor Cloud Engine V8.3",
    description="Risk Management SaaS for MT5 EA — Radar CRM Growth Loop",
    version="8.3.0",
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://47.129.1.31:8000,http://47.129.1.31").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
# Mount EA Router tai /ea/*
app.include_router(ea_router)
# Phase 1: Radar Scan + Live OHLCV
app.include_router(radar_router, prefix="/radar")
# Phase 2: Performance Attribution
app.include_router(perf_router,  prefix="/performance")
# Phase 3: ML Regime Classifier
app.include_router(ml_router,    prefix="/ml")
# Phase 4: Radar CRM — Growth Loop endpoints
app.include_router(radar_crm_router)
app.include_router(auth_router,       prefix="/auth")
app.include_router(identity_router,   prefix="/user")
app.include_router(billing_router,    prefix="/billing")
app.include_router(radar_id_router,   prefix="/radar")
app.include_router(growth_router,     prefix="/growth")
app.include_router(compliance_router, prefix="/compliance")
# Multi-Strategy — GET /strategy/presets, POST /strategy/select, GET /strategy/active
app.include_router(strategy_router)
# Static files — admin dashboards (zone_control, ops, scan, salemain)
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
# ==========================================
# CONFIG
# ==========================================
LARK_APP_ID      = os.environ.get("LARK_APP_ID", "cli_a92af9524c789e1a")
LARK_APP_SECRET  = os.environ.get("LARK_APP_SECRET", "")
LARK_BASE_TOKEN  = os.environ.get("LARK_BASE_TOKEN", "lpl2bYwliawcO8s5ddOj1s58pcf")
LARK_TABLE_ID    = os.environ.get("LARK_TABLE_ID", "tblc25ZSsf3CkdgS")
LARK_LOG_TABLE_ID = os.environ.get("LARK_LOG_TABLE_ID", "tbl9Og6oEtEDzlNb")
SMTP_EMAIL       = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD    = os.environ.get("SMTP_PASSWORD", "")
# ==========================================
# LARK INTEGRATION
# ==========================================
async def send_lark_bot_log(message: str):
    lark_webhook_url = os.environ.get(
        "LARK_BOT_WEBHOOK",
        "https://open.larksuite.com/open-apis/bot/v2/hook/c636040c-dd79-4e9b-88b0-465bfec596cd"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(lark_webhook_url, headers={"Content-Type": "application/json"},
                              json={"msg_type": "text", "content": {"text": f"[Z-ARMOR AUTO-SALE]\n{message}"}})
    except Exception as e:
        print(f"[LARK BOT ERROR] {e}", flush=True)
async def get_lark_tenant_token():
    url     = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        return resp.json().get("tenant_access_token")
async def create_pending_order_in_lark(order_id, name, email, tier, amount):
    token = await get_lark_tenant_token()
    if not token:
        return False
    url     = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"fields": {
        "Order ID": order_id, "Buyer Name": name, "Buyer Email": email,
        "Purchased Tier": tier, "Amount Paid": float(amount), "Payment Status": "PENDING"
    }}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        return resp.status_code == 200
async def log_license_to_lark(order_id: str, license_key: str, status: str = "SUCCESS"):
    token = await get_lark_tenant_token()
    if not token:
        return False
    url     = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_LOG_TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"fields": {
        "Thoi gian": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "ID Don": order_id, "Key da cap": license_key, "Trang thai": status
    }}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            return resp.status_code == 200
        except Exception as e:
            print(f"[LARK LOG ERROR] {e}", flush=True)
            return False
def send_license_email_to_customer(receiver_email: str, buyer_name: str, tier: str, license_key: str):
    """
    Gửi email license key cho customer
    Bao gồm: license key + link dashboard + hướng dẫn
    """
    if not SMTP_EMAIL or "email_cua_sep" in SMTP_EMAIL:
        return False

    # Dashboard URL
    dashboard_url = os.environ.get("NEW_BACKEND_URL", "http://47.129.1.31:8000")
    dashboard_link = f"{dashboard_url}/web/"

    msg = MIMEMultipart("alternative")
    msg['Subject'] = f"[Z-ARMOR CLOUD] Xác nhận Đơn hàng & Cấp phát License Key ({tier})"
    msg['From'] = f"Z-Armor Cloud <{SMTP_EMAIL}>"
    msg['To'] = receiver_email

    html_content = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: 'Courier New', monospace;
                background: #05070a;
                color: #fff;
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: #0a0f1a;
                border: 2px solid #00ff9d;
                border-radius: 8px;
                padding: 30px;
            }}
            h1 {{
                color: #00ff9d;
                text-transform: uppercase;
                letter-spacing: 2px;
                margin-bottom: 20px;
            }}
            .license-box {{
                background: #141922;
                border: 1px solid #00e5ff;
                border-radius: 4px;
                padding: 20px;
                margin: 20px 0;
                text-align: center;
            }}
            .license-key {{
                color: #00e5ff;
                font-size: 24px;
                font-weight: bold;
                letter-spacing: 2px;
                font-family: 'Courier New', monospace;
            }}
            .button {{
                display: inline-block;
                background: linear-gradient(135deg, #00ff9d 0%, #00e5ff 100%);
                color: #000;
                text-decoration: none;
                padding: 15px 40px;
                border-radius: 4px;
                font-weight: bold;
                margin: 20px 0;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            .instructions {{
                background: #141922;
                border-left: 4px solid #00ff9d;
                padding: 15px;
                margin: 20px 0;
            }}
            .step {{
                margin: 10px 0;
                padding-left: 20px;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #333;
                font-size: 12px;
                color: #888;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🛡️ SECURE PROTOCOL ACTIVATED</h1>

            <p>Kính chào <strong>{buyer_name}</strong>,</p>

            <p>Hệ thống Z-Armor Cloud đã cấp phát License Key cho bạn:</p>

            <div class="license-box">
                <div style="color: #888; font-size: 12px; margin-bottom: 10px;">YOUR LICENSE KEY</div>
                <div class="license-key">{license_key}</div>
                <div style="color: #888; font-size: 12px; margin-top: 10px;">Tier: {tier}</div>
            </div>

            <div style="text-align: center;">
                <a href="{dashboard_link}" class="button">
                    🚀 Truy cập Dashboard
                </a>
            </div>

            <div class="instructions">
                <strong style="color: #00ff9d;">📋 HƯỚNG DẪN KÍCH HOẠT:</strong>

                <div class="step">
                    <strong>Bước 1:</strong> Click vào button "Truy cập Dashboard" ở trên
                </div>

                <div class="step">
                    <strong>Bước 2:</strong> Nhập License Key: <code style="color: #00e5ff;">{license_key}</code>
                </div>

                <div class="step">
                    <strong>Bước 3:</strong> Bind license với MT5 Account ID của bạn
                </div>

                <div class="step">
                    <strong>Bước 4:</strong> Cấu hình RiskOS Parameters:
                    <ul style="margin: 10px 0; color: #aaa;">
                        <li>Max Daily Loss (%)</li>
                        <li>Max Positions</li>
                        <li>Stop Loss / Take Profit</li>
                        <li>Trading Hours</li>
                        <li>Và nhiều tính năng khác...</li>
                    </ul>
                </div>

                <div class="step">
                    <strong>Bước 5:</strong> Copy license key vào EA trên MetaTrader 5
                </div>
            </div>

            <div style="background: #1a1f2e; padding: 15px; border-radius: 4px; margin: 20px 0;">
                <strong style="color: #00ff9d;">⚡ QUICK START:</strong><br>
                <code style="color: #00e5ff;">
                Dashboard: {dashboard_link}<br>
                License: {license_key}<br>
                Support: admin@zarmor.cloud
                </code>
            </div>

            <p style="color: #888; font-size: 14px;">
                <strong>Lưu ý:</strong> License key này chỉ gửi 1 lần duy nhất.
                Vui lòng lưu lại email này để sử dụng sau.
            </p>

            <div class="footer">
                <strong>Z-ARMOR CLOUD</strong> - Risk Management SaaS for MT5<br>
                © 2026 Z-Armor. All rights reserved.<br>
                <a href="{dashboard_link}" style="color: #00e5ff;">Dashboard</a> |
                <a href="mailto:support@zarmor.cloud" style="color: #00e5ff;">Support</a>
            </div>
        </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(html_content, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}", flush=True)
        return False
# ==========================================
# PYDANTIC MODELS (tap trung 1 cho)
# ==========================================
class TradeEventPayload(BaseModel):
    account_id: str
    event_type: str
    ticket:     str
    symbol:     str
    trade_type: str
    volume:     float
    price:      float
    pnl:        Optional[float] = 0.0
    rr_ratio:   Optional[float] = 0.0
class WebCheckoutPayload(BaseModel):
    buyer_name:  str
    buyer_email: str
    tier:        str
    amount:      float
    method:      str
class EventModel(BaseModel):
    order_id:       Optional[str]   = "UNKNOWN"
    purchased_tier: str
    payment_status: str
    buyer_name:     Optional[str]   = "Khach hang an danh"
    buyer_email:    Optional[str]   = "no-email@zarmor.com"
    amount_paid:    Optional[float] = 0.0
class LarkWebhookBody(BaseModel):
    event: EventModel
class LogTradeRequest(BaseModel):
    account_id:  str
    trade_data:  dict
class CloseSessionRequest(BaseModel):
    account_id:       str
    session_summary:  dict
class LogAuditRequest(BaseModel):
    account_id: str
    action:     str
    message:    str
    severity:   Optional[str]  = "INFO"
    extra:      Optional[dict] = None
class SendTelegramRequest(BaseModel):
    account_id: str
    chat_id:    str
    message:    str
# ==========================================
# ROUTES — HEALTH & DASHBOARD
# ==========================================
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "8.3.1", "phase": "radar-crm+strategy", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/health")
async def health_check_alias():
    """Alias cho /api/health — dùng bởi load balancer / uptime monitor."""
    return {"status": "ok", "version": "8.3.1", "phase": "radar-crm+strategy", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Phase 4: Email Capture (scan.html gate) ──────────────────────
class EmailCapturePayload(BaseModel):
    email:             str
    asset_interest:    Optional[str] = ""
    timeframe_interest:Optional[str] = "H1"
    captured_at:       Optional[str] = ""
    source:            Optional[str] = "radar_scan_gate"
    ref:               Optional[str] = ""

@app.post("/api/email-capture")
async def api_email_capture(payload: EmailCapturePayload, request: Request, db=Depends(get_db)):
    """
    Phase 4: Lưu email từ scan gate vào radar_email_captures.
    Gọi từ scan.html khi user nhập email để xem full score.
    """
    from sqlalchemy import text
    ip = request.client.host if request.client else ""
    try:
        db.execute(text("""
            INSERT INTO radar_email_captures
                (id, email, asset_interest, timeframe_interest,
                 source, ref_code, ip_address, captured_at)
            VALUES
                (:id, :email, :asset, :tf, :source, :ref, :ip, NOW())
            ON CONFLICT (email) DO UPDATE SET
                last_seen_at   = NOW(),
                asset_interest = EXCLUDED.asset_interest
        """), {
            "id":     str(uuid.uuid4()),
            "email":  payload.email.strip().lower(),
            "asset":  payload.asset_interest or "",
            "tf":     payload.timeframe_interest or "H1",
            "source": payload.source or "radar_scan_gate",
            "ref":    payload.ref or "",
            "ip":     ip,
        })
        db.commit()
        # Upsert za_users để user có thể nhận magic link sau
        try:
            _upsert_za_user(payload.email.strip().lower())
        except Exception:
            pass
        return {"captured": True}
    except Exception as e:
        # Bảng chưa tồn tại → tự tạo rồi retry
        try:
            db.rollback()
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS radar_email_captures (
                    id            VARCHAR(40) PRIMARY KEY,
                    email         VARCHAR(200) UNIQUE NOT NULL,
                    asset_interest    VARCHAR(20),
                    timeframe_interest VARCHAR(10),
                    source        VARCHAR(50) DEFAULT 'radar_scan_gate',
                    ref_code      VARCHAR(20),
                    ip_address    VARCHAR(50),
                    converted     BOOLEAN DEFAULT FALSE,
                    captured_at   TIMESTAMPTZ DEFAULT NOW(),
                    last_seen_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            db.commit()
        except Exception:
            pass
        return {"captured": False, "note": "table initializing"}

@app.get("/api/email-captures")
async def api_email_captures_list(
    limit: int = 50,
    db=Depends(get_db),
    jwt_payload: dict = Depends(require_jwt),
):
    """Admin: xem danh sách email đã capture. Yêu cầu JWT."""
    from sqlalchemy import text
    if not jwt_payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        rows = db.execute(text("""
            SELECT email, asset_interest, source, ref_code,
                   converted, captured_at, last_seen_at
            FROM radar_email_captures
            ORDER BY captured_at DESC
            LIMIT :limit
        """), {"limit": min(limit, 500)}).mappings().fetchall()
        return {"count": len(rows), "captures": [dict(r) for r in rows]}
    except Exception as e:
        return {"count": 0, "captures": [], "error": str(e)}
# Cache dict cho init-data (tránh spam DB mỗi 1s)
_init_data_cache: dict = {}
@app.get("/api/init-data")
async def get_init_data(request: Request, account_id: str = "MainUnit", license_key: str = ""):
    import time as _t
    # decode_jwt_unsafe imported from auth at top — F-09: verifies HS256 signature
    # ── Sprint A: Dual-auth ──────────────────────────────────────
    # Ưu tiên: 1) Bearer JWT / HttpOnly cookie  2) X-License-Key header (F-13)  3) ?license_key param (legacy)
    owner_email = None
    auth_header = request.headers.get("Authorization", "")
    # Also check HttpOnly cookie (F-01)
    _cookie_token = request.cookies.get("za_access_token")
    _raw_token = auth_header[7:] if auth_header.startswith("Bearer ") else (_cookie_token or "")
    if _raw_token:
        jwt_payload = decode_jwt_unsafe(_raw_token)
        if jwt_payload:
            owner_email = jwt_payload.get("email")
            if not license_key:
                license_key = f"jwt_{owner_email[:8]}" if owner_email else ""
    # F-13: Accept license key from X-License-Key header (not URL param)
    if not license_key:
        license_key = request.headers.get("X-License-Key", "").strip()
    # Nếu không có JWT hợp lệ, fallback về license_key param
    if not owner_email and not license_key:
        return {"units_config": {}, "global_status": {
            "balance": 0, "equity": 0, "total_pnl": 0, "total_stl": 0,
            "open_trades": [], "license_active": False,
            "physics": {"state": "UNAUTHORIZED", "z_pressure": 0,
                        "damping_factor": 1.0, "is_hibernating": False, "velocity": 0},
            "chart_data": {"labels": [], "equity": [], "z_pressure": []}
        }, "error": "UNAUTHORIZED"}
    # Cache 800ms — dashboard poll mỗi 1s, không cần hit DB mỗi request
    _ck = f"id_{account_id}_{license_key[:8] if license_key else (owner_email or '')[:8]}"
    _cv = _init_data_cache.get(_ck)
    if _cv and _t.time() - _cv["ts"] < 0.8:
        return _cv["data"]
    try:
        result = await fetch_dashboard_state(account_id)
        # R-03: Fleet Isolation — filter units_config theo owner
        if result.get("units_config"):
            from database import SessionLocal
            from license_service import get_accounts_for_owner, get_owner_for_license
            try:
                db = SessionLocal()
                # JWT path: owner_email đã có từ JWT payload
                # legacy path: lookup email từ license_key
                email_for_filter = owner_email
                if not email_for_filter and license_key and not license_key.startswith("jwt_"):
                    email_for_filter = get_owner_for_license(db, license_key)
                if email_for_filter:
                    allowed_ids = get_accounts_for_owner(db, email_for_filter)
                    result["units_config"] = {
                        k: v for k, v in result["units_config"].items()
                        if str(k) in allowed_ids
                    }
                db.close()
            except Exception:
                pass
        _init_data_cache[_ck] = {"ts": _t.time(), "data": result}
        return result
    except Exception as e:
        return {
            "global_status": {
                "balance": 0, "equity": 0, "total_pnl": 0, "total_stl": 0,
                "open_trades": [], "license_active": True,
                "physics": {
                    "state": "DISCONNECTED", "z_pressure": 0,
                    "damping_factor": 1.0, "is_hibernating": False, "velocity": 0
                },
                "chart_data": {"labels": [], "equity": [], "z_pressure": []}
            },
            "units_config": {},
            "error": str(e)
        }
# ==========================================
# ROUTES — MT5 WEBHOOKS (legacy, giu nguyen)
# ==========================================
@app.post("/api/webhook/heartbeat")
async def webhook_heartbeat(request: Request):
    """
    EA MT5 gui heartbeat (legacy endpoint — khong can token).
    EA moi nen dung /ea/heartbeat thay the.
    """
    raw_data = await request.body()
    data     = json.loads(raw_data.decode("utf-8").strip('\x00').strip())
    # Normalize account_id
    acct_id = str(data.get("account_id", data.get("account", ""))).strip()
    # Default state
    if not data.get("state"):
        data["state"] = "OPTIMAL_FLOW"
    data.setdefault("z_pressure", 0.0)
    data.setdefault("fre_pct", 0.0)
    update_webhook_heartbeat(data)
    # [FIX] Cập nhật _mt5_cache với _last_hb để monitor không báo stale
    if acct_id:
        try:
            from api.dashboard_service import _mt5_cache
            import time as _t
            _now = _t.time()
            if acct_id not in _mt5_cache:
                # Tạo entry mới nếu chưa có
                _mt5_cache[acct_id] = {
                    "equity":   float(data.get("equity",  0) or 0),
                    "balance":  float(data.get("balance", 0) or 0),
                    "physics":  {"state": data["state"], "z_pressure": 0.0},
                    "_last_hb": _now,
                }
                print(f"[HEARTBEAT] Cache init for {acct_id}", flush=True)
            else:
                ch = _mt5_cache[acct_id]
                # Update _last_hb — đây là key để monitor biết EA đang sống
                ch["_last_hb"] = _now
                # Update equity/balance
                if data.get("equity"):  ch["equity"]  = float(data["equity"])
                if data.get("balance"): ch["balance"]  = float(data["balance"])
                # Chỉ reset DISCONNECTED → OPTIMAL_FLOW (không override CRITICAL etc)
                ph = ch.get("physics", {})
                if ph.get("state") in ("DISCONNECTED", "", None):
                    ph["state"] = data["state"]
                    ch["physics"] = ph
        except Exception as _ce:
            print(f"[HEARTBEAT] Cache update error: {_ce}", flush=True)
    print(f"[HEARTBEAT] OK | key={data.get('license_key','?')[:12]}... account={acct_id} equity={data.get('equity',0):.2f}", flush=True)
    return {"status": "ok"}
@app.post("/api/webhook/positions")
async def webhook_positions(request: Request):
    raw_data = await request.body()
    data     = json.loads(raw_data.decode("utf-8").strip('\x00').strip())
    # FIX: forward balance/equity nếu EA gửi kèm — tránh race condition với heartbeat
    update_webhook_positions(
        str(data.get("account_id")),
        data.get("positions", []),
        balance=data.get("balance"),
        equity=data.get("equity"),
    )
    return {"status": "ok"}
@app.post("/api/webhook/trade-event")
async def handle_trade_event(payload: TradeEventPayload):
    """Legacy trade event — EA moi nen dung /ea/trade-event co token."""
    try:
        units       = get_all_units()
        unit_config = units.get(payload.account_id, {})
        chat_id     = unit_config.get("telegram_config", {}).get("chat_id", "")
        is_active   = unit_config.get("telegram_config", {}).get("is_active", True)
        trader_name = unit_config.get("alias", f"Trader {payload.account_id}")
        if not chat_id or not is_active:
            return {"status": "ignored", "message": "Telegram chua cai dat."}
        if payload.event_type.upper() == "OPEN":
            await send_trade_opened(
                chat_id=chat_id, trader_name=trader_name,
                ticket=payload.ticket, symbol=payload.symbol,
                trade_type=payload.trade_type, volume=payload.volume, price=payload.price
            )
        elif payload.event_type.upper() == "CLOSE":
            await send_trade_closed(
                chat_id=chat_id, trader_name=trader_name,
                ticket=payload.ticket, symbol=payload.symbol,
                trade_type=payload.trade_type, pnl=payload.pnl, rr_ratio=payload.rr_ratio
            )
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
# ==========================================
# ROUTES — CONFIG MANAGEMENT
# ==========================================
@app.post("/api/update-unit-config")
async def update_config(request: Request,
                        jwt_payload: dict = Depends(require_jwt),
                        db=Depends(get_db)):
    """F-07: Requires JWT. Ghi ConfigAuditTrail cho mọi thay đổi config."""
    try:
        data       = await request.json()
        account_id = str(data.get("mt5_login") or data.get("unit_key") or "")
        if not account_id or account_id == "None":
            return {"status": "error", "message": "Thiếu mt5_login"}
        # F-07: Verify JWT có quyền trên account này
        if not check_account_access(account_id, jwt_payload):
            raise HTTPException(status_code=403, detail="Không có quyền trên account này")
        # BUG G FIX: Bảo vệ neural_profile nếu payload không gửi kèm
        # fetch_dashboard_state() trả về {"global_status":{...}, "units_config":{...}}
        # → phải lấy từ units_config[account_id].neural_profile, không phải top-level
        if "neural_profile" not in data:
            existing_units = get_all_units()
            existing_neural = existing_units.get(account_id, {}).get("neural_profile")
            if existing_neural:
                data["neural_profile"] = existing_neural
        update_unit_from_payload(account_id, data)
        invalidate_units_cache()  # BUG 2 FIX: force refresh cache để lần poll tiếp thấy config mới
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
@app.post("/api/unlock-unit")
async def unlock_unit(request: Request,
                      jwt_payload: dict = Depends(require_jwt),
                      db=Depends(get_db)):
    """F-06: Requires JWT. F-02: Unlock lưu vào DB — không thể bypass bằng localStorage."""
    data       = await request.json()
    account_id = data.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="Thiếu account_id")
    if not check_account_access(str(account_id), jwt_payload):
        raise HTTPException(status_code=403, detail="Không có quyền trên account này")
    ip     = request.client.host if request.client else ""
    result = set_account_lock_db(str(account_id), False, db,
                                  changed_by=jwt_payload.get("email", "?"), ip=ip)
    set_lock_status(account_id, False)   # sync in-memory cache
    return {"status": "unlocked", **result}
@app.post("/api/panic-kill")
async def panic_kill(request: Request,
                     jwt_payload: dict = Depends(require_jwt),
                     db=Depends(get_db)):
    """F-06: Requires JWT. F-02: Lock lưu vào DB — client không thể bypass."""
    data       = await request.json()
    account_id = data.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="Thiếu account_id")
    if not check_account_access(str(account_id), jwt_payload):
        raise HTTPException(status_code=403, detail="Không có quyền trên account này")
    ip     = request.client.host if request.client else ""
    result = set_account_lock_db(str(account_id), True, db,
                                  changed_by=jwt_payload.get("email", "?"), ip=ip)
    set_lock_status(account_id, True)   # sync in-memory cache
    return {"status": "locked", **result}
# ==========================================
# ROUTES — TELEGRAM
# ==========================================
@app.post("/api/test-telegram")
async def test_telegram(request: Request):
    data    = await request.json()
    chat_id = str(data.get("chat_id", ""))
    if not chat_id:
        return {"status": "error", "message": "Thieu chat_id"}
    await push_to_telegram(
        chat_id=chat_id,
        text="<b>[Z-ARMOR] Test ket noi thanh cong!</b>\nBot da nhan duoc tin hieu tu Tram Radar.",
        disable_notification=False
    )
    return {"status": "ok"}
@app.post("/api/send-telegram")
async def route_send_telegram(req: SendTelegramRequest):
    return await api_send_telegram(req.account_id, req.chat_id, req.message)
# ==========================================
# ROUTES — LICENSE
# ==========================================
@app.post("/api/bind-license")
async def bind_license(req: BindLicensePayload, db=Depends(get_db)):
    try:
        db_license = db.query(License).filter(License.license_key == req.license_key).first()
        if not db_license:
            return {"status": "error", "message": "Ma Ban quyen khong ton tai!"}
        if db_license.status == "ACTIVE":
            if db_license.bound_mt5_id == req.account_id:
                return {"status": "success", "message": "Ban quyen nay da lien ket voi MT5 cua ban."}
            return {"status": "error", "message": "Ma nay da bi su dung cho ID khac!"}
        if db_license.status != "UNUSED":
            return {"status": "error", "message": "Ma nay da bi khoa."}
        db_license.status       = "ACTIVE"
        db_license.bound_mt5_id = req.account_id
        db_license.expires_at   = datetime.now(timezone.utc) + timedelta(days=30)
        db.commit()
        init_payload = {
            "mt5_login": req.account_id, "alias": f"Trader {req.account_id}",
            "arm": False,   # BUG 3 FIX: Đảm bảo is_locked=False khi init tài khoản mới
            "telegram_config": {"is_active": True},
            "risk_params": {"daily_limit_money": 150, "max_dd": 10.0, "dd_type": "STATIC", "consistency": 97},
            "neural_profile": {"trader_archetype": "SNIPER", "historical_win_rate": 40.0,
                               "historical_rr": 1.5, "optimization_bias": "HALF_KELLY"}
        }
        update_unit_from_payload(req.account_id, init_payload)
        return {"status": "success", "message": "Kich hoat thanh cong. Da cap phep 30 ngay!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
@app.get("/api/verify-license/{account_id}")
async def verify_license_get(account_id: str, db=Depends(get_db)):
    db_license = db.query(License).filter(
        License.bound_mt5_id == str(account_id),
        License.status == "ACTIVE"
    ).first()
    if not db_license:
        return {"status": "error", "is_valid": False, "message": "ID nay chua co Ban quyen."}
    if db_license.expires_at and db_license.expires_at < datetime.now(timezone.utc):
        db_license.status = "EXPIRED"
        db.commit()
        return {"status": "error", "is_valid": False, "message": "Ban quyen DA HET HAN."}
    return {"status": "success", "is_valid": True, "message": "Ban quyen Hop le"}
@app.post("/api/verify-license")
async def verify_license_post(request: Request, db=Depends(get_db)):
    data = await request.json()
    return await verify_license_get(str(data.get("account_id", "")), db)
# ==========================================
# ROUTES — AI AGENT ENGINE
# ==========================================
@app.post("/api/log-trade")
async def route_log_trade(req: LogTradeRequest):
    result = api_log_trade(req.account_id, req.trade_data)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result["detail"])
    return result
@app.post("/api/close-session")
async def route_close_session(req: CloseSessionRequest):
    result = api_close_session(req.account_id, req.session_summary)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result["detail"])
    return result
@app.post("/api/log-audit")
async def route_log_audit(req: LogAuditRequest):
    return api_log_audit(
        account_id=req.account_id,
        action=req.action,
        message=req.message,
        severity=req.severity or "INFO",
        extra=req.extra
    )
@app.get("/api/trade-history/{account_id}")
async def route_get_trade_history(account_id: str, limit: int = 500):
    return api_get_trade_history(account_id, limit=limit)
@app.get("/api/session-history/{account_id}")
async def route_get_session_history(account_id: str, limit: int = 90):
    return api_get_session_history(account_id, limit=limit)
@app.get("/api/sync-history/{account_id}")
async def route_sync_history(account_id: str,
                              db=Depends(get_db),
                              jwt_payload: dict = Depends(require_jwt)):
    """F-08: Requires JWT. F-02: Verify account access."""
    # Chỉ cho phép truy cập account của chính mình (hoặc admin)
    if not check_account_access(str(account_id), jwt_payload):
        raise HTTPException(status_code=403, detail="Không có quyền truy cập account này")
    try:
        from database import TradeHistory, SessionHistory
        import json as _json
        raw_trades = (
            db.query(TradeHistory)
            .filter(TradeHistory.account_id == account_id)
            .order_by(TradeHistory.timestamp.desc())
            .limit(500).all()
        )
        raw_sessions = (
            db.query(SessionHistory)
            .filter(SessionHistory.account_id == account_id)
            .order_by(SessionHistory.closed_at.desc())
            .limit(90).all()
        )
        trades = [{
            "id": t.id, "account_id": t.account_id, "session_id": t.session_id,
            "timestamp": t.timestamp, "closed_at": t.closed_at,
            "symbol": t.symbol, "direction": t.direction, "result": t.result,
            "risk_amount": t.risk_amount, "actual_rr": t.actual_rr,
            "planned_rr": t.planned_rr, "profit": t.profit,
            "hour_of_day": t.hour_of_day, "day_of_week": t.day_of_week,
            "deviation_score": t.deviation_score,
        } for t in raw_trades]
        sessions = []
        for s in raw_sessions:
            try:    violations = _json.loads(s.violations or "[]")
            except: violations = []
            try:    contract = _json.loads(s.contract_json or "{}")
            except: contract = {}
            sessions.append({
                "session_id": s.session_id, "account_id": s.account_id,
                "date": s.date, "opened_at": s.opened_at, "closed_at": s.closed_at,
                "opening_balance": s.opening_balance, "closing_balance": s.closing_balance,
                "pnl": s.pnl, "actual_wr": s.actual_wr, "actual_rr_avg": s.actual_rr_avg,
                "actual_max_dd_hit": s.actual_max_dd_hit, "trades_count": s.trades_count,
                "wins": s.wins, "losses": s.losses, "compliance_score": s.compliance_score,
                "violations": violations, "contract_json": contract, "status": s.status,
            })
        return {
            "status": "ok", "trades": trades, "sessions": sessions,
            "meta": {
                "account_id": account_id,
                "trade_count": len(trades),
                "session_count": len(sessions),
                "synced_at": datetime.now(timezone.utc).isoformat() + "Z",
            }
        }
    except Exception as e:
        print(f"[SYNC-HISTORY ERROR] account={account_id}: {e}", flush=True)
        return {
            "status": "ok", "trades": [], "sessions": [],
            "meta": {
                "account_id": account_id, "trade_count": 0, "session_count": 0,
                "synced_at": datetime.now(timezone.utc).isoformat() + "Z",
                "warning": f"DB error: {str(e)[:100]}"
            }
        }
@app.get("/api/ai-analysis/{account_id}")
async def route_get_ai_analysis(account_id: str):
    return api_get_ai_analysis(account_id)
# ==========================================
# ROUTES — RADAR APPLY (Sprint C-3)
# ==========================================
class RadarApplyPayload(BaseModel):
    asset:      str
    timeframe:  str
    score:      int
    regime:     str     = ""
    email:      str     = ""
    timestamp:  str     = ""
@app.post("/api/radar-apply")
async def api_radar_apply(payload: RadarApplyPayload):
    """
    User nhấn 'Apply to Account' trong scan.html → sync regime_context vào units_config.
    EA đọc tại heartbeat kế tiếp (≤ 30s) thông qua radar_map injection.

    FIX C-3: Dùng engine._ea_params() thay vì duplicate threshold logic.
    engine._ea_params() là single source of truth cho allow_trade/position_pct/sl_multiplier.
    """
    try:
        from radar.engine import _ea_params, SCORE_LABELS

        score = int(payload.score)
        regime = payload.regime or "NEUTRAL"

        # Tính gate từ score (giống SCORE_LABELS trong engine.py)
        gate = "BLOCK"
        for lo, hi, *_, g in SCORE_LABELS:
            if lo <= score < hi:
                gate = g
                break

        ea = _ea_params(score, regime, gate)
        allow    = ea["allow_trade"]
        pos_pct  = ea["position_pct"]
        sl_mult  = ea["sl_multiplier"]
        state    = ea["state_cap"]

        regime_ctx = {
            "asset":          payload.asset,
            "timeframe":      payload.timeframe,
            "score":          score,
            "regime":         regime,
            "allow_trade":    allow,
            "position_pct":   pos_pct,
            "sl_multiplier":  sl_mult,
            "state_cap":      state,
            "applied_by":     payload.email or "scan_user",
            "applied_at":     payload.timestamp or datetime.now(timezone.utc).isoformat(),
        }
        # Upsert vào tất cả accounts của user (nếu biết email)
        updated = []
        from dashboard_service import get_units_config_cached, update_unit_from_payload
        units = get_units_config_cached()
        for acc_id, cfg in (units or {}).items():
            owner = cfg.get("owner_email", "") or cfg.get("buyer_email", "")
            if not payload.email or owner == payload.email or not owner:
                update_unit_from_payload(acc_id, {"regime_context": regime_ctx})
                updated.append(acc_id)
        print(f"[RADAR-APPLY] {payload.asset}/{payload.timeframe} score={score} gate={gate} state={state} pos={pos_pct}% → accounts={updated}", flush=True)
        return {
            "status":            "ok",
            "applied":           True,
            "state_cap":         state,
            "position_pct":      pos_pct,
            "sl_multiplier":     sl_mult,
            "allow_trade":       allow,
            "next_heartbeat_in": 30,
            "accounts_updated":  updated,
        }
    except Exception as e:
        print(f"[RADAR-APPLY] Error: {e}", flush=True)
        return {"status": "error", "message": str(e)}
# ==========================================
# ROUTES — BILLING / CHECKOUT
# ==========================================
@app.post("/api/checkout")
async def api_checkout(payload: CheckoutPayload, request: Request, db=Depends(get_db)):
    """
    AUTO-SALE WORKFLOW (FINAL VERSION - All bugs fixed)
    ===================================================
    1. Nhận request checkout (TRIAL_FREE hoặc PAID)
    2. Tạo order_id
    3. Ghi vào Lark Base (status = PENDING)
    4. TẠO LICENSE KEY (nếu là TRIAL_FREE)
    5. GỬI EMAIL cho customer
    6. BÁO TELEGRAM
    7. GHI LOG vào LARK_LOG_TABLE
    8. Trả về license_key cho user
    """
    # S0 FIX: Email dedup — chặn spam tạo trial liên tục
    if payload.method == "TRIAL_FREE" and payload.buyer_email:
        existing = db.query(License).filter(
            License.buyer_email == payload.buyer_email,
            License.is_trial == True,
            License.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
        ).first()
        if existing:
            return {"success": False, "error": "TRIAL_ALREADY_CREATED",
                    "message": "Email này đã tạo trial trong 24h qua. Vui lòng dùng license key đã nhận."}
    # Rate limit by IP
    client_ip = request.client.host if request.client else "unknown"
    _now = time.time()
    _ip_log = _co_ip_log.get(client_ip, [])
    _ip_log = [t for t in _ip_log if _now - t < 600]
    if len(_ip_log) >= CO_MAX_PER_IP:
        return {"success": False, "error": "RATE_LIMITED", "message": "Quá nhiều request. Thử lại sau 10 phút."}
    _ip_log.append(_now)
    _co_ip_log[client_ip] = _ip_log
    order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"
    buyer_name = payload.buyer_name or "Unknown"
    buyer_email = payload.buyer_email
    tier = payload.tier or "STARTER"
    amount = payload.amount or 0.0
    method = payload.method or "MANUAL"
    print(f"[CHECKOUT] START | order={order_id} email={buyer_email} tier={tier} method={method}", flush=True)
    # ═══════════════════════════════════════════════════════════
    # BƯỚC 1: Ghi vào Lark Base (bảng chính - status PENDING)
    # ═══════════════════════════════════════════════════════════
    lark_ok = await create_pending_order_in_lark(order_id, buyer_name, buyer_email, tier, amount)
    if not lark_ok:
        print(f"[CHECKOUT] ⚠️ Lark Base ghi thất bại (order vẫn tiếp tục)", flush=True)
    # ═══════════════════════════════════════════════════════════
    # BƯỚC 2: Tạo License Key (nếu TRIAL_FREE hoặc auto-provision)
    # ═══════════════════════════════════════════════════════════
    license_key = None
    expires_at = None

    if method == "TRIAL_FREE":
        # Tạo license key ngay lập tức
        license_key = f"ZARMOR-{uuid.uuid4().hex[:5].upper()}-{uuid.uuid4().hex[:5].upper()}"

        # Tính expires_at cho trial (7 ngày)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        # Lưu vào database với ĐẦY ĐỦ các fields
        new_license = License(
            license_key=license_key,
            tier=tier,
            status="ACTIVE",
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            bound_mt5_id=None,
            is_trial=True,
            amount_usd=amount,
            payment_method=method,
            expires_at=expires_at,
            max_machines=1,
            email_sent=False,
            strategy_id="S1",   # default strategy cho account mới
        )
        db.add(new_license)

        try:
            db.commit()
            print(f"[CHECKOUT] ✅ License created | key={license_key} expires={expires_at.strftime('%Y-%m-%d')}", flush=True)
        except Exception as db_error:
            db.rollback()
            print(f"[CHECKOUT] ❌ Database error: {db_error}", flush=True)
            raise HTTPException(500, f"Failed to create license: {str(db_error)}")

    elif method in ["STRIPE", "PAYPAL", "BANK_TRANSFER"]:
        # Paid checkout: chờ xác nhận payment trước khi tạo key
        print(f"[CHECKOUT] ⏳ Paid order - chờ payment confirmation để tạo key", flush=True)

    # ═══════════════════════════════════════════════════════════
    # BƯỚC 3: GỬI EMAIL cho customer
    # ═══════════════════════════════════════════════════════════
    email_sent = False
    if license_key and buyer_email:
        # Sprint A: upsert za_users — tạo account cho user ngay tại checkout
        try:
            # _upsert_za_user imported from auth at top
            _upsert_za_user(buyer_email)
            print(f"[CHECKOUT] ✅ za_users upserted for {buyer_email}", flush=True)
        except Exception as _ue:
            print(f"[CHECKOUT] ⚠️ za_users upsert failed: {_ue}", flush=True)
        loop = asyncio.get_event_loop()
        email_sent = await loop.run_in_executor(
            None, send_license_email_to_customer,
            buyer_email, buyer_name, tier, license_key
        )
        if email_sent:
            print(f"[CHECKOUT] ✅ Email sent to {buyer_email}", flush=True)
            try:
                new_license.email_sent = True
                db.commit()
            except:
                pass
        else:
            print(f"[CHECKOUT] ⚠️ Email FAILED (SMTP chưa config hoặc lỗi)", flush=True)

    # ═══════════════════════════════════════════════════════════
    # BƯỚC 4: BÁO TELEGRAM
    # ═══════════════════════════════════════════════════════════
    telegram_msg = (
        f"🛒 NEW CHECKOUT\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Order ID: {order_id}\n"
        f"Customer: {buyer_name}\n"
        f"Email: {buyer_email}\n"
        f"Tier: {tier}\n"
        f"Amount: ${amount}\n"
        f"Method: {method}\n"
    )
    if license_key:
        telegram_msg += f"License: {license_key}\n"
        telegram_msg += f"Expires: {expires_at.strftime('%Y-%m-%d')}\n"
        telegram_msg += f"Status: ✅ ACTIVE (Trial)\n"
    else:
        telegram_msg += f"Status: ⏳ PENDING PAYMENT\n"

    try:
        await safe_telegram_send(telegram_msg)
        print(f"[CHECKOUT] ✅ Telegram notification sent", flush=True)
    except Exception as tg_error:
        print(f"[CHECKOUT] ⚠️ Telegram FAILED: {tg_error}", flush=True)

    # ═══════════════════════════════════════════════════════════
    # BƯỚC 5: GHI LOG vào LARK_LOG_TABLE
    # ═══════════════════════════════════════════════════════════
    if license_key:
        log_ok = await log_license_to_lark(
            order_id=order_id,
            license_key=license_key,
            status="SUCCESS"
        )
        if log_ok:
            print(f"[CHECKOUT] ✅ Lark log created", flush=True)
        else:
            print(f"[CHECKOUT] ⚠️ Lark log FAILED", flush=True)

    # ═══════════════════════════════════════════════════════════
    # BƯỚC 6: GỬI LARK BOT NOTIFICATION
    # ═══════════════════════════════════════════════════════════
    lark_bot_msg = (
        f"🎉 NEW ORDER: {order_id}\n"
        f"Customer: {buyer_name} ({buyer_email})\n"
        f"Tier: {tier} | Amount: ${amount}\n"
    )
    if license_key:
        lark_bot_msg += f"License: {license_key}\n"
        if email_sent:
            lark_bot_msg += f"✅ Email sent successfully"
        else:
            lark_bot_msg += f"⚠️ Email failed (check SMTP config)"
    else:
        lark_bot_msg += f"⏳ Chờ payment confirmation"

    await send_lark_bot_log(lark_bot_msg)

    # ═══════════════════════════════════════════════════════════
    # BƯỚC 7: TRẢ VỀ KẾT QUẢ
    # ═══════════════════════════════════════════════════════════
    response = {
        "status": "success",
        "order_id": order_id,
        "message": "Checkout successful"
    }

    if license_key:
        response["license_key"] = license_key
        response["expires_at"] = expires_at.isoformat()
        response["message"] = "Trial license activated! Check your email."
    else:
        response["message"] = "Order created. Awaiting payment confirmation."

    print(f"[CHECKOUT] ✅ COMPLETE | order={order_id} license={license_key or 'PENDING'}", flush=True)
    return response
@app.post("/api/lark-webhook")
async def receive_lark_order(payload: LarkWebhookBody, db=Depends(get_db)):
    try:
        order = payload.event
        if order.payment_status.upper() != "PAID":
            return {"status": "error", "message": "Don hang chua thanh toan."}
        new_key     = f"ZARMOR-{order.purchased_tier.upper()}-{uuid.uuid4().hex[:6].upper()}"
        new_license = License(
            license_key=new_key, tier=order.purchased_tier,
            status="UNUSED", buyer_email=order.buyer_email,
            strategy_id="S1",
        )
        db.add(new_license)
        db.commit()
        admin_chat = os.environ.get("ADMIN_TELEGRAM_CHAT_ID", "7976137362")
        await push_to_telegram(
            chat_id=admin_chat,
            text=(f"CO DON HANG MOI TU LARK!\n"
                  f"Khach: {order.buyer_name}\nGoi: {order.purchased_tier}\nKey: {new_key}"),
            disable_notification=False
        )
        await log_license_to_lark(order_id=order.order_id, license_key=new_key, status="SUCCESS")
        loop2 = asyncio.get_event_loop()
        await loop2.run_in_executor(None, send_license_email_to_customer,
            order.buyer_email, order.buyer_name, order.purchased_tier, new_key)
        return {"status": "success", "message": "Tao License thanh cong!", "data": {"license_key": new_key}}
    except Exception as e:
        db.rollback()
        if 'order' in locals() and hasattr(order, 'order_id'):
            await log_license_to_lark(order_id=order.order_id, license_key="---", status=f"LOI: {str(e)[:50]}")
        return {"status": "error", "message": f"Loi: {str(e)}"}
# ==========================================
# LICENSE ADMIN — Machine tracking helpers
# ==========================================
LICENSE_ADMIN_TOKEN = os.environ.get("LICENSE_ADMIN_TOKEN", "CHANGE_ME_BEFORE_DEPLOY")
# In-memory machine registry: license_key → set of account_ids
_machine_registry: dict = {}
def _check_admin(request: Request):
    if request.headers.get("X-Admin-Token", "") != LICENSE_ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
def _get_machines(db, license_key: str) -> set:
    if license_key in _machine_registry:
        return _machine_registry[license_key]
    try:
        from database import LicenseActivation
        rows = db.query(LicenseActivation).filter(
            LicenseActivation.license_key == license_key
        ).all()
        accts = {r.account_id for r in rows}
    except Exception:
        accts = set()
    _machine_registry[license_key] = accts
    return accts
def _add_machine(db, license_key: str, account_id: str, magic: str = "") -> bool:
    """Thêm máy mới. Trả về True nếu là máy mới, False nếu đã có."""
    accts = _machine_registry.setdefault(license_key, set())
    try:
        from database import LicenseActivation
        row = db.query(LicenseActivation).filter(
            LicenseActivation.license_key == license_key,
            LicenseActivation.account_id  == account_id
        ).first()
        if row:
            row.last_seen = datetime.now(timezone.utc)
            db.commit()
            accts.add(account_id)
            return False
        db.add(LicenseActivation(
            license_key=license_key, account_id=account_id,
            magic=magic, first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc)
        ))
        db.commit()
    except Exception:
        db.rollback()
    accts.add(account_id)
    return True
# ==========================================
# HEARTBEAT — EA gọi GET mỗi BridgeInterval giây
# Thay thế cho cách dùng Python bridge riêng
# ── Rate-limit caches (in-memory) ─────────────────────────────
_hb_last_seen: dict = {}   # license_key → last heartbeat unix timestamp
_co_ip_log:    dict = {}   # ip → [timestamps] cho checkout
HB_MIN_INTERVAL = 20       # giây tối thiểu giữa 2 heartbeat / key

# ── FIX C-4: Centralized symbol → asset map ───────────────────────────────────
# Single source of truth — dùng chung cho heartbeat, radar-apply, và cockpit.
# Bao gồm broker variants: .pro, m suffix, .cash, .int
# Frontend cũng có thể fetch qua GET /radar/symbol-map (Sprint D).
SYMBOL_TO_ASSET: dict = {
    # GOLD variants
    "XAUUSD": "GOLD", "XAUUSDm": "GOLD", "XAUUSD.pro": "GOLD",
    "GOLD": "GOLD", "GOLD.pro": "GOLD", "GOLD.cash": "GOLD", "XAU": "GOLD",
    # EURUSD variants
    "EURUSD": "EURUSD", "EURUSDm": "EURUSD", "EURUSD.pro": "EURUSD",
    "EURUSD.cash": "EURUSD",
    # BTC variants
    "BTCUSD": "BTC", "BTCUSDm": "BTC", "BTCUSDT": "BTC",
    "BTCUSD.int": "BTC", "BTCUSDT.p": "BTC", "BTC": "BTC",
    # NASDAQ variants
    "NAS100": "NASDAQ", "NAS100m": "NASDAQ", "USTEC": "NASDAQ",
    "US100": "NASDAQ", "NAS100.cash": "NASDAQ", "NDX": "NASDAQ",
}

def _mt5_symbol_to_asset(symbol: str) -> str | None:
    """Map MT5 broker symbol → Radar asset key. Returns None nếu không nhận ra."""
    return SYMBOL_TO_ASSET.get(symbol) or SYMBOL_TO_ASSET.get(symbol.upper())
_hb_disconnect_last_alert = {}  # debounce 5min per account
CO_MAX_PER_IP   = 5        # max checkout / IP trong 10 phút
CO_WINDOW       = 600      # 10 phút
# ==========================================
async def _ea_heartbeat_handler(
    account:  str   = None,
    magic:    str   = "",
    license:  str   = "",
    equity:   float = 0,
    balance:  float = 0,
    ts:       str   = "",
    db=None,
    symbols:  str   = "",   # comma-separated MT5 symbols, e.g. "XAUUSD,EURUSD,BTCUSD"
    tf:       str   = "H1", # timeframe cho radar lookup
):
    """Logic xử lý heartbeat — dùng chung cho cả GET và POST."""
    if not license:
        return {"valid": False, "lock": False, "emergency": False,
                "reason": "NO_LICENSE_KEY"}
    # [C2] Rate limit: bỏ qua nếu < HB_MIN_INTERVAL giây từ lần trước
    _now = time.time()
    if _now - _hb_last_seen.get(license, 0) < HB_MIN_INTERVAL:
        return {"valid": True, "lock": False, "emergency": False, "reason": "OK_CACHED"}
    _hb_last_seen[license] = _now
    if len(_hb_last_seen) > 10000:
        _cutoff = _now - 3600
        for _k in [k for k,v in list(_hb_last_seen.items()) if v < _cutoff]:
            del _hb_last_seen[_k]
    db_license = db.query(License).filter(License.license_key == license).first()
    if not db_license:
        print(f"[HEARTBEAT] INVALID_KEY | account={account} key={license[:12]}...", flush=True)
        return {"valid": False, "lock": False, "emergency": False,
                "reason": "INVALID_KEY"}
    if db_license.status == "REVOKED":
        return {"valid": False, "lock": True, "emergency": False,
                "reason": "LICENSE_REVOKED"}
    if db_license.status == "EXPIRED" or (
        db_license.expires_at and db_license.expires_at < datetime.now(timezone.utc)
    ):
        if db_license.status != "EXPIRED":
            db_license.status = "EXPIRED"
            db.commit()
        return {"valid": False, "lock": True, "emergency": False,
                "reason": "LICENSE_EXPIRED"}
    if db_license.status not in ("ACTIVE", "UNUSED"):
        return {"valid": False, "lock": True, "emergency": False,
                "reason": "LICENSE_INACTIVE"}
    max_machines = getattr(db_license, "max_machines", 1) or 1
    known        = _get_machines(db, license)
    if account and account not in known:
        if len(known) >= max_machines:
            print(f"[HEARTBEAT] MACHINE_LIMIT | key={license[:12]}... account={account}", flush=True)
            return {"valid": False, "lock": True, "emergency": False,
                    "reason": "MACHINE_LIMIT_REACHED",
                    "detail": f"Toi da {max_machines} may. Lien he admin de reset."}
        _add_machine(db, license, account, magic)
    # [C1] Enforce MT5 binding
    _bound = getattr(db_license, "bound_mt5_id", None)
    if not _bound:
        print(f"[HEARTBEAT] NOT_BOUND | key={license[:12]} account={account}", flush=True)
        return {
            "valid": False, "lock": False, "emergency": False,
            "reason": "KEY_NOT_BOUND",
            "message": "Vao dashboard bind MT5 ID truoc khi chay EA."
        }
    if account and account != _bound:
        print(f"[HEARTBEAT] MT5_MISMATCH | key={license[:12]} expected={_bound} got={account}", flush=True)
        return {
            "valid": False, "lock": True, "emergency": False,
            "reason": "MT5_ID_MISMATCH",
            "message": "Key nay da bind vao MT5 ID khac. Lien he admin."
        }
    db.commit()
    # ── Phase 4B: Radar Context — gắn radar_map vào heartbeat response ──────
    radar_map = {}
    any_warn  = False  # init — set True nếu có symbol ở MINIMAL state
    try:
        from radar.router import get_radar_map_for_symbols
        # FIX C-4: dùng SYMBOL_TO_ASSET map để resolve broker symbols → Radar asset keys
        raw_syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else []
        sym_list = []
        for s in raw_syms:
            asset = _mt5_symbol_to_asset(s)
            if asset and asset not in sym_list:
                sym_list.append(asset)
            elif not asset:
                # Symbol không nhận ra — log warn nhưng không drop
                print(f"[HEARTBEAT] Unknown symbol '{s}' — not in SYMBOL_TO_ASSET map", flush=True)
        if not sym_list and account:
            try:
                unit_cfg = get_all_units().get(account, {})
                cfg_sym  = unit_cfg.get("current_symbol", "")
                if cfg_sym:
                    mapped = _mt5_symbol_to_asset(cfg_sym)
                    if mapped:
                        sym_list = [mapped]
            except Exception:
                pass
        if not sym_list:
            sym_list = ["GOLD"]  # default fallback — XAUUSD→GOLD via map
        radar_map = get_radar_map_for_symbols(sym_list, tf or "H1")
        any_avoid = any(v.get("allow_trade") is False for v in radar_map.values())
        any_warn  = any(v.get("state_cap") == "MINIMAL" for v in radar_map.values())
        if any_avoid:
            # FIX C-2: allow_trade=False được set khi gate=="BLOCK" (score<30) bởi engine._ea_params()
            # Trước đây hardcode score<20 — vùng 20-29 bị lọt qua.
            print(f"[HEARTBEAT] RADAR_AVOID | account={account} symbols={sym_list}", flush=True)
            return {
                "valid":      True,
                "lock":       True,
                "emergency":  False,
                "status":     db_license.status,
                "expires_at": db_license.expires_at.isoformat() if db_license.expires_at else "lifetime",
                "reason":     "RADAR_AVOID",
                "radar_map":  radar_map,
            }
        if any_warn:
            print(f"[HEARTBEAT] RADAR_WARN | account={account} symbols={sym_list}", flush=True)
    except Exception as _re:
        print(f"[HEARTBEAT] Radar context error (non-fatal): {_re}", flush=True)
        radar_map = {}

    # ── Multi-Strategy: inject strategy_profile từ license.strategy_id ───────
    # EA đọc qua CloudBridge._ParseStrategyProfile() → populate g_profile
    # g_profile được dùng bởi: Panel Tab 1, RegimeGateFilter, SizingEngine
    strategy_profile = None
    try:
        from strategy_presets import preset_to_heartbeat_profile
        sid = getattr(db_license, "strategy_id", None) or "S1"
        strategy_profile = preset_to_heartbeat_profile(sid)
    except Exception as _spe:
        print(f"[HEARTBEAT] strategy_profile inject error (non-fatal): {_spe}", flush=True)

    print(f"[HEARTBEAT] OK | key={license[:12]}... account={account} equity={equity:.2f} radar={list(radar_map.keys())} strategy={getattr(db_license,'strategy_id','S1')}", flush=True)

    hb_response = {
        "valid":      True,
        "lock":       False,
        "emergency":  False,
        "status":     db_license.status,
        "expires_at": db_license.expires_at.isoformat() if db_license.expires_at else "lifetime",
        "reason":     "RADAR_WARN" if any_warn else "OK",
        "radar_map":  radar_map,
    }
    if strategy_profile:
        hb_response["strategy_profile"] = strategy_profile
    return hb_response

@app.get("/heartbeat")
async def ea_heartbeat_get(
    account:  str   = None,
    magic:    str   = "",
    license:  str   = "",
    equity:   float = 0,
    balance:  float = 0,
    ts:       str   = "",
    symbols:  str   = "",
    tf:       str   = "H1",
    db=Depends(get_db)
):
    """GET /heartbeat — EA dùng WebRequest GET"""
    return await _ea_heartbeat_handler(account, magic, license, equity, balance, ts, db, symbols, tf)
@app.post("/heartbeat")
async def ea_heartbeat_post(
    request: Request,
    db=Depends(get_db)
):
    """
    POST /heartbeat — tương thích với EA phiên bản cũ dùng WebRequest POST.
    Đọc params từ query string hoặc JSON body.
    """
    account = magic = license = ts = ""
    equity = balance = 0.0
    try:
        body = await request.json()
        account  = str(body.get("account",  body.get("account_id", "")) or "")
        magic    = str(body.get("magic",    "") or "")
        license  = str(body.get("license",  body.get("license_key", "")) or "")
        equity   = float(body.get("equity",  0) or 0)
        balance  = float(body.get("balance", 0) or 0)
        ts       = str(body.get("ts", "") or "")
    except Exception:
        pass
    qp = request.query_params
    if not account:  account  = qp.get("account",  qp.get("account_id", ""))
    if not magic:    magic    = qp.get("magic",    "")
    if not license:  license  = qp.get("license",  qp.get("license_key", ""))
    if not equity:   equity   = float(qp.get("equity",  0) or 0)
    if not balance:  balance  = float(qp.get("balance", 0) or 0)
    if not ts:       ts       = qp.get("ts", "")
    symbols = ""
    tf      = "H1"
    try:
        body_raw = await request.body()
        if body_raw:
            import json as _j
            _b = _j.loads(body_raw.decode("utf-8").strip('\x00').strip())
            symbols = str(_b.get("symbols", "") or "")
            tf      = str(_b.get("tf", "H1") or "H1")
    except Exception:
        pass
    if not symbols: symbols = qp.get("symbols", "")
    if tf == "H1":  tf      = qp.get("tf", "H1")
    return await _ea_heartbeat_handler(account, magic, license, equity, balance, ts, db, symbols, tf)
# ==========================================
# ADMIN API — Quản lý license từ dashboard
# ==========================================
@app.post("/admin/licenses")
async def admin_create_license(
    request:      Request,
    owner_name:   str   = Query(""),
    owner_email:  str   = Query(""),
    plan:         str   = Query("standard"),
    max_machines: int   = Query(1),
    expires_at:   str   = Query(""),
    note:         str   = Query(""),
    db=Depends(get_db)
):
    """Tao license key moi. Header: X-Admin-Token required."""
    _check_admin(request)
    import uuid as _uuid
    key = "ZARMOR-" + _uuid.uuid4().hex[:5].upper() + "-" + _uuid.uuid4().hex[:5].upper()
    exp = None
    if expires_at:
        try:
             from datetime import datetime as _dt
             exp = _dt.fromisoformat(expires_at)
        except Exception:
             exp = None
    lic = License(
        license_key  = key,
        tier         = plan,
        status       = "ACTIVE",
        buyer_email  = owner_email or "admin@zarmor.com",
        bound_mt5_id = None,
        expires_at   = exp,
        max_machines = max_machines,
        strategy_id  = "S1",
    )
    db.add(lic)
    db.commit()
    print(f"[ADMIN] LICENSE CREATED | key={key} owner={owner_name} plan={plan}", flush=True)
    return {
        "status":      "created",
        "key":         key,
        "owner":       owner_name,
        "plan":        plan,
        "max_machines": max_machines,
        "expires_at":  expires_at or "lifetime",
    }
@app.get("/admin/licenses")
async def admin_list_licenses(request: Request, db=Depends(get_db)):
    _check_admin(request)
    rows = db.query(License).order_by(License.id.desc()).all()
    result = []
    for r in rows:
        machines = list(_get_machines(db, r.license_key))
        result.append({
            "id":           r.id,
            "license_key":  r.license_key,
            "tier":         getattr(r, "tier", "standard"),
            "status":       r.status,
            "bound_mt5_id": r.bound_mt5_id,
            "buyer_email":  getattr(r, "buyer_email", ""),
            "expires_at":   r.expires_at.isoformat() if r.expires_at else None,
            "max_machines": getattr(r, "max_machines", 1),
            "machines":     machines,
            "machine_count": len(machines),
            "strategy_id":  getattr(r, "strategy_id", "S1") or "S1",
        })
    return result
@app.post("/admin/licenses/{key}/revoke")
async def admin_revoke(key: str, request: Request, db=Depends(get_db)):
    _check_admin(request)
    lic = db.query(License).filter(License.license_key == key).first()
    if not lic:
        raise HTTPException(404, "License not found")
    lic.status = "REVOKED"
    db.commit()
    print(f"[ADMIN] REVOKED | key={key}", flush=True)
    return {"status": "revoked", "key": key}
@app.post("/admin/licenses/{key}/activate")
async def admin_activate(key: str, request: Request, db=Depends(get_db)):
    _check_admin(request)
    lic = db.query(License).filter(License.license_key == key).first()
    if not lic:
        raise HTTPException(404, "License not found")
    lic.status = "ACTIVE"
    db.commit()
    return {"status": "activated", "key": key}
@app.post("/admin/licenses/{key}/reset-machines")
async def admin_reset_machines(key: str, request: Request, db=Depends(get_db)):
    """Xóa danh sách máy — user có thể kích hoạt lại trên máy mới."""
    _check_admin(request)
    _machine_registry.pop(key, None)
    try:
        from database import LicenseActivation
        db.query(LicenseActivation).filter(
            LicenseActivation.license_key == key
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
    return {"status": "machines_reset", "key": key}
@app.get("/admin/stats")
async def admin_stats(request: Request, db=Depends(get_db)):
    _check_admin(request)
    total   = db.query(License).count()
    active  = db.query(License).filter(License.status == "ACTIVE").count()
    unused  = db.query(License).filter(License.status == "UNUSED").count()
    revoked = db.query(License).filter(License.status == "REVOKED").count()
    return {
        "total":   total,
        "active":  active,
        "unused":  unused,
        "revoked": revoked,
    }
# ==========================================
# STATIC FILES + ENTRYPOINT
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
web_path  = os.path.join(BASE_DIR, "web")
@app.get("/", response_class=FileResponse)
def landing_page():
    for name in ("salemain.html", "sales-main.html", "index_landing.html"):
        f = os.path.join(BASE_DIR, name)
        if os.path.exists(f):
            return FileResponse(f)
    return HTMLResponse("<h1>Z-ARMOR CLOUD</h1><p><a href='/web/'>Dashboard →</a></p>")
if os.path.exists(web_path):
    app.mount("/web", StaticFiles(directory=web_path, html=True), name="web")
    print(f"[INFO] Dashboard mounted at /web/ from {web_path}", flush=True)
@app.get("/manifest.json")
def get_manifest():
    manifest_path = os.path.join(BASE_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/json")
    return {"error": "manifest.json not found"}
@app.get("/favicon.ico")
def get_favicon():
    favicon_path = os.path.join(web_path, "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path, media_type="image/x-icon")
    return {"error": "favicon.ico not found"}
@app.get("/scan")
def radar_scan_page():
    for name in ("scan.html", "radar_widget_v3.html", "radar_scan.html"):
        f = os.path.join(BASE_DIR, name)
        if os.path.exists(f):
            return FileResponse(f, media_type="text/html")
    return HTMLResponse("""
        <html><body style="background:#020305;color:#00e5ff;font-family:monospace;padding:40px;text-align:center;">
        <h2 style="letter-spacing:3px;">⚡ RADAR SCAN</h2>
        <p style="color:#ff4444;margin-top:16px;">scan.html chưa được upload lên server.</p>
        <p style="color:#445;margin-top:8px;font-size:12px;">Copy file radar_widget_v3.html vào thư mục server và đổi tên thành scan.html</p>
        </body></html>
    """, status_code=200)
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, workers=1, reload=False)