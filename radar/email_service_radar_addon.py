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
    bd_rows = "".join(
        f"<tr><td style='color:#556;font-size:11px;padding:6px 0;"
        f"border-bottom:1px solid #0d0f14;'>{k.replace('_',' ').title()}</td>"
        f"<td style='text-align:right;color:{color};font-weight:900;font-size:12px;"
        f"border-bottom:1px solid #0d0f14;'>{int(v)}/100</td></tr>"
        for k, v in breakdown.items()
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
