"""
shared/libs/security/jwt_utils.py
===================================
JWT helpers dùng chung across tất cả services.
Extract từ Z-ARMOR-CLOUD/auth.py — đây là READ-ONLY side:
  - verify_token()     — validate JWT, trả dict payload
  - require_jwt()      — FastAPI Depends
  - optional_jwt()     — FastAPI Depends (không raise nếu no token)
  - decode_jwt_unsafe()— decode không verify (dùng cho revoke check)

QUAN TRỌNG:
  - Chỉ auth-service mới ISSUE token (create_access_token, create_refresh_token)
  - Các service khác chỉ VERIFY token qua shared library này
  - JWT_SECRET_KEY phải giống nhau trên tất cả services (từ Secrets Manager)
"""

import os
import logging
from typing import Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger("zarmor.security")

JWT_ALGORITHM = "HS256"

_security = HTTPBearer(auto_error=False)


def _get_jwt_secret() -> str:
    s = os.getenv("JWT_SECRET_KEY", "")
    if s:
        return s
    # Dev mode fallback
    debug = os.getenv("DEBUG", "false").lower() == "true"
    if debug:
        logger.warning("[JWT] JWT_SECRET_KEY not set — using dev fallback. DO NOT USE IN PROD.")
        return "dev-insecure-secret-change-me"
    raise RuntimeError("JWT_SECRET_KEY not set in environment. Refusing to start.")


def verify_token(token: str) -> dict:
    """
    Verify JWT signature + expiry.
    Returns decoded payload dict.
    Raises HTTPException 401 on any failure.
    """
    try:
        payload = pyjwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token đã hết hạn. Vui lòng đăng nhập lại.")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Token không hợp lệ: {e}")


def decode_jwt_unsafe(token: str) -> Optional[dict]:
    """
    Decode JWT mà không verify signature — dùng để đọc jti cho revoke check.
    Không dùng để authorize requests.
    """
    try:
        return pyjwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None


def _extract_token(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    """
    Thứ tự ưu tiên:
    1. Authorization: Bearer <token>
    2. Cookie: access_token
    3. Header: X-License-Key (backward-compat)
    """
    if credentials and credentials.credentials:
        return credentials.credentials
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token
    header_key = request.headers.get("X-License-Key")
    if header_key:
        return header_key
    return None


async def require_jwt(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """
    FastAPI Depends — bắt buộc có JWT hợp lệ.
    Trả về payload dict với: sub (email), account_ids, jti, ...
    """
    token = _extract_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa xác thực. Vui lòng đăng nhập.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_token(token)


async def optional_jwt(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> Optional[dict]:
    """
    FastAPI Depends — JWT optional, trả None nếu không có/invalid.
    Dùng cho endpoints public nhưng có thêm context nếu logged in.
    """
    token = _extract_token(request, credentials)
    if not token:
        return None
    try:
        return verify_token(token)
    except HTTPException:
        return None


def get_account_id_from_payload(payload: dict) -> Optional[str]:
    """Extract primary account_id từ JWT payload."""
    account_ids = payload.get("account_ids", [])
    if account_ids:
        return str(account_ids[0])
    return payload.get("sub")
