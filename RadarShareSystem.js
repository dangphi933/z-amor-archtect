/**
 * RadarShareSystem.js — Radar Architecture V4
 * Viral Share Engine · Z-Armor Platform
 *
 * Responsibilities:
 *   - Generate shareable scan links with ref_code tracking
 *   - Format share text for Telegram / Twitter / Copy
 *   - Track share events → backend analytics pipeline
 *   - Drive Growth Loop: share → referral scan → new user
 *
 * Integration:
 *   Identity Domain → ref_code (user.ref_code from JWT or email-derived)
 *   Growth Loop     → RadarGrowthLoop.advanceLoop() on share events
 *   Tactical Domain → receives scan result data for share content
 *
 * Growth Loop:
 *   Trader scans → Radar shows opportunity → Trader shares →
 *   New trader opens /scan link → Runs scan → Loop continues
 */

const RadarShareSystem = (() => {

  const BASE_URL = window.location.origin + '/scan';

  // ─── Ref Code Generation ──────────────────────────────────────────────
  /**
   * generateRef(email)
   * Derives a short URL-safe ref code from email.
   * In V4: server returns user.ref_code from Identity Domain.
   * This is the offline fallback only.
   */
  function generateRef(email) {
    if (!email) return '';
    try {
      return btoa(email.toLowerCase().trim())
        .replace(/[+/=]/g, '')
        .slice(0, 8);
    } catch (_) { return ''; }
  }

  /**
   * resolveRef(email)
   * Returns user's ref_code from Identity context (JWT) or falls back to generateRef.
   * Priority: window._userRefCode (from JWT) > generateRef(email)
   */
  function resolveRef(email) {
    return window._userRefCode || window._refCode || generateRef(email);
  }

  // ─── Share Link Builder ───────────────────────────────────────────────
  /**
   * generateShareLink({ asset, timeframe, email, extraParams })
   * Builds canonical share URL with ref_code.
   *
   * Format: /scan?asset=gold&tf=H1&ref=abc123
   *
   * This link is the viral entry point for the Growth Loop.
   * When clicked: new trader opens RadarScanPage, ref event is tracked.
   */
  function generateShareLink({ asset = 'GOLD', timeframe = '', email = '', extraParams = {} } = {}) {
    const params = new URLSearchParams();
    params.set('asset', asset.toLowerCase());
    if (timeframe) params.set('tf', timeframe.toUpperCase());

    const ref = resolveRef(email);
    if (ref) params.set('ref', ref);

    for (const [k, v] of Object.entries(extraParams)) {
      params.set(k, v);
    }

    return `${BASE_URL}?${params.toString()}`;
  }

  // ─── Share Text Builders ──────────────────────────────────────────────
  /**
   * buildShareText({ asset, score, regime, opportunity, timeframe, shareLink })
   * Full multi-line share message for Telegram.
   */
  function buildShareText({ asset, score, regime, opportunity, timeframe = 'H1', shareLink = '' }) {
    const link          = shareLink || generateShareLink({ asset, timeframe });
    const regimeDisplay = (regime || 'EXPANSION').replace(/_/g, ' ');
    const opp           = opportunity || 'HIGH';

    return [
      `⚡ ${asset} Radar Score: ${score}/100`,
      ``,
      `Regime: ${regimeDisplay}`,
      `Opportunity: ${opp}`,
      `Timeframe: ${timeframe}`,
      ``,
      `${opp === 'HIGH' || opp === 'VERY HIGH'
        ? '🟢 High-probability setup detected on Z-Armor Radar.'
        : '📡 Market scan complete on Z-Armor Radar.'}`,
      ``,
      link,
    ].join('\n');
  }

  /**
   * buildTwitterText({ asset, score, regime, shareLink })
   * Shorter text optimized for Twitter/X character limit.
   */
  function buildTwitterText({ asset, score, regime, shareLink = '' }) {
    const link = shareLink || generateShareLink({ asset });
    return `${asset} Radar Score just hit ${score}/100 on @ZArmor_AI (${(regime || 'EXPANSION').replace(/_/g,' ')} regime)\n${link}`;
  }

  // ─── Share Actions ────────────────────────────────────────────────────
  /**
   * shareToTelegram({ asset, score, regime, opportunity, timeframe, shareLink })
   */
  function shareToTelegram({ asset, score, regime, opportunity, timeframe, shareLink }) {
    const link = shareLink || generateShareLink({ asset, timeframe });
    const text = buildShareText({ asset, score, regime, opportunity, timeframe, shareLink: link });
    window.open(
      `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`,
      '_blank'
    );
  }

  /**
   * shareToTwitter({ asset, score, regime, shareLink })
   */
  function shareToTwitter({ asset, score, regime, shareLink }) {
    const link = shareLink || generateShareLink({ asset });
    const text = buildTwitterText({ asset, score, regime, shareLink: link });
    window.open(
      `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}`,
      '_blank', 'width=560,height=420'
    );
  }

  /**
   * copyToClipboard(text) → Promise<boolean>
   */
  async function copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      // Fallback for older browsers
      const ta = Object.assign(document.createElement('textarea'), {
        value: text,
        style: 'position:fixed;opacity:0',
      });
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    }
  }

  // ─── Event Tracking ───────────────────────────────────────────────────
  /**
   * trackEvent({ type, asset, timeframe, channel, ref, apiBase })
   * Tracks share and referral events for Growth Loop analytics.
   *
   * Events:
   *   scan_event      — user ran a scan
   *   share_event     — user shared scan result
   *   referral_scan   — new user opened a shared link and ran scan
   *
   * Backend stores in referral_events table (deduped by IP/24h).
   */
  async function trackEvent({ type, asset, timeframe = 'H1', channel = '', apiBase = '' }) {
    if (!apiBase) return;

    const ref     = window._refCode || '';
    const payload = {
      event_type : type,
      asset      : (asset || '').toUpperCase(),
      timeframe  : timeframe.toUpperCase(),
      channel,
      ref,
      timestamp  : new Date().toISOString(),
      page_url   : window.location.href,
    };

    try {
      // V4: unified event endpoint
      await fetch(`${apiBase}/radar/events`, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify(payload),
      });
    } catch (_) {
      // Legacy fallback
      try {
        await fetch(`${apiBase}/api/track-share`, {
          method  : 'POST',
          headers : { 'Content-Type': 'application/json' },
          body    : JSON.stringify(payload),
        });
      } catch (_2) { /* best effort */ }
    }
  }

  // ─── Referral Scan Detection ──────────────────────────────────────────
  /**
   * detectReferralScan()
   * Called on page load. If URL contains ?ref=, this is a referral scan.
   * Tracks referral_scan event and shows referral badge.
   */
  function detectReferralScan(apiBase = '') {
    const params = new URLSearchParams(window.location.search);
    const ref    = params.get('ref');
    if (!ref) return null;

    // Store ref globally for all subsequent tracking
    window._refCode = ref;

    // Show referral badge
    const badge = document.getElementById('ref-badge');
    if (badge) badge.style.display = 'block';

    // Track referral_scan event (non-blocking)
    const asset = params.get('asset') || '';
    trackEvent({ type: 'referral_scan', asset, channel: 'referral', apiBase });

    return ref;
  }

  // ─── Public API ───────────────────────────────────────────────────────
  return {
    generateRef,
    resolveRef,
    generateShareLink,
    buildShareText,
    buildTwitterText,
    shareToTelegram,
    shareToTwitter,
    copyToClipboard,
    trackEvent,
    detectReferralScan,
    // Legacy compat
    shareTelegram : ({ asset, score, regime, timeframe, shareLink } = {}) =>
      shareToTelegram({ asset, score, regime, timeframe, shareLink }),
    shareTwitter  : ({ asset, score, regime, shareLink } = {}) =>
      shareToTwitter({ asset, score, regime, shareLink }),
    copyText      : copyToClipboard,
    trackShare    : (asset, channel, apiBase) =>
      trackEvent({ type: 'share_event', asset, channel, apiBase }),
  };

})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = RadarShareSystem;
}
