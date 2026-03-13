"""
radar/router.py
===============
FastAPI router for Radar Scan + RegimeFit Score endpoints.

Endpoints:
  POST /radar/scan           — Compute score, optionally send report
  GET  /radar/result/{id}    — Public shareable result page (HTML)
  GET  /radar/feed           — All 12 combinations current scores
  GET  /radar/history        — User scan history (by email)
  GET  /radar/assets         — Supported assets + session info
  GET  /radar/stats          — Admin stats (total scans, by asset)
"""

import uuid
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from database import get_db
from .engine  import compute, compute_all, ASSET_PROFILES, TF_MULT
from .schemas import RadarScanRequest, RadarScanResponse, BreakdownOut

logger = logging.getLogger("zarmor.radar")
router = APIRouter(tags=["Radar Scan"])

BASE_URL = os.environ.get("NEW_BACKEND_URL", "http://47.129.243.206:8000")


# ── POST /radar/scan ────────────────────────────────────────────────────────────
@router.post("/scan", response_model=RadarScanResponse)
async def radar_scan(req: RadarScanRequest, db: Session = Depends(get_db)):
    """
    Tính RegimeFit Lite score. Không cần auth, không cần license.
    Rate: 10 req/IP/hour (TODO: Redis rate limit Phase 2).
    """
    result = compute(req.asset.value, req.timeframe.value)

    scan_id = f"SCAN-{uuid.uuid4().hex[:8].upper()}"

    # Persist to DB
    try:
        db.execute("""
            INSERT INTO radar_scans
              (scan_id, asset, timeframe, email, session, utc_hour, utc_dow,
               score, regime, label, confidence, breakdown, risk_notes, strategy_hint)
            VALUES
              (:id, :asset, :tf, :email, :session, :hour, :dow,
               :score, :regime, :label, :conf, :bd::jsonb, :notes::jsonb, :hint)
        """, {
            "id":      scan_id,
            "asset":   result.asset,
            "tf":      result.timeframe,
            "email":   req.email,
            "session": result.session,
            "hour":    datetime.now(timezone.utc).hour,
            "dow":     datetime.now(timezone.utc).weekday(),
            "score":   result.score,
            "regime":  result.regime,
            "label":   result.label,
            "conf":    result.confidence,
            "bd":      json.dumps(result.breakdown),
            "notes":   json.dumps(result.risk_notes),
            "hint":    result.strategy_hint,
        })
        db.commit()
    except Exception as e:
        logger.warning(f"[RADAR] DB insert failed: {e}")
        db.rollback()

    # Queue email report
    report_queued = False
    if req.send_report and req.email:
        try:
            from email_service import send_radar_report_email
            share_url = f"{BASE_URL}/radar/result/{scan_id}"
            import asyncio
            asyncio.create_task(
                send_radar_report_email(req.email, result.__dict__, share_url)
            )
            report_queued = True
        except Exception as e:
            logger.warning(f"[RADAR] Email queue failed: {e}")

    cta_url   = f"{BASE_URL}/web/?scan={scan_id}&asset={result.asset}"
    share_url = f"{BASE_URL}/radar/result/{scan_id}"

    return RadarScanResponse(
        scan_id       = scan_id,
        asset         = result.asset,
        timeframe     = result.timeframe,
        score         = result.score,
        regime        = result.regime,
        label         = result.label,
        label_text    = result.label_text,
        color         = result.color,
        emoji         = result.emoji,
        gate          = result.gate,
        confidence    = result.confidence,
        breakdown     = BreakdownOut(**result.breakdown),
        risk_notes    = result.risk_notes,
        strategy_hint = result.strategy_hint,
        risk_level    = result.risk_level,
        session       = result.session,
        cta_url       = cta_url,
        share_url     = share_url,
        report_queued = report_queued,
        timestamp_utc = result.timestamp_utc,
        ttl_sec       = result.ttl_sec,
    )


