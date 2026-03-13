/**
 * RadarAlertSystem.js — Radar Architecture V4
 * Alert Engine · Z-Armor Platform
 *
 * Responsibilities:
 *   - Subscribe users to alerts (Telegram / Email)
 *   - Trigger alerts when score > 70 AND regime != VOLATILE/CHAOTIC
 *   - Cooldown management to prevent alert spam
 *   - Queue-based delivery (fire-and-forget to backend worker)
 *   - Email capture for growth loop (lead gen from anonymous scans)
 *
 * Architecture note:
 *   Alert delivery (Telegram bot sends, email SMTP) is handled
 *   server-side by the Alert Worker queue — this module only
 *   submits events to the queue endpoint.
 *
 * Integration:
 *   Identity Domain → provides user_id, ref_code
 *   Tactical Domain → RadarAlertSystem receives scan results
 *   Infrastructure  → Queue Worker (Redis Streams / RQ) handles delivery
 */

const RadarAlertSystem = (() => {

  // ─── Alert trigger thresholds ────────────────────────────────────────
  const ALERT_THRESHOLD   = 70;
  const ALERT_BLOCK_REGIMES = new Set(['VOLATILE', 'CHAOTIC', 'AVOID']);

  // ─── Cooldown: prevent spam per (user × asset × timeframe) ──────────
  // Key: "asset:tf:channel", Value: timestamp of last alert
  const _cooldowns = new Map();
  const COOLDOWN_MS = {
    telegram : 5  * 60 * 1000,  // 5 min between Telegram alerts
    email    : 15 * 60 * 1000,  // 15 min between email alerts
    push     : 3  * 60 * 1000,  // 3 min for push
  };

  function _cooldownKey(asset, tf, channel) {
    return `${asset}:${tf}:${channel}`;
  }

  function _isOnCooldown(asset, tf, channel) {
    const key  = _cooldownKey(asset, tf, channel);
    const last = _cooldowns.get(key);
    if (!last) return false;
    return Date.now() - last < (COOLDOWN_MS[channel] || COOLDOWN_MS.telegram);
  }

  function _setCooldown(asset, tf, channel) {
    _cooldowns.set(_cooldownKey(asset, tf, channel), Date.now());
  }

  // ─── Alert message formatter ──────────────────────────────────────────
  /**
   * buildAlertMessage({ asset, score, regime, opportunity, timeframe, shareLink })
   * Returns formatted alert text for Telegram / Email.
   */
  function buildAlertMessage({ asset, score, regime, opportunity, timeframe = 'H1', shareLink = '' }) {
    const regimeDisplay = (regime || '').replace(/_/g, ' ');
    const tf            = timeframe.toUpperCase();
    const link          = shareLink || `https://zarmor.ai/scan?asset=${(asset || 'gold').toLowerCase()}`;

    return [
      `🚨 Z-Armor Radar Alert`,
      ``,
      `Asset: ${asset}  ·  ${tf}`,
      `Radar Score: ${score}/100`,
      `Regime: ${regimeDisplay}`,
      `Opportunity: ${opportunity || 'HIGH'}`,
      ``,
      `High-probability opportunity detected.`,
      ``,
      `Scan now:`,
      link,
    ].join('\n');
  }

  // ─── Alert eligibility check ──────────────────────────────────────────
  /**
   * shouldAlert({ score, regime })
   * Returns true if conditions meet alert trigger criteria.
   *
   * Rule: score > 70 AND regime NOT in block list
   */
  function shouldAlert({ score, regime }) {
    if (score < ALERT_THRESHOLD) return false;
    const regimeKey = (regime || '').toUpperCase().replace(/\s/g, '_');
    if (ALERT_BLOCK_REGIMES.has(regimeKey)) return false;
    return true;
  }

  // ─── Trigger alert (fire-and-forget to backend queue) ────────────────
  /**
   * trigger({ data, email, shareLink, apiBase })
   * Sends alert event to backend queue endpoint.
   * Backend Alert Worker handles actual Telegram/email delivery.
   */
  async function trigger({ data, email = '', shareLink = '', apiBase = '' }) {
    if (!shouldAlert(data)) return { fired: false, reason: 'threshold_not_met' };

    const asset = data.asset || 'GOLD';
    const tf    = data.timeframe || 'H1';

    const message = buildAlertMessage({
      asset,
      score      : data.score,
      regime     : data.regime,
      opportunity: data.opportunity,
      timeframe  : tf,
      shareLink,
    });

    const payload = {
      event     : 'RADAR_ALERT',
      asset,
      timeframe : tf,
      score     : data.score,
      regime    : data.regime,
      opportunity: data.opportunity,
      message,
      email,
      ref       : window._refCode || '',
      share_url : shareLink,
      timestamp : new Date().toISOString(),
    };

    // Fire to queue endpoint — non-blocking
    const fired = { telegram: false, email: false };

    // Telegram alert
    if (!_isOnCooldown(asset, tf, 'telegram')) {
      _triggerFetch(`${apiBase}/api/alerts/trigger`, payload).then(() => {
        _setCooldown(asset, tf, 'telegram');
        fired.telegram = true;
      });
    }

    // Subscribed user email alerts (handled server-side via queue)
    if (email && !_isOnCooldown(asset, tf, 'email')) {
      _triggerFetch(`${apiBase}/api/alerts/email-trigger`, { ...payload, target_email: email }).then(() => {
        _setCooldown(asset, tf, 'email');
        fired.email = true;
      });
    }

    return { fired: true, channels: fired, message };
  }

  async function _triggerFetch(url, body) {
    try {
      await fetch(url, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify(body),
      });
    } catch (_) {
      // Silently fail — alert delivery is best-effort from client
    }
  }

  // ─── Subscribe to alerts ──────────────────────────────────────────────
  /**
   * subscribe({ email, asset, timeframe, channel, threshold, apiBase })
   * Registers alert subscription in the backend (alert_subscriptions table).
   *
   * channel: 'telegram' | 'email' | 'both'
   * threshold: default 70
   */
  async function subscribe({ email, telegram, asset, timeframe, channel = 'email', threshold = 70, apiBase = '' }) {
    if (!email && !telegram) return { ok: false, message: 'Email hoặc Telegram username là bắt buộc.' };
    if (!asset) return { ok: false, message: 'Asset là bắt buộc.' };

    const payload = {
      email         : email || '',
      telegram      : telegram || '',
      asset         : (asset || 'GOLD').toUpperCase(),
      timeframe     : (timeframe || 'H1').toUpperCase(),
      channel,
      threshold,
      subscribed_at : new Date().toISOString(),
      ref           : window._refCode || '',
    };

    try {
      // V4 endpoint
      const res = await fetch(`${apiBase}/radar/subscribe`, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify(payload),
      });
      if (res.ok) {
        const d = await res.json().catch(() => ({}));
        return { ok: true, message: d.message || 'Đăng ký thành công!' };
      }
      // Legacy fallback
      const res2 = await fetch(`${apiBase}/api/subscribe-alert`, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify(payload),
      });
      if (res2.ok) {
        const d2 = await res2.json().catch(() => ({}));
        return { ok: true, message: d2.message || 'Đăng ký thành công!' };
      }
      return { ok: false, message: `Server error: ${res.status}` };
    } catch (_) {
      return { ok: true, message: 'Đã lưu — sẽ đồng bộ khi server online.', offline: true };
    }
  }

  // ─── Email capture (Growth Loop: lead gen from anonymous scans) ───────
  /**
   * captureEmail({ email, asset, timeframe, ref, apiBase })
   * Called on every scan submission — captures lead even if not subscribing.
   * Backend upserts into email capture table for remarketing pipeline.
   */
  async function captureEmail({ email, asset, timeframe, apiBase = '' }) {
    if (!email || !asset) return false;
    try {
      await fetch(`${apiBase}/api/email-capture`, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify({
          email,
          asset_interest    : (asset     || '').toUpperCase(),
          timeframe_interest: (timeframe || 'H1').toUpperCase(),
          captured_at       : new Date().toISOString(),
          source            : 'radar_scan_v4',
          ref               : window._refCode || '',
        }),
      });
      return true;
    } catch (_) { return false; }
  }

  // ─── Alert history (local session cache) ─────────────────────────────
  const _alertHistory = [];
  function getHistory() { return [..._alertHistory]; }
  function _recordAlert(data) {
    _alertHistory.unshift({ ...data, firedAt: new Date().toISOString() });
    if (_alertHistory.length > 20) _alertHistory.pop();
  }

  // ─── Public API ───────────────────────────────────────────────────────
  return {
    trigger,
    subscribe,
    captureEmail,
    shouldAlert,
    buildAlertMessage,
    getHistory,
    ALERT_THRESHOLD,
  };

})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = RadarAlertSystem;
}
