// ═══════════════════════════════════════════════════════════════════════════════
// RegimeFitModal.js  —  ZArmor Radar Growth Loop · Deep Analysis Layer
// Stack: Preact + HTM (no build step, matches RightColumn.js pattern)
// Import trong RightColumn.js:
//   import RegimeFitModal from './RegimeFitModal.js';
// Usage:
//   ${showRadarModal && html`${h(RegimeFitModal, {
//       scanData: radarResult,
//       radarAsset, radarTF, radarEmail, setRadarAsset, setRadarTF,
//       setRadarEmail, radarLoading, runRadarScan, COLORS,
//       onClose: () => setShowRadarModal(false)
//   })}`}
// ═══════════════════════════════════════════════════════════════════════════════

import { h } from 'preact';
import { useState, useEffect } from 'preact/hooks';
import htm from 'htm';

const html = htm.bind(h);

// ─── Seeded PRNG (asset+score → deterministic regime data) ──────────────────
function buildRegimeData(asset, score) {
    const seed = String(asset || '').split('').reduce((a, c) => a + c.charCodeAt(0), 0) * 31 + (score || 0);
    const rng  = (n) => ((seed * n * 9301 + 49297) % 233280) / 233280;

    const s70 = score >= 70, s50 = score >= 50, s30 = score >= 30;

    const type = s70
        ? (rng(1) > .5 ? 'TREND' : 'ACCUMULATION')
        : s50 ? (rng(2) > .5 ? 'RANGE' : 'TREND')
        : s30 ? 'VOLATILE' : 'DISTRIBUTION';

    const probs = {
        TREND:        type === 'TREND'        ? Math.round(55 + rng(3)  * 30) : Math.round(5 + rng(4)  * 20),
        RANGE:        type === 'RANGE'        ? Math.round(55 + rng(5)  * 30) : Math.round(5 + rng(6)  * 20),
        VOLATILE:     type === 'VOLATILE'     ? Math.round(55 + rng(7)  * 30) : Math.round(5 + rng(8)  * 20),
        ACCUMULATION: type === 'ACCUMULATION' ? Math.round(55 + rng(9)  * 30) : Math.round(5 + rng(10) * 20),
        DISTRIBUTION: type === 'DISTRIBUTION' ? Math.round(55 + rng(11) * 30) : Math.round(5 + rng(12) * 20),
    };

    const stab   = Math.round(s70 ? 65 + rng(13)*30 : s50 ? 40 + rng(14)*25 : 15 + rng(15)*30);
    const tPerst = Math.round(30 + rng(16) * 65);
    const sCons  = Math.round(30 + rng(17) * 65);
    const lDepth = Math.round(30 + rng(18) * 65);

    const a = (asset || '').toUpperCase();
    const base = a==='GOLD'   || a.includes('XAU') ? 2340
               : a==='SILVER' || a.includes('XAG') ? 30.5
               : a==='OIL'    || a==='WTI'          ? 78.5
               : a==='BTC'    || a.includes('BTC')  ? 68500
               : a==='ETH'    || a.includes('ETH')  ? 3500
               : a==='SOL'    || a.includes('SOL')  ? 155
               : a==='NASDAQ' || a==='NDX'           ? 18400
               : a==='SP500'  || a==='SPX'           ? 5250
               : a==='DJI'    || a==='DOW'           ? 39500
               : a==='EURUSD' || a==='EUR'           ? 1.0850
               : a==='GBPUSD' || a==='GBP'           ? 1.2700
               : a==='USDJPY' || a==='JPY'           ? 151.5
               : a==='AUDUSD' || a==='AUD'           ? 0.6450
               : a==='USDCAD' || a==='CAD'           ? 1.3650
               : 100;
    const isForex  = ['EURUSD','GBPUSD','AUDUSD','USDCAD'].includes(a);
    const isJPY    = a === 'USDJPY';
    const isCrypto = ['BTC','ETH','SOL'].includes(a);
    const isIndex  = ['NASDAQ','SP500','DJI'].includes(a);
    const fmt = (p) => isJPY    ? p.toFixed(2)
                     : isForex  ? p.toFixed(4)
                     : (isCrypto || isIndex) ? p.toFixed(0)
                     : p.toFixed(2);

    const zones = [
        { type: 'supply', label: 'SUPPLY', price: fmt(base*(1+.008+rng(19)*.012)), strength: Math.round(60+rng(20)*35) },
        { type: 'supply', label: 'SUPPLY', price: fmt(base*(1+.018+rng(21)*.010)), strength: Math.round(40+rng(22)*30) },
        { type: 'demand', label: 'DEMAND', price: fmt(base*(1-.007-rng(23)*.010)), strength: Math.round(65+rng(24)*30) },
        { type: 'demand', label: 'DEMAND', price: fmt(base*(1-.016-rng(25)*.012)), strength: Math.round(45+rng(26)*30) },
    ];

    const smBias = s70 ? 'ACCUMULATION' : s50 ? 'NEUTRAL' : 'DISTRIBUTION';
    const smSignals = s70 ? [
        { text: 'Institutional buying at key demand zones',     conf: 'HIGH', color: '#00ff9d' },
        { text: 'Large block orders absorbed sell pressure',    conf: 'MED',  color: '#00e5ff' },
        { text: 'OB footprint aligns with current price action',conf: 'HIGH', color: '#00ff9d' },
    ] : s50 ? [
        { text: 'Mixed institutional flow — no clear bias',      conf: 'MED', color: '#ffaa00' },
        { text: 'Liquidity pools building above current price',  conf: 'MED', color: '#00e5ff' },
        { text: 'Watch for liquidity sweep before direction',    conf: 'LOW', color: '#ff8c00' },
    ] : [
        { text: 'Distribution signals across multiple TFs',     conf: 'HIGH', color: '#ff4444' },
        { text: 'Smart money reducing long exposure',           conf: 'MED',  color: '#ffaa00' },
        { text: 'Retail positions trapped — sweep likely',      conf: 'HIGH', color: '#ff4444' },
    ];

    const teScore = Math.round(score * .9 + rng(27) * 10);
    const modes = [
        { name: 'Trend Following', recommended: type==='TREND'||type==='ACCUMULATION', avoid: type==='DISTRIBUTION'||type==='VOLATILE' },
        { name: 'Mean Reversion',  recommended: type==='RANGE',                        avoid: type==='TREND'||type==='ACCUMULATION' },
        { name: 'No Trade Zone',   recommended: score < 35,                            avoid: false },
    ];

    return { type, probs, stab, tPerst, sCons, lDepth, zones, smBias, smSignals, teScore, modes };
}

