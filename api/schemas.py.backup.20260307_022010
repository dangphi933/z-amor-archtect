from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
import uuid

# ==========================================
# 1. TỪ ĐIỂN TRẠNG THÁI (STRICT ENUMS)
# ==========================================
class LicenseTier(str, Enum):
    TRIAL = "TRIAL"
    STANDARD = "STANDARD"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"

class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    PENDING = "PENDING"

# ==========================================
# 2. LÕI VẬT LÝ Z-ARMOR (CORE PHYSICS)
# Khớp 100% với output của dashboard_service.py
# ==========================================
class PhysicsData(BaseModel):
    # ── Core Z-Pressure ───────────────────────────────────────────────
    state: str
    z_pressure: float
    base_pressure: float
    trailing_pressure: float
    peak_equity: float
    budget_capacity: float
    damping_factor: float = 1.0
    entropy_tax_rate: float = 0.0
    dbu_pct: float = Field(default=0.0)
    rem_capacity: float
    fre_pct: float
    cbr_pct: float
    velocity: float = 0.0
    is_hibernating: bool = False

    # ── BUG D FIX: Dual-Layer DD fields (v8.0) — thiếu hoàn toàn trước đây ──
    # Tầng 1 — Account Hard Floor
    dd_type: str = "STATIC"
    max_dd_pct: float = 10.0
    initial_balance: float = 0.0
    account_peak: float = 0.0
    account_hard_floor: float = 0.0
    dist_to_account_floor: float = 0.0
    account_dd_pct: float = 0.0
    account_buffer_pct: float = 100.0
    account_proximity_pressure: float = 0.0
    # Tầng 2 — Daily Trailing
    daily_peak: float = 0.0
    daily_floor: float = 0.0
    daily_giveback_pct: float = 0.0

# ==========================================
# 3. QUẢN LÝ BẢN QUYỀN (LICENSE METADATA)
# ==========================================
class LicenseData(BaseModel):
    license_key: str = Field(default_factory=lambda: f"ZARMOR-{uuid.uuid4().hex[:8].upper()}")
    tier: LicenseTier = LicenseTier.STANDARD
    status: LicenseStatus = LicenseStatus.ACTIVE
    max_mt5_accounts: int = Field(default=1, ge=1)
    bound_mt5_ids: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None  # Fix: Optional, không bắt buộc khi khởi tạo

# ==========================================
# 4. PAYLOAD API: TƯƠNG TÁC GIAO DIỆN (UI REQUESTS)
# ==========================================
class BindLicensePayload(BaseModel):
    """Khuôn đúc khi khách hàng nhập Key vào Radar"""
    license_key: str
    account_id: str

class CheckoutPayload(BaseModel):
    buyer_name: str
    buyer_email: str
    tier: Optional[str] = "STARTER"
    amount: Optional[float] = 0.0
    method: Optional[str] = "MANUAL"  # ← THÊM DÒNG NÀY

# ==========================================
# 5. PAYLOAD API: LARK AUTOMATION WEBHOOK
# ==========================================
class LarkSalesOrder(BaseModel):
    order_id: str
    lark_user_id: str
    buyer_email: EmailStr
    buyer_name: str
    purchased_tier: LicenseTier
    payment_status: str
    amount_paid: float
    
class LarkWebhookPayload(BaseModel):
    """Khuôn đúc hứng Webhook bắn về từ hệ thống Lark Suite"""
    schema_version: str = "2.0"
    header: Dict[str, Any] = {}
    event: LarkSalesOrder

# ==========================================
# 6. TIÊU CHUẨN TRẢ VỀ CHUNG (API RESPONSE)
# ==========================================
class ZArmorResponse(BaseModel):
    status: str
    message: str
    data: Optional[Any] = None
    timestamp: datetime = Field(default_factory=datetime.now)