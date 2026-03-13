"""
API SCHEMAS - FIXED VERSION
============================
Fix: Thêm field 'method' vào CheckoutPayload

HƯỚNG DẪN:
Thay thế file api/schemas.py bằng file này
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any


# ══════════════════════════════════════════════════════════
# CHECKOUT PAYLOAD (FIXED - Đã thêm field 'method')
# ══════════════════════════════════════════════════════════
class CheckoutPayload(BaseModel):
    """
    Payload cho endpoint /api/checkout
    
    Fields:
    - buyer_name: Tên người mua
    - buyer_email: Email người mua (để gửi license key)
    - tier: Gói dịch vụ (STARTER_TRIAL, PRO, ENTERPRISE...)
    - amount: Số tiền thanh toán
    - method: Phương thức thanh toán (TRIAL_FREE, STRIPE, PAYPAL, BANK_TRANSFER...)
    """
    buyer_name: str
    buyer_email: str
    tier: Optional[str] = "STARTER"
    amount: Optional[float] = 0.0
    method: Optional[str] = "MANUAL"  # ← FIX: Thêm field này


# ══════════════════════════════════════════════════════════
# BIND LICENSE PAYLOAD
# ══════════════════════════════════════════════════════════
class BindLicensePayload(BaseModel):
    """Payload để bind license key với MT5 account"""
    license: str
    mt5_id: str


# ══════════════════════════════════════════════════════════
# LARK WEBHOOK PAYLOAD
# ══════════════════════════════════════════════════════════
class LarkWebhookPayload(BaseModel):
    """
    Payload từ Lark webhook khi có thay đổi trong Lark Base
    """
    timestamp: str
    token: str
    type: str
    event: Optional[Dict[str, Any]] = None


# ══════════════════════════════════════════════════════════
# Z-ARMOR RESPONSE
# ══════════════════════════════════════════════════════════
class ZArmorResponse(BaseModel):
    """
    Response chuẩn từ Z-Armor API
    """
    valid: bool
    lock: bool = False
    emergency: bool = False
    status: Optional[str] = None
    expires_at: Optional[str] = None
    reason: Optional[str] = "OK"
    message: Optional[str] = None


# ══════════════════════════════════════════════════════════
# TRADE LOG PAYLOAD
# ══════════════════════════════════════════════════════════
class TradeLogPayload(BaseModel):
    """Payload để log trade từ EA"""
    account_id: str
    magic: str
    symbol: str
    direction: str  # BUY hoặc SELL
    entry_price: float
    lot_size: float
    timestamp: Optional[str] = None


# ══════════════════════════════════════════════════════════
# SESSION CLOSE PAYLOAD
# ══════════════════════════════════════════════════════════
class SessionClosePayload(BaseModel):
    """Payload để đóng trading session"""
    account_id: str
    magic: str
    session_id: str
    close_price: float
    profit: float
    timestamp: Optional[str] = None


# ══════════════════════════════════════════════════════════
# CONFIG UPDATE PAYLOAD
# ══════════════════════════════════════════════════════════
class ConfigUpdatePayload(BaseModel):
    """Payload để update cấu hình trading unit từ dashboard"""
    account_id: str
    magic: str
    config: Dict[str, Any]


# ══════════════════════════════════════════════════════════
# TELEGRAM MESSAGE PAYLOAD
# ══════════════════════════════════════════════════════════
class TelegramMessagePayload(BaseModel):
    """Payload để gửi message tới Telegram"""
    message: str
    silent: Optional[bool] = False


# ══════════════════════════════════════════════════════════
# AI ANALYSIS REQUEST
# ══════════════════════════════════════════════════════════
class AIAnalysisRequest(BaseModel):
    """Payload để request AI analysis"""
    account_id: str
    symbol: str
    timeframe: Optional[str] = "H1"
    data_points: Optional[int] = 100


# ══════════════════════════════════════════════════════════
# ADMIN CREATE LICENSE
# ══════════════════════════════════════════════════════════
class AdminCreateLicensePayload(BaseModel):
    """Payload để admin tạo license key mới"""
    owner_name: Optional[str] = ""
    owner_email: Optional[str] = ""
    plan: Optional[str] = "standard"
    max_machines: Optional[int] = 1
    expires_at: Optional[str] = None
    note: Optional[str] = ""


# ══════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════
__all__ = [
    "CheckoutPayload",
    "BindLicensePayload", 
    "LarkWebhookPayload",
    "ZArmorResponse",
    "TradeLogPayload",
    "SessionClosePayload",
    "ConfigUpdatePayload",
    "TelegramMessagePayload",
    "AIAnalysisRequest",
    "AdminCreateLicensePayload",
]