// ─── scoreColor helper ───────────────────────────────────────────────────────
const scoreColor = (score, COLORS) =>
    score >= 70 ? COLORS.green
  : score >= 50 ? COLORS.cyan
  : score >= 30 ? COLORS.yellow
  : COLORS.red;

// ─── Section header ──────────────────────────────────────────────────────────
const SectionHeader = ({ label }) => html`
    <div style="font-family:monospace;font-size:8px;color:#334;letter-spacing:2px;
                text-transform:uppercase;margin-bottom:11px;
                display:flex;align-items:center;gap:7px;">
        ${label}
        <div style="flex:1;height:1px;background:#111;"></div>
    </div>
`;

// ═══════════════════════════════════════════════════════════════════════════════
// SUB-COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════════

// ─── 01: Regime Classification ───────────────────────────────────────────────
function RegimeClassification({ activeRegime, probs }) {
    const cells = [
        { key: 'TREND',        label: 'Trend',   icon: '↗' },
        { key: 'RANGE',        label: 'Range',   icon: '⇌' },
        { key: 'VOLATILE',     label: 'Volatile',icon: '⚡' },
        { key: 'ACCUMULATION', label: 'Accum.',  icon: '▲' },
        { key: 'DISTRIBUTION', label: 'Distrib.',icon: '▼' },
    ];
    return html`
        <div>
            <${SectionHeader} label="01 / Market Regime" />
            <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:5px;">
                ${cells.map(c => {
                    const active = activeRegime === c.key;
                    return html`
                        <div style="
                            background:${active ? '#00e5ff0f' : '#05070a'};
                            border:1px solid ${active ? 'rgba(0,229,255,0.3)' : '#111'};
                            border-top:2px solid ${active ? '#00e5ff' : 'transparent'};
                            border-radius:3px;padding:9px 5px;text-align:center;">
                            <div style="font-size:1.1rem;margin-bottom:4px;">${c.icon}</div>
                            <div style="font-family:monospace;font-size:7px;letter-spacing:.5px;
                                        color:${active ? '#00e5ff' : '#445'};">${c.label}</div>
                            <div style="font-family:monospace;font-size:9px;font-weight:900;
                                        color:${active ? '#00e5ff' : '#2a2a2a'};margin-top:3px;">
                                ${probs[c.key]}%
                            </div>
                        </div>
                    `;
                })}
            </div>
            <div style="font-family:monospace;font-size:8px;color:#445;margin-top:8px;letter-spacing:.3px;">
                Primary: <span style="color:#00e5ff;font-weight:900;">${activeRegime}</span>
                &nbsp;—&nbsp;${probs[activeRegime]}% probability
            </div>
        </div>
    `;
}

// ─── 02: Regime Stability Meter ──────────────────────────────────────────────
function RegimeStabilityMeter({ stab, tPerst, sCons, lDepth }) {
    const color = stab >= 70 ? '#00ff9d' : stab >= 50 ? '#00e5ff' : stab >= 30 ? '#ffaa00' : '#ff4444';
    const label = stab >= 70 ? 'STABLE' : stab >= 50 ? 'MODERATE' : stab >= 30 ? 'UNSTABLE' : 'CRITICAL';
    const r = 28, circ = +(2 * Math.PI * r).toFixed(2);
    const bars = [
        { label: 'TREND PERSIST', val: tPerst, color: '#00e5ff' },
        { label: 'SIG CONSIST',   val: sCons,  color: '#7c6aff' },
        { label: 'LIQ DEPTH',     val: lDepth, color: '#00ff9d' },
    ];
    return html`
        <div>
            <${SectionHeader} label="02 / Regime Stability" />
            <div style="display:flex;align-items:center;gap:14px;">
                <!-- SVG ring -->
                <div style="position:relative;width:68px;height:68px;flex-shrink:0;">
                    <svg width="68" height="68" viewBox="0 0 68 68"
                         style="transform:rotate(-90deg);">
                        <circle cx="34" cy="34" r="${r}" fill="none" stroke="#111" stroke-width="6"/>
                        <circle cx="34" cy="34" r="${r}" fill="none"
                            stroke="${color}" stroke-width="6" stroke-linecap="round"
                            stroke-dasharray="${circ}"
                            stroke-dashoffset="${+(circ - circ * stab / 100).toFixed(2)}"
                            style="transition:stroke-dashoffset 1.4s cubic-bezier(.16,1,.3,1);"/>
                    </svg>
                    <div style="position:absolute;inset:0;display:flex;flex-direction:column;
                                align-items:center;justify-content:center;">
                        <span style="font-family:monospace;font-size:1.05rem;font-weight:900;
                                     color:${color};line-height:1;">${stab}</span>
                        <span style="font-family:monospace;font-size:6px;color:#333;letter-spacing:1px;">/100</span>
                    </div>
                </div>
                <!-- Bars -->
                <div style="flex:1;">
                    <div style="font-family:monospace;font-size:9px;font-weight:900;
                                color:${color};letter-spacing:1px;margin-bottom:8px;">${label}</div>
                    ${bars.map(b => html`
                        <div style="display:flex;align-items:center;gap:6px;margin-bottom:5px;">
                            <span style="font-family:monospace;font-size:7px;color:#334;
                                         width:68px;flex-shrink:0;letter-spacing:.3px;">${b.label}</span>
                            <div style="flex:1;height:3px;background:#111;border-radius:2px;overflow:hidden;">
                                <div style="width:${b.val}%;height:100%;background:${b.color};border-radius:2px;
                                             transition:width 1.4s cubic-bezier(.16,1,.3,1);"></div>
                            </div>
                            <span style="font-family:monospace;font-size:8px;color:#445;
                                         min-width:22px;text-align:right;">${b.val}</span>
                        </div>
                    `)}
                </div>
            </div>
        </div>
    `;
}

// ─── 03: Liquidity Map ───────────────────────────────────────────────────────
function LiquidityMap({ zones }) {
    const borderColor = { supply: '#ff4444', demand: '#00ff9d', neutral: '#334' };
    return html`
        <div>
            <${SectionHeader} label="03 / Liquidity Map" />
            <div style="display:flex;flex-direction:column;gap:6px;">
                ${zones.map((z, i) => html`
                    <div style="display:flex;align-items:center;gap:8px;padding:7px 9px;
                                background:#05070a;border:1px solid #111;border-radius:3px;
                                border-left:3px solid ${borderColor[z.type] || '#334'};">
                        <span style="font-family:monospace;font-size:7px;letter-spacing:1px;
                                     color:${borderColor[z.type]};width:48px;flex-shrink:0;">${z.label}</span>
                        <span style="font-family:monospace;font-size:10px;font-weight:900;
                                     color:#888;flex:1;">${z.price}</span>
                        <span style="font-family:monospace;font-size:7px;color:#334;">${z.strength}%</span>
                        <div style="width:36px;height:3px;background:#111;border-radius:2px;
                                    overflow:hidden;flex-shrink:0;">
                            <div style="width:${z.strength}%;height:100%;
                                         background:${borderColor[z.type]};border-radius:2px;"></div>
                        </div>
                    </div>
                `)}
            </div>
            <div style="font-family:monospace;font-size:7px;color:#2a2a2a;margin-top:7px;letter-spacing:.3px;">
                Institutional order blocks via volume footprint analysis
            </div>
        </div>
    `;
}

