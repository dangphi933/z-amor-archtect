"""
email_service.py — Gửi license key qua Gmail SMTP
Dùng biến môi trường: SMTP_USER, SMTP_APP_PASSWORD, SMTP_FROM_NAME
"""

import smtplib
import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logger = logging.getLogger("zarmor.email")

def _server_url():
    return os.environ.get("NEW_BACKEND_URL", "http://47.129.243.206:8000").rstrip("/")


def _get_smtp_config():
    user     = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_APP_PASSWORD", "")
    name     = os.environ.get("SMTP_FROM_NAME", "Z-ARMOR CLOUD")
    return user, password, name


async def send_license_email(
    to_email: str,
    buyer_name: str,
    tier: str,
    key: str,
    expires_at=None,
) -> bool:
    smtp_user, smtp_pass, from_name = _get_smtp_config()

    if not smtp_user or not smtp_pass:
        logger.error("❌ EMAIL SKIP: SMTP_USER hoặc SMTP_APP_PASSWORD chưa cấu hình trong .env")
        return False

    try:
        # Format hạn sử dụng
        if expires_at:
            if hasattr(expires_at, "strftime"):
                exp_str = expires_at.strftime("%d/%m/%Y")
            else:
                exp_str = str(expires_at)[:10]
        else:
            exp_str = "Lifetime"

        is_trial = "TRIAL" in tier.upper()
        tier_display = tier.replace("_TRIAL", " (Trial)").replace("_", " ")

        subject = f"[Z-ARMOR CLOUD] {'🎁 Key Dùng Thử' if is_trial else '✅ Xác Nhận License'} — {tier_display}"

        html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#05070a;font-family:monospace;">
  <div style="max-width:560px;margin:40px auto;background:#080a0f;border:1px solid #00e5ff33;border-radius:6px;overflow:hidden;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#020305,#0a0c10);padding:28px 32px;border-bottom:2px solid #00e5ff44;">
      <div style="font-size:22px;font-weight:900;color:#00e5ff;letter-spacing:3px;">⚡ Z-ARMOR CLOUD</div>
      <div style="font-size:11px;color:#334;margin-top:4px;letter-spacing:1px;">RISK INTELLIGENCE PLATFORM</div>
    </div>

    <!-- Body -->
    <div style="padding:28px 32px;">
      <p style="color:#aaa;font-size:14px;margin:0 0 16px;">Xin chào <strong style="color:#00e5ff;">{buyer_name}</strong>,</p>

      <p style="color:#888;font-size:13px;line-height:1.7;margin:0 0 24px;">
        {'Cảm ơn bạn đã đăng ký dùng thử Z-ARMOR CLOUD. Key của bạn đã được kích hoạt tự động.' if is_trial else 'Thanh toán của bạn đã được xác nhận. License key dưới đây đã sẵn sàng.'}
      </p>

      <!-- Key Box -->
      <div style="background:#020305;border:1px solid #00ff9d55;border-left:3px solid #00ff9d;border-radius:4px;padding:20px 24px;margin:0 0 24px;text-align:center;">
        <div style="font-size:10px;color:#00ff9d88;letter-spacing:2px;margin-bottom:10px;">LICENSE KEY</div>
        <div style="font-size:18px;font-weight:900;color:#00ff9d;letter-spacing:2px;word-break:break-all;">{key}</div>
      </div>

      <!-- Info table -->
      <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
        <tr>
          <td style="padding:8px 0;border-bottom:1px solid #111;color:#555;font-size:12px;">Gói</td>
          <td style="padding:8px 0;border-bottom:1px solid #111;color:#00e5ff;font-size:12px;font-weight:bold;text-align:right;">{tier_display}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;border-bottom:1px solid #111;color:#555;font-size:12px;">Hạn sử dụng</td>
          <td style="padding:8px 0;border-bottom:1px solid #111;color:#{'ff9900' if is_trial else '00ff9d'};font-size:12px;font-weight:bold;text-align:right;">{exp_str}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#555;font-size:12px;">Trạng thái</td>
          <td style="padding:8px 0;color:#00ff9d;font-size:12px;font-weight:bold;text-align:right;">✅ ACTIVE</td>
        </tr>
      </table>

      <!-- Steps -->
      <div style="background:#020305;border:1px solid #ffffff11;border-radius:4px;padding:20px 24px;margin:0 0 24px;">
        <div style="font-size:10px;color:#00e5ff88;letter-spacing:2px;margin-bottom:14px;">HƯỚNG DẪN CÀI ĐẶT</div>

        <div style="margin-bottom:12px;display:flex;align-items:flex-start;">
          <span style="background:#00e5ff;color:#000;font-weight:900;font-size:10px;padding:2px 7px;border-radius:2px;margin-right:10px;flex-shrink:0;">B1</span>
          <span style="color:#aaa;font-size:12px;line-height:1.6;">Mở <strong style="color:#fff;">MT5</strong> → chọn EA <strong style="color:#fff;">ZArmorKernel</strong> → vào tab <strong style="color:#fff;">Inputs</strong></span>
        </div>
        <div style="margin-bottom:12px;display:flex;align-items:flex-start;">
          <span style="background:#00e5ff;color:#000;font-weight:900;font-size:10px;padding:2px 7px;border-radius:2px;margin-right:10px;flex-shrink:0;">B2</span>
          <span style="color:#aaa;font-size:12px;line-height:1.6;">Điền <strong style="color:#fff;">Cloud server URL</strong> = <code style="color:#00ff9d;background:#011;padding:1px 5px;border-radius:2px;">{_server_url()}</code></span>
        </div>
        <div style="margin-bottom:12px;display:flex;align-items:flex-start;">
          <span style="background:#00e5ff;color:#000;font-weight:900;font-size:10px;padding:2px 7px;border-radius:2px;margin-right:10px;flex-shrink:0;">B3</span>
          <span style="color:#aaa;font-size:12px;line-height:1.6;">Điền <strong style="color:#fff;">License Key</strong> = <code style="color:#00ff9d;background:#011;padding:1px 5px;border-radius:2px;">{key}</code></span>
        </div>
        <div style="display:flex;align-items:flex-start;">
          <span style="background:#00e5ff;color:#000;font-weight:900;font-size:10px;padding:2px 7px;border-radius:2px;margin-right:10px;flex-shrink:0;">B4</span>
          <span style="color:#aaa;font-size:12px;line-height:1.6;">Nhấn <strong style="color:#fff;">OK</strong> → vào dashboard để cấu hình thêm</span>
        </div>
      </div>

      <!-- CTA -->
      <div style="text-align:center;margin-bottom:24px;">
        <a href="{_server_url()}/web/?key={key}" style="display:inline-block;background:#00e5ff;color:#000;font-weight:900;font-size:13px;letter-spacing:1px;padding:14px 36px;border-radius:3px;text-decoration:none;">
          ⚡ MỞ DASHBOARD &amp; CÀI ĐẶT NGAY →
        </a>
      </div>

      <p style="color:#333;font-size:11px;line-height:1.6;margin:0;text-align:center;">
        Link dashboard tự động điền key cho bạn.<br>
        Hỗ trợ: Reply email này hoặc Telegram admin.
      </p>
    </div>

    <!-- Footer -->
    <div style="padding:16px 32px;background:#020305;border-top:1px solid #111;text-align:center;">
      <div style="font-size:10px;color:#222;letter-spacing:1px;">Z-ARMOR CLOUD © 2026 — flyhomecompany@gmail.com</div>
    </div>

  </div>
