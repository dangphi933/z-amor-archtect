"""
app/senders/email_sender.py
=============================
Email sender — extract từ email_service.py monolith.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("zarmor.notification.email")

SMTP_EMAIL    = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_NAME     = os.getenv("SMTP_FROM_NAME", "Z-ARMOR CLOUD")
BACKEND_URL   = os.getenv("BACKEND_URL", "http://localhost:8003")


class EmailSender:
    def _is_configured(self) -> bool:
        if not SMTP_EMAIL or not SMTP_PASSWORD:
            logger.warning("[EMAIL] SMTP not configured")
            return False
        return True

    def send(self, to_email: str, subject: str, html_body: str) -> bool:
        if not self._is_configured() or not to_email:
            return True
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{FROM_NAME} <{SMTP_EMAIL}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        return self._smtp_send(to_email, msg)

    def send_license(self, to_email: str, buyer_name: str, tier: str, license_key: str) -> bool:
        """License delivery email — giữ nguyên format từ monolith."""
        if not self._is_configured() or not to_email:
            return True
        dashboard_link = f"{BACKEND_URL}/web/"
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
          <div style="background:#1B3A5C;padding:24px;text-align:center;">
            <h1 style="color:#fff;margin:0;">⚔️ Z-ARMOR CLOUD</h1>
            <p style="color:#aad4ff;margin:4px 0;">License Activated</p>
          </div>
          <div style="padding:32px;background:#f9f9f9;">
            <p>Chào <strong>{buyer_name or to_email}</strong>,</p>
            <p>License <strong>{tier}</strong> của bạn đã được kích hoạt thành công.</p>
            <div style="background:#fff;border:2px solid #2E75B6;border-radius:8px;padding:20px;
                        text-align:center;margin:20px 0;">
              <p style="margin:0;color:#888;font-size:13px;">LICENSE KEY</p>
              <p style="font-size:20px;font-weight:bold;letter-spacing:3px;color:#1B3A5C;margin:8px 0;">
                {license_key}
              </p>
            </div>
            <p>Truy cập dashboard tại: <a href="{dashboard_link}">{dashboard_link}</a></p>
            <p style="color:#888;font-size:12px;">Không chia sẻ license key. Mỗi key chỉ dùng cho 1 MT5 account.</p>
          </div>
        </div>
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Z-ARMOR] License {tier} đã kích hoạt — {license_key[:8]}***"
        msg["From"]    = f"{FROM_NAME} <{SMTP_EMAIL}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))
        return self._smtp_send(to_email, msg)

    def _smtp_send(self, to_email: str, msg) -> bool:
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
                s.ehlo(); s.starttls(); s.ehlo()
                s.login(SMTP_EMAIL, SMTP_PASSWORD)
                s.sendmail(SMTP_EMAIL, to_email, msg.as_string())
            logger.info(f"[EMAIL] Sent to {to_email}")
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("[EMAIL] SMTP auth failed — check credentials")
            return True  # Don't retry auth errors
        except Exception as e:
            logger.error(f"[EMAIL] Send failed to {to_email}: {e}")
            return False