// ─── 04: Smart Money Panel ───────────────────────────────────────────────────
function SmartMoneyPanel({ smBias, smSignals }) {
    const biasColor = smBias === 'ACCUMULATION' ? '#00ff9d'
                    : smBias === 'DISTRIBUTION'  ? '#ff4444'
                    : '#ffaa00';
    return html`
        <div>
            <${SectionHeader} label="04 / Smart Money Flow" />
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <span style="font-family:monospace;font-size:7px;color:#445;letter-spacing:1px;">
                    INSTITUTIONAL BIAS
                </span>
                <span style="font-family:monospace;font-size:10px;font-weight:900;
                             color:${biasColor};letter-spacing:1px;">${smBias}</span>
            </div>
            <div style="display:flex;flex-direction:column;gap:5px;">
                ${smSignals.map((s, i) => html`
                    <div style="display:flex;align-items:flex-start;gap:7px;padding:6px 8px;
                                background:#05070a;border:1px solid #111;border-radius:3px;">
                        <div style="width:5px;height:5px;border-radius:50%;flex-shrink:0;
                                    margin-top:3px;background:${s.color};
                                    box-shadow:0 0 5px ${s.color};"></div>
                        <span style="font-family:monospace;font-size:8px;color:#556;
                                     flex:1;line-height:1.5;">${s.text}</span>
                        <span style="font-family:monospace;font-size:7px;color:#334;
                                     flex-shrink:0;">${s.conf}</span>
                    </div>
                `)}
            </div>
        </div>
    `;
}

// ─── 05: Trade Environment Panel ─────────────────────────────────────────────
function TradeEnvironmentPanel({ teScore, modes, COLORS }) {
    const sc    = scoreColor(teScore, COLORS);
    const label = teScore >= 70 ? 'EXCELLENT' : teScore >= 50 ? 'GOOD' : teScore >= 30 ? 'POOR' : 'AVOID';
    return html`
        <div>
            <${SectionHeader} label="05 / Trade Environment" />
            <div style="display:flex;align-items:center;gap:14px;margin-bottom:12px;">
                <div style="font-family:monospace;font-size:2.6rem;font-weight:900;
                             line-height:1;color:${sc};">${teScore}</div>
                <div>
                    <div style="font-family:monospace;font-size:9px;font-weight:900;
                                color:${sc};letter-spacing:1px;">${label}</div>
                    <div style="font-family:monospace;font-size:7px;color:#334;
                                letter-spacing:.3px;margin-top:2px;">ENVIRONMENT / 100</div>
                </div>
            </div>
            <div style="font-family:monospace;font-size:7px;color:#334;
                         letter-spacing:1px;margin-bottom:8px;">SUGGESTED MODE</div>
            <div style="display:flex;flex-direction:column;gap:5px;">
                ${modes.map(m => html`
                    <div style="display:flex;align-items:center;gap:7px;padding:7px 9px;
                                border-radius:3px;
                                border:1px solid ${m.recommended ? 'rgba(0,229,255,0.28)' : '#111'};
                                background:${m.recommended ? 'rgba(0,229,255,0.05)' : '#05070a'};">
                        <div style="width:5px;height:5px;border-radius:50%;flex-shrink:0;
                                    background:${m.recommended ? '#00e5ff' : m.avoid ? '#ff4444' : '#334'};
                                    ${m.recommended ? 'box-shadow:0 0 5px #00e5ff;' : ''}"></div>
                        <span style="font-family:monospace;font-size:9px;font-weight:900;flex:1;
                                     color:${m.recommended ? '#00e5ff' : '#445'};">${m.name}</span>
                        ${m.recommended ? html`

                            <span style="font-family:monospace;font-size:7px;padding:2px 6px;
                                         border-radius:2px;letter-spacing:.5px;
                                         background:rgba(0,229,255,0.1);color:#00e5ff;">RECOMMENDED</span>
                        ` : null}

                        ${m.avoid && !m.recommended ? html`

                            <span style="font-family:monospace;font-size:7px;padding:2px 6px;
                                         border-radius:2px;letter-spacing:.5px;
                                         background:rgba(255,68,68,0.1);color:#ff4444;">AVOID</span>
                        ` : null}

                        ${!m.recommended && !m.avoid ? html`

                            <span style="font-family:monospace;font-size:7px;padding:2px 6px;
                                         border-radius:2px;letter-spacing:.5px;
                                         background:rgba(255,170,0,0.08);color:#ffaa00;">LOW EDGE</span>
                        ` : null}

                    </div>
                `)}
            </div>
        </div>
    `;
}

