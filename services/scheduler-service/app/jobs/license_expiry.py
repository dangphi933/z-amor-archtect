"""app/jobs/license_expiry.py — Check & notify license sắp hết hạn."""

import logging
from datetime import datetime, timezone, timedelta
from shared.libs.database.models import SessionLocal, License
from shared.libs.messaging.redis_streams import publish_notification

logger = logging.getLogger("zarmor.scheduler.license_expiry")


def run_license_expiry_check():
    db = SessionLocal()
    updated = 0
    try:
        now = datetime.now(timezone.utc)

        # Mark EXPIRED
        expired = db.query(License).filter(
            License.status == "ACTIVE",
            License.expires_at < now,
        ).all()

        for lic in expired:
            lic.status = "EXPIRED"
            updated += 1
            logger.info(f"[LICENSE_EXPIRY] Marking expired: {lic.license_key[:8]}*** {lic.tier}")
            if lic.buyer_email:
                publish_notification("EMAIL_NOTIFY", {
                    "to_email": lic.buyer_email,
                    "subject":  "[Z-ARMOR] License đã hết hạn",
                    "html_body": f"<p>License <b>{lic.tier}</b> ({lic.license_key[:8]}***) đã hết hạn. "
                                 f"<a href='https://zarmor.cloud/billing'>Gia hạn ngay →</a></p>",
                }, source="scheduler-service")

        # Notify admin
        if expired:
            publish_notification("DEFCON3_SILENT", {
                "account_id": "system",
                "message":    f"⏰ {len(expired)} license(s) expired và đã được cập nhật trạng thái.",
            }, source="scheduler-service")

        db.commit()
        logger.info(f"[LICENSE_EXPIRY] Done: {updated} licenses marked expired")
    except Exception as e:
        db.rollback()
        logger.error(f"[LICENSE_EXPIRY] Failed: {e}")
    finally:
        db.close()
