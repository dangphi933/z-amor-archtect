"""
lark_service.py — Push đơn hàng lên Lark Base
Dùng đúng tên fields theo bảng thực tế đã tạo
"""

import os
import logging
import httpx
from datetime import datetime

logger = logging.getLogger("zarmor.lark")

def _cfg():
    return {
        "app_id":     os.environ.get("LARK_APP_ID",       "cli_a92af9524c789e1a"),
        "app_secret": os.environ.get("LARK_APP_SECRET",   ""),
        "app_token":  os.environ.get("LARK_BASE_APP_TOKEN",
                      os.environ.get("LARK_BASE_TOKEN",   "O52xbKlUwapuKFsV0JbjAbzBpSh")),
        "table_id":   os.environ.get("LARK_ORDERS_TABLE_ID",
                      os.environ.get("LARK_TABLE_ID",     "tbl4QZsvepLv8jnT")),
    }


async def _get_tenant_token() -> str:
    cfg = _cfg()
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json={
            "app_id":     cfg["app_id"],
            "app_secret": cfg["app_secret"],
        })
    data  = resp.json()
    token = data.get("tenant_access_token", "")
    if not token:
        logger.error(f"Lark token error: {data}")
    return token


async def push_order_to_lark(
    buyer_name:  str,
    buyer_email: str,
    tier:        str,
    amount:      float,
    method:      str,
    key:         str,
    key_id:      int,
    status:      str,
) -> str | None:
    """
    Ghi record vào Lark Base.
    Trả về record_id nếu thành công, None nếu lỗi.
    """
    cfg   = _cfg()
    token = await _get_tenant_token()
    if not token:
        raise ValueError("Không lấy được Lark tenant token")

    url     = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── Fields mapping — khớp tên cột TIẾNG VIỆT thực tế trong Lark Base ──
    fields = {
        "Tên khách hàng": buyer_name,
        "Email":          buyer_email,
        "Gói":            tier,
        "Số tiền (USD)":  float(amount),
        "Trạng thái":     status,
        "License Key":    key,
        "Phương thức":    method,
        "Key ID":         key_id,
        "Thời gian đặt":  int(datetime.now().timestamp() * 1000),
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=headers, json={"fields": fields})

    data = resp.json()
    logger.debug(f"Lark response: {data}")

    if resp.status_code == 200 and data.get("code") == 0:
        record_id = data["data"]["record"]["record_id"]
        logger.info(f"✅ Lark record created: {record_id}")
        return record_id
    else:
        # Log chi tiết để debug field name mismatch
        err_msg = data.get("msg", "") or str(data)
        logger.error(f"❌ Lark push failed [{resp.status_code}]: {err_msg}")
        logger.error(f"   Fields sent: {list(fields.keys())}")
        raise ValueError(f"Lark error {resp.status_code}: {err_msg}")


async def update_order_status_in_lark(
    record_id: str,
    status:    str,
    activated_at: datetime = None,
) -> bool:
    cfg   = _cfg()
    token = await _get_tenant_token()
    if not token:
        return False

    url     = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records/{record_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    fields = {"Trạng thái": status}
    if activated_at:
        fields["Thời gian kích hoạt"] = int(activated_at.timestamp() * 1000)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(url, headers=headers, json={"fields": fields})

    ok = resp.status_code == 200 and resp.json().get("code") == 0
    if not ok:
        logger.error(f"Lark update failed: {resp.text[:200]}")
    return ok