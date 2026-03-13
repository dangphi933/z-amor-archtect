"""
api/user_portal_router.py — User Self-Service Portal
=====================================================
Cho phép khách hàng quản lý tài khoản qua email:

FLOW:
  1. Đăng ký / Đăng nhập bằng email → nhận Magic Link (không cần password)
  2. Click link → vào portal, xem license, quản lý MT5 accounts
  3. Mua gói mới / renew ngay trong portal
  4. Thêm / xóa MT5 account_id

ENDPOINTS:
  POST /portal/auth/request-link   — gửi magic link vào email
  GET  /portal/auth/verify          — verify token từ magic link → JWT
  GET  /portal/me                   — profile + licenses + MT5 accounts
  POST /portal/mt5/add              — thêm MT5 account
  POST /portal/mt5/remove           — xóa MT5 account
  POST /portal/checkout             — mua gói / trial từ portal
  GET  /portal/licenses             — danh sách licenses của user
"""

import os, uuid, time, hmac, hashlib, json, smtplib, logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portal", tags=["user-portal"])

# ── Config ────────────────────────────────────────────────────────────────────
SMTP_EMAIL    = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
BACKEND_URL   = os.environ.get("NEW_BACKEND_URL", "http://localhost:8000")
JWT_SECRET    = os.environ.get("JWT_SECRET_KEY", "zarmor-portal-secret")
MAGIC_TTL     = 900        # 15 phút
SESSION_TTL   = 86400 * 7  # 7 ngày

# In-memory stores (MVP — đủ dùng cho vài trăm user)
_magic_tokens:   dict = {}   # token → {email, exp}
_session_tokens: dict = {}   # token → {email, exp, created_at}
_portal_rl:      dict = {}   # email → [timestamps] (rate limit magic link)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _now() -> float:
    return time.time()

def _gen_token(n: int = 32) -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex[:n - 32]

