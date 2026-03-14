"""
app/jobs/remarketing.py
=========================
Job: Remarketing emails — mỗi 24 giờ.
Extract từ remarketing_scheduler.py monolith.

Targets:
  1. Trial users sắp hết hạn (< 3 ngày còn lại)
  2. Trial users đã hết hạn trong 7 ngày
  3. Paid users sắp hết hạn (< 7 ngày còn lại)
"""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from shared.libs.database.models import SessionLocal, License
from shared.libs.messaging.redis_streams import publish_notification

logger = logging.getLogger("zarmor.scheduler.remarketing")


def run_remarketing():
    db = SessionLocal()
    sent = 0
    try:
        now = datetime.now(timezone.utc)

        # Target 1: Trial expiring soon (≤3 days)
        trial_expiring = db.query(License).filter(
            License.status == "ACTIVE",
            License.is_trial == True,
            License.expires_at >= now,
            License.expires_at <= now + timedelta(days=3),
            License.buyer_email.isnot(None),
        ).all()

        for lic in trial_expiring:
            days_left = int((lic.expires_at - now).total_seconds() / 86400)
            _send_remarketing_email(
                email=lic.buyer_email,
                subject=f"[Z-ARMOR] Trial của bạn hết hạn sau {days_left} ngày",
                body=f"""
                <p>Gói Trial của bạn sẽ hết hạn vào <b>{lic.expires_at.strftime('%d/%m/%Y')}</b>.</p>
                <p>Nâng cấp lên <b>ARMOR</b> hoặc <b>ARSENAL</b> để tiếp tục bảo vệ tài khoản:</p>
                <ul>
                  <li>ARMOR — $29/tháng — 3 accounts</li>
                  <li>ARSENAL — $79/tháng — 10 accounts</li>
                </ul>
                <p><a href="https://zarmor.cloud/billing">Nâng cấp ngay →</a></p>
                """,
            )
            sent += 1

        # Target 2: Trial expired (0-7 days ago)
        trial_expired = db.query(License).filter(
            License.status == "EXPIRED",
            License.is_trial == True,
            License.expires_at >= now - timedelta(days=7),
            License.expires_at < now,
            License.buyer_email.isnot(None),
        ).all()

        for lic in trial_expired:
            days_ago = int((now - lic.expires_at).total_seconds() / 86400)
            _send_remarketing_email(
                email=lic.buyer_email,
                subject=f"[Z-ARMOR] Trial của bạn đã hết hạn {days_ago} ngày",
                body=f"""
                <p>Gói Trial đã hết hạn. Tài khoản của bạn hiện <b>không được bảo vệ</b>.</p>
                <p><a href="https://zarmor.cloud/billing">Kích hoạt lại ngay →</a></p>
                """,
            )
            sent += 1

        # Target 3: Paid expiring soon (≤7 days)
        paid_expiring = db.query(License).filter(
            License.status == "ACTIVE",
            License.is_trial == False,
            License.expires_at >= now,
            License.expires_at <= now + timedelta(days=7),
            License.buyer_email.isnot(None),
        ).all()

        for lic in paid_expiring:
            days_left = int((lic.expires_at - now).total_seconds() / 86400)
            _send_remarketing_email(
                email=lic.buyer_email,
                subject=f"[Z-ARMOR] Gia hạn {lic.tier} — còn {days_left} ngày",
                body=f"""
                <p>License <b>{lic.tier}</b> của bạn sẽ hết hạn vào
                   <b>{lic.expires_at.strftime('%d/%m/%Y')}</b>.</p>
                <p>Gia hạn để tránh gián đoạn bảo vệ tài khoản.</p>
                <p><a href="https://zarmor.cloud/billing">Gia hạn ngay →</a></p>
                """,
            )
            sent += 1

        logger.info(f"[REMARKETING] Done: {sent} emails queued")
    finally:
        db.close()


def _send_remarketing_email(email: str, subject: str, body: str):
    header = """
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
      <div style="background:#1B3A5C;padding:20px;text-align:center;">
        <h2 style="color:#fff;margin:0;">⚔️ Z-ARMOR CLOUD</h2>
      </div>
      <div style="padding:30px;background:#f9f9f9;">
    """
    footer = """
      </div>
      <div style="background:#e5e5e5;padding:12px;text-align:center;font-size:11px;color:#888;">
        Z-ARMOR CLOUD | Unsubscribe | Support: support@zarmor.cloud
      </div>
    </div>
    """
    publish_notification("EMAIL_NOTIFY", {
        "to_email":  email,
        "subject":   subject,
        "html_body": header + body + footer,
    }, source="scheduler-service")
