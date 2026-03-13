"""
email_service.py — Z-ARMOR CLOUD Email Service
================================================
Tập trung tất cả email functions:
  - send_license_email_to_customer()   ← license delivery
  - send_radar_report_email()          ← radar scan report
  - _get_smtp_config()                 ← shared SMTP config helper
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("zarmor.email")


# ── SMTP Config ────────────────────────────────────────────────────────────────

def _get_smtp_config():
    """Returns (smtp_user, smtp_pass, from_name) from environment."""
    smtp_user = os.environ.get("SMTP_EMAIL", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    from_name = "Z-Armor Cloud"
    return smtp_user, smtp_pass, from_name


def _smtp_send(smtp_user: str, smtp_pass: str, to_email: str, msg) -> bool:
    """Shared SMTP send helper — blocking (run in executor for async callers)."""
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, to_email, msg.as_string())
        return True
    except Exception as e:
        logger.error(f"[EMAIL] SMTP send failed to {to_email}: {e}")
        return False


# ── License Email ──────────────────────────────────────────────────────────────

def send_license_email_to_customer(receiver_email: str, buyer_name: str,
                                    tier: str, license_key: str) -> bool:
    """
    Gửi email license key cho customer sau khi checkout.
    Blocking — wrap bằng asyncio.run_in_executor() khi gọi từ async handler.
    """
    smtp_user, smtp_pass, from_name = _get_smtp_config()
    if not smtp_user or "email_cua_sep" in smtp_user:
        logger.warning("[EMAIL] SMTP not configured, skipping license email")
        return False

    dashboard_url  = os.environ.get("NEW_BACKEND_URL", "http://47.129.243.206:8000")
    dashboard_link = f"{dashboard_url}/web/"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Z-ARMOR CLOUD] Xác nhận Đơn hàng & Cấp phát License Key ({tier})"
    msg["From"]    = f"{from_name} <{smtp_user}>"
    msg["To"]      = receiver_email

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#05070a;font-family:'Courier New',monospace;">
<div style="max-width:600px;margin:32px auto;background:#0a0f1a;border:2px solid #00ff9d;border-radius:8px;padding:30px;">
  <h1 style="color:#00ff9d;text-transform:uppercase;letter-spacing:2px;margin-bottom:20px;">
    ⚡ Z-ARMOR CLOUD
  </h1>
  <p style="color:#aaa;font-size:13px;">Xin chào <strong style="color:#fff;">{buyer_name}</strong>,</p>
  <p style="color:#aaa;font-size:13px;">Cảm ơn bạn đã đăng ký Z-Armor Cloud <strong style="color:#00ff9d;">{tier}</strong>.</p>

  <div style="background:#141922;border:1px solid #00e5ff;border-radius:4px;padding:20px;margin:20px 0;text-align:center;">
    <div style="font-size:11px;color:#445;letter-spacing:3px;margin-bottom:8px;">LICENSE KEY</div>
    <div style="color:#00e5ff;font-size:22px;font-weight:bold;letter-spacing:2px;word-break:break-all;">
      {license_key}
    </div>
  </div>

  <div style="margin:20px 0;">
    <a href="{dashboard_link}"
       style="display:inline-block;background:#00ff9d;color:#000;font-weight:900;
              font-size:13px;padding:14px 28px;border-radius:4px;text-decoration:none;letter-spacing:1px;">
      🚀 MỞ DASHBOARD →
    </a>
  </div>

  <p style="color:#445;font-size:11px;">
    Nếu cần hỗ trợ, vui lòng reply email này.<br>
    — Z-Armor Cloud Team
  </p>
</div>
</body></html>"""

    msg.attach(MIMEText(html, "html", "utf-8"))
    result = _smtp_send(smtp_user, smtp_pass, receiver_email, msg)
    if result:
        logger.info(f"[EMAIL] License email sent → {receiver_email} ({tier})")
    return result


# ── Radar Report Email ─────────────────────────────────────────────────────────

