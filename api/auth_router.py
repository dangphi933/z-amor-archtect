"""
api/auth_router.py — Z-ARMOR CLOUD
Sprint A: Email Magic Link Authentication

  POST /auth/magic-request   — email → gửi OTP 6 số, TTL 15 phút
  POST /auth/magic-verify    — email + OTP → JWT + refresh token
  POST /auth/login           — license_key → JWT (giữ backward-compat)
  POST /auth/logout          — revoke current session
  GET  /auth/me              — current user info
  POST /auth/refresh         — rotate refresh token
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
from auth_service import (
    create_access_token, create_refresh_token, store_session,
    revoke_session, rotate_refresh_token,
    get_user_by_license,
    get_or_create_user_by_email,
    send_magic_otp, verify_magic_otp,
    require_auth, optional_auth
)

router = APIRouter(tags=["auth"])

# ── Request models ──────────────────────────────────────────────────

class MagicRequestReq(BaseModel):
    email: str                        # không dùng EmailStr để tránh dep nặng

class MagicVerifyReq(BaseModel):
    email: str
    otp: str                          # 6 chữ số dạng string

class LoginLicenseReq(BaseModel):
    license_key: str

class RefreshReq(BaseModel):
    refresh_token: str


# ══════════════════════════════════════════════════════════════════════
# MAGIC LINK — Sprint A
# ══════════════════════════════════════════════════════════════════════

@router.post("/magic-request")
async def auth_magic_request(req: MagicRequestReq, request: Request):
    """
    Bước 1: User nhập email → backend tạo OTP 6 số, gửi qua SMTP.
    Rate limit: 3 request / 15 phút / email (Redis counter).
    Auto-create za_users nếu email chưa tồn tại (trial account).
    """
    email = req.email.strip().lower()
    if not email or "@" not in email or len(email) > 200:
        raise HTTPException(status_code=400, detail="Email không hợp lệ")

    client_ip = request.client.host if request.client else "unknown"

    result = await send_magic_otp(email, client_ip)

    if result == "RATE_LIMITED":
        raise HTTPException(
            status_code=429,
            detail="Quá nhiều yêu cầu. Vui lòng chờ 15 phút trước khi thử lại."
        )
    if result == "SEND_FAILED":
        raise HTTPException(
            status_code=500,
            detail="Không thể gửi email. Vui lòng thử lại sau hoặc liên hệ support."
        )

    return {
        "status": "sent",
        "message": f"Mã xác nhận đã gửi đến {email}. Kiểm tra hộp thư (và thư mục Spam).",
        "expires_in": 900,   # 15 phút
        "email": email
    }


@router.post("/magic-verify")
async def auth_magic_verify(req: MagicVerifyReq, request: Request):
    """
    Bước 2: User nhập OTP → verify → trả JWT + refresh token.
    Single-use OTP: sau khi verify thành công, OTP bị xoá khỏi Redis.
    Max 5 lần sai → lock email 30 phút.
    """
    email = req.email.strip().lower()
    otp   = req.otp.strip().replace(" ", "")

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email không hợp lệ")
    if not otp.isdigit() or len(otp) != 6:
        raise HTTPException(status_code=400, detail="OTP phải là 6 chữ số")

    client_ip = request.client.host if request.client else "unknown"

    verify_result = verify_magic_otp(email, otp, client_ip)

    if verify_result == "LOCKED":
        raise HTTPException(
            status_code=429,
            detail="Tài khoản bị khóa tạm thời do nhập sai quá nhiều lần. Thử lại sau 30 phút."
        )
    if verify_result == "EXPIRED":
        raise HTTPException(
            status_code=401,
            detail="Mã xác nhận đã hết hạn. Vui lòng yêu cầu mã mới."
        )
    if verify_result == "INVALID":
        raise HTTPException(
            status_code=401,
            detail="Mã xác nhận không đúng. Vui lòng kiểm tra lại."
        )

    # OTP hợp lệ — load hoặc tạo user
    user = get_or_create_user_by_email(email)
    if not user:
        raise HTTPException(status_code=500, detail="Lỗi tạo tài khoản. Vui lòng thử lại.")

    # Tạo JWT
    access_token, jti = create_access_token(
        user["user_id"], user["email"], user["tier"],
        user["account_ids"], user.get("ref_code", "")
    )
    refresh_token = create_refresh_token()
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")
    store_session(user["user_id"], jti, refresh_token, ip, ua)

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
        "expires_in":    86400,
        "user": {
            "email":       user["email"],
            "tier":        user["tier"],
            "account_ids": user["account_ids"],
            "licenses":    user.get("licenses", []),
            "ref_code":    user.get("ref_code", ""),
        }
    }


# ══════════════════════════════════════════════════════════════════════
# LICENSE LOGIN — backward-compat (giữ nguyên cho user cũ)
# ══════════════════════════════════════════════════════════════════════

@router.post("/login")
async def auth_login(req: LoginLicenseReq, request: Request):
    """Login bằng license key → JWT. Giữ cho user cũ chưa có email auth."""
    user = get_user_by_license(req.license_key.strip())
    if not user:
        raise HTTPException(status_code=401, detail="License key không hợp lệ hoặc đã hết hạn")

    access_token, jti = create_access_token(
        user["user_id"], user["email"], user["tier"],
        user["account_ids"], user.get("ref_code", "")
    )
    refresh_token = create_refresh_token()
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")
    store_session(user["user_id"], jti, refresh_token, ip, ua)

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
        "expires_in":    86400,
        "user": {
            "email":       user["email"],
            "tier":        user["tier"],
            "account_ids": user["account_ids"],
            "licenses":    user.get("licenses", []),
            "ref_code":    user.get("ref_code", ""),
        }
    }


@router.post("/logout")
async def auth_logout(ctx: dict = Depends(require_auth)):
    """Revoke current session."""
    revoke_session(ctx.get("jti", ""))
    return {"success": True, "message": "Logged out"}


@router.get("/me")
async def auth_me(ctx: dict = Depends(require_auth)):
    """Trả thông tin user hiện tại từ JWT payload."""
    return {
        "user_id":     ctx.get("sub"),
        "email":       ctx.get("email"),
        "tier":        ctx.get("tier"),
        "account_ids": ctx.get("account_ids", []),
        "licenses":    ctx.get("licenses", []),
        "ref_code":    ctx.get("ref_code", ""),
        "scope":       ctx.get("scope"),
    }


@router.post("/refresh")
async def auth_refresh(req: RefreshReq, request: Request):
    """Rotate refresh token → new access + refresh token."""
    result = rotate_refresh_token(req.refresh_token)
    if not result:
        raise HTTPException(status_code=401, detail="Refresh token không hợp lệ hoặc đã hết hạn")
    new_access, new_refresh, _ = result
    return {
        "access_token":  new_access,
        "refresh_token": new_refresh,
        "token_type":    "bearer",
        "expires_in":    86400,
    }