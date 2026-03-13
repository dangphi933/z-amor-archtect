/**
 * RadarScanPage.js — Radar Architecture V4
 * Page Controller · Z-Armor Platform
 *
 * Responsibilities:
 *   - Parse URL params: /scan?asset=gold&tf=H1&ref=abc123
 *   - Manage asset / timeframe selection state
 *   - Orchestrate scan flow: Identity check → Cache → Engine → Display
 *   - Render V4 result: Score, Regime, Opportunity, Components, Share
 *   - Coordinate between all V4 modules
 *
 * V4 Scan Flow (cache-first, prevents compute storms at 50k users):
 *   1. User triggers scan
 *   2. POST /radar/scan → backend checks precomputed cache (~30s TTL)
 *   3. If cache HIT: return immediately (< 10ms response)
 *   4. If cache MISS: backend computes → caches → returns
 *   5. Client renders result from API or falls back to RadarScoreEngine.compute()
 *
 * URL Format:
 *   /scan               — default (GOLD, H1)
 *   /scan?asset=gold    — specific asset
 *   /scan?asset=eurusd&tf=H4
 *   /scan?asset=btc&ref=abc123  — referral entry
 *   /scan?asset=gold&email=x@y.com&auto=true  — auto-scan
 */

const RadarScanPage = (() => {

  // ─── Asset mapping (aliases → canonical) ─────────────────────────────
  const ASSET_MAP = {
    GOLD  : 'GOLD',  XAU: 'GOLD', XAUUSD: 'GOLD',
    EUR   : 'EURUSD', EURUSD: 'EURUSD',
    BTC   : 'BTC',   BTCUSD: 'BTC', BITCOIN: 'BTC',
    NASDAQ: 'NASDAQ', NAS: 'NASDAQ', NDX: 'NASDAQ', QQQ: 'NASDAQ',
    OIL   : 'OIL',   CRUDE: 'OIL', WTI: 'OIL',
    SILVER: 'SILVER', XAG: 'SILVER', XAGUSD: 'SILVER',
  };

  const ASSET_ORDER = ['GOLD', 'EURUSD', 'BTC', 'NASDAQ'];
  const TF_VALID    = ['M5', 'M15', 'H1', 'H4', 'D1', 'W1'];

  // ─── URL Parameter Parsing ────────────────────────────────────────────
  function parseURLParams() {
    const p        = new URLSearchParams(window.location.search);
    const rawAsset = (p.get('asset') || '').toUpperCase();
    const rawTF    = (p.get('tf')    || '').toUpperCase();
    const email    = p.get('email')  || '';
    const ref      = p.get('ref')    || '';
    const auto     = p.get('auto')   === 'true';
    const regime   = p.get('regime') || '';   // V4: optional regime hint

    const asset = ASSET_MAP[rawAsset] || null;
    const tf    = TF_VALID.includes(rawTF) ? rawTF : null;

    return { asset, tf, email, ref, auto, regime };
  }

  // ─── Asset & TF DOM Selectors ─────────────────────────────────────────
  function applyAsset(asset) {
    const idx = ASSET_ORDER.indexOf(asset);
    document.querySelectorAll('#asset-grid .sel-btn').forEach((b, i) => {
      b.classList.toggle('active', i === idx);
    });
  }

  function applyTF(tf) {
    document.querySelectorAll('#tf-grid .sel-btn').forEach(b => {
      b.classList.toggle('active', b.textContent.trim() === tf);
    });
  }

  // ─── Opportunity Panel (V4 new section) ──────────────────────────────
  /**
   * renderOpportunityPanel(result)
   * Renders the V4 Opportunity Strength section in the result card.
   * Shows: Score, Regime, Opportunity Level, 4 Component bars.
   */
  function renderOpportunityPanel(result) {
    const panel = document.getElementById('v4-opportunity-panel');
    if (!panel) return;

    const oColor = result.opportunityColor || result.color || '#00ff9d';
    const comps  = result.components || {};
    const compLabels = [
      { key: 'trend',      label: 'Trend Structure',       icon: '📈', weight: '35%' },
      { key: 'volatility', label: 'Volatility Expansion',  icon: '⚡', weight: '30%' },
      { key: 'liquidity',  label: 'Liquidity Condition',   icon: '💧', weight: '20%' },
      { key: 'momentum',   label: 'Momentum Alignment',    icon: '🎯', weight: '15%' },
    ];

    const compHTML = compLabels.map(c => {
      const val   = comps[c.key] || 0;
      const color = _compColor(val);
      const state = val >= 70 ? 'Strong' : val >= 50 ? 'Rising' : val >= 30 ? 'Moderate' : 'Weak';
      return `
        <div class="v4-comp-row">
          <div class="v4-comp-left">
            <span class="v4-comp-icon">${c.icon}</span>
            <div>
              <div class="v4-comp-label">${c.label}</div>
              <div class="v4-comp-state" style="color:${color};">${state}</div>
            </div>
          </div>
          <div class="v4-comp-right">
            <div class="v4-comp-bar-track">
              <div class="v4-comp-bar-fill" data-w="${val}" style="background:${color};"></div>
            </div>
            <div class="v4-comp-val" style="color:${color};">${val}</div>
          </div>
        </div>`;
    }).join('');

    panel.innerHTML = `
      <div class="v4-opp-header">
        <div class="v4-opp-badge" style="color:${oColor};border-color:${oColor}44;background:${oColor}0d;">
          ${result.opportunity || 'HIGH'} OPPORTUNITY
        </div>
        <div class="v4-opp-regime" style="color:${oColor};">
          ${(result.regime || '').replace(/_/g, ' ')}
        </div>
      </div>
      <div class="v4-comps">${compHTML}</div>
    `;

    panel.style.display = 'block';

    // Animate bars after paint
    requestAnimationFrame(() => {
      panel.querySelectorAll('.v4-comp-bar-fill').forEach(el => {
        el.style.transition = 'width 0.9s ease';
        el.style.width = el.dataset.w + '%';
      });
    });
  }

  function _compColor(val) {
    if (val >= 70) return '#00ff9d';
    if (val >= 50) return '#00e5ff';
    if (val >= 30) return '#ffaa00';
    return '#ff3355';
  }

  // ─── Init ─────────────────────────────────────────────────────────────
  /**
   * init(onAutoScan)
   * Called once on page load. Reads URL params, applies UI state.
   * Fires onAutoScan callback if auto=true or (asset + email) in URL.
   */
  function init(onAutoScan) {
    const { asset, tf, email, ref, auto, regime } = parseURLParams();

    if (asset) { applyAsset(asset); window._selAsset = asset; }
    if (tf)    { applyTF(tf);       window._selTF    = tf; }
    if (email) {
      const el = document.getElementById('gate-email');
      if (el) el.value = email;
    }

    // Referral detection is now handled by RadarShareSystem.detectReferralScan()
    // (called separately after RadarShareSystem loads)

    if ((auto || (asset && email)) && onAutoScan) {
      setTimeout(onAutoScan, 600);
    }

    // Track scan_event if arriving with asset param (direct URL intent)
    if (asset && typeof RadarShareSystem !== 'undefined') {
      RadarShareSystem.trackEvent({
        type    : ref ? 'referral_scan' : 'scan_event',
        asset,
        timeframe: tf || 'H1',
        channel : ref ? 'referral' : 'direct',
        apiBase : window.location.origin,
      });
    }
  }

  // ─── Public API ───────────────────────────────────────────────────────
  return {
    init,
    parseURLParams,
    applyAsset,
    applyTF,
    renderOpportunityPanel,
    ASSET_MAP,
    ASSET_ORDER,
    TF_VALID,
  };

})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = RadarScanPage;
}