async def send_radar_report_email(
    to_email: str,
    scan_result: dict,
    share_url: str,
) -> bool:
    """
    Gửi Radar Scan report qua email (async — gọi trực tiếp từ async handler).
    scan_result: dict từ RadarResult.__dict__ hoặc DB row.
    """
    import asyncio
    smtp_user, smtp_pass, from_name = _get_smtp_config()
    if not smtp_user or not smtp_pass:
        return False

    asset    = scan_result.get("asset", "GOLD")
    tf       = scan_result.get("timeframe", "H1")
    score    = scan_result.get("score", 0)
    regime   = scan_result.get("regime", "NEUTRAL")
    label    = scan_result.get("label", "NEUTRAL")
    session  = scan_result.get("session", "")
    strategy = scan_result.get("strategy_hint", "")
    risk_lvl = scan_result.get("risk_level", "MEDIUM")
    conf     = scan_result.get("confidence", "MEDIUM")

    color_map = {
        "STRONG": "#00ff9d", "GOOD": "#00e5ff",
        "CAUTION": "#ffaa00", "RISKY": "#ff7700", "AVOID": "#ff4444",
    }
    color = color_map.get(label, "#00e5ff")

    notes_raw = scan_result.get("risk_notes", [])
    if isinstance(notes_raw, str):
        import json
        try:
            notes_raw = json.loads(notes_raw)
        except Exception:
            notes_raw = []
    notes_html = "".join(
        f"<li style='color:#889;font-size:12px;padding:5px 0;"
        f"border-bottom:1px solid #0d0f14;line-height:1.5;'>{n}</li>"
        for n in (notes_raw or [])
    )

    breakdown = scan_result.get("breakdown", {})
    if isinstance(breakdown, str):
        import json
        try:
            breakdown = json.loads(breakdown)
        except Exception:
            breakdown = {}
    bd_rows = "".join(
        f"<tr><td style='color:#556;font-size:11px;padding:6px 0;"
        f"border-bottom:1px solid #0d0f14;'>{k.replace('_',' ').title()}</td>"
        f"<td style='text-align:right;color:{color};font-weight:900;font-size:12px;"
        f"border-bottom:1px solid #0d0f14;'>{int(v) if isinstance(v,(int,float)) else v}</td></tr>"
        for k, v in breakdown.items()
        if isinstance(v, (int, float)) and k not in ("adx_live","rsi_live","atr_pct_live")
    )

    subject = f"[Z-ARMOR] ⚡ Radar: {asset} {tf} — {regime.replace('_',' ')} {score}/100"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#05070a;font-family:'Courier New',monospace;">
<div style="max-width:500px;margin:32px auto;background:#080a0f;border:1px solid {color}33;border-radius:8px;overflow:hidden;">
  <div style="background:linear-gradient(135deg,#020305,#0a0c10);padding:22px 28px;border-bottom:2px solid {color}44;">
    <div style="font-size:11px;color:{color};letter-spacing:3px;font-weight:900;">⚡ Z-ARMOR RADAR SCAN</div>
    <div style="font-size:20px;color:#fff;font-weight:900;margin-top:4px;">{asset} / {tf}</div>
    <div style="font-size:11px;color:#445;margin-top:2px;">{session}</div>
  </div>
  <div style="padding:24px 28px;">
    <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
      <tr>
        <td style="color:{color};font-size:16px;font-weight:900;letter-spacing:1px;">{regime.replace("_"," ")}</td>
        <td style="text-align:right;color:{color};font-size:40px;font-weight:900;line-height:1;">
          {score}<span style="font-size:16px;color:#445;">/100</span>
        </td>
      </tr>
    </table>
    <div style="background:#0a0c12;border-radius:3px;height:6px;margin-bottom:8px;">
      <div style="background:{color};width:{score}%;height:6px;border-radius:3px;"></div>
    </div>
    <div style="font-size:11px;color:#445;margin-bottom:20px;">{label} &nbsp;•&nbsp; {conf} CONFIDENCE &nbsp;•&nbsp; Risk: {risk_lvl}</div>
    <div style="font-size:10px;color:{color}88;letter-spacing:2px;margin-bottom:10px;">SCORE BREAKDOWN</div>
    <div style="background:#020305;border:1px solid #ffffff0d;border-radius:4px;padding:8px 14px;margin-bottom:20px;">
      <table style="width:100%;border-collapse:collapse;">{bd_rows}</table>
    </div>
    <div style="font-size:10px;color:{color}88;letter-spacing:2px;margin-bottom:10px;">MARKET CONDITIONS</div>
    <ul style="background:#020305;border:1px solid #ffffff0d;border-radius:4px;padding:8px 14px 4px;list-style:none;margin:0 0 20px;">{notes_html}</ul>
    <div style="background:#020305;border-left:3px solid {color};padding:12px 16px;border-radius:0 4px 4px 0;font-size:13px;color:#aaa;line-height:1.6;margin-bottom:24px;">{strategy}</div>
    <div style="text-align:center;margin-bottom:16px;">
      <a href="{share_url}" style="display:inline-block;background:{color};color:#000;font-weight:900;font-size:13px;padding:14px 32px;border-radius:4px;text-decoration:none;letter-spacing:1px;">
        ⚡ OPEN DEEP REGIME ANALYSIS →
      </a>
    </div>
    <div style="text-align:center;">
      <a href="{share_url}" style="font-size:11px;color:{color}88;text-decoration:none;">📋 Share Result: {share_url}</a>
    </div>
  </div>
  <div style="padding:14px 28px;background:#020305;border-top:1px solid #0d0f14;text-align:center;">
    <div style="font-size:10px;color:#334;">Z-ARMOR CLOUD © 2026 &nbsp;•&nbsp; flyhomecompany@gmail.com</div>
  </div>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{smtp_user}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _smtp_send, smtp_user, smtp_pass, to_email, msg)
        if result:
            logger.info(f"[EMAIL] Radar report → {to_email} ({asset}/{tf} {score})")
        return result
    except Exception as e:
        logger.error(f"[EMAIL] Radar report error: {e}")
        return False