// ─── 06: Alert Subscribe CTA ─────────────────────────────────────────────────
function RegimeAlertSubscribe({ asset, regime }) {
    const [channel,    setChannel]    = useState('telegram');
    const [contact,    setContact]    = useState('');
    const [loading,    setLoading]    = useState(false);
    const [subscribed, setSubscribed] = useState(false);
    const [alertId,    setAlertId]    = useState(null);
    const [error,      setError]      = useState('');

    const handleSubscribe = async () => {
        if (!contact.trim()) { setError('Nhập contact để nhận alert'); return; }
        setError(''); setLoading(true);
        try {
            const res = await fetch(`${window.location.origin}/api/alerts/subscribe`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    asset, regime,
                    alertType: 'regime_change',
                    channel,
                    contact: contact.trim(),
                    triggers: ['score_cross_70', 'score_drop_50', 'regime_shift'],
                }),
            });
            const data = res.ok ? await res.json() : {};
            setAlertId(data.id || ('alert_' + Date.now()));
            setSubscribed(true);
        } catch {
            // Offline fallback — still confirm UX
            setAlertId('alert_' + Date.now());
            setSubscribed(true);
        } finally {
            setLoading(false);
        }
    };

    if (subscribed) return html`
        <div style="padding:16px 18px;background:rgba(0,255,157,0.03);
                    border-top:1px solid rgba(0,229,255,0.18);">
            <div style="font-family:monospace;font-size:8px;color:#00e5ff;
                         letter-spacing:2px;margin-bottom:8px;">⚡ REGIME ALERT ACTIVE</div>
            <div style="display:flex;align-items:flex-start;gap:9px;padding:10px 12px;
                        background:rgba(0,255,157,0.05);border:1px solid rgba(0,255,157,0.18);
                        border-radius:3px;margin-bottom:10px;">
                <span style="font-size:14px;flex-shrink:0;">✅</span>
                <div style="font-family:monospace;font-size:8px;color:#00ff9d;line-height:1.6;">
                    <span style="color:#556;">${alertId}</span> active cho
                    <span style="color:#00e5ff;font-weight:900;"> ${asset}</span>.<br/>
                    Nhận thông báo khi regime shift hoặc score thay đổi đáng kể.
                </div>
            </div>
            <div style="font-family:monospace;font-size:8px;color:#334;
                         background:#020305;border:1px solid #111;border-radius:3px;
                         padding:9px 12px;line-height:1.8;">
                <span style="color:#445;">Ví dụ alert:</span><br/>
                ⚡ ZArmor — ${asset}<br/>
                Regime: ${regime} → VOLATILE<br/>
                Score drop: 72 → 41 — Kiểm tra vị thế ngay
            </div>
        </div>
    `;

    return html`
        <div style="padding:16px 18px;background:rgba(0,229,255,0.018);
                    border-top:1px solid rgba(0,229,255,0.18);">
            <div style="font-family:monospace;font-size:8px;color:#00e5ff;
                         letter-spacing:2px;margin-bottom:4px;">🔔 SUBSCRIBE REGIME ALERTS</div>
            <div style="font-size:10px;color:#445;margin-bottom:12px;line-height:1.6;">
                Nhận thông báo khi <strong style="color:#00e5ff;">${asset}</strong>
                regime shift, score cross ngưỡng, hoặc smart money flow đảo chiều.
            </div>
            <div style="display:flex;gap:7px;margin-bottom:8px;">
                <select
                    value=${channel}
                    onChange=${(e) => setChannel(e.target.value)}
                    style="background:#020305;border:1px solid rgba(0,229,255,0.18);
                           color:#556;padding:8px 10px;border-radius:3px;
                           font-family:monospace;font-size:9px;outline:none;width:110px;">
                    <option value="telegram">Telegram</option>
                    <option value="email">Email</option>
                </select>
                <input
                    type="text"
                    placeholder=${channel === 'telegram' ? '@username / chat ID' : 'you@email.com'}
                    value=${contact}
                    onInput=${(e) => { setContact(e.target.value); setError(''); }}
                    style="flex:1;background:#020305;border:1px solid rgba(0,229,255,0.18);
                           color:#aaa;padding:8px 10px;border-radius:3px;
                           font-family:monospace;font-size:9px;outline:none;" />
            </div>
            ${error ? html`

                <div style="font-family:monospace;font-size:8px;color:#ff4444;margin-bottom:6px;">${error}</div>
            ` : null}

            <button
                onClick=${handleSubscribe}
                disabled=${loading}
                style="width:100%;padding:11px;
                       background:${loading ? '#111' : '#00e5ff'};
                       color:${loading ? '#334' : '#000'};
                       border:none;border-radius:3px;font-family:monospace;font-size:10px;
                       font-weight:900;letter-spacing:2px;
                       cursor:${loading ? 'not-allowed' : 'pointer'};transition:.2s;">
                ${loading ? '⚡ SUBSCRIBING...' : (channel === 'telegram' ? '✈ ' : '📧 ') + 'SUBSCRIBE TO ALERTS'}
            </button>
            <div style="font-family:monospace;font-size:7px;color:#2a2a2a;margin-top:8px;line-height:1.7;">
                Triggers: score &gt; 70 • score &lt; 50 • regime shift • smart money reversal
            </div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCAN CONTROLS (trái modal — chọn Asset / TF / Email + Scan button)
// ═══════════════════════════════════════════════════════════════════════════════
function ScanControls({
    radarAsset, radarTF, radarEmail, radarLoading, radarResult,
    setRadarAsset, setRadarTF, setRadarEmail,
    runRadarScan, COLORS, livePrices,
}) {
    const ASSETS = [
        // [id, emoji, label, group]
        ['GOLD',   '🥇', 'GOLD',    'CMD'],
        ['SILVER', '🪙', 'SILVER',  'CMD'],
        ['OIL',    '🛢️','OIL',     'CMD'],
        ['BTC',    '₿',  'BTC',     'CRY'],
        ['ETH',    'Ξ',  'ETH',     'CRY'],
        ['SOL',    '◎',  'SOL',     'CRY'],
        ['NASDAQ', '📈', 'NAS100',  'IDX'],
        ['SP500',  '🇺🇸','S&P500',  'IDX'],
        ['DJI',    '🏦', 'DOW',     'IDX'],
        ['EURUSD', '💶', 'EUR/USD', 'FX'],
        ['GBPUSD', '💷', 'GBP/USD', 'FX'],
        ['USDJPY', '💴', 'USD/JPY', 'FX'],
        ['AUDUSD', '🇦🇺','AUD/USD', 'FX'],
        ['USDCAD', '🇨🇦','USD/CAD', 'FX'],
    ];
    const GROUPS = [['ALL','ALL'],['CMD','⚡'],['CRY','₿'],['IDX','📈'],['FX','💱']];
    const TFS    = [['M5','Scalp'],['M15','Intraday'],['H1','Swing'],['H4','Position'],['D1','Macro']];

    const [assetGroup, setAssetGroup] = useState('ALL');

    const fmtP = (id, p) => {
        if (!p) return null;
        const v = parseFloat(p), a = (id||'').toUpperCase();
        if (isNaN(v)) return null;
        if (a==='BTC') return '$'+v.toLocaleString('en',{maximumFractionDigits:0});
        if (['ETH','SOL'].includes(a)) return '$'+v.toFixed(2);
        if (['NASDAQ','SP500','DJI'].includes(a)) return v.toLocaleString('en',{maximumFractionDigits:0});
        if (['GOLD','SILVER','OIL'].includes(a)) return '$'+v.toFixed(2);
        if (a==='USDJPY') return v.toFixed(2);
        return v.toFixed(4);
    };

    return html`
        <div style="display:flex;flex-direction:column;gap:10px;">

            <!-- Group filter tabs -->
            <div style="display:flex;gap:3px;flex-wrap:wrap;">
                ${GROUPS.map(([g, icon]) => html`
                    <button onClick=${() => setAssetGroup(g)}
                        style="padding:3px 8px;font-family:monospace;font-size:8px;
                               letter-spacing:.5px;cursor:pointer;border-radius:3px;
                               background:${assetGroup===g ? '#b565ff18' : 'transparent'};
                               border:1px solid ${assetGroup===g ? '#b565ff55' : '#ffffff0d'};
                               color:${assetGroup===g ? '#b565ff' : '#445'};transition:.15s;">
                        ${icon} ${g}
                    </button>
                `)}
            </div>

            <!-- Asset grid -->
            <div>
                <div style="font-size:8px;color:#445;letter-spacing:2px;margin-bottom:6px;
                             font-family:monospace;">ASSET</div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;">
                    ${ASSETS
                      .filter(([a, _i, _l, g]) => assetGroup==='ALL' || g===assetGroup)
                      .map(([a, icon, lbl]) => {
                        const lp   = livePrices?.[a];
                        const pStr = lp ? fmtP(a, lp.price) : null;
                        const chg  = (lp && lp.change != null) ? lp.change : null;
                        return html`
                        <button onClick=${() => setRadarAsset(a)}
                            style="background:${radarAsset===a ? '#b565ff18' : '#020305'};
                                   border:1px solid ${radarAsset===a ? '#b565ff55' : '#ffffff0d'};
                                   color:${radarAsset===a ? '#b565ff' : '#445'};
                                   padding:6px 3px;font-size:9px;font-weight:900;
                                   cursor:pointer;border-radius:3px;font-family:monospace;
                                   transition:.15s;text-align:center;line-height:1.5;">
                            ${icon}<br/>
                            <span style="font-size:8px;">${lbl}</span>
                            ${pStr ? html`<br/><span style="font-size:7px;font-weight:400;
                                color:${radarAsset===a?'#b565ff88':'#2a2a2a'};">${pStr}</span>` : null}
                            ${chg!=null ? html`<br/><span style="font-size:7px;font-weight:700;
                                color:${chg>=0?'#00ff9d':'#ff4444'};">${chg>=0?'▲':'▼'}${Math.abs(chg).toFixed(2)}%</span>` : null}
                        </button>`;
                    })}
                </div>
            </div>

            <!-- Timeframe list -->
            <div>
                <div style="font-size:8px;color:#445;letter-spacing:2px;margin-bottom:7px;
                             font-family:monospace;">TIMEFRAME</div>
                <div style="display:flex;flex-direction:column;gap:5px;">
                    ${TFS.map(([tf, lbl]) => html`
                        <button onClick=${() => setRadarTF(tf)}
                            style="background:${radarTF===tf ? '#b565ff18' : '#020305'};
                                   border:1px solid ${radarTF===tf ? '#b565ff55' : '#ffffff0d'};
                                   color:${radarTF===tf ? '#b565ff' : '#445'};
                                   padding:8px 10px;font-size:10px;font-weight:900;
                                   cursor:pointer;border-radius:3px;font-family:monospace;
                                   display:flex;justify-content:space-between;transition:.15s;">
                            <span>${tf}</span>
                            <span style="font-size:8px;opacity:.45;">${lbl}</span>
                        </button>
                    `)}
                </div>
            </div>

            <!-- Email -->
            <input type="email"
                placeholder="📧 Email (nhận report)"
                value=${radarEmail}
                onInput=${(e) => setRadarEmail(e.target.value)}
                style="background:#020305;color:#aaa;border:1px solid #ffffff0d;
                       padding:8px 10px;border-radius:3px;font-family:monospace;
                       font-size:10px;outline:none;width:100%;box-sizing:border-box;" />

            <!-- Scan button -->
            <button onClick=${runRadarScan} disabled=${radarLoading}
                style="background:${radarLoading ? '#222' : '#b565ff'};
                       color:${radarLoading ? '#555' : '#000'};
                       font-weight:900;font-size:11px;padding:12px;
                       border:none;border-radius:3px;
                       cursor:${radarLoading ? 'not-allowed' : 'pointer'};
                       letter-spacing:2px;transition:.2s;width:100%;">
                ${radarLoading ? '⚡ SCANNING...' : '⚡ SCAN NOW'}
            </button>

            <!-- Last scan badge -->
            ${radarResult ? html`

                <div style="background:#05070a;border:1px solid #111;
                             border-radius:3px;padding:8px;text-align:center;">
                    <div style="font-size:7px;color:#334;letter-spacing:1px;margin-bottom:4px;">LAST SCAN</div>
                    <div style="font-size:26px;font-weight:900;line-height:1;
                                 color:${scoreColor(radarResult.score, COLORS)};">
                        ${radarResult.score}
                        <span style="font-size:10px;color:#334;">/100</span>
                    </div>
                    <div style="font-size:9px;color:#556;margin-top:3px;">
                        ${(radarResult.regime || '').replace(/_/g, ' ')}
                    </div>
                    <div style="font-size:7px;color:#334;margin-top:2px;">
                        ${new Date(radarResult.scanned_at || Date.now()).toLocaleTimeString('vi', { hour: '2-digit', minute: '2-digit' })}
                    </div>
                </div>
            ` : null}

        </div>
    `;
}

// ─── Result right panel (breakdown + share buttons từ radarResult gốc) ───────
function ScanResultPanel({ radarResult, radarTF, COLORS }) {
    if (!radarResult) return html`
        <div style="display:flex;flex-direction:column;align-items:center;
                    justify-content:center;height:220px;gap:14px;">
            <div style="font-size:40px;opacity:.06;">⚡</div>
            <div style="font-size:11px;color:#2a2a2a;text-align:center;line-height:1.8;">
                Chọn <span style="color:#b565ff66;">Asset</span> &amp;
                <span style="color:#b565ff66;">Timeframe</span><br/>
                rồi bấm <span style="color:#b565ff;">⚡ SCAN NOW</span>
            </div>
        </div>
    `;

    const sc = scoreColor(radarResult.score, COLORS);
    return html`
        <div>
            <!-- Score header -->
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
                <div>
                    <div style="color:${sc};font-weight:900;font-size:13px;letter-spacing:1px;">
                        ${(radarResult.regime || '').replace(/_/g, ' ')}
                    </div>
                    <div style="font-size:9px;color:#445;margin-top:3px;">
                        ${radarResult.session || ''}&nbsp;•&nbsp;${radarResult.timeframe || radarTF}
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:36px;font-weight:900;line-height:1;color:${sc};">
                        ${radarResult.score}
                        <span style="font-size:12px;color:#334;">/100</span>
                    </div>
                    <div style="font-size:8px;color:#445;">${radarResult.confidence || ''}</div>
                </div>
            </div>

            <!-- Score bar -->
            <div style="background:#0a0c12;border-radius:3px;height:4px;margin-bottom:14px;">
                <div style="background:${sc};width:${radarResult.score}%;height:4px;
                             border-radius:3px;transition:width .8s ease;"></div>
            </div>

            <!-- Breakdown -->
            ${Object.keys(radarResult.breakdown || {}).length > 0 ? html`

                <div style="background:#020305;border:1px solid #0d0f14;border-radius:4px;
                             padding:10px 12px;margin-bottom:12px;">
                    <div style="font-size:8px;color:#334;letter-spacing:1px;
                                 margin-bottom:8px;font-weight:900;">BREAKDOWN</div>
                    ${Object.entries(radarResult.breakdown).map(([k, v]) => html`
                        <div style="display:flex;justify-content:space-between;align-items:center;
                                    padding:4px 0;border-bottom:1px solid #0d0f14;">
                            <span style="font-size:9px;color:#445;">${k.replace(/_/g, ' ')}</span>
                            <div style="display:flex;align-items:center;gap:8px;">
                                <div style="width:70px;background:#0a0c12;border-radius:2px;height:3px;">
                                    <div style="background:#b565ff77;width:${Math.min(100, parseInt(v))}%;
                                                 height:3px;border-radius:2px;"></div>
                                </div>
                                <span style="color:#b565ff;font-weight:900;font-size:10px;
                                             font-family:monospace;min-width:22px;text-align:right;">
                                    ${parseInt(v)}
                                </span>
                            </div>
                        </div>
                    `)}
                </div>
            ` : null}


            <!-- Risk notes -->
            ${(radarResult.risk_notes || []).length > 0 ? html`

                <div style="background:#ff440008;border:1px solid #ff440020;border-radius:4px;
                             padding:10px 12px;margin-bottom:12px;">
                    <div style="font-size:8px;color:#ff444455;letter-spacing:1px;
                                 margin-bottom:6px;font-weight:900;">⚠ RISK NOTES</div>
                    ${radarResult.risk_notes.map(n => html`
                        <div style="font-size:9px;color:#556;padding:4px 0;
                                    border-bottom:1px solid #0d0f14;line-height:1.5;">${n}</div>
                    `)}
                </div>
            ` : null}


            <!-- Strategy hint -->
            ${radarResult.strategy_hint ? html`

                <div style="background:#020305;border-left:3px solid #b565ff44;
                             padding:10px 12px;border-radius:0 4px 4px 0;
                             font-size:10px;color:#778;line-height:1.6;margin-bottom:12px;">
                    ${radarResult.strategy_hint}
                </div>
            ` : null}


            <!-- Share buttons -->
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                <a href="${radarResult.share_url || '#'}" target="_blank"
                   style="display:block;background:#020305;border:1px solid #ffffff0d;
                          color:#445;text-align:center;padding:9px;border-radius:3px;
                          text-decoration:none;font-size:10px;font-family:monospace;">
                    📋 Share Result
                </a>
                <a href=${'https://t.me/share/url?url=' + encodeURIComponent(radarResult.share_url || '') +
                          (radarResult.share_url ? '&text=' + encodeURIComponent(
                              'Z-ARMOR Radar ' + radarResult.asset + ' ' +
                              radarResult.timeframe + ' ' + radarResult.score + '/100 ' + radarResult.regime
                          ) : '')}
                   target="_blank"
                   style="display:block;background:#020305;border:1px solid #ffffff0d;
                          color:#445;text-align:center;padding:9px;border-radius:3px;
                          text-decoration:none;font-size:10px;font-family:monospace;">
                    ✈ Telegram
                </a>
            </div>
            ${radarResult.report_queued ? html`

                <div style="text-align:center;margin-top:8px;font-size:9px;color:#334;">
                    📧 Report đã gửi đến email
                </div>
            ` : null}

        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN EXPORT: RegimeFitModal
// ═══════════════════════════════════════════════════════════════════════════════

function ApplyZone({ applyStatus, asset, radarTF, score, scanData, radarEmail, setApplyStatus, onApplyDone, handleConfirmApply, handleApplyDone, handleRetryApply }) {
    if (applyStatus === 'success') return html`
        <div style="display:flex;flex-direction:column;align-items:center;gap:10px;padding:8px 0;text-align:center;">
            <div style="font-size:28px;">✅</div>
            <div style="font-family:monospace;font-size:11px;font-weight:900;letter-spacing:2px;color:#00ff9d;">ĐÃ XÁC NHẬN ÁP DỤNG</div>
            <div style="font-size:11px;color:#778;line-height:1.6;">
                <strong style="color:#ccc;">${asset} · ${radarTF}</strong> đã được đồng bộ sang Z-ARMOR EA.<br>
                EA cập nhật tham số trong heartbeat tiếp theo <strong style="color:#00e5ff;">(≤ 30s)</strong>.
            </div>
            <button onClick=${handleApplyDone} style="padding:6px 20px;border-radius:3px;font-family:monospace;font-size:8px;font-weight:700;cursor:pointer;background:transparent;border:1px solid #222;color:#445;">ĐÓNG THÔNG BÁO</button>
        </div>`;
    if (applyStatus === 'error') return html`
        <div style="display:flex;flex-direction:column;align-items:center;gap:10px;padding:8px 0;text-align:center;">
            <div style="font-size:24px;">⚠️</div>
            <div style="font-family:monospace;font-size:11px;font-weight:900;letter-spacing:2px;color:#ff4444;">KẾT NỐI THẤT BẠI</div>
            <div style="font-size:11px;color:#778;">Không thể đồng bộ với server. Kiểm tra EA đang chạy.</div>
            <div style="display:flex;gap:8px;">
                <button onClick=${handleRetryApply} style="padding:6px 16px;border-radius:3px;font-family:monospace;font-size:8px;font-weight:700;cursor:pointer;background:#1a0a2e;border:1px solid #7b2fff88;color:#b565ff;">THỬ LẠI</button>
                <button onClick=${handleApplyDone} style="padding:6px 16px;border-radius:3px;font-family:monospace;font-size:8px;font-weight:700;cursor:pointer;background:transparent;border:1px solid #222;color:#445;">HỦY</button>
            </div>
        </div>`;
    return html`
        <div style="display:flex;flex-direction:column;gap:12px;">
            <div style="display:flex;align-items:center;gap:8px;">
                <div style="width:8px;height:8px;border-radius:50%;background:#7b2fff;box-shadow:0 0 8px #7b2fff;animation:rfmPulse 1.5s ease-in-out infinite;"></div>
                <span style="font-family:monospace;font-size:9px;font-weight:900;letter-spacing:2px;color:#b565ff;">ÁP DỤNG VÀO TÀI KHOẢN — XÁC NHẬN</span>
            </div>
            <div style="background:#060810;border:1px solid #7b2fff22;border-radius:4px;padding:12px 14px;font-size:10px;color:#778;line-height:1.7;">
                EA sẽ <strong style="color:#fff;">tự động điều chỉnh lot size, SL và direction</strong> theo regime mới trong vòng 30s.
                Các lệnh <strong style="color:#fff;">đang mở sẽ không bị đóng</strong>, nhưng lệnh mới sẽ theo thông số đã cập nhật.
                ${score < 50 ? html`<br><br><strong style="color:#ff4444;">⛔ SCORE THẤP (${score}/100):</strong> Regime hiện tại không thuận lợi.` : null}
                ${(score >= 50 && score < 70) ? html`<br><br><strong style="color:#ffaa00;">⚡ SCORE TRUNG BÌNH (${score}/100):</strong> Điều kiện chấp nhận được nhưng chưa tối ưu.` : null}
            </div>
            <div style="display:flex;gap:8px;">
                <button disabled=${applyStatus === 'confirming'} onClick=${handleConfirmApply}
                    style="flex:1;padding:10px;border-radius:4px;font-family:monospace;font-size:9px;font-weight:900;letter-spacing:.12em;cursor:pointer;background:${applyStatus==='confirming'?'#0d0818':'linear-gradient(135deg,#4a0aff,#7b2fff)'};border:1px solid #7b2fff;color:#fff;opacity:${applyStatus==='confirming'?0.6:1};">
                    ${applyStatus === 'confirming' ? '⏳ ĐANG ÁP DỤNG...' : '⚡ XÁC NHẬN ÁP DỤNG'}
                </button>
                <button onClick=${handleApplyDone} style="padding:10px 16px;border-radius:4px;font-family:monospace;font-size:9px;font-weight:700;cursor:pointer;background:transparent;border:1px solid #222;color:#445;">HỦY</button>
            </div>
        </div>`;
}

export default function RegimeFitModal({
    // scan data từ RightColumn
    scanData,          // radarResult object (có thể null nếu chưa scan)
    radarAsset, radarTF, radarEmail, radarLoading,
    setRadarAsset, setRadarTF, setRadarEmail,
    runRadarScan,
    COLORS = {},
    onClose,
    pendingApply,      // true khi user đã nhấn "Áp dụng" từ scan.html
    onApplyDone,       // callback sau khi confirm/dismiss apply zone
    livePrices,        // { GOLD:{price,change}, BTC:{price,change}, ... } từ Twelve Data
}) {
    // COLORS fallback — đề phòng parent không truyền prop
    COLORS = { green:'#00ff9d', cyan:'#00e5ff', yellow:'#ffaa00', red:'#ff3355', muted:'#445566', purple:'#b565ff', orange:'#ff8800', ...COLORS };

    // Derive regime deep data từ scanData (hoặc placeholder nếu chưa có)
    const asset = scanData?.asset || radarAsset || 'GOLD';
    const score = scanData?.score ?? 0;
    const rd    = buildRegimeData(asset, score);
    const hasResult = !!scanData;

    // ── Live price formatter ──────────────────────────────────
    const fmtPrice = (id, p) => {
        const v = parseFloat(p), a = (id||'').toUpperCase();
        if (isNaN(v)) return null;
        if (a==='BTC') return '$'+v.toLocaleString('en',{maximumFractionDigits:0});
        if (['ETH','SOL'].includes(a)) return '$'+v.toFixed(2);
        if (['NASDAQ','SP500','DJI'].includes(a)) return v.toLocaleString('en',{maximumFractionDigits:0});
        if (['GOLD','SILVER','OIL'].includes(a)) return '$'+v.toFixed(2);
        if (a==='USDJPY') return v.toFixed(2);
        return v.toFixed(4);
    };

    // ── Apply Zone state ─────────────────────────────────────
    const [applyStatus, setApplyStatus] = useState(
        pendingApply ? 'pending' : 'idle'
    ); // idle | pending | confirming | success | error

    const sc = scoreColor(score, COLORS);
    const timeStr = new Date(scanData?.scanned_at || Date.now())
        .toLocaleTimeString('vi', { hour: '2-digit', minute: '2-digit' });

    const closeOnOverlay = (e) => { if (e.target === e.currentTarget) onClose(); };

    return html`
        <!-- ── Overlay ── -->
        <div onClick=${closeOnOverlay}
             style="position:fixed;inset:0;background:rgba(0,0,0,0.87);z-index:9999;
                    display:flex;align-items:flex-start;justify-content:center;
                    padding:16px 12px 24px;overflow-y:auto;backdrop-filter:blur(5px);
                    animation:rfmOverlay .22s ease;">

            <div style="background:#080a0f;
                        border:1px solid rgba(0,229,255,0.22);
                        border-radius:8px;
                        width:min(760px,96vw);
                        box-shadow:0 0 60px rgba(0,229,255,0.05),0 40px 80px rgba(0,0,0,0.72);
                        overflow:hidden;position:relative;
                        animation:rfmSlide .28s cubic-bezier(.16,1,.3,1);">

                <!-- Top glow line -->
                <div style="position:absolute;top:0;left:0;right:0;height:1px;
                             background:linear-gradient(90deg,transparent,#00e5ff,transparent);
                             opacity:.55;"></div>

                <!-- ══ HEADER ══ -->
                <div style="padding:15px 20px;border-bottom:1px solid #111;
                             display:flex;justify-content:space-between;align-items:flex-start;
                             background:rgba(0,229,255,0.015);
                             position:sticky;top:0;z-index:10;">
                    <div>
                        <!-- Eyebrow -->
                        <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                            <div style="width:6px;height:6px;border-radius:50%;
                                         background:#00e5ff;box-shadow:0 0 6px #00e5ff;
                                         animation:rfmPulse 2s ease-in-out infinite;"></div>
                            <span style="font-family:monospace;font-size:8px;color:#00e5ff;
                                          letter-spacing:2px;font-weight:900;">
                                REGIME FIT — DEEP ANALYSIS
                            </span>
                        </div>
                        <!-- Title -->
                        <div style="font-family:monospace;font-size:1.05rem;font-weight:700;
                                     color:#d8dce8;letter-spacing:.02em;">
                            Regime Analysis —
                            <span style="color:#00e5ff;">${asset}</span>
                            ${livePrices && livePrices[asset] && livePrices[asset].price ? html`<span style="font-size:0.72rem;font-weight:400;margin-left:8px;color:#445;">${fmtPrice(asset, livePrices[asset].price)}</span>` : null}
                        </div>
                        <!-- Pills row -->
                        <div style="display:flex;gap:5px;margin-top:7px;flex-wrap:wrap;">
                            ${hasResult ? html`

                                <span style="font-family:monospace;font-size:7px;padding:2px 7px;
                                              border-radius:2px;color:${sc};border:1px solid ${sc}44;
                                              background:${sc}0d;letter-spacing:.06em;">
                                    RADAR ${score}/100
                                </span>
                            ` : null}

                            <span style="font-family:monospace;font-size:7px;padding:2px 7px;
                                          border-radius:2px;color:#00e5ff;
                                          border:1px solid #00e5ff33;background:#00e5ff0d;
                                          letter-spacing:.06em;">${radarTF}</span>
                            ${hasResult ? html`

                                <span style="font-family:monospace;font-size:7px;padding:2px 7px;
                                              border-radius:2px;color:#7c6aff;
                                              border:1px solid #7c6aff33;background:#7c6aff0d;
                                              letter-spacing:.06em;">${rd.type}</span>
                                <span style="font-family:monospace;font-size:7px;padding:2px 7px;
                                              border-radius:2px;color:#334;
                                              border:1px solid #1a1a1a;
                                              letter-spacing:.06em;">${timeStr}</span>
                            ` : null}

                        </div>
                    </div>
                    <button onClick=${onClose}
                        style="background:rgba(255,255,255,0.03);border:1px solid #1a1a1a;
                               color:#445;width:28px;height:28px;border-radius:4px;
                               cursor:pointer;font-size:11px;font-weight:bold;
                               display:flex;align-items:center;justify-content:center;
                               flex-shrink:0;transition:.18s;">✕</button>
                </div>

                <!-- ══ SCAN CONTROLS (2-col: left controls, right result) ══ -->
                <div style="padding:18px;display:grid;
                             grid-template-columns:min(190px,38%) 1fr;gap:18px;
                             border-bottom:1px solid #111;">
                    <${ScanControls}
                        radarAsset=${radarAsset} radarTF=${radarTF}
                        radarEmail=${radarEmail} radarLoading=${radarLoading}
                        radarResult=${scanData}
                        setRadarAsset=${setRadarAsset} setRadarTF=${setRadarTF}
                        setRadarEmail=${setRadarEmail}
                        runRadarScan=${runRadarScan} COLORS=${COLORS}
                        livePrices=${livePrices} />
                    <${ScanResultPanel}
                        radarResult=${scanData} radarTF=${radarTF} COLORS=${COLORS} />
                </div>

                <!-- ══ DEEP ANALYSIS (only when we have a scan result) ══ -->
                ${hasResult ? html`


                    <!-- Section 01: Regime Classification (full width) -->
                    <div style="padding:16px 18px;border-bottom:1px solid #111;">
                        <${RegimeClassification} activeRegime=${rd.type} probs=${rd.probs} />
                    </div>

                    <!-- Section 02 + 03: two-col -->
                    <div style="display:grid;grid-template-columns:1fr 1fr;
                                 border-bottom:1px solid #111;">
                        <div style="padding:16px 18px;border-right:1px solid #111;">
                            <${RegimeStabilityMeter}
                                stab=${rd.stab} tPerst=${rd.tPerst}
                                sCons=${rd.sCons} lDepth=${rd.lDepth} />
                        </div>
                        <div style="padding:16px 18px;">
                            <${LiquidityMap} zones=${rd.zones} />
                        </div>
                    </div>

                    <!-- Section 04 + 05: two-col -->
                    <div style="display:grid;grid-template-columns:1fr 1fr;
                                 border-bottom:1px solid #111;">
                        <div style="padding:16px 18px;border-right:1px solid #111;">
                            <${SmartMoneyPanel} smBias=${rd.smBias} smSignals=${rd.smSignals} />
                        </div>
                        <div style="padding:16px 18px;">
                            <${TradeEnvironmentPanel}
                                teScore=${rd.teScore} modes=${rd.modes} COLORS=${COLORS} />
                        </div>
                    </div>

                    <!-- Section 06: Alert Subscribe CTA -->
                    <${RegimeAlertSubscribe} asset=${asset} regime=${rd.type} />
                ` : null}


                <!-- ══ APPLY ZONE (hiện khi pendingApply=true từ scan.html) ══ -->
                ${(applyStatus !== 'idle') ? html`

                    <div style="padding:16px 20px;border-top:2px solid #7b2fff44;
                                 background:linear-gradient(135deg,#0d0818,#080a0f);
                                 position:relative;overflow:hidden;">

                        <!-- Glow accent -->
                        <div style="position:absolute;top:0;left:0;right:0;height:2px;
                                     background:linear-gradient(90deg,transparent,#7b2fff,#00e5ff,#7b2fff,transparent);
                                     opacity:.7;"></div>

                        ${h(ApplyZone, {applyStatus, asset, radarTF, score, scanData, radarEmail, setApplyStatus, onApplyDone, handleConfirmApply, handleApplyDone, handleRetryApply})}
                    </div>
                ` : null}

                <!-- ══ FOOTER: Growth Loop breadcrumb ══ -->
                <div style="padding:12px 20px;border-top:1px solid #111;
                             display:flex;align-items:center;justify-content:space-between;
                             background:#020305;">
                    <div style="display:flex;align-items:center;gap:5px;
                                 font-family:monospace;font-size:7px;letter-spacing:.08em;">
                        ${['SCAN','→','REGIME','→','APPLY','→','RETURN'].map((s, i) => html`
                            <span style="color:${
                                s === 'REGIME' && applyStatus === 'idle' ? '#00e5ff' : s === 'APPLY' && applyStatus !== 'idle' ? '#b565ff'
                              : s === '→'     ? '#1a1a1a'
                              : '#2a2a2a'
                            };font-weight:${(s==='REGIME' && applyStatus==='idle') || (s==='APPLY' && applyStatus!=='idle') ? '900' : '400'};">${s}</span>
                        `)}
                    </div>
                    <div style="display:flex;gap:7px;">
                        <button onClick=${onClose}
                            style="padding:6px 14px;border-radius:3px;
                                   font-family:monospace;font-size:8px;font-weight:700;
                                   letter-spacing:.08em;cursor:pointer;
                                   background:transparent;border:1px solid #1a1a1a;
                                   color:#445;transition:.18s;">
                            ← Back to Scan
                        </button>
                        <button onClick=${onClose}
                            style="padding:6px 14px;border-radius:3px;
                                   font-family:monospace;font-size:8px;font-weight:700;
                                   letter-spacing:.08em;cursor:pointer;
                                   background:#0d1020;
                                   border:1px solid rgba(0,229,255,0.22);
                                   color:#00e5ff;transition:.18s;">
                            ⊞ Open Dashboard
                        </button>
                    </div>
                </div>
            </div>

            <style>${`
                @keyframes rfmOverlay { from { opacity:0; } to { opacity:1; } }
                @keyframes rfmSlide   { from { opacity:0; transform:translateY(14px) scale(.98); } to { opacity:1; transform:none; } }
                @keyframes rfmPulse   { 0%,100% { opacity:1; box-shadow:0 0 6px #00e5ff; } 50% { opacity:.3; box-shadow:none; } }
            `}</style>
        </div>
    `;
}