# ── GET /radar/result/{scan_id} — Shareable HTML page ──────────────────────────
@router.get("/result/{scan_id}", response_class=HTMLResponse)
async def radar_result_page(scan_id: str, db: Session = Depends(get_db)):
    """Public shareable result page. Optimized for Telegram link previews."""

    row = None
    try:
        row = db.execute(
            "SELECT * FROM radar_scans WHERE scan_id = :id", {"id": scan_id}
        ).fetchone()
    except Exception:
        pass

    if not row:
        return HTMLResponse("<h1>Scan not found</h1>", status_code=404)

    # Track view
    try:
        db.execute(
            "UPDATE radar_scans SET result_viewed = TRUE WHERE scan_id = :id",
            {"id": scan_id}
        )
        db.commit()
    except Exception:
        pass

    score   = row["score"]
    regime  = row["regime"]
    asset   = row["asset"]
    tf      = row["timeframe"]
    label   = row["label"] or "NEUTRAL"
    session = row["session"] or ""

    # Color mapping
    color_map = {
        "STRONG": "#00ff9d", "GOOD": "#00e5ff",
        "CAUTION": "#ffaa00", "RISKY": "#ff7700", "AVOID": "#ff4444"
    }
    color = color_map.get(label, "#00e5ff")
    bar   = score

    notes_raw = row["risk_notes"] or "[]"
    if isinstance(notes_raw, str):
        import json as _j
        try:
            notes_list = _j.loads(notes_raw)
        except Exception:
            notes_list = []
    else:
        notes_list = notes_raw or []
    notes_html = "".join(f"<li>{n}</li>" for n in notes_list)

    strategy = row["strategy_hint"] or ""
    cta_url  = f"{BASE_URL}/web/?scan={scan_id}&asset={asset}"
    scan_url = f"{BASE_URL}/radar/result/{scan_id}"

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta property="og:title" content="Z-ARMOR Radar: {asset} {tf} — {regime} {score}/100">
  <meta property="og:description" content="{strategy}">
  <meta property="og:url" content="{scan_url}">
  <title>Z-ARMOR Radar — {asset} {tf}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #05070a; font-family: 'Courier New', monospace; color: #ccc;
            display: flex; justify-content: center; padding: 24px 16px; min-height: 100vh; }}
    .card {{ width: 100%; max-width: 480px; background: #080a0f;
             border: 1px solid {color}44; border-radius: 8px; overflow: hidden; }}
    .header {{ background: linear-gradient(135deg,#020305,#0a0c10);
               padding: 20px 24px; border-bottom: 2px solid {color}55; }}
    .brand {{ font-size: 11px; color: {color}; letter-spacing: 3px; font-weight: 900; }}
    .title {{ font-size: 18px; color: #fff; font-weight: 900; margin-top: 4px; }}
    .subtitle {{ font-size: 12px; color: #556; margin-top: 2px; }}
    .body {{ padding: 24px; }}
    .score-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
    .regime-badge {{ font-size: 14px; font-weight: 900; color: {color}; letter-spacing: 1px; }}
    .score-num {{ font-size: 36px; font-weight: 900; color: {color}; line-height: 1; }}
    .score-max {{ font-size: 14px; color: #445; }}
    .bar-bg {{ background: #0a0c12; border-radius: 3px; height: 6px; margin-bottom: 6px; }}
    .bar-fill {{ background: {color}; width: {bar}%; height: 6px; border-radius: 3px;
                 transition: width 0.8s ease; }}
    .conf {{ font-size: 11px; color: #556; margin-bottom: 20px; }}
    .section-title {{ font-size: 10px; color: {color}88; letter-spacing: 2px;
                      margin-bottom: 10px; margin-top: 18px; }}
    .breakdown {{ background: #020305; border: 1px solid #ffffff0d;
                  border-radius: 4px; padding: 14px 16px; margin-bottom: 16px; }}
    .bd-row {{ display: flex; justify-content: space-between; align-items: center;
               padding: 5px 0; border-bottom: 1px solid #0d0f14; font-size: 12px; }}
    .bd-row:last-child {{ border-bottom: none; }}
    .bd-label {{ color: #667; }}
    .bd-bar {{ width: 80px; background: #0a0c12; border-radius: 2px; height: 4px;
               display: inline-block; margin: 0 8px; vertical-align: middle; }}
    .bd-fill {{ background: {color}88; height: 4px; border-radius: 2px; }}
    .bd-val {{ color: {color}; font-weight: 900; min-width: 26px; text-align: right; }}
    .notes {{ padding: 0; list-style: none; }}
    .notes li {{ font-size: 12px; color: #889; padding: 5px 0;
                 border-bottom: 1px solid #0d0f14; line-height: 1.5; }}
    .notes li:last-child {{ border-bottom: none; }}
    .strategy {{ background: #020305; border-left: 3px solid {color};
                 padding: 12px 16px; font-size: 13px; color: #aaa;
                 border-radius: 0 4px 4px 0; margin-top: 16px; line-height: 1.6; }}
    .cta {{ display: block; margin-top: 24px; background: {color}; color: #000;
            font-weight: 900; text-align: center; padding: 14px;
            border-radius: 4px; text-decoration: none; font-size: 13px;
            letter-spacing: 1px; transition: opacity 0.2s; }}
    .cta:hover {{ opacity: 0.85; }}
    .share-row {{ display: flex; gap: 10px; margin-top: 12px; }}
    .share-btn {{ flex: 1; background: #0a0c12; border: 1px solid #ffffff11;
                  color: #667; font-size: 12px; padding: 10px;
                  text-align: center; border-radius: 4px; cursor: pointer;
                  text-decoration: none; }}
    .share-btn:hover {{ border-color: {color}55; color: {color}; }}
    .footer {{ padding: 14px 24px; background: #020305;
               border-top: 1px solid #0d0f14; text-align: center;
               font-size: 10px; color: #334; }}
  </style>
</head>
<body>
<div class="card">
  <div class="header">
    <div class="brand">⚡ Z-ARMOR RADAR SCAN</div>
    <div class="title">{asset} / {tf}</div>
    <div class="subtitle">{session} &nbsp;•&nbsp; {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M')} UTC</div>
  </div>

  <div class="body">
    <div class="score-row">
      <div class="regime-badge">{regime.replace("_"," ")}</div>
      <div><span class="score-num">{score}</span><span class="score-max"> /100</span></div>
    </div>
    <div class="bar-bg"><div class="bar-fill"></div></div>
    <div class="conf">{label} &nbsp;•&nbsp; {row.get("confidence","MEDIUM")} CONFIDENCE &nbsp;•&nbsp; Risk: {row.get("risk_level","MEDIUM") or "MEDIUM"}</div>

    <div class="section-title">SCORE BREAKDOWN</div>
    <div class="breakdown">
      {''.join([
          f'<div class="bd-row"><span class="bd-label">{k.replace("_"," ").title()}</span>'
          f'<span class="bd-bar"><span class="bd-fill" style="width:{min(100,int(v))}%"></span></span>'
          f'<span class="bd-val">{int(v)}</span></div>'
          for k, v in (json.loads(row["breakdown"]) if isinstance(row["breakdown"], str) else (row["breakdown"] or {})).items()
      ])}
    </div>

    <div class="section-title">MARKET CONDITIONS</div>
    <ul class="notes">{notes_html}</ul>

    <div class="section-title">STRATEGY HINT</div>
    <div class="strategy">{strategy}</div>

    <a href="{cta_url}" class="cta" onclick="trackCTA('{scan_id}')">
      ⚡ OPEN DEEP REGIME ANALYSIS →
    </a>

    <div class="share-row">
      <a class="share-btn" href="https://t.me/share/url?url={scan_url}&text=Z-ARMOR+Radar+{asset}+{tf}+{regime}+{score}/100" target="_blank">
        ✈ Telegram
      </a>
      <a class="share-btn" href="#" onclick="copyLink('{scan_url}'); return false;">
        📋 Copy Link
      </a>
      <a class="share-btn" href="{BASE_URL}/web/?scan=new">
        🔄 Scan Again
      </a>
    </div>
  </div>

  <div class="footer">Z-ARMOR CLOUD © 2026 &nbsp;•&nbsp; REGIME FIT INTELLIGENCE</div>
</div>

<script>
function copyLink(url) {{
  navigator.clipboard.writeText(url).then(() => {{
    const btn = event.target;
    btn.textContent = '✅ Copied!';
    setTimeout(() => btn.textContent = '📋 Copy Link', 2000);
  }});
}}
async function trackCTA(scanId) {{
  try {{
    await fetch('/radar/track-cta/' + scanId, {{method:'POST'}});
  }} catch(e) {{}}
}}
</script>
</body>
</html>"""
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=3600"})


# ── GET /radar/feed — All 12 combinations ──────────────────────────────────────
@router.get("/feed")
async def radar_feed():
    """
    Current scores for all 12 combinations.
    Used by daily digest email and landing page ticker.
    """
    results = compute_all()
    timestamp = datetime.now(timezone.utc).isoformat()

    # Flatten to list sorted by H1 score desc
    flat = []
    for asset, tfs in results.items():
        for tf, data in tfs.items():
            flat.append({
                "asset":   asset,
                "timeframe": tf,
                **data,
                "timestamp_utc": timestamp,
            })

    flat.sort(key=lambda x: (x["timeframe"] != "H1", -x["score"]))
    return {"status": "ok", "count": len(flat), "feed": flat, "timestamp_utc": timestamp}


# ── GET /radar/result/{scan_id}/json — JSON version ────────────────────────────
@router.get("/data/{scan_id}")
async def radar_data(scan_id: str, db: Session = Depends(get_db)):
    """JSON version of scan result — for dashboard embed."""
    try:
        row = db.execute(
            "SELECT * FROM radar_scans WHERE scan_id = :id", {"id": scan_id}
        ).fetchone()
    except Exception as e:
        raise HTTPException(500, str(e))
    if not row:
        raise HTTPException(404, "Scan not found")
    return dict(row)


# ── GET /radar/history — User scan history ─────────────────────────────────────
@router.get("/history")
async def radar_history(
    email: str = Query(..., description="User email"),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db)
):
    """Scan history for a user email. Used for radar history feature."""
    try:
        rows = db.execute("""
            SELECT scan_id, asset, timeframe, score, regime, label,
                   session, created_at
            FROM radar_scans
            WHERE email = :email
            ORDER BY created_at DESC
            LIMIT :limit
        """, {"email": email, "limit": limit}).fetchall()
    except Exception as e:
        raise HTTPException(500, str(e))

    return {
        "email":   email,
        "count":   len(rows),
        "history": [dict(r) for r in rows],
    }


# ── GET /radar/assets — Meta endpoint ─────────────────────────────────────────
@router.get("/assets")
async def radar_assets():
    """Supported assets + current session info."""
    from .engine import _get_session
    now = datetime.now(timezone.utc)
    asset_info = {}
    for asset in ASSET_PROFILES:
        _, _, _, session = _get_session(asset, now.hour)
        asset_info[asset] = {"current_session": session}

    return {
        "assets":     list(ASSET_PROFILES.keys()),
        "timeframes": list(TF_MULT.keys()),
        "session_utc_hour": now.hour,
        "asset_sessions": asset_info,
    }


# ── GET /radar/stats — Admin stats ────────────────────────────────────────────
@router.get("/stats")
async def radar_stats(db: Session = Depends(get_db)):
    """Aggregate stats for admin monitoring."""
    try:
        total = db.execute("SELECT COUNT(*) FROM radar_scans").scalar()
        today = db.execute(
            "SELECT COUNT(*) FROM radar_scans WHERE created_at > NOW() - INTERVAL '24 hours'"
        ).scalar()
        by_asset = db.execute("""
            SELECT asset, COUNT(*) as cnt, AVG(score) as avg_score
            FROM radar_scans
            GROUP BY asset ORDER BY cnt DESC
        """).fetchall()
        conversions = db.execute(
            "SELECT COUNT(*) FROM radar_scans WHERE converted = TRUE"
        ).scalar()
    except Exception as e:
        raise HTTPException(500, str(e))

    return {
        "total_scans":    total,
        "scans_24h":      today,
        "conversions":    conversions,
        "by_asset":       [dict(r) for r in by_asset],
    }


# ── POST /radar/track-cta/{scan_id} — CTA click tracking ─────────────────────
@router.post("/track-cta/{scan_id}")
async def track_cta(scan_id: str, db: Session = Depends(get_db)):
    try:
        db.execute(
            "UPDATE radar_scans SET cta_clicked = TRUE WHERE scan_id = :id",
            {"id": scan_id}
        )
        db.commit()
    except Exception:
        pass
    return {"ok": True}
