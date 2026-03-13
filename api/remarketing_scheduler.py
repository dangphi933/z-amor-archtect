"""
remarketing_scheduler.py — Sprint 5
Chạy mỗi 6h, tự động gửi email remarketing theo 6 triggers:
1. Trial sắp hết hạn D-3
2. License sắp hết hạn D-7, D-1
3. License đã hết hạn D+1, D+7, D+14
4. User inactive 14 ngày
"""
import os, asyncio
from datetime import datetime, timezone, timedelta
from database import SessionLocal

TRIGGERS = [
    ("TRIAL_EXPIRY_D3",  "trial_expiry",  -3,  True,  "⏰ Trial hết hạn trong 3 ngày"),
    ("LIC_EXPIRY_D7",    "lic_expiry",    -7,  False, "🔔 License hết hạn trong 7 ngày"),
    ("LIC_EXPIRY_D1",    "lic_expiry",    -1,  False, "‼️ License hết hạn NGÀY MAI"),
    ("LIC_EXPIRED_D1",   "lic_expired",   1,   False, "License đã hết hạn"),
    ("LIC_EXPIRED_D7",   "lic_expired",   7,   False, "Win-back: 7 ngày chưa renew"),
    ("LIC_EXPIRED_D14",  "lic_expired",   14,  False, "Win-back cuối: 14 ngày"),
]

TEMPLATES = {
    "trial_expiry": {
        "subject": "⏰ Trial Z-ARMOR hết hạn trong {days} ngày",
        "body": "Chào {name},\n\nTrial của bạn hết hạn vào {expires}.\n\nNâng cấp lên ARMOR để tiếp tục sử dụng:\n{upgrade_url}\n\nZ-ARMOR Team"
    },
    "lic_expiry": {
        "subject": "🔔 License Z-ARMOR sắp hết hạn",
        "body": "Chào {name},\n\nLicense {tier} hết hạn vào {expires}.\n\nGia hạn ngay để không bị gián đoạn:\n{renew_url}\n\nZ-ARMOR Team"
    },
    "lic_expired": {
        "subject": "Z-ARMOR: License đã hết hạn — Kích hoạt lại",
        "body": "Chào {name},\n\nLicense {tier} đã hết hạn {days} ngày trước.\n\nKích hoạt lại ngay:\n{renew_url}\n\nZ-ARMOR Team"
    },
}


async def run_remarketing():
    """Entry point — gọi từ scheduler mỗi 6h."""
    from sqlalchemy import text
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    sent = 0
    try:
        for trigger_id, template_key, day_offset, is_trial, label in TRIGGERS:
            target_date = (now + timedelta(days=day_offset)).date()
            rows = db.execute(text("""
                SELECT buyer_email, buyer_name, tier, expires_at, license_key
                FROM license_keys
                WHERE is_trial = :trial
                  AND status IN ('ACTIVE','TRIAL')
                  AND DATE(expires_at) = :target
                  AND buyer_email IS NOT NULL
            """),{"trial":is_trial,"target":target_date}).fetchall()

            for email, name, tier, expires_at, lkey in rows:
                # Check if already sent today to avoid dup
                already = db.execute(text("""
                    SELECT 1 FROM audit_logs
                    WHERE email=:e AND action=:action AND DATE(created_at)=:today
                """),{"e":email,"action":trigger_id,"today":now.date()}).fetchone()
                if already: continue

                base_url = os.getenv("NEW_BACKEND_URL","http://47.129.1.31:8000")
                tmpl = TEMPLATES[template_key]
                subject = tmpl["subject"].format(days=abs(day_offset), tier=tier)
                body = tmpl["body"].format(
                    name=name or "Trader",
                    days=abs(day_offset),
                    tier=tier,
                    expires=expires_at.strftime("%d/%m/%Y") if expires_at else "N/A",
                    upgrade_url=f"{base_url}/sale",
                    renew_url=f"{base_url}/sale",
                )
                _send_remarketing_email(email, subject, body)
                db.execute(text("""
                    INSERT INTO audit_logs (account_id,action,severity,message,email)
                    VALUES ('system',:action,'INFO',:msg,:email)
                """),{"action":trigger_id,"msg":f"Remarketing: {label}","email":email})
                sent += 1

        db.commit()
        print(f"[REMARKETING] Sent {sent} emails", flush=True)
    except Exception as e:
        db.rollback()
        print(f"[REMARKETING] Error: {e}", flush=True)
    finally:
        db.close()


def _send_remarketing_email(to_email, subject, body):
    import smtplib
    from email.mime.text import MIMEText
    smtp_email = os.getenv("SMTP_EMAIL","")
    smtp_pass  = os.getenv("SMTP_PASSWORD","")
    if not smtp_email: return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"]    = smtp_email
        msg["To"]      = to_email
        s = smtplib.SMTP("smtp.gmail.com", 587)
        s.starttls(); s.login(smtp_email, smtp_pass)
        s.sendmail(smtp_email, to_email, msg.as_string()); s.quit()
    except Exception as e:
        print(f"[REMARKETING] Email fail {to_email}: {e}", flush=True)


async def start_remarketing_scheduler():
    """Background loop chạy mỗi 6h."""
    while True:
        try:
            await run_remarketing()
        except Exception as e:
            print(f"[REMARKETING] Scheduler error: {e}", flush=True)
        await asyncio.sleep(6 * 3600)
