"""
api/radar_identity_router.py — Sprint 4
Radar Integration với Identity:
- Scan quota enforcement (Redis counter)
- user_id attribution vào radar_scans
- Alert subscriptions có user context
- Referral tracking
"""
import os, uuid, hashlib
from datetime import datetime, date, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from auth_service import require_auth, optional_auth
from database import SessionLocal

router = APIRouter(tags=["radar-identity"])

QUOTA_MAP = {"TRIAL":50,"ARMOR":500,"ARSENAL":2000,"FLEET":999999}


def _ensure_radar_identity_tables():
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # Thêm user_id vào radar_scans nếu chưa có
        db.execute(text("""
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='radar_scans' AND column_name='user_id'
              ) THEN
                ALTER TABLE radar_scans ADD COLUMN user_id VARCHAR(100);
                CREATE INDEX idx_radar_scans_user ON radar_scans(user_id);
              END IF;
            END $$;
        """))
        # alert_subscriptions
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS alert_subscriptions (
                user_id   VARCHAR(100) NOT NULL,
                asset     VARCHAR(50)  NOT NULL,
                timeframe VARCHAR(20)  NOT NULL,
                threshold FLOAT        DEFAULT 70,
                channel   VARCHAR(20)  DEFAULT 'telegram',
                active    BOOLEAN      DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, asset, timeframe)
            )"""))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_alert_sub_asset ON alert_subscriptions(asset,timeframe,active)"))
        # referral_events
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS referral_events (
                id               VARCHAR(36) PRIMARY KEY,
                ref_code         VARCHAR(20) NOT NULL,
                referrer_user_id VARCHAR(100),
                asset            VARCHAR(50),
                ip               VARCHAR(50),
                converted        BOOLEAN DEFAULT FALSE,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            )"""))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_ref_events_code ON referral_events(ref_code)"))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[RADAR-IDENTITY] Table init warning: {e}", flush=True)
    finally:
        db.close()


# ── Quota check (Redis nếu có, fallback DB count) ──────────────────
def check_and_increment_quota(user_id: str, tier: str) -> bool:
    """True = còn quota, False = đã hết."""
    limit = QUOTA_MAP.get(tier, 20)
    today = date.today().isoformat()
    # Try Redis first
    try:
        import redis as _redis
        r = _redis.from_url(os.getenv("REDIS_URL","redis://127.0.0.1:6379/0"))
        key = f"user_quota:{user_id}:{today}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, 86400)
        return count <= limit
    except Exception:
        pass
    # Fallback: DB count
    from sqlalchemy import text
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT COUNT(*) FROM radar_scans
            WHERE user_id=:uid AND DATE(created_at)=:today
        """),{"uid":user_id,"today":today}).fetchone()
        return (row[0] if row else 0) < limit
    except Exception:
        return True
    finally:
        db.close()


# ── Alert dedup (Redis TTL 5 min) ──────────────────────────────────
def is_alert_recently_sent(user_id: str, asset: str, tf: str) -> bool:
    try:
        import redis as _redis
        r = _redis.from_url(os.getenv("REDIS_URL","redis://127.0.0.1:6379/0"))
        key = f"alert_sent:{user_id}:{asset}:{tf}"
        return r.exists(key) > 0
    except Exception:
        return False

def mark_alert_sent(user_id: str, asset: str, tf: str):
    try:
        import redis as _redis
        r = _redis.from_url(os.getenv("REDIS_URL","redis://127.0.0.1:6379/0"))
        r.setex(f"alert_sent:{user_id}:{asset}:{tf}", 300, "1")
    except Exception:
        pass


# ── Endpoints ──────────────────────────────────────────────────────

class AlertSubReq(BaseModel):
    asset:     str
    timeframe: str
    threshold: float = 70.0
    channel:   str   = "telegram"

@router.post("/alerts/subscribe")
async def subscribe_alert(req: AlertSubReq, ctx: dict = Depends(require_auth)):
    from sqlalchemy import text
    user_id = ctx.get("sub")
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO alert_subscriptions (user_id,asset,timeframe,threshold,channel)
            VALUES (:uid,:asset,:tf,:thr,:ch)
            ON CONFLICT (user_id,asset,timeframe) DO UPDATE
            SET threshold=:thr, channel=:ch, active=TRUE
        """),{"uid":user_id,"asset":req.asset.lower(),"tf":req.timeframe.upper(),
              "thr":req.threshold,"ch":req.channel})
        db.commit()
        return {"success":True,"message":f"Alert đăng ký: {req.asset.upper()} {req.timeframe} threshold={req.threshold}"}
    finally:
        db.close()

@router.delete("/alerts/{asset}/{timeframe}")
async def unsubscribe_alert(asset: str, timeframe: str, ctx: dict = Depends(require_auth)):
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE alert_subscriptions SET active=FALSE
            WHERE user_id=:uid AND asset=:a AND timeframe=:tf
        """),{"uid":ctx.get("sub"),"a":asset.lower(),"tf":timeframe.upper()})
        db.commit()
        return {"success":True}
    finally:
        db.close()

@router.get("/alerts")
async def list_alerts(ctx: dict = Depends(require_auth)):
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT asset,timeframe,threshold,channel,active,created_at
            FROM alert_subscriptions WHERE user_id=:uid ORDER BY created_at DESC
        """),{"uid":ctx.get("sub")}).fetchall()
        return {"alerts":[{"asset":r[0],"timeframe":r[1],"threshold":r[2],
                           "channel":r[3],"active":r[4]} for r in rows]}
    finally:
        db.close()