def _sign(data: str) -> str:
    return hmac.new(JWT_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()

def _make_session(email: str) -> str:
    token = _gen_token(48)
    _session_tokens[token] = {
        "email":      email,
        "exp":        _now() + SESSION_TTL,
        "created_at": _now(),
    }
    return token

def _get_current_user(request: Request) -> str:
    """Lấy email từ session token — dùng làm dependency."""
    token = (
        request.headers.get("X-Portal-Token")
        or request.cookies.get("zarmor_portal_token")
        or request.query_params.get("token")
    )
    if not token:
        raise HTTPException(401, "Chưa đăng nhập. Vui lòng kiểm tra email để lấy link đăng nhập.")
    sess = _session_tokens.get(token)
    if not sess:
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
    if sess["exp"] < _now():
        del _session_tokens[token]
        raise HTTPException(401, "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
    return sess["email"]

def get_db():
    from database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── Email sender ──────────────────────────────────────────────────────────────
def _send_magic_link_email(to_email: str, magic_link: str, is_new_user: bool):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        logger.warning("[PORTAL] SMTP chưa cấu hình — không gửi magic link được")
        return False
    try:
        action_text = "Đăng ký tài khoản" if is_new_user else "Đăng nhập"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Z-ARMOR] Link {action_text} của bạn"
        msg["From"]    = f"Z-Armor Cloud <{SMTP_EMAIL}>"
        msg["To"]      = to_email

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body {{ font-family: 'Courier New', monospace; background:#05070a; color:#fff; margin:0; padding:40px; }}
  .wrap {{ max-width:560px; margin:0 auto; background:#0a0f1a; border:1px solid #00e5ff; border-radius:8px; padding:36px; }}
  h2 {{ color:#00e5ff; letter-spacing:3px; font-size:18px; margin:0 0 8px; }}
  .sub {{ color:#445; font-size:12px; margin:0 0 28px; letter-spacing:1px; }}
  p {{ color:#aab; font-size:14px; line-height:1.7; }}
  .btn {{ display:inline-block; margin:24px 0; padding:14px 32px;
          background:linear-gradient(135deg,#00ff9d,#00e5ff);
          color:#05070a!important; font-weight:bold; font-size:15px;
          text-decoration:none; border-radius:4px; letter-spacing:1px; }}
  .warn {{ color:#ffaa00; font-size:12px; margin-top:24px; border-top:1px solid #1a2030; padding-top:16px; }}
  code {{ color:#00e5ff; background:#141922; padding:2px 8px; border-radius:3px; font-size:13px; }}
</style>
</head>
<body>
<div class="wrap">
  <h2>Z-ARMOR CLOUD</h2>
  <p class="sub">RISK MANAGEMENT SAAS FOR MT5</p>
  <p>Xin chào,<br>
  Bạn yêu cầu <strong style="color:#00e5ff">{action_text}</strong> vào Z-Armor Cloud Portal.<br>
  Click nút bên dưới để {'tạo tài khoản và ' if is_new_user else ''}đăng nhập ngay:</p>
  <a href="{magic_link}" class="btn">▶ {action_text.upper()}</a>
  <p>Hoặc copy link này vào trình duyệt:<br>
  <code style="font-size:11px;word-break:break-all">{magic_link}</code></p>
  <p class="warn">
  ⏱ Link có hiệu lực trong <strong>15 phút</strong>.<br>
  🔒 Nếu bạn không yêu cầu đăng nhập, hãy bỏ qua email này.
  </p>
</div>
</body></html>"""

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SMTP_EMAIL, SMTP_PASSWORD)
            s.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        logger.info(f"[PORTAL] Magic link sent → {to_email}")
        return True
    except Exception as e:
        logger.error(f"[PORTAL] Email error: {e}")
        return False


def _send_welcome_email(to_email: str, license_key: str, tier: str):
    """Gửi email welcome khi user đăng ký mới + nhận license."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return False
    try:
        portal_url = f"{BACKEND_URL}/portal/dashboard"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Z-ARMOR] Chào mừng! License Key của bạn đã sẵn sàng"
        msg["From"]    = f"Z-Armor Cloud <{SMTP_EMAIL}>"
        msg["To"]      = to_email

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family:'Courier New',monospace; background:#05070a; color:#fff; margin:0; padding:40px; }}
  .wrap {{ max-width:560px; margin:0 auto; background:#0a0f1a; border:2px solid #00ff9d; border-radius:8px; padding:36px; }}
  h2 {{ color:#00ff9d; letter-spacing:3px; font-size:18px; margin:0 0 4px; }}
  .key-box {{ background:#141922; border:1px solid #00e5ff; border-radius:6px; padding:20px; margin:24px 0; text-align:center; }}
  .key {{ color:#00e5ff; font-size:22px; font-weight:bold; letter-spacing:2px; }}
  .tier {{ display:inline-block; background:#00ff9d22; color:#00ff9d; border:1px solid #00ff9d;
           padding:3px 12px; border-radius:3px; font-size:12px; letter-spacing:2px; margin-bottom:8px; }}
  .btn {{ display:inline-block; margin:20px 0; padding:14px 32px;
          background:linear-gradient(135deg,#00ff9d,#00e5ff);
          color:#05070a!important; font-weight:bold; font-size:15px;
          text-decoration:none; border-radius:4px; }}
  .step {{ background:#0d1520; border-left:3px solid #00e5ff; padding:12px 16px; margin:10px 0;
           font-size:13px; color:#aab; }}
  .step strong {{ color:#fff; }}
</style>
</head>
<body>
<div class="wrap">
  <h2>🎯 Z-ARMOR CLOUD</h2>
  <p style="color:#445;font-size:12px;margin:0 0 20px;letter-spacing:1px">RISK MANAGEMENT SAAS FOR MT5</p>
  <p>Xin chào! Tài khoản của bạn đã được tạo thành công.</p>
  <div class="key-box">
    <div class="tier">{tier}</div>
    <div style="color:#aab;font-size:12px;margin-bottom:8px">LICENSE KEY</div>
    <div class="key">{license_key}</div>
  </div>
  <p style="color:#aab;font-size:13px"><strong>Các bước tiếp theo:</strong></p>
  <div class="step"><strong>1.</strong> Mở MetaTrader 5 → Expert Advisors → ZArmorKernel</div>
  <div class="step"><strong>2.</strong> Nhập License Key vào ô <code style="color:#00e5ff">LicenseKey</code></div>
  <div class="step"><strong>3.</strong> Nhập Server URL: <code style="color:#00e5ff">{BACKEND_URL}</code></div>
  <div class="step"><strong>4.</strong> Vào Portal để thêm MT5 Account ID và quản lý tài khoản</div>
  <a href="{portal_url}" class="btn">▶ VÀO PORTAL QUẢN LÝ</a>
  <p style="color:#445;font-size:11px;margin-top:20px;border-top:1px solid #1a2030;padding-top:16px">
  Lưu ý: License key chỉ gửi 1 lần. Hãy lưu lại cẩn thận.<br>
  Hỗ trợ: Reply email này hoặc liên hệ Telegram admin.
  </p>
</div>
</body></html>"""
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SMTP_EMAIL, SMTP_PASSWORD)
            s.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        logger.error(f"[PORTAL] Welcome email error: {e}")
        return False


# ── Schemas ───────────────────────────────────────────────────────────────────
class RequestLinkPayload(BaseModel):
    email: str
    plan:  Optional[str] = None   # nếu đến từ trang checkout → auto flow

class AddMT5Payload(BaseModel):
    account_id: str
    note:       Optional[str] = ""   # tên ghi nhớ, vd "Live Gold Account"

class RemoveMT5Payload(BaseModel):
    account_id: str
    license_key: str

class PortalCheckoutPayload(BaseModel):
    tier:        str   # TRIAL_FREE / STARTER / PRO
    method:      Optional[str] = "TRIAL_FREE"


# ══════════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/auth/request-link")
async def request_magic_link(payload: RequestLinkPayload, request: Request):
    """
    Gửi magic link vào email.
    Rate limit: 3 link / email / 10 phút.
    """
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Email không hợp lệ.")

    # Rate limit
    _now_ts  = _now()
    _rl_times = [t for t in _portal_rl.get(email, []) if _now_ts - t < 600]
    if len(_rl_times) >= 3:
        raise HTTPException(429, "Bạn đã yêu cầu quá nhiều link. Vui lòng thử lại sau 10 phút.")
    _rl_times.append(_now_ts)
    _portal_rl[email] = _rl_times

    # Tạo magic token
    token     = _gen_token(40)
    magic_url = f"{BACKEND_URL}/portal/auth/verify?token={token}&email={email}"
    if payload.plan:
        magic_url += f"&plan={payload.plan}"

    _magic_tokens[token] = {
        "email": email,
        "exp":   _now_ts + MAGIC_TTL,
        "plan":  payload.plan,
    }

    # Kiểm tra user mới hay cũ
    from database import SessionLocal, License
    db = SessionLocal()
    try:
        is_new = db.query(License).filter(License.buyer_email == email).first() is None
    finally:
        db.close()

    ok = _send_magic_link_email(email, magic_url, is_new)
    if not ok:
        # Dev mode: trả token ra (chỉ khi DEBUG=True)
        if os.environ.get("DEBUG", "False").lower() == "true":
            return {"ok": True, "dev_link": magic_url, "note": "DEBUG mode — link returned"}

    return {
        "ok":      True,
        "message": f"Link đăng nhập đã gửi tới {email}. Kiểm tra hộp thư (kể cả Spam).",
        "expires": "15 phút",
    }


@router.get("/auth/verify")
async def verify_magic_link(
    token: str = Query(...),
    email: str = Query(...),
    plan:  str = Query(default=None),
):
    """
    Verify magic link → tạo session → redirect về portal dashboard.
    """
    email = email.strip().lower()
    data  = _magic_tokens.get(token)

    if not data:
        return HTMLResponse(_error_page("Link không hợp lệ hoặc đã được sử dụng."), status_code=400)
    if data["exp"] < _now():
        del _magic_tokens[token]
        return HTMLResponse(_error_page("Link đã hết hạn (15 phút). Vui lòng yêu cầu link mới."), status_code=400)
    if data["email"] != email:
        return HTMLResponse(_error_page("Link không hợp lệ."), status_code=400)

    # Dùng 1 lần
    del _magic_tokens[token]

    # Tạo session
    session_token = _make_session(email)

    # Redirect về dashboard với cookie
    redirect_url = f"{BACKEND_URL}/portal/dashboard"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key="zarmor_portal_token",
        value=session_token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
    )
    logger.info(f"[PORTAL] Login OK: {email}")
    return response


@router.post("/auth/logout")
async def logout(request: Request):
    token = request.cookies.get("zarmor_portal_token")
    if token and token in _session_tokens:
        del _session_tokens[token]
    response = HTMLResponse('{"ok":true}')
    response.delete_cookie("zarmor_portal_token")
    return response


# ══════════════════════════════════════════════════════════════════════════════
# USER DATA ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/me")
async def get_me(
    request: Request,
    db: Session = Depends(get_db),
    email: str  = Depends(_get_current_user),
):
    """Profile + tất cả licenses + MT5 accounts."""
    from database import License, LicenseActivation
    from sqlalchemy import text

    licenses_raw = db.query(License).filter(
        License.buyer_email == email
    ).order_by(License.id.desc()).all()

    licenses = []
    for lic in licenses_raw:
        # Lấy MT5 accounts đã bind
        try:
            acts = db.query(LicenseActivation).filter(
                LicenseActivation.license_key == lic.license_key
            ).all()
            mt5_accounts = [{
                "account_id": a.account_id,
                "magic":      a.magic,
                "first_seen": str(a.first_seen)[:19] if a.first_seen else None,
                "last_seen":  str(a.last_seen)[:19]  if a.last_seen  else None,
                "note":       getattr(a, "note", ""),
            } for a in acts]
        except Exception:
            # Nếu LicenseActivation chưa có note column
            mt5_accounts = []
            if lic.bound_mt5_id:
                mt5_accounts = [{"account_id": lic.bound_mt5_id}]

        now_utc = datetime.now(timezone.utc)
        exp     = lic.expires_at
        is_exp  = exp and exp.replace(tzinfo=timezone.utc) < now_utc if exp else False
        days_left = None
        if exp and not is_exp:
            exp_aware = exp.replace(tzinfo=timezone.utc) if exp.tzinfo is None else exp
            days_left = max(0, (exp_aware - now_utc).days)

        licenses.append({
            "license_key":   lic.license_key,
            "tier":          lic.tier or "STARTER",
            "status":        "EXPIRED" if is_exp else (lic.status or "ACTIVE"),
            "is_trial":      bool(getattr(lic, "is_trial", False)),
            "expires_at":    str(exp)[:19] if exp else None,
            "days_left":     days_left,
            "max_machines":  getattr(lic, "max_machines", 1) or 1,
            "mt5_accounts":  mt5_accounts,
            "created_at":    str(getattr(lic, "created_at", ""))[:19],
        })

    return {
        "email":    email,
        "licenses": licenses,
        "total":    len(licenses),
        "active":   sum(1 for l in licenses if l["status"] == "ACTIVE"),
    }


@router.get("/licenses")
async def list_licenses(
    request: Request,
    db: Session = Depends(get_db),
    email: str  = Depends(_get_current_user),
):
    """Alias cho /me — chỉ trả danh sách licenses."""
    data = await get_me(request, db, email)
    return {"licenses": data["licenses"]}


# ══════════════════════════════════════════════════════════════════════════════
# MT5 ACCOUNT MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/mt5/add")
async def add_mt5_account(
    payload: AddMT5Payload,
    request: Request,
    db:      Session = Depends(get_db),
    email:   str     = Depends(_get_current_user),
):
    """
    Thêm MT5 account vào license đang ACTIVE.
    Nếu user có nhiều license → thêm vào license ACTIVE gần nhất.
    """
    from database import License, LicenseActivation

    account_id = str(payload.account_id).strip()
    if not account_id.isdigit() or len(account_id) < 5:
        raise HTTPException(400, "MT5 Account ID phải là số (ví dụ: 413408816).")

    # Tìm license ACTIVE
    lic = db.query(License).filter(
        License.buyer_email == email,
        License.status      == "ACTIVE",
    ).order_by(License.id.desc()).first()

    if not lic:
        raise HTTPException(404, "Không tìm thấy license đang active. Vui lòng mua gói trước.")

    # Kiểm tra limit
    max_m = getattr(lic, "max_machines", 1) or 1
    try:
        current_count = db.query(LicenseActivation).filter(
            LicenseActivation.license_key == lic.license_key
        ).count()
    except Exception:
        current_count = 1 if lic.bound_mt5_id else 0

    if current_count >= max_m:
        raise HTTPException(400,
            f"License của bạn chỉ cho phép tối đa {max_m} tài khoản MT5. "
            f"Hãy xóa bớt tài khoản cũ hoặc nâng cấp gói."
        )

    # Kiểm tra account đã tồn tại chưa
    try:
        existing = db.query(LicenseActivation).filter(
            LicenseActivation.license_key == lic.license_key,
            LicenseActivation.account_id  == account_id,
        ).first()
        if existing:
            raise HTTPException(400, f"MT5 Account {account_id} đã được thêm vào license này.")

        db.add(LicenseActivation(
            license_key=lic.license_key,
            account_id=account_id,
            magic="",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        ))
        # Update bound_mt5_id nếu chưa có
        if not lic.bound_mt5_id:
            lic.bound_mt5_id = account_id
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[PORTAL] Add MT5 error: {e}")
        raise HTTPException(500, f"Lỗi database: {e}")

    logger.info(f"[PORTAL] MT5 added: {email} → {account_id} (license={lic.license_key[:12]}...)")
    return {
        "ok":         True,
        "message":    f"Đã thêm MT5 Account {account_id} thành công.",
        "license_key": lic.license_key,
        "account_id":  account_id,
    }


@router.post("/mt5/remove")
async def remove_mt5_account(
    payload: RemoveMT5Payload,
    request: Request,
    db:      Session = Depends(get_db),
    email:   str     = Depends(_get_current_user),
):
    """Xóa MT5 account khỏi license (chỉ owner mới được xóa)."""
    from database import License, LicenseActivation

    # Xác minh license thuộc về user này
    lic = db.query(License).filter(
        License.license_key == payload.license_key,
        License.buyer_email == email,
    ).first()
    if not lic:
        raise HTTPException(403, "Không có quyền thao tác với license này.")

    try:
        deleted = db.query(LicenseActivation).filter(
            LicenseActivation.license_key == payload.license_key,
            LicenseActivation.account_id  == payload.account_id,
        ).delete()
        # Xóa bound_mt5_id nếu đang là account này
        if lic.bound_mt5_id == payload.account_id:
            # Gán sang account khác nếu còn
            remaining = db.query(LicenseActivation).filter(
                LicenseActivation.license_key == payload.license_key
            ).first()
            lic.bound_mt5_id = remaining.account_id if remaining else None
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Lỗi: {e}")

    if deleted == 0:
        raise HTTPException(404, "MT5 Account không tìm thấy trong license này.")

    logger.info(f"[PORTAL] MT5 removed: {email} → {payload.account_id}")
    return {"ok": True, "message": f"Đã xóa MT5 Account {payload.account_id}."}


# ══════════════════════════════════════════════════════════════════════════════
# PORTAL CHECKOUT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/checkout")
async def portal_checkout(
    payload: PortalCheckoutPayload,
    request: Request,
    db:      Session = Depends(get_db),
    email:   str     = Depends(_get_current_user),
):
    """
    Mua gói / kích hoạt trial từ trong portal.
    Trial: tạo key ngay, gửi email xác nhận.
    Paid: trả link payment.
    """
    from database import License

    tier   = (payload.tier or "TRIAL_FREE").upper()
    method = (payload.method or "TRIAL_FREE").upper()

    # Kiểm tra trial chưa dùng
    if method == "TRIAL_FREE":
        trial_used = db.query(License).filter(
            License.buyer_email == email,
            License.is_trial    == True,
        ).first()
        if trial_used:
            raise HTTPException(400,
                "Bạn đã sử dụng gói Trial. Hãy mua gói có phí để tiếp tục."
            )

        # Tạo license key
        key        = f"ZARMOR-{uuid.uuid4().hex[:5].upper()}-{uuid.uuid4().hex[:5].upper()}"
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        new_lic = License(
            license_key    = key,
            tier           = "TRIAL",
            status         = "ACTIVE",
            buyer_name     = email.split("@")[0],
            buyer_email    = email,
            bound_mt5_id   = None,
            is_trial       = True,
            amount_usd     = 0.0,
            payment_method = "TRIAL_FREE",
            expires_at     = expires_at,
            max_machines   = 1,
            email_sent     = False,
        )
        db.add(new_lic)
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"Lỗi tạo license: {e}")

        # Gửi email welcome
        _send_welcome_email(email, key, "TRIAL 7 NGÀY")

        return {
            "ok":          True,
            "license_key": key,
            "tier":        "TRIAL",
            "expires_at":  str(expires_at)[:19],
            "message":     "Đã kích hoạt Trial 7 ngày. Kiểm tra email để xem hướng dẫn.",
        }

    # Paid plans
    tier_prices = {
        "STARTER": 29,
        "PRO":     79,
        "ELITE":   149,
    }
    price = tier_prices.get(tier, 0)
    if price == 0:
        raise HTTPException(400, f"Gói {tier} không hợp lệ.")

    return {
        "ok":          True,
        "action":      "redirect_payment",
        "tier":        tier,
        "amount_usd":  price,
        "message":     f"Vui lòng hoàn tất thanh toán ${price} để kích hoạt gói {tier}.",
        "note":        "Tích hợp Stripe/PayPal — liên hệ admin để mua.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# PORTAL DASHBOARD (HTML)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard", response_class=HTMLResponse)
async def portal_dashboard(request: Request):
    """Serve trang dashboard — frontend tự gọi /portal/me qua API."""
    backend_url = BACKEND_URL
    return HTMLResponse(_dashboard_html(backend_url))


@router.get("/login", response_class=HTMLResponse)
async def portal_login_page(
    plan: str = Query(default=""),
    ref:  str = Query(default=""),
):
    """Trang login — nhập email, nhận magic link."""
    return HTMLResponse(_login_html(plan, ref))


# ══════════════════════════════════════════════════════════════════════════════
# HTML TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

def _error_page(msg: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Z-Armor — Lỗi</title>
<style>body{{background:#05070a;color:#fff;font-family:'Courier New',monospace;display:flex;
align-items:center;justify-content:center;min-height:100vh;margin:0}}
.box{{text-align:center;border:1px solid #ff3355;padding:40px;border-radius:8px;max-width:400px}}
h2{{color:#ff3355}}p{{color:#aab;font-size:14px}}
a{{color:#00e5ff}}
</style></head><body>
<div class="box">
<h2>⚠ LỖI</h2>
<p>{msg}</p>
<p><a href="/portal/login">← Yêu cầu link mới</a></p>
</div></body></html>"""


def _login_html(plan: str = "", ref: str = "") -> str:
    plan_js = f'"{plan}"' if plan else 'null'
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-Armor — Đăng nhập / Đăng ký</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing:border-box; margin:0; padding:0 }}
:root {{
  --bg:      #05070a;
  --card:    #0a0f1a;
  --border:  #1a2535;
  --accent:  #00e5ff;
  --green:   #00ff9d;
  --red:     #ff3355;
  --muted:   #4a5568;
  --text:    #e2e8f0;
}}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: 'Rajdhani', sans-serif;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}}
/* Animated grid bg */
.grid-bg {{
  position:fixed; inset:0; z-index:0;
  background-image:
    linear-gradient(rgba(0,229,255,.03) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,229,255,.03) 1px,transparent 1px);
  background-size:40px 40px;
  animation: gridMove 20s linear infinite;
}}
@keyframes gridMove {{ to {{ background-position:40px 40px }} }}
.glow {{
  position:fixed; width:500px; height:500px; border-radius:50%;
  background: radial-gradient(circle,rgba(0,229,255,.06),transparent 70%);
  pointer-events:none; z-index:0;
  animation: glowPulse 4s ease-in-out infinite alternate;
}}
@keyframes glowPulse {{ from{{opacity:.5;transform:scale(.9)}} to{{opacity:1;transform:scale(1.1)}} }}
.card {{
  position:relative; z-index:1;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 48px 40px;
  width: 100%;
  max-width: 420px;
  box-shadow: 0 0 80px rgba(0,229,255,.08);
  animation: slideUp .5s cubic-bezier(.16,1,.3,1);
}}
@keyframes slideUp {{ from{{opacity:0;transform:translateY(24px)}} to{{opacity:1;transform:translateY(0)}} }}
.logo {{
  text-align:center;
  margin-bottom: 32px;
}}
.logo-text {{
  font-family:'Share Tech Mono',monospace;
  font-size:22px;
  letter-spacing:4px;
  color: var(--green);
}}
.logo-sub {{
  font-size:11px;
  letter-spacing:3px;
  color: var(--muted);
  margin-top:4px;
}}
.title {{
  font-size:26px;
  font-weight:700;
  color:#fff;
  margin-bottom:8px;
}}
.subtitle {{
  font-size:14px;
  color: var(--muted);
  margin-bottom:32px;
  line-height:1.6;
}}
label {{
  display:block;
  font-size:12px;
  letter-spacing:2px;
  color: var(--muted);
  margin-bottom:8px;
  text-transform:uppercase;
}}
input[type=email] {{
  width:100%;
  background: #0d1520;
  border: 1px solid var(--border);
  border-radius:6px;
  padding: 14px 16px;
  font-size:16px;
  color: var(--text);
  font-family:'Share Tech Mono',monospace;
  outline:none;
  transition: border-color .2s, box-shadow .2s;
}}
input[type=email]:focus {{
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(0,229,255,.1);
}}
.btn {{
  width:100%;
  margin-top:20px;
  padding:16px;
  background: linear-gradient(135deg, var(--green), var(--accent));
  border: none;
  border-radius:6px;
  font-family:'Rajdhani',sans-serif;
  font-size:16px;
  font-weight:700;
  letter-spacing:2px;
  color: #05070a;
  cursor:pointer;
  transition: opacity .2s, transform .1s;
}}
.btn:hover {{ opacity:.9; transform:translateY(-1px) }}
.btn:active {{ transform:translateY(0) }}
.btn:disabled {{ opacity:.5; cursor:not-allowed; transform:none }}
.msg {{
  margin-top:16px;
  padding:12px 16px;
  border-radius:6px;
  font-size:14px;
  line-height:1.6;
  display:none;
}}
.msg.ok {{ background:#00ff9d11; border:1px solid #00ff9d44; color:#00ff9d }}
.msg.err {{ background:#ff335511; border:1px solid #ff335544; color:#ff7088 }}
.divider {{ border:none; border-top:1px solid var(--border); margin:28px 0 }}
.features {{
  display:grid; gap:10px;
}}
.feat {{
  display:flex; gap:12px; align-items:flex-start;
  font-size:13px; color:#7a8fa6;
}}
.feat-icon {{ color:var(--green); font-size:16px; flex-shrink:0; margin-top:1px }}
</style>
</head>
<body>
<div class="grid-bg"></div>
<div class="glow" style="top:-100px;left:-100px"></div>
<div class="card">
  <div class="logo">
    <div class="logo-text">Z-ARMOR</div>
    <div class="logo-sub">CLOUD ENGINE V8.3</div>
  </div>
  <div class="title">Đăng nhập / Đăng ký</div>
  <div class="subtitle">Nhập email của bạn — chúng tôi gửi link đăng nhập ngay lập tức.<br>Không cần mật khẩu.</div>

  <label for="email">Địa chỉ Email</label>
  <input type="email" id="email" placeholder="you@example.com" autocomplete="email">

  <button class="btn" id="btn" onclick="requestLink()">
    GỬI LINK ĐĂNG NHẬP
  </button>

  <div class="msg" id="msg"></div>

  <hr class="divider">
  <div class="features">
    <div class="feat"><span class="feat-icon">⚡</span><span>Quản lý license & MT5 accounts trong 1 nơi</span></div>
    <div class="feat"><span class="feat-icon">🔒</span><span>Đăng nhập bảo mật không cần mật khẩu</span></div>
    <div class="feat"><span class="feat-icon">📊</span><span>Xem Radar score realtime cho từng symbol</span></div>
  </div>
</div>

<script>
const plan = {plan_js};

function showMsg(text, type) {{
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = 'msg ' + type;
  el.style.display = 'block';
}}

async function requestLink() {{
  const email = document.getElementById('email').value.trim();
  if (!email || !email.includes('@')) {{
    showMsg('Vui lòng nhập email hợp lệ.', 'err');
    return;
  }}
  const btn = document.getElementById('btn');
  btn.disabled = true;
  btn.textContent = 'ĐANG GỬI...';
  try {{
    const body = {{ email }};
    if (plan) body.plan = plan;
    const r = await fetch('/portal/auth/request-link', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify(body)
    }});
    const d = await r.json();
    if (r.ok) {{
      showMsg('✅ ' + d.message, 'ok');
      btn.textContent = 'ĐÃ GỬI — KIỂM TRA EMAIL';
    }} else {{
      showMsg('❌ ' + (d.detail || 'Có lỗi xảy ra.'), 'err');
      btn.disabled = false;
      btn.textContent = 'GỬI LẠI';
    }}
  }} catch(e) {{
    showMsg('❌ Không kết nối được server.', 'err');
    btn.disabled = false;
    btn.textContent = 'THỬ LẠI';
  }}
}}

document.getElementById('email').addEventListener('keydown', e => {{
  if (e.key === 'Enter') requestLink();
}});
</script>
</body>
</html>"""


def _dashboard_html(backend_url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-Armor — Portal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#05070a; --card:#0a0f1a; --card2:#0d1520;
  --border:#1a2535; --accent:#00e5ff; --green:#00ff9d;
  --orange:#ffaa00; --red:#ff3355; --muted:#4a5568; --text:#e2e8f0;
}}
body{{background:var(--bg);color:var(--text);font-family:'Rajdhani',sans-serif;min-height:100vh}}
/* Grid bg */
body::before{{content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background-image:linear-gradient(rgba(0,229,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(0,229,255,.025) 1px,transparent 1px);
  background-size:40px 40px}}
.layout{{position:relative;z-index:1;max-width:900px;margin:0 auto;padding:24px 16px}}
/* Header */
.hdr{{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px;padding-bottom:20px;border-bottom:1px solid var(--border)}}
.logo{{font-family:'Share Tech Mono',monospace;font-size:18px;letter-spacing:4px;color:var(--green)}}
.logo span{{color:var(--muted);font-size:11px;display:block;letter-spacing:2px;margin-top:2px}}
.user-email{{font-size:13px;color:var(--muted);font-family:'Share Tech Mono',monospace}}
.logout-btn{{background:none;border:1px solid var(--border);color:var(--muted);padding:6px 14px;
  border-radius:4px;cursor:pointer;font-family:'Rajdhani',sans-serif;font-size:13px;
  transition:border-color .2s,color .2s}}
.logout-btn:hover{{border-color:var(--red);color:var(--red)}}
/* Section title */
.section-title{{font-size:12px;letter-spacing:3px;color:var(--muted);text-transform:uppercase;margin-bottom:16px;margin-top:32px}}
/* License card */
.lic-card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:24px;margin-bottom:16px;
  transition:border-color .2s}}
.lic-card:hover{{border-color:#1e3048}}
.lic-header{{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:12px}}
.lic-key{{font-family:'Share Tech Mono',monospace;font-size:16px;color:var(--accent);letter-spacing:1px}}
.badge{{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:1px}}
.badge.active{{background:#00ff9d18;border:1px solid #00ff9d44;color:var(--green)}}
.badge.expired{{background:#ff335518;border:1px solid #ff335544;color:var(--red)}}
.badge.trial{{background:#ffaa0018;border:1px solid #ffaa0044;color:var(--orange)}}
.lic-meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}}
.meta-item .label{{font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-bottom:4px}}
.meta-item .val{{font-size:15px;font-weight:600;color:#fff}}
.meta-item .val.warn{{color:var(--orange)}}
/* MT5 accounts */
.mt5-list{{display:flex;flex-direction:column;gap:8px}}
.mt5-item{{background:var(--card2);border:1px solid var(--border);border-radius:6px;padding:12px 16px;
  display:flex;align-items:center;justify-content:space-between;gap:12px}}
.mt5-id{{font-family:'Share Tech Mono',monospace;font-size:14px;color:var(--accent)}}
.mt5-meta{{font-size:12px;color:var(--muted)}}
.rm-btn{{background:none;border:1px solid #ff335533;color:#ff335588;padding:5px 12px;
  border-radius:4px;cursor:pointer;font-size:12px;transition:all .2s;white-space:nowrap}}
.rm-btn:hover{{background:#ff335511;border-color:var(--red);color:var(--red)}}
/* Add MT5 form */
.add-form{{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}}
.add-input{{flex:1;min-width:180px;background:#0d1520;border:1px solid var(--border);
  border-radius:6px;padding:10px 14px;font-size:14px;color:var(--text);
  font-family:'Share Tech Mono',monospace;outline:none;transition:border-color .2s}}
.add-input:focus{{border-color:var(--accent)}}
.add-btn{{padding:10px 20px;background:linear-gradient(135deg,var(--green),var(--accent));
  border:none;border-radius:6px;font-family:'Rajdhani',sans-serif;font-weight:700;
  font-size:14px;letter-spacing:1px;color:#05070a;cursor:pointer;white-space:nowrap}}
.add-btn:disabled{{opacity:.5;cursor:not-allowed}}
/* Empty state */
.empty{{text-align:center;padding:48px 24px;color:var(--muted);border:1px dashed var(--border);border-radius:10px}}
.empty-icon{{font-size:40px;margin-bottom:12px}}
.empty p{{font-size:14px;margin-bottom:20px}}
/* Trial CTA */
.cta-box{{background:linear-gradient(135deg,#001a12,#001520);border:1px solid #00ff9d33;
  border-radius:10px;padding:28px;text-align:center}}
.cta-box h3{{font-size:20px;color:var(--green);margin-bottom:8px}}
.cta-box p{{font-size:14px;color:var(--muted);margin-bottom:20px}}
.cta-btn{{display:inline-block;padding:14px 32px;background:linear-gradient(135deg,var(--green),var(--accent));
  border:none;border-radius:6px;font-family:'Rajdhani',sans-serif;font-weight:700;
  font-size:15px;letter-spacing:2px;color:#05070a;cursor:pointer}}
/* Toast */
.toast{{position:fixed;bottom:24px;right:24px;z-index:999;padding:14px 20px;
  border-radius:8px;font-size:14px;font-weight:600;letter-spacing:.5px;
  transform:translateY(100px);opacity:0;transition:all .3s cubic-bezier(.16,1,.3,1)}}
.toast.show{{transform:translateY(0);opacity:1}}
.toast.ok{{background:#00ff9d;color:#05070a}}
.toast.err{{background:#ff3355;color:#fff}}
/* Loading */
.spinner{{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.2);
  border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:8px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
@media(max-width:480px){{
  .lic-header{{flex-direction:column}}
  .hdr{{flex-direction:column;align-items:flex-start;gap:12px}}
}}
</style>
</head>
<body>
<div class="layout">
  <!-- Header -->
  <div class="hdr">
    <div class="logo">Z-ARMOR CLOUD <span>USER PORTAL V8.3</span></div>
    <div style="display:flex;align-items:center;gap:16px">
      <div class="user-email" id="user-email">...</div>
      <button class="logout-btn" onclick="logout()">ĐĂNG XUẤT</button>
    </div>
  </div>

  <!-- Main content -->
  <div id="main"><div style="text-align:center;padding:60px;color:var(--muted)">
    <div class="spinner"></div> Đang tải...
  </div></div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = '{backend_url}';

// ── Auth helper ───────────────────────────────────────────────────────────────
function getToken() {{
  const m = document.cookie.match(/zarmor_portal_token=([^;]+)/);
  return m ? m[1] : null;
}}
function authHeaders() {{
  return {{'Content-Type':'application/json','X-Portal-Token': getToken() || ''}};
}}

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg, type='ok') {{
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast ' + type + ' show';
  setTimeout(() => el.className = 'toast', 3000);
}}

// ── Logout ────────────────────────────────────────────────────────────────────
async function logout() {{
  await fetch(API + '/portal/auth/logout', {{method:'POST', headers:authHeaders()}});
  document.cookie = 'zarmor_portal_token=; max-age=0';
  window.location.href = '/portal/login';
}}

// ── Format helpers ────────────────────────────────────────────────────────────
function formatDate(s) {{
  if (!s) return '—';
  return s.replace('T',' ').slice(0,16);
}}
function daysLabel(n) {{
  if (n === null || n === undefined) return '—';
  if (n <= 0) return '<span style="color:var(--red)">Đã hết hạn</span>';
  if (n <= 3) return '<span style="color:var(--red)">' + n + ' ngày</span>';
  if (n <= 7) return '<span style="color:var(--orange)">' + n + ' ngày</span>';
  return '<span style="color:var(--green)">' + n + ' ngày</span>';
}}

// ── Render ────────────────────────────────────────────────────────────────────
function renderLicenseCard(lic) {{
  const statusBadge = lic.status === 'ACTIVE'
    ? `<span class="badge ${{lic.is_trial ? 'trial' : 'active'}}">${{lic.is_trial ? '⏱ TRIAL' : '✓ ACTIVE'}}</span>`
    : `<span class="badge expired">✗ EXPIRED</span>`;

  const mt5Items = (lic.mt5_accounts || []).map(acc => `
    <div class="mt5-item">
      <div>
        <div class="mt5-id">#${{acc.account_id}}</div>
        <div class="mt5-meta">Last seen: ${{formatDate(acc.last_seen)}}</div>
      </div>
      <button class="rm-btn" onclick="removeMT5('${{lic.license_key}}','${{acc.account_id}}')">✕ XÓA</button>
    </div>`).join('');

  const canAdd = (lic.mt5_accounts || []).length < lic.max_machines;

  return `
  <div class="lic-card" id="card-${{lic.license_key.replace(/[^a-zA-Z0-9]/g,'-')}}">
    <div class="lic-header">
      <div>
        <div style="font-size:11px;letter-spacing:2px;color:var(--muted);margin-bottom:6px">LICENSE KEY</div>
        <div class="lic-key">${{lic.license_key}}</div>
      </div>
      ${{statusBadge}}
    </div>
    <div class="lic-meta">
      <div class="meta-item">
        <div class="label">Gói</div>
        <div class="val">${{lic.tier}}</div>
      </div>
      <div class="meta-item">
        <div class="label">Còn lại</div>
        <div class="val">${{daysLabel(lic.days_left)}}</div>
      </div>
      <div class="meta-item">
        <div class="label">Hết hạn</div>
        <div class="val" style="font-size:13px">${{formatDate(lic.expires_at)}}</div>
      </div>
      <div class="meta-item">
        <div class="label">MT5 Accounts</div>
        <div class="val">${{(lic.mt5_accounts||[]).length}} / ${{lic.max_machines}}</div>
      </div>
    </div>

    <div style="font-size:11px;letter-spacing:2px;color:var(--muted);margin-bottom:10px">TÀI KHOẢN MT5</div>
    <div class="mt5-list">
      ${{mt5Items || '<div style="color:var(--muted);font-size:13px;padding:8px 0">Chưa có tài khoản MT5 nào.</div>'}}
    </div>

    ${{canAdd && lic.status === 'ACTIVE' ? `
    <div class="add-form">
      <input class="add-input" id="mt5-input-${{lic.license_key}}"
        placeholder="MT5 Account ID (vd: 413408816)" type="text" maxlength="20">
      <button class="add-btn" onclick="addMT5('${{lic.license_key}}')">+ THÊM</button>
    </div>` : (lic.status === 'ACTIVE' ? `<div style="font-size:12px;color:var(--muted);margin-top:12px">Đã đạt giới hạn ${{lic.max_machines}} tài khoản. Nâng cấp gói để thêm.</div>` : '')}}
  </div>`;
}}

function renderDashboard(data) {{
  document.getElementById('user-email').textContent = data.email;

  if (data.licenses.length === 0) {{
    document.getElementById('main').innerHTML = `
    <div class="section-title">Tổng quan</div>
    <div class="empty">
      <div class="empty-icon">🛡</div>
      <p>Bạn chưa có license nào. Kích hoạt Trial miễn phí 7 ngày ngay!</p>
    </div>
    <div class="cta-box" style="margin-top:16px">
      <h3>🚀 Bắt đầu miễn phí</h3>
      <p>Trial 7 ngày đầy đủ tính năng — không cần thẻ tín dụng</p>
      <button class="cta-btn" onclick="activateTrial()">KÍCH HOẠT TRIAL NGAY</button>
    </div>`;
    return;
  }}

  const active = data.licenses.filter(l => l.status === 'ACTIVE');
  const expired = data.licenses.filter(l => l.status !== 'ACTIVE');

  let html = `<div class="section-title">License đang hoạt động (${{active.length}})</div>`;
  if (active.length === 0) html += `<div style="color:var(--muted);font-size:14px;margin-bottom:16px">Không có license active.</div>`;
  active.forEach(l => html += renderLicenseCard(l));

  if (expired.length > 0) {{
    html += `<div class="section-title" style="margin-top:32px">Đã hết hạn (${{expired.length}})</div>`;
    expired.forEach(l => html += renderLicenseCard(l));
  }}

  // CTA renew nếu sắp hết
  const soonExp = active.filter(l => l.days_left !== null && l.days_left <= 7);
  if (soonExp.length > 0) {{
    html += `<div class="cta-box" style="margin-top:24px">
      <h3>⚠ Sắp hết hạn</h3>
      <p>${{soonExp.length}} license sẽ hết hạn trong 7 ngày. Liên hệ admin để gia hạn.</p>
    </div>`;
  }}

  document.getElementById('main').innerHTML = html;
}}

// ── Actions ───────────────────────────────────────────────────────────────────
async function addMT5(licKey) {{
  const input = document.getElementById('mt5-input-' + licKey);
  const accountId = input?.value?.trim();
  if (!accountId) {{ toast('Nhập MT5 Account ID.', 'err'); return; }}
  if (!/^\\d{{5,}}$/.test(accountId)) {{ toast('Account ID phải là số (5+ chữ số).', 'err'); return; }}

  try {{
    const r = await fetch(API + '/portal/mt5/add', {{
      method:'POST', headers:authHeaders(),
      body: JSON.stringify({{account_id: accountId}})
    }});
    const d = await r.json();
    if (r.ok) {{ toast('✅ ' + d.message); loadDashboard(); }}
    else {{ toast('❌ ' + (d.detail || 'Lỗi'), 'err'); }}
  }} catch(e) {{ toast('❌ Lỗi kết nối.', 'err'); }}
}}

async function removeMT5(licKey, accountId) {{
  if (!confirm(`Xóa MT5 Account #${{accountId}} khỏi license?`)) return;
  try {{
    const r = await fetch(API + '/portal/mt5/remove', {{
      method:'POST', headers:authHeaders(),
      body: JSON.stringify({{license_key: licKey, account_id: accountId}})
    }});
    const d = await r.json();
    if (r.ok) {{ toast('✅ Đã xóa account #' + accountId); loadDashboard(); }}
    else {{ toast('❌ ' + (d.detail || 'Lỗi'), 'err'); }}
  }} catch(e) {{ toast('❌ Lỗi kết nối.', 'err'); }}
}}

async function activateTrial() {{
  try {{
    const r = await fetch(API + '/portal/checkout', {{
      method:'POST', headers:authHeaders(),
      body: JSON.stringify({{tier:'TRIAL_FREE', method:'TRIAL_FREE'}})
    }});
    const d = await r.json();
    if (r.ok) {{
      toast('🎉 Trial đã kích hoạt! Kiểm tra email.');
      loadDashboard();
    }} else {{
      toast('❌ ' + (d.detail || 'Lỗi'), 'err');
    }}
  }} catch(e) {{ toast('❌ Lỗi kết nối.', 'err'); }}
}}

// ── Load ──────────────────────────────────────────────────────────────────────
async function loadDashboard() {{
  if (!getToken()) {{
    window.location.href = '/portal/login';
    return;
  }}
  try {{
    const r = await fetch(API + '/portal/me', {{headers: authHeaders()}});
    if (r.status === 401) {{
      window.location.href = '/portal/login';
      return;
    }}
    const data = await r.json();
    renderDashboard(data);
  }} catch(e) {{
    document.getElementById('main').innerHTML =
      '<div style="color:var(--red);text-align:center;padding:48px">Không tải được dữ liệu. Thử refresh trang.</div>';
  }}
}}

loadDashboard();
</script>
</body>
</html>"""