</body>
</html>
"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{from_name} <{smtp_user}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())

        logger.info(f"✅ EMAIL SENT → {to_email} | key={key[:16]}...")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ EMAIL AUTH FAIL: {e} | user={smtp_user}")
        logger.error("   → Kiểm tra App Password tại https://myaccount.google.com/apppasswords")
        return False
    except Exception as e:
        logger.error(f"❌ EMAIL ERROR → {to_email}: {e}")
        return False 
# Alias for backward compatibility 
def send_license_email_to_customer(receiver_email, buyer_name, tier, license_key): 
    import asyncio 
    return asyncio.run(send_license_email(receiver_email, buyer_name, tier, license_key)) 

"""
ADD THIS TO email_service.py  (append to end of file)
=====================================================
Radar Scan report email — dark terminal theme.
"""

async def send_radar_report_email(
    to_email: str,
    scan_result: dict,
    share_url: str,
) -> bool:
    """
    Gửi Radar Scan report qua email.
    scan_result: dict từ RadarResult.__dict__ hoặc DB row
    """
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
    bar   = score

    notes_raw = scan_result.get("risk_notes", [])
    if isinstance(notes_raw, str):
        import json as _j
        try:
            notes_list = _j.loads(notes_raw)
        except Exception:
            notes_list = []
    else:
        notes_list = notes_raw or []
    notes_html = "".join(
        f"<li style='color:#889;font-size:12px;padding:5px 0;"
        f"border-bottom:1px solid #0d0f14;line-height:1.5;'>{n}</li>"
        for n in notes_list
    )

    breakdown = scan_result.get("breakdown", {})
    if isinstance(breakdown, str):
        import json as _j
        try:
            breakdown = _j.loads(breakdown)
        except Exception:
            breakdown = {}
    # FIX: breakdown chứa cả numeric scores VÀ string metadata (data_source, source, cache...)
    _SKIP_KEYS = {"data_source", "source", "cache", "timestamp", "ttl", "error"}
    bd_rows = "".join(
        f"<tr><td style='color:#556;font-size:11px;padding:6px 0;"
        f"border-bottom:1px solid #0d0f14;'>{k.replace('_',' ').title()}</td>"
        f"<td style='text-align:right;color:{color};font-weight:900;font-size:12px;"
        f"border-bottom:1px solid #0d0f14;'>{int(float(v))}/100</td></tr>"
        for k, v in breakdown.items()
        if k not in _SKIP_KEYS
        and str(v).replace('.','',1).replace('-','',1).isdigit()
    )

    subject = f"[Z-ARMOR] ⚡ Radar: {asset} {tf} — {regime.replace('_',' ')} {score}/100"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#05070a;font-family:'Courier New',monospace;">