@router.get("/quota")
async def get_quota(ctx: dict = Depends(require_auth)):
    """Quota usage hôm nay."""
    from sqlalchemy import text
    user_id = ctx.get("sub")
    tier    = ctx.get("tier","TRIAL")
    today   = date.today().isoformat()
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT COUNT(*) FROM radar_scans WHERE user_id=:uid AND DATE(created_at)=:today
        """),{"uid":user_id,"today":today}).fetchone()
        used = row[0] if row else 0
        limit = QUOTA_MAP.get(tier, 20)
        return {"used":used,"limit":limit,"remaining":max(0,limit-used),"tier":tier}
    finally:
        db.close()


# ── Internal helpers dùng bởi radar scan endpoint ──────────────────

def attribute_scan(scan_id: str, user_id: str):
    """Gán user_id vào radar_scan row (gọi sau khi scan xong)."""
    if not user_id or not scan_id:
        return
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("UPDATE radar_scans SET user_id=:uid WHERE scan_id=:sid"),
                   {"uid":user_id,"sid":scan_id})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def check_and_push_alerts(asset: str, timeframe: str, score: float):
    """Check alert_subscriptions và push notification async."""
    from sqlalchemy import text
    db = SessionLocal()
    try:
        subs = db.execute(text("""
            SELECT user_id,channel,threshold FROM alert_subscriptions
            WHERE asset=:a AND timeframe=:tf AND active=TRUE AND threshold<=:score
        """),{"a":asset.lower(),"tf":timeframe.upper(),"score":score}).fetchall()
    except Exception:
        subs = []
    finally:
        db.close()

    for sub in subs:
        uid, channel, threshold = sub
        if is_alert_recently_sent(uid, asset, timeframe):
            continue
        mark_alert_sent(uid, asset, timeframe)
        # Get user email for email alerts
        if channel in ("email","both"):
            _send_alert_email_async(uid, asset, timeframe, score)
        if channel in ("telegram","both"):
            _send_alert_telegram_async(uid, asset, timeframe, score)


def _send_alert_telegram_async(user_id, asset, tf, score):
    try:
        import asyncio, httpx
        from sqlalchemy import text
        db = SessionLocal()
        try:
            # Get telegram chat_id from user's license
            row = db.execute(text("""
                SELECT tc.chat_id FROM telegram_configs tc
                JOIN license_activations la ON tc.account_id=la.account_id
                JOIN license_keys lk ON la.license_key=lk.license_key
                WHERE lk.buyer_email=(SELECT email FROM za_users WHERE id=:uid LIMIT 1)
                LIMIT 1
            """),{"uid":user_id}).fetchone()
        except Exception:
            row = None
        finally:
            db.close()
        if not row:
            return
        bot = os.getenv("TELEGRAM_BOT_TOKEN","")
        if not bot: return
        msg = f"🎯 Z-ARMOR RADAR ALERT\n{asset.upper()} {tf}\nScore: {score:.0f}/100\nThreshold vượt {score:.0f} ≥ trigger"
        asyncio.create_task(httpx.AsyncClient().post(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            json={"chat_id":row[0],"text":msg}
        ))
    except Exception:
        pass


def _send_alert_email_async(user_id, asset, tf, score):
    try:
        import asyncio
        from sqlalchemy import text
        db = SessionLocal()
        try:
            row = db.execute(text("SELECT email FROM za_users WHERE id=:uid"),{"uid":user_id}).fetchone()
        except Exception:
            row = None
        finally:
            db.close()
        if not row or not row[0]:
            return
        email = row[0]
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _do_send_alert_email, email, asset, tf, score)
    except Exception:
        pass


def _do_send_alert_email(email, asset, tf, score):
    try:
        import smtplib
        from email.mime.text import MIMEText
        smtp_email = os.getenv("SMTP_EMAIL","")
        smtp_pass  = os.getenv("SMTP_PASSWORD","")
        if not smtp_email: return
        msg = MIMEText(f"Z-ARMOR Radar Alert\n\n{asset.upper()} {tf} Score: {score:.0f}/100\n\nXem chi tiết: http://47.129.1.31:8000/scan?asset={asset}&tf={tf}")
        msg["Subject"] = f"[Z-ARMOR] Radar Alert: {asset.upper()} {tf} — Score {score:.0f}"
        msg["From"]    = smtp_email
        msg["To"]      = email
        s = smtplib.SMTP("smtp.gmail.com", 587)
        s.starttls(); s.login(smtp_email, smtp_pass)
        s.sendmail(smtp_email, email, msg.as_string()); s.quit()
    except Exception:
        pass


def track_referral(ref_code: str, asset: str, ip: str):
    """Track referral event — dedup theo IP+ref_code trong 24h."""
    if not ref_code: return
    try:
        import redis as _redis
        r = _redis.from_url(os.getenv("REDIS_URL","redis://127.0.0.1:6379/0"))
        dedup_key = f"ref_track:{ip}:{ref_code}"
        if r.exists(dedup_key): return
        r.setex(dedup_key, 86400, "1")
    except Exception:
        pass
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # Get referrer user_id
        row = db.execute(text("SELECT id FROM za_users WHERE ref_code=:rc"),{"rc":ref_code}).fetchone()
        referrer_id = row[0] if row else None
        db.execute(text("""
            INSERT INTO referral_events (id,ref_code,referrer_user_id,asset,ip)
            VALUES (:id,:rc,:rid,:asset,:ip)
        """),{"id":str(uuid.uuid4()),"rc":ref_code,"rid":referrer_id,"asset":asset,"ip":ip})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def init_radar_identity():
    try:
        _ensure_radar_identity_tables()
        print("[RADAR-IDENTITY] Tables ready", flush=True)
    except Exception as e:
        print(f"[RADAR-IDENTITY] Warning: {e}", flush=True)
