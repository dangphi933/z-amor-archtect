"""
app/routers/auth_router.py
============================
HTTP endpoints /auth/* — extract từ api/auth_router.py monolith.
"""

from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from ..services.auth_service import (
    send_magic_otp, verify_magic_otp,
    create_access_token, create_refresh_token,
    store_session, revoke_session, rotate_refresh_token,
    get_or_create_user, get_user_by_license,
    _get_account_ids_for_email, is_jti_revoked,
    COOKIE_SECURE,
)
from shared.libs.security.jwt_utils import require_jwt, optional_jwt

router = APIRouter(tags=["auth"])


# ── Request Models ────────────────────────────────────────────────

class MagicRequestReq(BaseModel):
    email: str

class MagicVerifyReq(BaseModel):
    email: str
    otp: str

class LoginLicenseReq(BaseModel):
    license_key: str

class RefreshReq(BaseModel):
    refresh_token: str


# ══════════════════════════════════════════════════════════════════
# POST /auth/magic-request
# ══════════════════════════════════════════════════════════════════

@router.post("/magic-request")
async def auth_magic_request(req: MagicRequestReq, request: Request):
    """Email → OTP 6 số. Rate limit: 3 req / 15 phút / email."""
    email = req.email.strip().lower()
    if not email or "@" not in email or len(email) > 200:
        raise HTTPException(400, "Email không hợp lệ")

    ip = request.client.host if request.client else "unknown"
    result = await send_magic_otp(email, ip)

    if result == "RATE_LIMITED":
        raise HTTPException(429, "Quá nhiều yêu cầu. Vui lòng chờ 15 phút.")
    if result == "SEND_FAILED":
        raise HTTPException(500, "Không thể gửi email. Thử lại sau.")

    get_or_create_user(email)  # Auto-create nếu chưa có
    return {"status": "sent", "message": f"Mã xác nhận đã gửi đến {email}.", "expires_in": 900}


# ══════════════════════════════════════════════════════════════════
# POST /auth/magic-verify
# ══════════════════════════════════════════════════════════════════

@router.post("/magic-verify")
async def auth_magic_verify(req: MagicVerifyReq, request: Request, response: Response):
    """Email + OTP → JWT access token + refresh token."""
    email = req.email.strip().lower()
    result = verify_magic_otp(email, req.otp)

    if result == "INVALID":
        raise HTTPException(400, "Mã xác nhận không đúng.")
    if result == "EXPIRED":
        raise HTTPException(400, "Mã xác nhận đã hết hạn. Vui lòng yêu cầu mã mới.")
    if result == "MAX_ATTEMPTS":
        raise HTTPException(429, "Quá nhiều lần thử sai. Yêu cầu mã mới.")

    account_ids = _get_account_ids_for_email(email)
    access_token = create_access_token(email, account_ids)
    refresh_token, refresh_jti = create_refresh_token(email)

    ip = request.client.host if request.client else ""
    store_session(email, refresh_jti, ip)

    # HttpOnly cookie (F-01)
    _set_auth_cookies(response, access_token, refresh_token)

    return {
        "status":        "ok",
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "email":         email,
        "account_ids":   account_ids,
    }


# ══════════════════════════════════════════════════════════════════
# POST /auth/login  (license_key backward-compat)
# ══════════════════════════════════════════════════════════════════

@router.post("/login")
async def auth_login_license(req: LoginLicenseReq, request: Request, response: Response):
    """License key → JWT. Backward-compatible với monolith."""
    user = get_user_by_license(req.license_key)
    if not user:
        raise HTTPException(401, "License key không hợp lệ hoặc chưa kích hoạt.")

    email = user["email"]
    if not email:
        raise HTTPException(401, "License chưa gán email. Dùng magic link.")

    account_ids = _get_account_ids_for_email(email)
    access_token = create_access_token(email, account_ids, extra={"license_key": req.license_key})
    refresh_token, refresh_jti = create_refresh_token(email)

    ip = request.client.host if request.client else ""
    store_session(email, refresh_jti, ip)
    _set_auth_cookies(response, access_token, refresh_token)

    return {
        "status":       "ok",
        "access_token": access_token,
        "email":        email,
        "tier":         user.get("tier"),
        "account_ids":  account_ids,
    }


# ══════════════════════════════════════════════════════════════════
# POST /auth/logout
# ══════════════════════════════════════════════════════════════════

@router.post("/logout")
async def auth_logout(response: Response, payload: dict = require_jwt):
    jti = payload.get("jti")
    if jti:
        revoke_session(jti)
    _clear_auth_cookies(response)
    return {"status": "ok", "message": "Đã đăng xuất."}


# ══════════════════════════════════════════════════════════════════
# GET /auth/me
# ══════════════════════════════════════════════════════════════════

@router.get("/me")
async def auth_me(payload: dict = require_jwt):
    return {
        "email":       payload.get("sub"),
        "account_ids": payload.get("account_ids", []),
        "exp":         payload.get("exp"),
    }


# ══════════════════════════════════════════════════════════════════
# POST /auth/refresh
# ══════════════════════════════════════════════════════════════════

@router.post("/refresh")
async def auth_refresh(req: RefreshReq, response: Response):
    try:
        tokens = rotate_refresh_token(req.refresh_token)
    except ValueError as e:
        raise HTTPException(401, str(e))
    _set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return {"status": "ok", **tokens}


# ── Cookie helpers ────────────────────────────────────────────────

def _set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    response.set_cookie(
        "access_token", access_token,
        httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=86400,
    )
    response.set_cookie(
        "refresh_token", refresh_token,
        httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=86400 * 30,
    )


def _clear_auth_cookies(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