<div style="max-width:500px;margin:32px auto;background:#080a0f;
            border:1px solid {color}33;border-radius:8px;overflow:hidden;">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#020305,#0a0c10);
              padding:22px 28px;border-bottom:2px solid {color}44;">
    <div style="font-size:11px;color:{color};letter-spacing:3px;font-weight:900;">
      ⚡ Z-ARMOR RADAR SCAN
    </div>
    <div style="font-size:20px;color:#fff;font-weight:900;margin-top:4px;">
      {asset} / {tf}
    </div>
    <div style="font-size:11px;color:#445;margin-top:2px;">{session}</div>
  </div>

  <!-- Score -->
  <div style="padding:24px 28px;">
    <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
      <tr>
        <td style="color:{color};font-size:16px;font-weight:900;letter-spacing:1px;">
          {regime.replace("_"," ")}
        </td>
        <td style="text-align:right;color:{color};font-size:40px;
                   font-weight:900;line-height:1;">
          {score}<span style="font-size:16px;color:#445;">/100</span>
        </td>
      </tr>
    </table>

    <!-- Score bar -->
    <div style="background:#0a0c12;border-radius:3px;height:6px;margin-bottom:8px;">
      <div style="background:{color};width:{bar}%;height:6px;border-radius:3px;"></div>
    </div>
    <div style="font-size:11px;color:#445;margin-bottom:20px;">
      {label} &nbsp;•&nbsp; {conf} CONFIDENCE &nbsp;•&nbsp; Risk: {risk_lvl}
    </div>

    <!-- Breakdown -->
    <div style="font-size:10px;color:{color}88;letter-spacing:2px;margin-bottom:10px;">
      SCORE BREAKDOWN
    </div>
    <div style="background:#020305;border:1px solid #ffffff0d;
                border-radius:4px;padding:8px 14px;margin-bottom:20px;">
      <table style="width:100%;border-collapse:collapse;">
        {bd_rows}
      </table>
    </div>

    <!-- Notes -->
    <div style="font-size:10px;color:{color}88;letter-spacing:2px;margin-bottom:10px;">
      MARKET CONDITIONS
    </div>
    <ul style="background:#020305;border:1px solid #ffffff0d;
               border-radius:4px;padding:8px 14px 4px;list-style:none;
               margin:0 0 20px;">
      {notes_html}
    </ul>

    <!-- Strategy -->
    <div style="background:#020305;border-left:3px solid {color};
                padding:12px 16px;border-radius:0 4px 4px 0;
                font-size:13px;color:#aaa;line-height:1.6;margin-bottom:24px;">
      {strategy}
    </div>

    <!-- CTA -->
    <div style="text-align:center;margin-bottom:16px;">
      <a href="{share_url}"
         style="display:inline-block;background:{color};color:#000;
                font-weight:900;font-size:13px;padding:14px 32px;
                border-radius:4px;text-decoration:none;letter-spacing:1px;">
        ⚡ OPEN DEEP REGIME ANALYSIS →
      </a>
    </div>

    <!-- Share -->
    <div style="text-align:center;">
      <a href="{share_url}"
         style="font-size:11px;color:{color}88;text-decoration:none;">
        📋 Share Result: {share_url}
      </a>
    </div>
  </div>

  <!-- Footer -->
  <div style="padding:14px 28px;background:#020305;
              border-top:1px solid #0d0f14;text-align:center;">
    <div style="font-size:10px;color:#334;">
      Z-ARMOR CLOUD © 2026 &nbsp;•&nbsp; flyhomecompany@gmail.com
    </div>
  </div>
</div>
</body></html>"""

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{from_name} <{smtp_user}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, to_email, msg.as_string())
        import logging
        logging.getLogger("zarmor.email").info(f"✅ Radar report → {to_email}")
        return True
    except Exception as e:
        import logging
        logging.getLogger("zarmor.email").error(f"❌ Radar email error: {e}")
        return False
