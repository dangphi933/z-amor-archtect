"""
keygen.py — Tạo License Key định dạng ZARMOR-XXXX-XXXX-XXXX-XXXX
"""

import uuid
import secrets
import string
from datetime import datetime, timedelta, timezone
from config import settings


def generate_license_key(tier: str) -> str:
    """
    Sinh key ngẫu nhiên dạng: ZARMOR-A1B2-C3D4-E5F6-G7H8
    Dùng secrets để đảm bảo cryptographically secure.
    """
    alphabet = string.ascii_uppercase + string.digits
    # Bỏ các ký tự dễ nhầm: 0, O, I, 1
    alphabet = alphabet.translate(str.maketrans('', '', '0O1I'))

    segments = []
    for _ in range(4):
        segment = ''.join(secrets.choice(alphabet) for _ in range(4))
        segments.append(segment)

    prefix = _tier_prefix(tier)
    return f"{prefix}-{'-'.join(segments)}"


def _tier_prefix(tier: str) -> str:
    """Map tier → prefix của key."""
    tier_upper = tier.upper()
    if "TRIAL" in tier_upper:
        return "ZARMOR-T"
    elif "ELITE" in tier_upper:
        return "ZARMOR-E"
    elif "PRO" in tier_upper:
        return "ZARMOR-P"
    else:
        return "ZARMOR-S"


def compute_expiry(tier: str, amount: float) -> datetime | None:
    """
    Tính ngày hết hạn dựa trên tier.
    - Trial: TRIAL_DURATION_DAYS ngày kể từ bây giờ
    - Paid: None (không hết hạn) hoặc custom logic
    """
    now = datetime.now(timezone.utc)

    if amount == 0 or "TRIAL" in tier.upper():
        return now + timedelta(days=settings.TRIAL_DURATION_DAYS)

    # Các gói trả phí — có thể mở rộng logic subscription ở đây
    # Hiện tại: không hết hạn (lifetime)
    return None
