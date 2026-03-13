"""
radar/scheduler.py — Radar Scheduler (Refresh + Alert)
=======================================================
Hai background jobs chạy song song từ lifespan startup:

  1. RadarRefreshScheduler (30 phút)
     Auto-refresh radar cache cho tất cả asset/TF targets.
     EA poll heartbeat 30s → nhận radar_map từ cache mới nhất.

  2. AlertCheckScheduler (15 phút)  ← G-02 FIX
     Query radar_alert_subs, compute score hiện tại cho mỗi sub,
     gửi email khi score vượt ngưỡng hoặc sụt dưới ngưỡng.
     Implements Luồng C kiến trúc 3 miền.

Deploy: gọi start_radar_scheduler() + start_alert_scheduler()
        từ lifespan() trong main.py.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────

AUTO_REFRESH_TARGETS = [
    ("GOLD",   "H1"),
    ("EURUSD", "H1"),
    ("BTC",    "H1"),
    ("NASDAQ", "H1"),
    ("GOLD",   "M15"),
    ("EURUSD", "M15"),
    ("GOLD",   "M5"),
]

REFRESH_INTERVAL_SECONDS = 1800   # 30 phút
ALERT_CHECK_INTERVAL     = 900    # 15 phút
ALERT_RISE_THRESHOLD     = 70     # score vượt lên ≥ 70 → gửi alert "STRONG signal"
ALERT_DROP_THRESHOLD     = 40     # score sụt xuống < 40 → gửi alert "Regime changed"
ALERT_MIN_DELTA          = 10     # chênh lệch tối thiểu để trigger (tránh noise)
ALERT_COOLDOWN_HOURS     = 4      # không spam cùng asset trong 4 giờ

# ─── STATE ────────────────────────────────────────────────────────────────────

_radar_task:  Optional[asyncio.Task] = None
_alert_task:  Optional[asyncio.Task] = None
_is_running:  bool = False

# Cache last score per (email, asset, tf) để detect flip
# key: f"{email}:{asset}:{tf}" → {"score": int, "last_alert": datetime}
_alert_state: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# RADAR REFRESH SCHEDULER
# ══════════════════════════════════════════════════════════════════════════════

async def _refresh_loop():
    """Background loop: refresh radar cache mỗi 30 phút."""
    global _is_running

    logger.info("[RADAR SCHEDULER] Bắt đầu auto-refresh loop (interval=30m)")
    logger.info("[RADAR SCHEDULER] Chờ 90s trước warm-up đầu tiên (tránh rate limit khi restart)...")

    for _ in range(9):
        if not _is_running:
            return
        await asyncio.sleep(10)

    await _do_refresh_all()

    while _is_running:
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
        if not _is_running:
            break
        await _do_refresh_all()


async def _do_refresh_all():
    """Refresh toàn bộ targets — sequential để không overload TwelveData."""
    try:
        from radar.engine import compute
        refreshed = 0
        errors    = 0
        start_ts  = datetime.now(timezone.utc)

        for asset, tf in AUTO_REFRESH_TARGETS:
            try:
                result = compute(asset, tf)
                refreshed += 1
                # RadarResult is a Pydantic/dataclass object — use attribute access
                _score  = result.score  if hasattr(result, 'score')  else result.get('score', '?')
                _regime = result.regime if hasattr(result, 'regime') else result.get('regime', '?')
                logger.debug(
                    f"[RADAR SCHEDULER] Refreshed {asset}/{tf} "
                    f"score={_score} regime={_regime}"
                )
            except Exception as e:
                errors += 1
                logger.warning(f"[RADAR SCHEDULER] Error refreshing {asset}/{tf}: {e}")
            await asyncio.sleep(10)  # 10s giữa mỗi asset → 70s tổng

        elapsed = (datetime.now(timezone.utc) - start_ts).total_seconds()
        logger.info(
            f"[RADAR SCHEDULER] Refresh complete: "
            f"{refreshed} OK, {errors} errors, {elapsed:.1f}s"
        )
    except Exception as e:
        logger.error(f"[RADAR SCHEDULER] Refresh loop error: {e}")


def start_radar_scheduler():
    global _radar_task, _is_running
    if _radar_task and not _radar_task.done():
        logger.info("[RADAR SCHEDULER] Already running")
        return
    _is_running = True
    _radar_task = asyncio.create_task(_refresh_loop())
    logger.info("[RADAR SCHEDULER] Started ✓")


def stop_radar_scheduler():
    global _is_running, _radar_task
    _is_running = False
    if _radar_task and not _radar_task.done():
        _radar_task.cancel()
        logger.info("[RADAR SCHEDULER] Stopped ✓")


async def force_refresh_asset(asset: str, tf: str = "H1") -> dict:
    from radar.engine import compute
    return compute(asset, tf)


# ══════════════════════════════════════════════════════════════════════════════
# ALERT CHECK SCHEDULER  ← G-02 FIX: Luồng C
# ══════════════════════════════════════════════════════════════════════════════

async def _alert_loop():
    """
    Background loop: kiểm tra score flip mỗi 15 phút.
    Kiến trúc 3 miền — Luồng C:
      C1: query alert_subscribers + compute score
      C2: so sánh với last_score → trigger email nếu vượt/sụt ngưỡng
    """
    global _is_running

    logger.info("[ALERT SCHEDULER] Bắt đầu alert check loop (interval=15m)")

    # Chờ 3 phút sau startup trước khi check lần đầu
    # (để radar cache warm-up xong)
    await asyncio.sleep(180)

    while _is_running:
        try:
            await _check_all_alerts()
        except Exception as e:
            logger.error(f"[ALERT SCHEDULER] Loop error: {e}")

        await asyncio.sleep(ALERT_CHECK_INTERVAL)


async def _check_all_alerts():
    """
    C1: Query radar_alert_subs (active=TRUE).
    C2: Compute score hiện tại từ radar cache.
    C3: Trigger email nếu score vượt/sụt threshold.
    """
    try:
        from database import get_db_session
        from sqlalchemy import text
        db = next(get_db_session())
    except Exception as e:
        logger.warning(f"[ALERT SCHEDULER] DB connect failed: {e}")
        return

    triggered = 0
    checked   = 0

    try:
        rows = db.execute(text(
            "SELECT email, asset, timeframe, channel "
            "FROM radar_alert_subs WHERE active = TRUE"
        )).fetchall()
    except Exception as e:
        logger.warning(f"[ALERT SCHEDULER] Query alert_subs failed: {e}")
        db.close()
        return
    finally:
        pass  # db.close() ở cuối

    logger.info(f"[ALERT SCHEDULER] Checking {len(rows)} active subscribers...")

    for row in rows:
        email   = row[0]
        asset   = row[1]
        tf      = row[2] or "H1"
        channel = row[3] or "email"

        try:
            checked += 1
            score, regime, label = await _get_current_score(asset, tf)
            if score is None:
                continue

            state_key  = f"{email}:{asset}:{tf}"
            prev_state = _alert_state.get(state_key, {})
            prev_score = prev_state.get("score")
            last_alert = prev_state.get("last_alert")

            # Cập nhật last known score dù không trigger
            _alert_state[state_key] = {
                "score":      score,
                "last_alert": last_alert,
            }

            # Kiểm tra cooldown
            if last_alert:
                cooldown_end = last_alert + timedelta(hours=ALERT_COOLDOWN_HOURS)
                if datetime.now(timezone.utc) < cooldown_end:
                    continue

            # Tính delta
            delta = abs(score - prev_score) if prev_score is not None else 0

            # Điều kiện trigger:
            # 1. Score vừa vượt lên ≥ ALERT_RISE_THRESHOLD (từ dưới lên)
            rise_trigger = (
                score >= ALERT_RISE_THRESHOLD and
                (prev_score is None or prev_score < ALERT_RISE_THRESHOLD) and
                delta >= ALERT_MIN_DELTA
            )
            # 2. Score vừa sụt xuống < ALERT_DROP_THRESHOLD (từ trên xuống)
            drop_trigger = (
                score < ALERT_DROP_THRESHOLD and
                (prev_score is None or prev_score >= ALERT_DROP_THRESHOLD) and
                delta >= ALERT_MIN_DELTA
            )

            if rise_trigger or drop_trigger:
                alert_type = "STRONG_SIGNAL" if rise_trigger else "REGIME_CHANGED"
                sent = await _send_alert_email(
                    email=email, asset=asset, tf=tf,
                    score=score, regime=regime, label=label,
                    prev_score=prev_score, alert_type=alert_type,
                )
                if sent:
                    triggered += 1
                    _alert_state[state_key]["last_alert"] = datetime.now(timezone.utc)
                    logger.info(
                        f"[ALERT SCHEDULER] Sent {alert_type} → {email} | "
                        f"{asset}/{tf} score={score} (prev={prev_score})"
                    )

        except Exception as e:
            logger.warning(f"[ALERT SCHEDULER] Error checking {email}/{asset}/{tf}: {e}")

    db.close()
    logger.info(
        f"[ALERT SCHEDULER] Done: checked={checked} "
        f"triggered={triggered} subscribers={len(rows)}"
    )


async def _get_current_score(asset: str, tf: str):
    """
    Lấy score hiện tại từ radar cache (không gọi API mới).
    Returns: (score, regime, label) hoặc (None, None, None) nếu cache miss.
    """
    try:
        from radar.engine import compute
        result = compute(asset, tf)
        if result:
            # Handle both dict and RadarResult object
            if hasattr(result, 'score'):
                return result.score, getattr(result, 'regime', ''), getattr(result, 'label', '')
            elif isinstance(result, dict) and "score" in result:
                return result["score"], result.get("regime", ""), result.get("label", "")
        return None, None, None
    except Exception as e:
        logger.debug(f"[ALERT SCHEDULER] Score fetch failed {asset}/{tf}: {e}")
        return None, None, None


async def _send_alert_email(
    email: str, asset: str, tf: str,
    score: int, regime: str, label: str,
    prev_score, alert_type: str,
) -> bool:
    """
    Gửi alert email qua SMTP.
    Luồng C3: alert link dẫn về /scan?asset=GOLD&tf=H1 → user re-engage.
    """
    try:
        smtp_user = os.environ.get("SMTP_USER",         "")
        smtp_pass = os.environ.get("SMTP_APP_PASSWORD", "")
        from_name = os.environ.get("SMTP_FROM_NAME",    "Z-ARMOR CLOUD")
        base_url  = os.environ.get("NEW_BACKEND_URL",   "http://47.129.243.206:8000")

        if not smtp_user or not smtp_pass:
            logger.warning("[ALERT SCHEDULER] SMTP chưa cấu hình — skip email")
            return False

        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        # ── Build content ─────────────────────────────────────────────────────
        scan_link  = f"{base_url}/scan?asset={asset.lower()}&tf={tf}"
        regime_str = regime.replace("_", " ").title()
        delta_str  = (
            f"+{score - prev_score}" if prev_score and score > prev_score
            else f"{score - prev_score}" if prev_score
            else "new"
        )

        if alert_type == "STRONG_SIGNAL":
            subject   = f"[Z-ARMOR] ⚡ {asset} {tf} — {regime_str} {score}/100 — Strong Signal!"
            headline  = f"Strong Regime Detected on {asset}"
            subhead   = f"Score just crossed {ALERT_RISE_THRESHOLD} threshold"
            cta_text  = "View Full Analysis →"
            color_acc = "#00ff9d"
        else:
            subject   = f"[Z-ARMOR] ⚠️ {asset} {tf} — Regime Changed ({score}/100)"
            headline  = f"Regime Shift on {asset}"
            subhead   = f"Score dropped below {ALERT_DROP_THRESHOLD} — conditions changed"
            cta_text  = "Check Current Conditions →"
            color_acc = "#ffaa00"

        label_colors = {
            "STRONG": "#00ff9d", "GOOD": "#00e5ff",
            "CAUTION": "#ffaa00", "RISKY": "#ff7700", "AVOID": "#ff4444",
        }
        label_color = label_colors.get(label, "#aaa")

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0a0c10;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0c10;padding:32px 0;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#111318;border-radius:12px;overflow:hidden;border:1px solid #1a1f2e;">

  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#0a0c10 0%,#1a1f2e 100%);padding:28px 32px;border-bottom:1px solid #1a1f2e;">
    <p style="margin:0;font-size:11px;color:#556;letter-spacing:3px;text-transform:uppercase;">Z-ARMOR CLOUD · REGIME ALERT</p>
    <h1 style="margin:8px 0 0;font-size:22px;color:#e2e8f0;font-weight:700;">{headline}</h1>
    <p style="margin:6px 0 0;font-size:13px;color:#6b7a99;">{subhead}</p>
  </td></tr>

  <!-- Score Card -->
  <tr><td style="padding:24px 32px;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="background:#0d0f14;border-radius:8px;padding:16px 20px;border:1px solid #1a1f2e;" width="48%">
          <p style="margin:0;font-size:10px;color:#445;text-transform:uppercase;letter-spacing:2px;">Asset / TF</p>
          <p style="margin:6px 0 0;font-size:20px;color:#e2e8f0;font-weight:700;">{asset} <span style="color:#445;font-size:14px;">/ {tf}</span></p>
        </td>
        <td width="4%"></td>
        <td style="background:#0d0f14;border-radius:8px;padding:16px 20px;border:1px solid #1a1f2e;" width="48%">
          <p style="margin:0;font-size:10px;color:#445;text-transform:uppercase;letter-spacing:2px;">Score</p>
          <p style="margin:6px 0 0;font-size:20px;font-weight:700;color:{color_acc};">{score}<span style="color:#445;font-size:14px;">/100</span>
            <span style="font-size:12px;color:#556;margin-left:8px;">{delta_str}</span>
          </p>
        </td>
      </tr>
      <tr><td height="12" colspan="3"></td></tr>
      <tr>
        <td style="background:#0d0f14;border-radius:8px;padding:16px 20px;border:1px solid #1a1f2e;" width="48%">
          <p style="margin:0;font-size:10px;color:#445;text-transform:uppercase;letter-spacing:2px;">Regime</p>
          <p style="margin:6px 0 0;font-size:15px;color:#e2e8f0;font-weight:700;">{regime_str}</p>
        </td>
        <td width="4%"></td>
        <td style="background:#0d0f14;border-radius:8px;padding:16px 20px;border:1px solid #1a1f2e;" width="48%">
          <p style="margin:0;font-size:10px;color:#445;text-transform:uppercase;letter-spacing:2px;">Signal Label</p>
          <p style="margin:6px 0 0;font-size:15px;font-weight:700;color:{label_color};">{label}</p>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- CTA -->
  <tr><td style="padding:0 32px 32px;" align="center">
    <a href="{scan_link}" style="display:inline-block;background:{color_acc};color:#000;font-weight:700;font-size:14px;padding:14px 32px;border-radius:8px;text-decoration:none;letter-spacing:0.5px;">{cta_text}</a>
    <p style="margin:16px 0 0;font-size:11px;color:#334;">
      Unsubscribe: reply with subject "UNSUBSCRIBE {asset} {tf}"
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{from_name} <{smtp_user}>"
        msg["To"]      = email
        msg.attach(MIMEText(html, "html"))

        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        await loop.run_in_executor(None, _smtp_send, smtp_user, smtp_pass, email, msg)
        return True

    except Exception as e:
        logger.warning(f"[ALERT SCHEDULER] Email send failed → {email}: {e}")
        return False


def _smtp_send(user, password, to, msg):
    """Blocking SMTP call — run in executor để không block event loop."""
    import smtplib
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as s:
        s.login(user, password)
        s.sendmail(user, to, msg.as_string())


def start_alert_scheduler():
    """Khởi động alert scheduler — gọi từ lifespan startup."""
    global _alert_task, _is_running
    if _alert_task and not _alert_task.done():
        logger.info("[ALERT SCHEDULER] Already running")
        return
    _is_running = True
    _alert_task = asyncio.create_task(_alert_loop())
    logger.info("[ALERT SCHEDULER] Started ✓ (check every 15min, cooldown=4h)")


def stop_alert_scheduler():
    """Dừng alert scheduler — gọi từ lifespan shutdown."""
    global _is_running, _alert_task
    _is_running = False
    if _alert_task and not _alert_task.done():
        _alert_task.cancel()
        logger.info("[ALERT SCHEDULER] Stopped ✓")


# ─── STATUS ───────────────────────────────────────────────────────────────────

def get_scheduler_status() -> dict:
    """Trả về trạng thái cả 2 schedulers — cho /api/health endpoint."""
    return {
        "radar_scheduler": {
            "running":       _is_running and (_radar_task and not _radar_task.done()),
            "targets_count": len(AUTO_REFRESH_TARGETS),
            "interval_sec":  REFRESH_INTERVAL_SECONDS,
        },
        "alert_scheduler": {
            "running":           _is_running and (_alert_task and not _alert_task.done()),
            "interval_sec":      ALERT_CHECK_INTERVAL,
            "rise_threshold":    ALERT_RISE_THRESHOLD,
            "drop_threshold":    ALERT_DROP_THRESHOLD,
            "cooldown_hours":    ALERT_COOLDOWN_HOURS,
            "cached_states":     len(_alert_state),
        },
    }