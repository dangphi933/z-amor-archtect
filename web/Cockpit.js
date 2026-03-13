import { h } from 'preact';
import { useState, useEffect, useRef } from 'preact/hooks';
import htm from 'htm';
import LeftColumn from './LeftColumn.js';
import RightColumn from './RightColumn.js';
import SetupModal from './SetupModal.js';
import MacroModal from './MacroModal.js';
import AiGuardCenter from './AiGuardCenter.js';

// 💡 IMPORT CÁC MODULE LÕI TỪ AI AGENT VÀ PATCHES
import { logTrade, updateTradeResult, checkCompliance, closeSession, generateDebrief } from './aiAgentEngine.js';
import { ComplianceAlertBanner, DebriefingPanel, writeAuditLog } from './CockpitPatches.js';

const html = htm.bind(h);

// F-16: Only log in dev environment
const _isDev = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const _log = (...a) => _isDev && _log(...a);
const _warn = (...a) => _isDev && _warn(...a);


// ══════════════════════════════════════════════════════════════════
// SPRINT B — JWT AUTH HELPERS
// ══════════════════════════════════════════════════════════════════

const _getToken  = () => localStorage.getItem('za_access_token') || '';
const _getRefresh = () => localStorage.getItem('za_refresh_token') || '';
const _setTokens  = (access, refresh) => {
    localStorage.setItem('za_access_token',  access);
    localStorage.setItem('za_refresh_token', refresh);
};
const _clearTokens = () => {
    localStorage.removeItem('za_access_token');
    localStorage.removeItem('za_refresh_token');
    localStorage.removeItem('za_user');
};
const _getUser = () => {
    try { return JSON.parse(localStorage.getItem('za_user') || 'null'); } catch { return null; }
};
const _isTokenExpired = (token) => {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return Date.now() / 1000 > payload.exp - 60; // 60s buffer
    } catch { return true; }
};

// ── LoginGate Component ──────────────────────────────────────────

function LoginGate({ apiBase, onLogin }) {
    const [step, setStep]       = useState('email');
    const [email, setEmail]     = useState('');
    const [otp, setOtp]         = useState('');
    const [error, setError]     = useState('');
    const [busy, setBusy]       = useState(false);
    const [countdown, setCountdown] = useState(0);
    const otpInputRef = useRef(null);

    const C = { bg:'#05070a', panel:'#0a0f1a', cyan:'#00e5ff', green:'#00ff9d', red:'#ff2a6d', muted:'#556677', border:'#1a2030' };

    useEffect(() => {
        if (countdown <= 0) return;
        const t = setTimeout(() => setCountdown(c => c - 1), 1000);
        return () => clearTimeout(t);
    }, [countdown]);

    useEffect(() => {
        if (step === 'otp') setTimeout(() => otpInputRef.current && otpInputRef.current.focus(), 100);
    }, [step]);

    const requestOtp = async () => {
        const e = email.trim().toLowerCase();
        if (!e || !e.includes('@')) { setError('Email không hợp lệ'); return; }
        setBusy(true); setError('');
        try {
            const res  = await fetch(`${apiBase}/auth/magic-request`, {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ email: e }),
            });
            const data = await res.json();
            if (res.ok) { setStep('otp'); setCountdown(60); }
            else if (res.status === 429) setError('Quá nhiều yêu cầu. Vui lòng chờ 15 phút.');
            else setError(data.detail || 'Không thể gửi email. Thử lại sau.');
        } catch { setError('Mất kết nối server.'); }
        finally { setBusy(false); }
    };

    const verifyOtp = async () => {
        const e = email.trim().toLowerCase();
        const o = otp.trim().replace(/\s/g,'');
        if (o.length !== 6 || !/^\d+$/.test(o)) { setError('OTP phải là 6 chữ số'); return; }
        setBusy(true); setError('');
        try {
            const res  = await fetch(`${apiBase}/auth/magic-verify`, {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ email: e, otp: o }),
            });
            const data = await res.json();
            if (res.ok) {
                _setTokens(data.access_token, data.refresh_token);
                localStorage.setItem('za_user', JSON.stringify(data.user));
                onLogin(data.user);
            } else if (res.status === 429) {
                setError('Tài khoản bị khóa tạm thời. Thử lại sau 30 phút.');
            } else {
                setError(data.detail || 'Mã không đúng hoặc đã hết hạn.');
            }
        } catch { setError('Mất kết nối server.'); }
        finally { setBusy(false); }
    };

    const loginByKey = async () => {
        const lk = (document.getElementById('lk-fallback') || {}).value || '';
        if (!lk.trim()) return;
        setBusy(true); setError('');
        try {
            const res  = await fetch(`${apiBase}/auth/login`, {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ license_key: lk.trim() }),
            });
            const data = await res.json();
            if (res.ok) {
                _setTokens(data.access_token, data.refresh_token);
                localStorage.setItem('za_user', JSON.stringify(data.user));
                localStorage.setItem('zarmor_license_key', lk.trim());
                onLogin(data.user);
            } else setError(data.detail || 'License key không hợp lệ.');
        } catch { setError('Mất kết nối server.'); }
        finally { setBusy(false); }
    };

    const inp = (extra) => ({
        style: `width:100%;box-sizing:border-box;background:#050810;border:1px solid ${error ? C.red : C.border};color:#fff;padding:12px 14px;border-radius:4px;font-family:'Courier New',monospace;font-size:13px;outline:none;`,
        ...extra
    });

    // ── render helpers (no nested html``) ───────────────────────
    const emailStep = h('div', null,
        h('div', {style:'margin-bottom:16px'},
            h('label', {style:`display:block;font-size:10px;color:${C.muted};letter-spacing:1px;margin-bottom:6px;`}, 'EMAIL'),
            h('input', {
                type:'email', value:email, autofocus:true,
                placeholder:'your@email.com',
                style:`width:100%;box-sizing:border-box;background:#050810;border:1px solid ${error?C.red:C.border};color:#fff;padding:12px 14px;border-radius:4px;font-family:'Courier New',monospace;font-size:13px;outline:none;`,
                onInput: e => { setEmail(e.target.value); setError(''); },
                onKeyDown: e => { if (e.key==='Enter' && !busy) requestOtp(); },
            })
        ),
        h('button', {
            onClick: requestOtp, disabled: busy,
            style:`width:100%;background:${busy?C.border:'linear-gradient(135deg,'+C.cyan+',#0099bb)'};color:${busy?C.muted:'#000'};border:none;padding:13px;border-radius:4px;font-family:'Courier New',monospace;font-size:12px;font-weight:bold;cursor:${busy?'not-allowed':'pointer'};letter-spacing:1px;`,
        }, busy ? '⏳ ĐANG GỬI...' : '📨 GỬI MÃ XÁC NHẬN')
    );

    const otpStep = h('div', null,
        h('div', {style:`background:#040810;border:1px solid ${C.cyan}33;border-radius:6px;padding:14px 16px;margin-bottom:16px;text-align:center;`},
            h('div', {style:`font-size:10px;color:${C.muted};margin-bottom:4px;`}, 'Đã gửi mã đến'),
            h('div', {style:`color:${C.cyan};font-size:13px;`}, email),
            h('div', {style:'font-size:9px;color:#334455;margin-top:4px;'}, 'Kiểm tra hộp thư (và thư mục Spam)')
        ),
        h('div', {style:'margin-bottom:16px'},
            h('label', {style:`display:block;font-size:10px;color:${C.muted};letter-spacing:1px;margin-bottom:6px;`}, 'MÃ XÁC NHẬN (6 SỐ)'),
            h('input', {
                ref: otpInputRef, type:'text', inputMode:'numeric', maxLength:'6', value:otp,
                placeholder:'000000',
                style:`width:100%;box-sizing:border-box;background:#050810;border:1px solid ${error?C.red:C.border};color:${C.cyan};padding:12px 14px;border-radius:4px;font-family:'Courier New',monospace;font-size:28px;font-weight:bold;letter-spacing:10px;outline:none;text-align:center;`,
                onInput: e => { setOtp(e.target.value.replace(/\D/g,'')); setError(''); },
                onKeyDown: e => { if (e.key==='Enter' && !busy) verifyOtp(); },
            })
        ),
        h('button', {
            onClick: verifyOtp, disabled: busy,
            style:`width:100%;background:${busy?C.border:'linear-gradient(135deg,'+C.green+',#00aa66)'};color:${busy?C.muted:'#000'};border:none;padding:13px;border-radius:4px;font-family:'Courier New',monospace;font-size:12px;font-weight:bold;cursor:${busy?'not-allowed':'pointer'};letter-spacing:1px;margin-bottom:12px;`,
        }, busy ? '⏳ ĐANG XÁC NHẬN...' : '✅ XÁC NHẬN & ĐI VÀO DASHBOARD'),
        h('div', {style:'display:flex;align-items:center;justify-content:space-between;'},
            h('button', {
                onClick: () => { setStep('email'); setOtp(''); setError(''); },
                style:`background:transparent;border:none;color:${C.muted};font-size:10px;cursor:pointer;font-family:'Courier New',monospace;`
            }, '← Đổi email'),
            countdown > 0
                ? h('span', {style:'font-size:9px;color:#334;'}, `Gửi lại sau ${countdown}s`)
                : h('button', {
                    onClick: requestOtp,
                    style:`background:transparent;border:none;color:${C.cyan};font-size:10px;cursor:pointer;font-family:'Courier New',monospace;`
                  }, 'Gửi lại mã')
        )
    );

    return html`
        <div style="position:fixed;inset:0;background:${C.bg};display:flex;align-items:center;justify-content:center;z-index:99999;font-family:'Courier New',monospace;">
            <div style="position:absolute;inset:0;background-image:linear-gradient(${C.border}22 1px,transparent 1px),linear-gradient(90deg,${C.border}22 1px,transparent 1px);background-size:40px 40px;pointer-events:none;"></div>
            <div style="position:relative;width:420px;background:${C.panel};border:1px solid ${C.border};border-top:2px solid ${C.cyan};border-radius:8px;padding:36px;box-shadow:0 24px 80px #000c;">

                <div style="text-align:center;margin-bottom:28px;">
                    <div style="color:${C.cyan};font-size:11px;letter-spacing:4px;margin-bottom:6px;">Z-ARMOR CLOUD</div>
                    <div style="color:#fff;font-size:18px;font-weight:bold;letter-spacing:1px;">🔐 SECURE ACCESS</div>
                    <div style="color:${C.muted};font-size:11px;margin-top:6px;">Risk Management Platform · MT5</div>
                </div>

                <div style="display:flex;align-items:center;gap:8px;margin-bottom:24px;">
                    <div style="flex:1;height:2px;background:${C.cyan};border-radius:2px;"></div>
                    <div style="font-size:9px;color:${C.muted};letter-spacing:1px;white-space:nowrap;">
                        BƯỚC ${step==='email'?'1/2':'2/2'} — ${step==='email'?'NHẬP EMAIL':'NHẬP MÃ XÁC NHẬN'}
                    </div>
                    <div style="flex:1;height:2px;background:${step==='otp'?C.cyan:C.border};border-radius:2px;"></div>
                </div>

                ${step === 'email' ? emailStep : otpStep}

                ${error ? html`
                    <div style="margin-top:12px;background:#1a050a;border:1px solid ${C.red}44;border-radius:4px;padding:10px 12px;font-size:11px;color:${C.red};">
                        ⚠ ${error}
                    </div>
                ` : null}

                <div style="margin-top:20px;padding-top:16px;border-top:1px solid ${C.border};">
                    <details style="cursor:pointer;">
                        <summary style="font-size:9px;color:#334;letter-spacing:1px;outline:none;user-select:none;">
                            HOẶC ĐĂNG NHẬP BẰNG LICENSE KEY (CŨ)
                        </summary>
                        <div style="margin-top:10px;display:flex;gap:8px;">
                            <input id="lk-fallback" type="text" placeholder="ZARMOR-XXXXX-XXXXX"
                                style="flex:1;background:#050709;border:1px solid #1a2030;color:#aaa;padding:8px 10px;border-radius:3px;font-family:monospace;font-size:11px;outline:none;"
                                onKeyDown=${e => { if (e.key === 'Enter') loginByKey(); }}
                            />
                            <button onClick=${loginByKey}
                                style="background:#1a2030;color:#aaa;border:1px solid #2a3040;padding:8px 12px;border-radius:3px;cursor:pointer;font-size:10px;font-family:'Courier New',monospace;">
                                LOGIN
                            </button>
                        </div>
                    </details>
                </div>
            </div>
        </div>
    `;
}

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
    ? 'http://127.0.0.1:8000' 
    : `http://${window.location.hostname}:8000`;

const COLORS = { 
    bg: '#05070a', panelBg: '#0b0e14', cyan: '#00e5ff', green: '#00ff9d', 
    red: '#ff2a6d', yellow: '#f5d300', textMuted: '#555', border: '#222', orange: '#ff8800', purple: '#b565ff'
};

const REGIME_DISPLAY = {
    "ABSOLUTE_ZERO":       { color: "#00bfff", label: "ABSOLUTE ZERO (IDLE)",          icon: "🔵", pulse: false },
    "OPTIMAL_FLOW":        { color: COLORS.green, label: "OPTIMAL FLOW (GOLDILOCKS)",  icon: "🟢", pulse: false },
    "KINETIC_EROSION":     { color: COLORS.yellow, label: "KINETIC EROSION (WARNING)", icon: "🟡", pulse: true  },
    "TURBULENT_FORCE":     { color: COLORS.red, label: "TURBULENT FORCE (CRITICAL)",  icon: "🔴", pulse: true  },
    "CRITICAL_BREACH":     { color: "#ff0000", label: "CRITICAL BREACH (SCRAM)",      icon: "🚨", pulse: true  },
    "ACCOUNT_LIQUIDATION": { color: "#ff0000", label: "ACCOUNT FLOOR BREACHED ☢️",   icon: "💀", pulse: true  },
    "POSITIVE_LOCK":       { color: COLORS.green, label: "POSITIVE LOCK (SECURED)",   icon: "🛡️", pulse: true  },
    "HIBERNATING":         { color: COLORS.cyan, label: "SYSTEM HIBERNATING",         icon: "⏸️", pulse: false },
    "DISCONNECTED":        { color: "#555", label: "SYSTEM DISCONNECTED",             icon: "🔌", pulse: false }
};

export default function Cockpit() {
    const [unitsConfig, setUnitsConfig] = useState({});
    const [globalStatus, setGlobalStatus] = useState({ 
        license_active: true, balance: 0, total_pnl: 0, total_stl: 0, open_trades: [],
        physics: { state: "SCANNING", z_pressure: 0, velocity: 0, damping_factor: 1.0, is_hibernating: false, mur_pct: 0 },
        chart_data: { labels: [], equity: [], z_pressure: [] },
        daily_pnl_money: 0
    });

    // ── Sprint B: JWT auth state ─────────────────────────────────
    const [authUser, setAuthUser] = useState(() => {
        const token = _getToken();
        if (token && !_isTokenExpired(token)) return _getUser();
        return null;
    });

    // Auto-refresh token khi gần hết hạn
    useEffect(() => {
        const tryRefresh = async () => {
            const token   = _getToken();
            const refresh = _getRefresh();
            if (!token || !refresh) return;
            if (!_isTokenExpired(token)) return;
            try {
                const res  = await fetch(`${API_BASE}/auth/refresh`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh_token: refresh }),
                });
                const data = await res.json();
                if (res.ok) {
                    _setTokens(data.access_token, data.refresh_token);
                } else {
                    _clearTokens();
                    setAuthUser(null);
                }
            } catch { /* silent — sẽ thử lại lần sau */ }
        };
        tryRefresh();
        const interval = setInterval(tryRefresh, 5 * 60 * 1000); // check mỗi 5 phút
        return () => clearInterval(interval);
    }, [authUser]);

    // Nếu chưa đăng nhập → render LoginGate
    if (!authUser) {
        return html`<${LoginGate} apiBase=${API_BASE} onLogin=${(user) => { setAuthUser(user); }} />`;
    }
    // ── End Sprint B auth gate ───────────────────────────────────
    
    const [currentAccountId, setCurrentAccountId] = useState(localStorage.getItem('zarmor_id') || 'MainUnit');
    const [accountList, setAccountList] = useState(() => {
        try { return JSON.parse(localStorage.getItem('zarmor_accounts') || '[]'); } catch { return []; }
    });
    const [showAccountMenu, setShowAccountMenu] = useState(false);
    const accountMenuRef = useRef(null);

    // Tự mở NEW mode nếu URL có ?key=xxx
    const _urlKey = new URLSearchParams(window.location.search).get('key') || '';
    if (_urlKey) {
        localStorage.setItem('zarmor_license_key', _urlKey);
        window.history.replaceState({}, '', window.location.pathname); // F-05: remove key from URL
    }
    const [activeSetup, setActiveSetup] = useState(_urlKey ? '__NEW__' : null);
    const [showMacro, setShowMacro] = useState(false); 
    const [showAiBudget, setShowAiBudget] = useState(false); 

    // 💡 STATE MỚI CHO AI AGENT
    const prevTradesRef = useRef([]);
    const lastWarnLevelRef = useRef(0);
    const rolloverFiredRef = useRef(false);
    const [complianceAlerts, setComplianceAlerts] = useState([]);
    const [showDebrief, setShowDebrief] = useState(null);

    const radarCanvasRef = useRef(null);
    const animState = useRef({ p: 0, e: 0, vp: 0, ve: 0, lastTime: performance.now() });

    // ── RADAR MAP STATE ───────────────────────────────────────────────────
    const [radarMap, setRadarMap] = useState({});
    const [radarTF, setRadarTF] = useState('H1');
    const radarRefreshRef = useRef(null);

    const SYMBOL_TO_ASSET = {
        'XAUUSD': 'GOLD', 'XAUUSDm': 'GOLD', 'GOLD': 'GOLD',
        'EURUSD': 'EURUSD', 'EURUSDm': 'EURUSD',
        'BTCUSD': 'BTC', 'BTCUSDm': 'BTC', 'BTCUSDT': 'BTC',
        'NAS100': 'NASDAQ', 'USTEC': 'NASDAQ', 'NAS100m': 'NASDAQ',
    };

    const getRadarForSymbol = (symbol) => {
        const asset = SYMBOL_TO_ASSET[symbol] || symbol?.replace('m','').toUpperCase();
        return radarMap[`${asset}/${radarTF}`] || radarMap[asset] || null;
    };

    const fetchRadarMap = async () => {
        const symbols = (globalStatus.open_trades || []).map(t => t.symbol).filter(Boolean);
        const assets = [...new Set(symbols.map(s => SYMBOL_TO_ASSET[s] || s?.replace('m','').toUpperCase()).filter(Boolean))];
        if (assets.length === 0) assets.push('GOLD');
        const newMap = {};
        await Promise.allSettled(assets.map(async (asset) => {
            try {
                const r = await fetch(`${API_BASE}/radar/scan`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ asset, timeframe: radarTF, email: 'cockpit@internal' }),
                    signal: AbortSignal.timeout(5000),
                });
                if (!r.ok) return;
                const d = await r.json();
                newMap[`${asset}/${radarTF}`] = {
                    score: d.score || 0, label: d.label || '',
                    regime: d.regime || 'UNKNOWN',
                    allow_trade: d.allow_trade !== false,
                    position_pct: d.position_pct || 0,
                    sl_multiplier: d.sl_multiplier || 1.0,
                    state_cap: d.state_cap || '',
                    updated_at: d.timestamp_utc || new Date().toISOString(),
                };
            } catch (_) {}
        }));
        if (Object.keys(newMap).length > 0) setRadarMap(prev => ({ ...prev, ...newMap }));
    };

    useEffect(() => {
        fetchRadarMap();
        radarRefreshRef.current = setInterval(fetchRadarMap, 300000);
        return () => clearInterval(radarRefreshRef.current);
    }, [radarTF]);

    const prevTradeCount = useRef(0);
    useEffect(() => {
        const curr = (globalStatus.open_trades || []).length;
        if (curr !== prevTradeCount.current) { prevTradeCount.current = curr; fetchRadarMap(); }
    }, [globalStatus.open_trades]);

    const radarScoreColor = (score) => {
        if (score === undefined || score === null) return '#333';
        if (score >= 70) return COLORS.green;
        if (score >= 50) return COLORS.cyan;
        if (score >= 30) return COLORS.yellow;
        return COLORS.red;
    };
    const radarRegimeColor = (regime) => {
        const r = (regime || '').toUpperCase();
        if (r.includes('STRONG_TREND') || r.includes('TRENDING')) return COLORS.green;
        if (r.includes('BREAKOUT')) return COLORS.cyan;
        if (r.includes('NEUTRAL')) return COLORS.yellow;
        if (r.includes('MEAN_REV')) return '#b565ff';
        if (r.includes('VOLATILE') || r.includes('UNCERTAIN')) return COLORS.orange;
        return '#555';
    };

    // ref để fetchData closure luôn đọc được currentAccountId mới nhất
    const currentAccountIdRef = useRef(localStorage.getItem('zarmor_id') || 'MainUnit');
    const fetchRetryRef = useRef(0);  // đếm số lần fetch fail liên tiếp

    const fetchData = async () => {
        try {
            const activeId = currentAccountIdRef.current;

            // Sprint B: JWT auth — Bearer header ưu tiên, fallback license_key
            const jwt = _getToken();
            const _lk = new URLSearchParams(window.location.search).get('key')
                     || localStorage.getItem('zarmor_license_key') || '';

            const headers = {};
            if (jwt && !_isTokenExpired(jwt)) {
                headers['Authorization'] = `Bearer ${jwt}`;
            }

            let qp = activeId !== 'MainUnit' ? `account_id=${activeId}` : '';
            // F-13: license_key as header instead of URL param
            if (!headers['Authorization'] && _lk) {
                headers['X-License-Key'] = _lk; // avoid URL logs
            }
            const targetParam = qp ? `?${qp}` : '';
            const res = await fetch(`${API_BASE}/api/init-data${targetParam}`, {
                headers,
                signal: AbortSignal.timeout(4000)
            });
            const data = await res.json();
            // Token expired → về login
            if (res.status === 401) { _clearTokens(); setAuthUser(null); return; }
            fetchRetryRef.current = 0;
            if (data.units_config) { setUnitsConfig(data.units_config); }
            if (data.global_status) setGlobalStatus(data.global_status);
        } catch (e) {
            fetchRetryRef.current += 1;
            // Sau 3 lần fail liên tiếp → đánh dấu DISCONNECTED trong UI
            if (fetchRetryRef.current >= 3) {
                setGlobalStatus(prev => ({
                    ...prev,
                    physics: { ...(prev.physics || {}), state: 'DISCONNECTED', z_pressure: 0 }
                }));
            }
        }
    };

    // 💡 1. ĐỒNG BỘ AI MEMORY KHI KHỞI ĐỘNG TERMINAL (Option A — server-side sync)
    const [syncStatus, setSyncStatus] = useState(null); // null | 'syncing' | 'ok' | 'error' | 'unavailable'

    useEffect(() => {
        const accountId = localStorage.getItem("zarmor_id");
        if (!accountId) return;

        const syncData = async (attempt = 1) => {
            setSyncStatus('syncing');
            try {
                const res = await fetch(`${API_BASE}/api/sync-history/${accountId}`, {
                    headers: { 'Authorization': `Bearer ${_getToken()}` }, // F-08
                    signal: AbortSignal.timeout(5000)
                });

                // Endpoint chưa tồn tại trên server → bỏ qua, không crash
                if (res.status === 404) {
                    _warn(`⚠️ /api/sync-history/${accountId} trả về 404 — endpoint chưa được triển khai trên server.`);
                    setSyncStatus('unavailable');
                    return;
                }

                // Lỗi server khác (500, 503...)
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }

                const data = await res.json();

                if (data.status !== "ok") {
                    _warn("⚠️ sync-history trả về status không hợp lệ:", data);
                    setSyncStatus('error');
                    return;
                }

                // Chỉ ghi vào localStorage nếu chưa có dữ liệu local (tránh overwrite dữ liệu mới hơn)
                const existingTrades = localStorage.getItem(`zarmor_trades_${accountId}`);
                const existingSessions = localStorage.getItem(`zarmor_sessions_${accountId}`);

                if (!existingTrades || JSON.parse(existingTrades).length === 0) {
                    localStorage.setItem(`zarmor_trades_${accountId}`, JSON.stringify(data.trades || []));
                    _log(`✅ Khôi phục ${data.meta?.trade_count ?? (data.trades?.length ?? 0)} lệnh từ Cloud`);
                }
                if (!existingSessions || JSON.parse(existingSessions).length === 0) {
                    localStorage.setItem(`zarmor_sessions_${accountId}`, JSON.stringify(data.sessions || []));
                    _log(`✅ Khôi phục ${data.meta?.session_count ?? (data.sessions?.length ?? 0)} phiên từ Cloud`);
                }

                setSyncStatus('ok');
                writeAuditLog(accountId, 'CLOUD_SYNC', `☁️ Đồng bộ AI memory thành công | ${data.meta?.trade_count ?? 0} lệnh, ${data.meta?.session_count ?? 0} phiên`);

            } catch (err) {
                _warn(`⚠️ Không thể đồng bộ AI memory từ Cloud (lần ${attempt}):`, err);

                // Tự động retry tối đa 3 lần với delay tăng dần
                if (attempt < 3) {
                    const delay = attempt * 3000; // 3s, 6s
                    _log(`🔄 Thử lại sync sau ${delay / 1000}s...`);
                    setTimeout(() => syncData(attempt + 1), delay);
                } else {
                    setSyncStatus('error');
                    console.error("❌ Sync thất bại sau 3 lần thử. Dùng dữ liệu local.");
                }
            }
        };

        syncData();
    }, []);

    // ── ACCOUNT SWITCHER ──────────────────────────────────────────────────
    const switchAccount = (id) => {
        currentAccountIdRef.current = id;
        localStorage.setItem('zarmor_id', id);
        setCurrentAccountId(id);
        setShowAccountMenu(false);
        fetchRetryRef.current = 0;
        fetchData();
    };

    // Sync accountList từ unitsConfig — CHỈ dùng data server (R-03 fleet isolation)
    useEffect(() => {
        const ids = Object.keys(unitsConfig || {});
        if (ids.length === 0) return;
        // Không merge với prev — chỉ hiển thị accounts server cho phép
        localStorage.setItem('zarmor_accounts', JSON.stringify(ids));
        setAccountList(ids);
    }, [unitsConfig]);

    // Đóng dropdown khi click ra ngoài
    useEffect(() => {
        if (!showAccountMenu) return;
        const handler = (e) => {
            if (accountMenuRef.current && !accountMenuRef.current.contains(e.target))
                setShowAccountMenu(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [showAccountMenu]);

    useEffect(() => {
        fetchData();
        // Polling thích nghi: 1s khi connected, 5s khi DISCONNECTED (tránh spam server)
        let interval = 1000;
        let timer = setInterval(() => {
            const isDisconnected = fetchRetryRef.current >= 3;
            const newInterval = isDisconnected ? 5000 : 1000;
            if (newInterval !== interval) {
                interval = newInterval;
                clearInterval(timer);
                timer = setInterval(fetchData, interval);
            }
            fetchData();
        }, interval);
        return () => clearInterval(timer);
    }, [currentAccountId]);

    // Lắng nghe sự kiện Đóng Session để bật Modal Tóm tắt
    useEffect(() => {
        const handler = (e) => setShowDebrief(e.detail);
        window.addEventListener('zarmor_session_closed', handler);
        return () => window.removeEventListener('zarmor_session_closed', handler);
    }, []);

    const myUnitConfig = unitsConfig[currentAccountId] || unitsConfig['MainUnit'] || {};
    const riskParams = myUnitConfig.risk_params || {};
    const neural = myUnitConfig.neural_profile || {};
    const isLocked = myUnitConfig.is_locked === true;
    
    const balance = globalStatus.balance || 0;
    const startBalance = globalStatus?.start_balance || balance;
    const currentEquity = globalStatus.equity || balance;
    
    const activeTrades = globalStatus.open_trades || [];
    
    const sumProjectedYield = activeTrades.reduce((sum, t) => sum + (parseFloat(t.tp_money) || 0), 0);
    const sumFloatingRisk = activeTrades.reduce((sum, t) => sum + Math.abs(parseFloat(t.stl_money) || 0), 0);

    const physics = globalStatus.physics || {};
    const physicsRegime = physics.state || "OPTIMAL_FLOW"; 
    const isHibernating = physicsRegime === "HIBERNATING";
    const finalZPressure = physics.z_pressure || 0.0;
    const frePct = physics.fre_pct || 0.0; 
    
    const rawDailyLoss = physics.budget_capacity || parseFloat(riskParams.tactical_daily_money) || 150;
    const closedLoss = Math.max(0, startBalance - balance);
    const deployedBudget = closedLoss + sumFloatingRisk;

    // ── TẦNG 1: Account DD fields ────────────────────────────────────
    const ddType            = riskParams.dd_type || physics.dd_type || 'STATIC';
    const maxDdPct          = parseFloat(riskParams.max_dd || physics.max_dd_pct) || 10;
    const accountHardFloor  = physics.account_hard_floor || 0;
    const accountPeak       = physics.account_peak || balance;
    const distToAccFloor    = physics.dist_to_account_floor || 0;
    const accountDdPct      = physics.account_dd_pct || 0;
    const accountBufferPct  = physics.account_buffer_pct || 100;  // % buffer còn lại trước floor

    // ── TẦNG 2: Daily DD fields ──────────────────────────────────────
    const dailyPeak         = physics.daily_peak || physics.peak_equity || startBalance;
    const dailyGivebackPct  = physics.daily_giveback_pct || 0;    // % giveback so với allowed

    // 💡 2. MÁY QUÉT LỆNH AI AGENT (TRADE LOGGER)
    useEffect(() => {
        if (!activeTrades || !currentAccountId) return;

        const prev = prevTradesRef.current;
        const prevTickets = new Set(prev.map(t => String(t.ticket)));
        const currTickets = new Set(activeTrades.map(t => String(t.ticket)));

        // Lệnh MỚI MỞ
        const newTrades = activeTrades.filter(t => !prevTickets.has(String(t.ticket)));
        newTrades.forEach(t => {
            const plannedRR = neural?.historical_rr || 2.0;
            const riskAmount = parseFloat(t.risk_amount) || Math.abs(parseFloat(t.open_price || 0) - parseFloat(t.sl || 0)) * parseFloat(t.volume || 0.01) * 10 || 0;

            const entry = logTrade(currentAccountId, {
                symbol: t.symbol, direction: t.side || t.type, risk_amount: riskAmount,
                planned_rr: plannedRR, hour_of_day: new Date().getHours(),
                day_of_week: new Date().getDay(), ticket: t.ticket
            });
            t._agent_id = entry?.id;

            // KIỂM TRA ĐẠO ĐỨC LỆNH (COMPLIANCE)
            const check = checkCompliance(currentAccountId,
                { risk_amount: riskAmount, planned_rr: plannedRR },
                { daily_used: deployedBudget, current_dd_pct: frePct }
            );

            if (check && check.violations && check.violations.length > 0) {
                check.violations.forEach(v => {
                    writeAuditLog(currentAccountId, 'COMPLIANCE_VIOL', v.detail, { severity: v.severity });
                });
                setComplianceAlerts(check.violations);
            }

            writeAuditLog(currentAccountId, 'TRADE_OPEN', `[${t.ticket}] ${t.symbol} ${t.side || t.type} | Risk $${riskAmount.toFixed(0)} | Planned R:R 1:${plannedRR}`);
        });

        // LỆNH VỪA ĐÓNG
        const closedTrades = prev.filter(t => !currTickets.has(String(t.ticket)));
        closedTrades.forEach(t => {
            const profit = parseFloat(t.profit || t.pnl || 0);
            const result = profit > 0 ? 'WIN' : profit < 0 ? 'LOSS' : 'BE';
            const riskAmt = parseFloat(t.risk_amount || Math.abs(parseFloat(t.open_price || 0) - parseFloat(t.sl || 0)) * parseFloat(t.volume || 0.01) * 10 || 1);
            const actualRR = riskAmt > 0 ? Math.abs(profit) / riskAmt : 0;

            updateTradeResult(currentAccountId, t._agent_id, result, actualRR);

            const resultIcon = result === 'WIN' ? '✅' : result === 'LOSS' ? '❌' : '⚡';
            writeAuditLog(currentAccountId,
                result === 'WIN' ? 'TRADE_WIN' : result === 'LOSS' ? 'TRADE_LOSS' : 'INFO',
                `${resultIcon} [${t.ticket}] ${t.symbol} ĐÓNG | ${result} | P&L: ${profit >= 0 ? '+' : null}$${profit.toFixed(2)} | R:R thực: ${actualRR.toFixed(2)}`,
                { profit, actualRR }
            );
        });

        prevTradesRef.current = activeTrades;
    }, [activeTrades, currentAccountId, neural, deployedBudget, frePct]);

    // 💡 3. CẢNH BÁO DRAWDOWN — DUAL LAYER
    useEffect(() => {
        // --- Tầng 2: Daily floating risk DD ---
        const pct = (frePct / maxDdPct) * 100;
        if (pct >= 90 && lastWarnLevelRef.current < 90) {
            writeAuditLog(currentAccountId, 'DD_WARNING', `☢️ CRITICAL: Floating risk ${frePct.toFixed(1)}% chạm ${pct.toFixed(0)}% capacity (Max ${maxDdPct}%). Xem xét đóng lệnh!`, { severity: 'CRITICAL' });
            lastWarnLevelRef.current = 90;
        } else if (pct >= 75 && pct < 90 && lastWarnLevelRef.current < 75) {
            writeAuditLog(currentAccountId, 'DD_WARNING', `⚠️ WARNING: Floating risk ${frePct.toFixed(1)}% đang tiến đến Max DD ${maxDdPct}%`, { severity: 'HIGH' });
            lastWarnLevelRef.current = 75;
        } else if (pct < 50) {
            lastWarnLevelRef.current = 0;
        }

        // --- Tầng 1: Account floor proximity ---
        if (accountHardFloor > 0) {
            if (accountBufferPct <= 0) {
                writeAuditLog(currentAccountId, 'ACCOUNT_FLOOR_BREACH', `💀 TẦNG 1 BỊ XUYÊN THỦNG: Equity đã xuyên ${ddType} Floor $${accountHardFloor.toFixed(0)}!`, { severity: 'CRITICAL' });
            } else if (accountBufferPct <= 20) {
                writeAuditLog(currentAccountId, 'ACCOUNT_FLOOR_WARN', `🔴 CẢNH BÁO TẦNG 1: Chỉ còn ${accountBufferPct.toFixed(0)}% buffer trước ${ddType} Floor $${accountHardFloor.toFixed(0)}`, { severity: 'HIGH' });
            }
        }
    }, [frePct, maxDdPct, accountBufferPct, accountHardFloor, currentAccountId, ddType]);

    // 💡 4. NHẬN DIỆN GIỜ ROLLOVER & TỔNG KẾT PHIÊN
    useEffect(() => {
        const rolloverHour = Number(riskParams?.rollover_hour) || 0;
        const tgChatId = myUnitConfig.telegram_config?.chat_id;

        const check = () => {
            const now = new Date();
            if (now.getHours() === rolloverHour && now.getMinutes() === 0) {
                if (rolloverFiredRef.current) return;
                rolloverFiredRef.current = true;

                const session = (() => {
                    try { return JSON.parse(localStorage.getItem(`zarmor_current_session_${currentAccountId}`) || 'null'); } catch { return null; }
                })();

                if (session && session.status === 'ACTIVE') {
                    const finalPnL = globalStatus?.total_pnl || 0;
                    const closed = closeSession(currentAccountId, finalPnL, frePct);

                    if (closed) {
                        writeAuditLog(currentAccountId, 'SESSION_CLOSE', `📊 SESSION CLOSED | PnL: ${finalPnL >= 0 ? '+' : null}$${finalPnL.toFixed(2)} | Compliance: ${closed.compliance_score}% | DD hit: ${frePct.toFixed(1)}%`, { pnl: finalPnL, compliance: closed.compliance_score });

                        if (tgChatId) {
                            const debrief = generateDebrief(closed);
                            fetch(`${API_BASE}/api/send-telegram`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ account_id: currentAccountId, chat_id: tgChatId, message: debrief })
                            }).catch(() => {});
                        }

                        window.dispatchEvent(new CustomEvent('zarmor_session_closed', { detail: closed }));
                        setTimeout(() => { rolloverFiredRef.current = false; }, 60000);
                    }
                }
            }
        };

        const intv = setInterval(check, 30000); // Quét mỗi 30s
        return () => clearInterval(intv);
    }, [riskParams?.rollover_hour, currentAccountId, globalStatus, frePct, myUnitConfig]);

    let kineticRatio = 0;
    if (sumFloatingRisk > 0) kineticRatio = sumProjectedYield / sumFloatingRisk;
    else if (sumProjectedYield > 0) kineticRatio = 99.9;

    const targetRR = parseFloat(neural.historical_rr) || 1.5;
    let disciplineStatus = "AWAITING TRADES";
    let disciplineColor = "#555";
    
    if (activeTrades.length > 0) {
        if (sumFloatingRisk === 0) {
            disciplineStatus = "NO STOPLOSS DETECTED (FATAL)";
            disciplineColor = COLORS.red;
        } else if (kineticRatio >= targetRR) {
            disciplineStatus = "EDGE ALIGNED (TUÂN THỦ LỜI THỀ)";
            disciplineColor = COLORS.green;
        } else if (kineticRatio >= 1.0) {
            disciplineStatus = "SUB-OPTIMAL (R:R THẤP HƠN CAM KẾT)";
            disciplineColor = COLORS.yellow;
        } else {
            disciplineStatus = "THERMODYNAMIC VIOLATION (R:R ÂM)";
            disciplineColor = COLORS.red;
        }
    }

    const configuredTarget = parseFloat(riskParams.target_profit) || 0;
    const netDailyPnL = currentEquity - startBalance;
    let saturationPct = configuredTarget > 0 ? (Math.max(0, netDailyPnL) / configuredTarget) * 100 : 0;
    saturationPct = Math.min(100, Math.max(0, saturationPct));

    const maxBarVal = Math.max(sumFloatingRisk, sumProjectedYield) * 1.1 || 100;
    const riskBarPct = (sumFloatingRisk / maxBarVal) * 100;
    const rewardBarPct = (sumProjectedYield / maxBarVal) * 100;

    let statusStyle = REGIME_DISPLAY[physicsRegime] || REGIME_DISPLAY["OPTIMAL_FLOW"];
    if (physicsRegime.includes("ACCOUNT_LIQUIDATION")) statusStyle = REGIME_DISPLAY["ACCOUNT_LIQUIDATION"];
    else if (physicsRegime.includes("POSITIVE_LOCK") || physicsRegime.includes("PROFIT")) statusStyle = REGIME_DISPLAY["POSITIVE_LOCK"];
    else if (physicsRegime.includes("ABSOLUTE_ZERO") || physicsRegime.includes("IDLE") || physicsRegime.includes("ZERO")) statusStyle = REGIME_DISPLAY["ABSOLUTE_ZERO"];
    else if (physicsRegime.includes("OPTIMAL_FLOW") || physicsRegime.includes("FLOW") || physicsRegime.includes("OPTIMAL")) statusStyle = REGIME_DISPLAY["OPTIMAL_FLOW"];
    else if (physicsRegime.includes("KINETIC_EROSION") || physicsRegime.includes("EROSION") || physicsRegime.includes("ELEVATED")) statusStyle = REGIME_DISPLAY["KINETIC_EROSION"];
    else if (physicsRegime.includes("TURBULENT_FORCE") || physicsRegime.includes("TURBULENT") || physicsRegime.includes("CRITICAL")) statusStyle = REGIME_DISPLAY["TURBULENT_FORCE"];
    else if (physicsRegime.includes("CRITICAL_BREACH") || physicsRegime.includes("BREACH") || physicsRegime.includes("LOCKED")) statusStyle = REGIME_DISPLAY["CRITICAL_BREACH"];
    else if (physicsRegime.includes("DISCONNECT")) statusStyle = REGIME_DISPLAY["DISCONNECTED"];

    const dbuPct = rawDailyLoss > 0 ? (deployedBudget / rawDailyLoss) * 100 : 0.0;
    const finalDamping = physics.damping_factor !== undefined ? physics.damping_factor : 1.0;

    let finalZColor = "#00bfff";
    if (finalZPressure < 0.15) finalZColor = "#00bfff";
    else if (finalZPressure <= 0.60) finalZColor = COLORS.green;
    else if (finalZPressure <= 0.85) finalZColor = COLORS.yellow;
    else if (finalZPressure < 1.0) finalZColor = COLORS.red;
    else finalZColor = "#ff0000";

    const basePressure = physics.base_pressure || 0;
    const trailingPressure = physics.daily_trailing_pressure || physics.trailing_pressure || 0;
    const basePct = Math.min(basePressure * 100, 100);
    const trailPct = Math.min(trailingPressure * 100, 100);

    const p_hat = Math.min(finalZPressure, 1.5); 
    const e_hat = Math.min(frePct / 5.0, 1.5); 

    useEffect(() => {
        const canvas = radarCanvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        let animationId;

        const resize = () => {
            const parent = canvas.parentElement;
            canvas.width = parent.clientWidth;
            canvas.height = parent.clientHeight;
        };
        window.addEventListener('resize', resize);
        resize();

        const drawArrow = (fromX, fromY, toX, toY, color) => {
            const headlen = 10; const dx = toX - fromX; const dy = toY - fromY; const angle = Math.atan2(dy, dx);
            ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(fromX, fromY); ctx.lineTo(toX, toY);
            ctx.lineTo(toX - headlen * Math.cos(angle - Math.PI / 6), toY - headlen * Math.sin(angle - Math.PI / 6)); ctx.moveTo(toX, toY);
            ctx.lineTo(toX - headlen * Math.cos(angle + Math.PI / 6), toY - headlen * Math.sin(angle + Math.PI / 6)); ctx.stroke();
        };

        const loop = (time) => {
            const dt = Math.min((time - animState.current.lastTime) / 1000, 0.1); 
            animState.current.lastTime = time;

            let { p, e, vp, ve } = animState.current;
            const newP = p + (p_hat - p) * 3 * dt; const newE = e + (e_hat - e) * 3 * dt;
            const newVp = (newP - p) / dt; const newVe = (newE - e) / dt;
            const accP = (newVp - vp) / dt; const accE = (newVe - ve) / dt;
            const accMag = Math.sqrt(accP * accP + accE * accE);

            animState.current = { p: newP, e: newE, vp: newVp, ve: newVe, lastTime: time };

            ctx.clearRect(0, 0, canvas.width, canvas.height);
            const padX = 60, padY = 50; const w = canvas.width - padX * 2; const h = canvas.height - padY * 2;
            const scaleX = w / 1.5; const scaleY = h / 1.5;
            const getX = (val) => padX + val * scaleX; const getY = (val) => canvas.height - padY - val * scaleY;

            ctx.fillStyle = COLORS.red + '1A';
            ctx.fillRect(getX(1.0), getY(1.5), scaleX * 0.5, scaleY * 1.5); 
            ctx.fillRect(getX(0), getY(1.5), scaleX * 1.0, scaleY * 0.5);   
            ctx.strokeStyle = COLORS.red; ctx.lineWidth = 1.5; ctx.setLineDash([5, 5]);
            ctx.beginPath(); ctx.moveTo(getX(1.0), getY(0)); ctx.lineTo(getX(1.0), getY(1.5)); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(getX(0), getY(1.0)); ctx.lineTo(getX(1.5), getY(1.0)); ctx.stroke(); ctx.setLineDash([]);

            ctx.fillStyle = COLORS.red + '11'; 
            ctx.fillRect(getX(0.85), getY(1.0), scaleX * 0.15, scaleY * 1.0);

            ctx.fillStyle = COLORS.yellow + '11'; 
            ctx.fillRect(getX(0.60), getY(1.0), scaleX * 0.25, scaleY * 1.0);

            ctx.save(); ctx.beginPath(); ctx.ellipse(getX(0), getY(0), scaleX * 0.6, scaleY * 0.6, 0, 0, Math.PI * 2); ctx.clip();
            ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.fillStyle = COLORS.green + '1A'; ctx.fill(); ctx.restore();
            ctx.beginPath(); ctx.ellipse(getX(0), getY(0), scaleX * 0.6, scaleY * 0.6, 0, 0, Math.PI * 2); ctx.strokeStyle = COLORS.green + '88'; ctx.lineWidth = 1; ctx.stroke();

            ctx.strokeStyle = '#333'; ctx.lineWidth = 1; ctx.beginPath();
            ctx.moveTo(getX(0), getY(0)); ctx.lineTo(getX(1.5), getY(0)); 
            ctx.moveTo(getX(0), getY(0)); ctx.lineTo(getX(0), getY(1.5)); ctx.stroke();

            ctx.fillStyle = '#888'; ctx.font = '10px monospace';
            ctx.fillText('P̂ (CAP. PRESSURE)', getX(1.5) - 100, getY(0) + 18); 
            ctx.save(); ctx.translate(getX(0) - 35, getY(1.5) + 60); ctx.rotate(-Math.PI / 2); ctx.fillText('Ê (RISK EXP.)', 0, 0); ctx.restore();

            ctx.textAlign = 'center';
            [0.15, 0.60, 0.85, 1.0].forEach(v => {
                ctx.beginPath(); ctx.moveTo(getX(v), getY(0)); ctx.lineTo(getX(v), getY(0)+4); ctx.strokeStyle='#555'; ctx.stroke();
                ctx.fillText(v.toFixed(2), getX(v), getY(0) + 15);
            });
            ctx.textAlign = 'left';

            let pointColor = "#00bfff"; 
            if (newP < 0.15) pointColor = "#00bfff";
            else if (newP <= 0.60) pointColor = COLORS.green;
            else if (newP <= 0.85) pointColor = COLORS.yellow;
            else if (newP < 1.0) pointColor = COLORS.red;
            else pointColor = "#ff0000";
            
            if (dbuPct >= 80.0) pointColor = COLORS.purple; 

            let vibX = 0, vibY = 0;
            if (accMag > 1.0 || dbuPct >= 80.0) { 
                vibX = (Math.random() - 0.5) * 3; 
                vibY = (Math.random() - 0.5) * 3; 
            }
            const px = getX(newP) + vibX; const py = getY(newE) + vibY;

            const w_rect = px - getX(0);
            const h_rect = getY(0) - py;
            if (w_rect > 0 && h_rect > 0) {
                const grad = ctx.createLinearGradient(getX(0), getY(0), px, py);
                grad.addColorStop(0, 'transparent');
                grad.addColorStop(1, pointColor + '44'); 

                ctx.fillStyle = grad; 
                ctx.fillRect(getX(0), py, w_rect, h_rect);
                
                ctx.setLineDash([3, 5]);
                ctx.strokeStyle = pointColor + '88';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(px, py); ctx.lineTo(getX(0), py); 
                ctx.moveTo(px, py); ctx.lineTo(px, getY(0)); 
                ctx.stroke();
                ctx.setLineDash([]);
            }

            ctx.fillStyle = COLORS.panelBg + 'CC';
            ctx.fillRect(canvas.width - 150, 10, 140, 60);
            ctx.strokeStyle = '#333'; ctx.strokeRect(canvas.width - 150, 10, 140, 60);
            
            ctx.font = 'bold 10px monospace';
            ctx.fillStyle = COLORS.cyan; ctx.fillText(`B̂ (USED): ${dbuPct.toFixed(1)}%`, canvas.width - 140, 25);
            ctx.fillStyle = COLORS.purple; ctx.fillText(`Ê (EXP.) : ${frePct.toFixed(1)}%`, canvas.width - 140, 42); 
            ctx.fillStyle = pointColor; ctx.fillText(`P̂ (CAP.) : ${(finalZPressure*100).toFixed(1)}%`, canvas.width - 140, 59);

            const baseRadius = 4;
            const massRadius = baseRadius + (Math.min(dbuPct, 100.0) / 100.0) * 6; 

            const speed = Math.sqrt(newVp*newVp + newVe*newVe);
            const damp = finalDamping;
            const arrowX = newVp * damp * scaleX * 2.0; const arrowY = newVe * damp * scaleY * 2.0;
            let arrColor = COLORS.cyan; if (speed > 0.05 && (newP > 0.8 || newE > 0.8)) arrColor = COLORS.orange; if (accMag > 1.5) arrColor = COLORS.red;
            if (speed > 0.01) drawArrow(px, py, px + arrowX, py - arrowY, arrColor);

            ctx.shadowBlur = 10; ctx.shadowColor = pointColor; ctx.fillStyle = pointColor; ctx.beginPath(); 
            ctx.arc(px, py, massRadius, 0, Math.PI * 2); ctx.fill();
            
            if (accMag > 1.0 || pointColor === COLORS.red || pointColor === "#ff0000" || pointColor === COLORS.purple) {
                const pulseSize = massRadius + Math.abs(Math.sin(time/200)) * 6; 
                ctx.beginPath(); ctx.arc(px, py, pulseSize, 0, Math.PI * 2); ctx.fillStyle = pointColor + '44'; ctx.fill();
            }
            ctx.shadowBlur = 0; animationId = requestAnimationFrame(loop);
        };

        animationId = requestAnimationFrame(loop);
        
        return () => { window.removeEventListener('resize', resize); cancelAnimationFrame(animationId); };
    }, [p_hat, e_hat, finalDamping, dbuPct, finalZPressure, frePct]);

    const handlePanicKill = async () => {
        if (!window.confirm("☢️ INITIATE SCRAM: Đóng toàn bộ lệnh và NGỦ ĐÔNG hệ thống ngay lập tức?")) return;
        try { const _jh = _getToken() ? { 'Authorization': `Bearer ${_getToken()}` } : {}; await fetch(`${API_BASE}/api/panic-kill`, { method: 'POST', headers: { 'Content-Type': 'application/json', ..._jh }, body: JSON.stringify({ account_id: currentAccountId }) }); fetchData(); } catch (e) {}
    };

    const handleReboot = async () => {
        if (!window.confirm("⚡ REBOOT: Bạn muốn đánh thức hệ thống trở lại?")) return;
        try { const _jh = _getToken() ? { 'Authorization': `Bearer ${_getToken()}` } : {}; await fetch(`${API_BASE}/api/unlock-unit`, { method: 'POST', headers: { 'Content-Type': 'application/json', ..._jh }, body: JSON.stringify({ account_id: currentAccountId }) }); fetchData(); } catch (e) {}
    };

    const formatMoney = (val) => {
        const num = parseFloat(val) || 0;
        return (num >= 0 ? '+' : '') + num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' $';
    };

    return html`
        <div class="responsive-cockpit">
            
            <style>
                @keyframes pulseEffect { 0%{transform:scale(1);opacity:1} 50%{transform:scale(1.15);opacity:0.7} 100%{transform:scale(1);opacity:1} }
                @keyframes blinker { 50%{opacity:0.3} }
                @keyframes blink { 50%{opacity:0} }
                @keyframes rowIn { from{opacity:0;transform:translateY(-3px)} to{opacity:1;transform:translateY(0)} }
                @keyframes pnlGreen { 0%,100%{box-shadow:none} 50%{box-shadow:inset 0 0 8px #00ff9d22} }
                @keyframes pnlRed   { 0%,100%{box-shadow:none} 50%{box-shadow:inset 0 0 8px #ff2a6d22} }
                .pulse-icon { animation: pulseEffect 1s infinite cubic-bezier(0.25,0.8,0.25,1); }
                .blink-text { animation: blinker 1.5s linear infinite; }
                .scanline-bg { background: linear-gradient(rgba(0,229,255,0.025) 1px,transparent 1px),linear-gradient(90deg,rgba(0,229,255,0.025) 1px,transparent 1px); background-size:20px 20px; }
                .trade-table-container::-webkit-scrollbar { width:3px; height:3px; }
                .trade-table-container::-webkit-scrollbar-track { background:#050709; }
                .trade-table-container::-webkit-scrollbar-thumb { background:#1c1c1c; border-radius:2px; }

                /* ── LAYOUT ── */
                .responsive-cockpit {
                    background: ${COLORS.bg}; color: #fff;
                    height: 100vh; width: 100vw;
                    display: grid;
                    grid-template-columns: 330px minmax(0,1fr) 330px;
                    gap: 8px; padding: 8px;
                    font-family: monospace;
                    overflow: hidden;
                    box-sizing: border-box;
                }
                .main-panel {
                    display: flex; flex-direction: column;
                    gap: 6px;
                    overflow-y: auto; overflow-x: hidden;
                    width: 100%; padding-right: 2px;
                    scrollbar-width: thin; scrollbar-color: #1a1a1a #05070a;
                }

                /* ── TOP BANNER: compact ── */
                .top-alert-banner {
                    display: flex; justify-content: space-between; align-items: center;
                    padding: 8px 14px;
                    border-radius: 3px; flex-shrink: 0; transition: 0.5s;
                }

                /* ── FINANCIAL STATS: 5 cột ── */
                .financial-stats {
                    display: grid;
                    grid-template-columns: 1.2fr 1fr 1fr 1fr 1fr;
                    background: #000;
                    border-bottom: 1px solid #1a1a1a;
                    padding: 6px 0;
                }
                .financial-stats > div {
                    border-right: 1px solid #111;
                    padding: 2px 8px;
                }
                .financial-stats > div:last-child { border-right: none; }

                /* ── TRADE TABLE ── */
                .trade-table-container { flex:1; overflow-y:auto; overflow-x:auto; width:100%; }
                .trade-row {
                    display: grid;
                    grid-template-columns: 54px 70px 46px 46px 76px 76px 80px 80px 70px 50px 90px;
                    gap: 3px; align-items: center;
                    min-width: 750px;
                }
                .trade-row > span {
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                    font-size: 10px;
                }
                .trade-row:hover { background: rgba(0,229,255,0.035) !important; }
                .trade-row { animation: rowIn 0.18s ease; }
                .pnl-pos { animation: pnlGreen 2.5s infinite; }
                .pnl-neg { animation: pnlRed 2.5s infinite; }

                /* ── RESPONSIVE mobile ── */
                @media (max-width: 1100px) {
                    body, html, #root { height: auto !important; overflow-y: auto !important; overflow-x: hidden !important; background: ${COLORS.bg}; }
                    .responsive-cockpit { display: flex !important; flex-direction: column !important; height: auto !important; min-height: 100vh; overflow: visible !important; padding: 8px !important; }
                    aside, .main-panel { width: 100% !important; max-width: 100vw !important; box-sizing: border-box !important; overflow: visible !important; height: auto !important; max-height: none !important; flex: none !important; }
                    .top-alert-banner { flex-direction: column; gap: 10px; text-align: center; }
                    .top-alert-banner > div { width: 100% !important; border: none !important; }
                    .financial-stats { grid-template-columns: 1fr 1fr 1fr !important; row-gap: 8px; }
                    .trade-table-container { overflow-x: auto !important; }
                    .scanline-bg { min-height: 200px !important; height: auto !important; }
                }
            </style>

            <aside style="display: flex; flex-direction: column; overflow: hidden; gap: 10px;">
                <${LeftColumn} global_status=${globalStatus} units_config=${unitsConfig} COLORS=${COLORS} onOpenMacro=${() => setShowMacro(true)} />
            </aside>

            <main class="main-panel">
                <!-- ── HEADER BAR + ACCOUNT SWITCHER ── -->
                <div style="display: flex; justify-content: space-between; align-items: center; background: #0b0e14; border: 1px solid #222; padding: 5px 15px; border-radius: 4px; flex-shrink: 0; position: relative; z-index: 100;">
                    <div style="color: ${COLORS.cyan}; font-size: 12px; font-weight: bold; letter-spacing: 1px;">Z-ARMOR CLOUD TERMINAL</div>

                    <div style="display: flex; align-items: center; gap: 10px;">

                        <!-- SYNC BADGES -->
                        ${syncStatus === 'syncing' ? html`<div style="font-size: 9px; color: ${COLORS.cyan}; background: ${COLORS.cyan}11; border: 1px solid ${COLORS.cyan}44; padding: 3px 8px; border-radius: 2px; animation: blinker 1.5s linear infinite;">☁️ SYNCING...</div>` : null}
                        ${syncStatus === 'ok' ? html`<div style="font-size: 9px; color: ${COLORS.green}; background: ${COLORS.green}11; border: 1px solid ${COLORS.green}44; padding: 3px 8px; border-radius: 2px;">✅ SYNCED</div>` : null}
                        ${syncStatus === 'error' ? html`<div style="font-size: 9px; color: ${COLORS.yellow}; background: ${COLORS.yellow}11; border: 1px solid ${COLORS.yellow}44; padding: 3px 8px; border-radius: 2px;">⚠️ LOCAL</div>` : null}
                        ${syncStatus === 'unavailable' ? html`<div style="font-size: 9px; color: #444; background: #111; border: 1px solid #333; padding: 3px 8px; border-radius: 2px;">🔌 OFFLINE</div>` : null}

                        <!-- CONNECTION STATUS -->
                        <div style="color: ${physicsRegime === 'DISCONNECTED' ? '#ff0000' : '#00ffcc'}; font-size: 9px; font-weight: bold; background: #05070a; padding: 3px 8px; border-radius: 2px; border: 1px solid ${physicsRegime === 'DISCONNECTED' ? '#ff000055' : '#00ffcc44'};">
                            ${physicsRegime === 'DISCONNECTED' ? '⚠️ MẤT KẾT NỐI' : '📡 LIVE'}
                        </div>

                        <!-- ── ACCOUNT SWITCHER DROPDOWN ── -->
                        <div ref=${accountMenuRef} style="position: relative;">
                            <button
                                onClick=${() => setShowAccountMenu(v => !v)}
                                style="display: flex; align-items: center; gap: 8px; background: ${showAccountMenu ? COLORS.cyan + '18' : '#05070a'}; border: 1px solid ${showAccountMenu ? COLORS.cyan + '88' : '#333'}; color: #fff; padding: 4px 10px; border-radius: 3px; cursor: pointer; font-family: monospace; font-size: 10px; font-weight: bold; transition: 0.2s; white-space: nowrap;">
                                <span style="color: ${COLORS.cyan};">▣</span>
                                <span style="color: ${COLORS.cyan};">${myUnitConfig.alias || currentAccountId}</span>
                                ${myUnitConfig.alias ? html`<span style="color: #333; font-size: 8px;">· ${currentAccountId}</span>` : null}
                                <span style="color: #444; font-size: 8px; margin-left: 2px;">${showAccountMenu ? '▲' : '▼'}</span>
                            </button>

                            ${showAccountMenu ? html`

                                <div style="position: absolute; top: calc(100% + 6px); right: 0; z-index: 9999; background: #070910; border: 1px solid #222; border-radius: 4px; min-width: 320px; box-shadow: 0 12px 40px rgba(0,0,0,0.9); overflow: hidden;">

                                    <!-- Dropdown header -->
                                    <div style="padding: 8px 14px; background: #020305; border-bottom: 1px solid #1a1a1a; display: flex; justify-content: space-between; align-items: center;">
                                        <span style="font-size: 9px; color: #444; letter-spacing: 1px; font-weight: bold;">⚡ FLEET OVERVIEW</span>
                                        <span style="font-size: 8px; color: #222;">${accountList.length} tài khoản${!localStorage.getItem('zarmor_license_key') ? ' ⚠' : null}</span>
                                    </div>

                                    <!-- Account rows -->
                                    ${accountList.length === 0 ? html`
                                        <div style="padding: 12px 14px; font-size: 9px; color: #333; text-align: center; font-style: italic;">
                                            Chưa có tài khoản — ARM tài khoản đầu tiên bên dưới
                                        </div>
                                    ` : accountList.map(id => {
                                        const cfg    = unitsConfig[id] || {};
                                        const isAct  = id === currentAccountId;
                                        const isLk   = cfg.is_locked === true;
                                        const alias  = cfg.alias || id;
                                        const maxDd  = cfg.risk_params?.max_dd || 10;
                                        const ddNow  = (isAct ? (globalStatus?.physics?.account_dd_pct || 0) : 0);
                                        const hasCfg = !!cfg.risk_params;
                                        return html`
                                            <div
                                                onClick=${() => switchAccount(id)}
                                                style="padding: 9px 14px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; background: ${isAct ? COLORS.cyan + '0d' : 'transparent'}; border-left: 2px solid ${isAct ? COLORS.cyan : 'transparent'}; border-bottom: 1px solid #0f0f0f; transition: background 0.15s;"
                                                onMouseEnter=${e => { if (!isAct) e.currentTarget.style.background = '#ffffff08'; }}
                                                onMouseLeave=${e => { if (!isAct) e.currentTarget.style.background = 'transparent'; }}>

                                                <div style="display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0;">
                                                    <div style="font-size: 10px; color: ${isAct ? COLORS.cyan : '#aaa'}; font-weight: ${isAct ? 'bold' : 'normal'}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                                                        ${alias}
                                                    </div>
                                                    <div style="font-size: 8px; color: #333; font-family: monospace;">ID: ${id}</div>
                                                </div>

                                                <div style="display: flex; align-items: center; gap: 10px; flex-shrink: 0; margin-left: 12px;">
                                                    ${hasCfg ? html`
                                                        <div style="font-size: 8px; color: #444; font-family: monospace; text-align: right;">
                                                            ${isAct && ddNow > 0 ? html`<span style="color: ${ddNow >= maxDd * 0.8 ? COLORS.red : COLORS.yellow};">DD ${ddNow.toFixed(1)}%/${maxDd}%</span>` : html`<span>Max ${maxDd}%</span>`}
                                                        </div>
                                                    ` : null}
                                                    <div style="font-size: 9px; padding: 2px 7px; border-radius: 10px; background: ${isLk ? COLORS.green + '18' : '#1a0a0a'}; border: 1px solid ${isLk ? COLORS.green + '44' : COLORS.red + '33'}; color: ${isLk ? COLORS.green : COLORS.red}; white-space: nowrap;">
                                                        ${isLk ? '🔒 ARMED' : '🔓 SETUP'}
                                                    </div>
                                                    <button
                                                        onClick=${e => { e.stopPropagation(); setShowAccountMenu(false); setActiveSetup(id); }}
                                                        style="background: #0a0c10; border: 1px solid #222; color: #555; width: 24px; height: 24px; border-radius: 3px; cursor: pointer; font-size: 11px; display: flex; align-items: center; justify-content: center;"
                                                        title="Cấu hình tài khoản ${id}">⚙</button>
                                                </div>
                                            </div>
                                        `;
                                    })}

                                    <!-- Add account button -->
                                    <div
                                        onClick=${() => { setShowAccountMenu(false); setActiveSetup('__NEW__'); }}
                                        style="padding: 10px 14px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; border-top: 1px solid #1a1a1a; color: ${COLORS.yellow}; font-size: 9px; font-weight: bold; letter-spacing: 1px;"
                                        onMouseEnter=${e => e.currentTarget.style.background = COLORS.yellow + '0a'}
                                        onMouseLeave=${e => e.currentTarget.style.background = 'transparent'}>
                                        ＋ THÊM TÀI KHOẢN MỚI
                                    </div>
                                </div>
                            ` : null}
                        </div>
                        <!-- ── END ACCOUNT SWITCHER ── -->

                    </div>
                </div>


                

                <!-- Sprint B: User Info Bar -->
                ${authUser ? html`

                    <div style="background:#050a10;border:1px solid #1a2535;border-radius:4px;padding:7px 14px;display:flex;align-items:center;gap:12px;flex-shrink:0;">
                        <span style="font-size:9px;color:#00e5ff;letter-spacing:1px;font-weight:bold;">✅ AUTHENTICATED</span>
                        <span style="font-size:10px;color:#556677;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${authUser.email}</span>
                        <span style="font-size:9px;padding:2px 8px;border-radius:10px;background:#00e5ff15;border:1px solid #00e5ff33;color:#00e5ff;">${authUser.tier || 'TRIAL'}</span>
                        <button
                            onClick=${() => { _clearTokens(); setAuthUser(null); }}
                            style="background:transparent;border:1px solid #1a2030;color:#334;padding:4px 10px;border-radius:3px;cursor:pointer;font-size:9px;font-family:'Courier New',monospace;letter-spacing:1px;"
                            title="Đăng xuất">
                            LOGOUT
                        </button>
                    </div>
                ` : null}

                <div class="top-alert-banner" style="background: ${statusStyle.color + '15'}; border: 1px solid ${statusStyle.color + '55'}; box-shadow: inset 0 0 20px ${statusStyle.color + '11'}; flex-shrink: 0;">
                    
                    <!-- KHU VỰC TRÁI: Regime label -->
                    <div style="display:flex;align-items:center;gap:10px;width:28%;justify-content:flex-start;">
                        <div class=${statusStyle.pulse?"pulse-icon":""} style="font-size:22px;flex-shrink:0;">${statusStyle.icon}</div>
                        <div>
                            <div style="font-size:7px;color:${statusStyle.color};font-weight:bold;letter-spacing:1.5px;margin-bottom:1px;">QUANTITATIVE REGIME</div>
                            <div style="font-size:11px;font-weight:900;color:#fff;text-shadow:0 0 8px ${statusStyle.color+'66'};line-height:1.2;">${statusStyle.label}</div>
                            ${isHibernating?html`<span class="blink-text" style="background:${COLORS.yellow};color:#000;font-size:7px;font-weight:bold;padding:1px 4px;border-radius:2px;margin-top:2px;display:inline-block;">⏸ HIBERNATING</span>` : null}
                            ${physicsRegime==='ACCOUNT_LIQUIDATION'?html`<span class="blink-text" style="background:#ff0000;color:#fff;font-size:7px;font-weight:bold;padding:1px 4px;border-radius:2px;margin-top:2px;display:inline-block;">💀 FLOOR BREACH</span>` : null}
                        </div>
                    </div>

                    <!-- KHU VỰC GIỮA: Z-Pressure + 3 bars -->
                    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;border-left:1px solid #222;border-right:1px solid #222;padding:0 14px;width:44%;">
                        <div style="font-size:7px;color:#555;letter-spacing:1px;margin-bottom:1px;">MASTER Z-PRESSURE (P̂)</div>
                        <div style="font-size:20px;font-weight:bold;color:${finalZColor};font-family:'Courier New',monospace;line-height:1.1;">
                            ${finalZPressure.toFixed(4)}
                        </div>
                        <!-- Weighted contribution: L/G/A = đóng góp thực vào Z (weighted), không phải raw % -->
                        ${(() => {
                            const aw = physics.adaptive_weights || {};
                            const lc = Math.min(1.0, physics.base_pressure || 0);
                            const gc = Math.min(1.0, physics.daily_trailing_pressure || physics.trailing_pressure || 0);
                            const ac = Math.min(1.0, (physics.account_proximity_pressure || 0) / 0.15);
                            const contribL = (aw.daily_loss || 0.4) * lc;
                            const contribG = (aw.giveback || 0.2) * gc;
                            const contribA = (aw.account || 0.3) * ac;
                            const total = contribL + contribG + contribA;
                            if (total < 0.005) return '';
                            return html`
                                <div style="font-size:7px; color:#333; margin-top:1px; display:flex; gap:5px; letter-spacing:0.5px;" title="Đóng góp có trọng số vào Z (L=Loss G=Giveback A=Account)">
                                    ${contribL>0.005 ? html`<span style="color:${COLORS.cyan}55;">L:${(contribL*100).toFixed(0)}%</span>` : null}
                                    ${contribG>0.005 ? html`<span style="color:${COLORS.yellow}66;">G:${(contribG*100).toFixed(0)}%</span>` : null}
                                    ${contribA>0.005 ? html`<span style="color:${COLORS.red}66;">A:${(contribA*100).toFixed(0)}%</span>` : null}
                                </div>
                            `;
                        })()}
                        <div style="width: 100%; margin-top: 6px; display: flex; flex-direction: column; gap: 5px;">

                            <!-- Bar 1: BASE — áp suất budget ngày -->
                            <div style="display: flex; align-items: center; gap: 5px;" title="BASE: Floating SL / Remaining Daily Budget">
                                <span style="font-size: 7px; color: #888; width: 42px; text-align: right; letter-spacing: 0.5px;">BASE</span>
                                <div style="flex: 1; height: 4px; background: #111; border-radius: 2px; overflow: hidden; border: 1px solid #222;">
                                    <div style="width: ${Math.min(basePct, 100)}%; height: 100%; background: ${basePct >= 80 ? COLORS.red : COLORS.cyan}; transition: width 0.3s;"></div>
                                </div>
                                <span style="font-size: 7px; color: #555; width: 26px; text-align: left; font-family: monospace;">${Math.min(basePct, 100).toFixed(0)}%</span>
                            </div>

                            <!-- Bar 2: D.TRAIL — daily trailing profit giveback -->
                            <div style="display: flex; align-items: center; gap: 5px;" title="DAILY TRAIL: Giveback lợi nhuận ngày / Allowed giveback (profit_lock_pct)">
                                <span style="font-size: 7px; color: ${COLORS.yellow}; width: 42px; text-align: right; letter-spacing: 0.5px;">D.TRAIL</span>
                                <div style="flex: 1; height: 4px; background: #111; border-radius: 2px; overflow: hidden; border: 1px solid #222;">
                                    <div style="width: ${Math.min(dailyGivebackPct, 100)}%; height: 100%; background: ${dailyGivebackPct >= 80 ? COLORS.red : COLORS.yellow}; transition: width 0.3s;"></div>
                                </div>
                                <span style="font-size: 7px; color: ${COLORS.yellow}; width: 26px; text-align: left; font-family: monospace;">${Math.min(dailyGivebackPct, 100).toFixed(0)}%</span>
                            </div>

                            <!-- Bar 3: A.WALL — khoảng cách đến Account Floor (inverted: đầy = gần sàn) -->
                            <!-- NOTE: T.WALL/S.WALL là CẢNH BÁO proximity, KHÔNG phải Z input trực tiếp -->
                            <!-- account_component trong Z chỉ active khi buffer < 30% warn zone -->
                            ${(() => {
                                const consumed = Math.max(0, Math.min(100, 100 - accountBufferPct));
                                const wallColor = consumed >= 90 ? '#ff0000'
                                    : consumed >= 70 ? COLORS.red
                                    : consumed >= 40 ? COLORS.yellow : '#333';
                                const wallLabel = ddType === 'TRAILING' ? 'T.WALL' : 'S.WALL';
                                // account_component trong Z chỉ active khi consumed > 70% (buffer < 30%)
                                const isZActive = consumed > 70;
                                const wallTitle = `${ddType} ACCOUNT FLOOR: $${accountHardFloor > 0 ? accountHardFloor.toFixed(0) : '?'} | Buffer: ${accountBufferPct.toFixed(0)}% còn lại${isZActive ? ' ⚠ ĐANG ĐÓ VÀO Z' : ' (chưa ảnh hưởng Z)'}`;
                                return html`
                                    <div style="display: flex; align-items: center; gap: 5px;" title="${wallTitle}">
                                        <span style="font-size: 7px; color: ${isZActive ? COLORS.red : '#444'}; width: 42px; text-align: right; letter-spacing: 0.5px;">${wallLabel}</span>
                                        <div style="flex: 1; height: 4px; background: #111; border-radius: 2px; overflow: hidden; border: 1px solid ${consumed >= 40 ? COLORS.red + '44' : '#1a1a1a'};">
                                            <div style="width: ${consumed}%; height: 100%; background: ${isZActive ? wallColor : '#2a2a2a'}; transition: width 0.3s;"></div>
                                        </div>
                                        <span style="font-size: 7px; color: ${isZActive ? COLORS.red : '#333'}; width: 26px; text-align: left; font-family: monospace;">${consumed > 0 ? consumed.toFixed(0)+'%' : '—'}</span>
                                    </div>
                                `;
                            })()}
                        </div>
                    </div>

                    <!-- KHU VỰC PHẢI: Balance/Equity + Damping + DD -->
                    <div style="text-align:right; width:28%; padding-right:4px; display:flex; flex-direction:column; gap:5px; justify-content:center;">

                        <!-- Balance + Equity nổi bật -->
                        <div style="display:flex; justify-content:flex-end; gap:14px; padding-bottom:6px; border-bottom:1px solid #1a1a1a;">
                            <div>
                                <div style="font-size:7px;color:#334;letter-spacing:1px;margin-bottom:1px;">BALANCE</div>
                                <div style="font-size:12px;font-weight:900;color:#777;font-family:monospace;">$${balance.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</div>
                            </div>
                            <div>
                                <div style="font-size:7px;color:#334;letter-spacing:1px;margin-bottom:1px;">EQUITY</div>
                                <div style="font-size:12px;font-weight:900;font-family:monospace;color:${currentEquity >= balance ? COLORS.green : COLORS.red};">$${currentEquity.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</div>
                            </div>
                            <div>
                                <div style="font-size:7px;color:#334;letter-spacing:1px;margin-bottom:1px;">P&L</div>
                                <div style="font-size:12px;font-weight:900;font-family:monospace;color:${netDailyPnL >= 0 ? COLORS.green : COLORS.red};">${netDailyPnL >= 0 ? '+' : null}${netDailyPnL.toFixed(2)}</div>
                            </div>
                        </div>

                        <!-- Damping -->
                        <div style="display:flex; align-items:center; justify-content:flex-end; gap:8px;">
                            <span style="font-size:7px;color:#555;letter-spacing:1px;">DAMPING</span>
                            <div style="width:50px;height:5px;background:#111;border:1px solid #333;border-radius:2px;overflow:hidden;">
                                <div style="width:${finalDamping*100}%;height:100%;background:${finalDamping===1.0?COLORS.green:finalDamping===0?COLORS.red:COLORS.yellow};transition:0.3s;"></div>
                            </div>
                            <span style="font-size:13px;font-weight:900;color:${finalDamping<1.0?COLORS.yellow:COLORS.green};">${finalDamping.toFixed(1)}x</span>
                        </div>

                        <!-- DD badges row -->
                        <div style="display:flex; justify-content:flex-end; gap:4px; flex-wrap:wrap;">
                            <div style="font-size:7px;padding:2px 6px;border-radius:2px;
                                background:${ddType==='TRAILING'?COLORS.red+'18':'#0a0a0a'};
                                border:1px solid ${accountBufferPct<=30?COLORS.red:ddType==='TRAILING'?COLORS.red+'55':'#2a2a2a'};
                                color:${accountBufferPct<=30?COLORS.red:ddType==='TRAILING'?COLORS.red+'cc':'#444'};"
                                title="${ddType} Floor: $${accountHardFloor>0?accountHardFloor.toFixed(0):'?'} | Buffer ${accountBufferPct.toFixed(0)}%">
                                ${ddType==='TRAILING'?'📉':'🔒'} ${ddType}${accountHardFloor>0?' $'+accountHardFloor.toLocaleString('en-US',{maximumFractionDigits:0}):''}
                            </div>
                            ${(() => {
                                const dp = dailyPeak - startBalance;
                                if (dp > 0) return html`
                                    <div style="font-size:7px;padding:2px 6px;border-radius:2px;
                                        background:${COLORS.yellow}10;
                                        border:1px solid ${dailyGivebackPct>=60?COLORS.yellow:COLORS.yellow+'33'};
                                        color:${dailyGivebackPct>=60?COLORS.yellow:COLORS.yellow+'77'};"
                                        title="Daily Peak (Tầng 2)">
                                        🏔 +$${dp.toLocaleString('en-US',{maximumFractionDigits:0})}
                                    </div>
                                `;
                                return '';
                            })()}
                            ${accountHardFloor>0&&accountDdPct>0?html`
                                <div style="font-size:7px;color:${accountDdPct>=maxDdPct*0.7?COLORS.red:'#444'};font-family:monospace;padding:2px 0;">
                                    ACC.DD ${accountDdPct.toFixed(1)}%/${maxDdPct}%
                                </div>
                            ` : null}

                        </div>
                    </div>
                </div>

                <!-- ── RADAR MAP STRIP ── -->
                ${Object.keys(radarMap).length > 0 ? html`

                    <div style="background:#050810;border:1px solid #0d1525;border-radius:4px;padding:6px 12px;display:flex;align-items:center;gap:8px;flex-shrink:0;flex-wrap:wrap;">
                        <span style="font-size:8px;color:#334;letter-spacing:2px;font-weight:bold;white-space:nowrap;">📡 RADAR</span>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;flex:1;">
                        ${Object.entries(radarMap).map(([key, r]) => {
                            const sc = radarScoreColor(r.score);
                            const rc = radarRegimeColor(r.regime);
                            const blocked = !r.allow_trade;
                            return html`
                                <div style="display:flex;align-items:center;gap:5px;background:${blocked?'#1a0005':'#080c12'};
                                    border:1px solid ${blocked?COLORS.red+'44':sc+'33'};border-radius:3px;padding:3px 8px;white-space:nowrap;">
                                    <span style="font-size:9px;color:${sc};font-weight:bold;font-family:monospace;">${r.score?.toFixed(0) ?? '--'}</span>
                                    <span style="font-size:8px;color:#334;">${key.split('/')[0]}</span>
                                    <span style="font-size:7px;color:${rc};background:${rc}18;padding:1px 4px;border-radius:2px;">${r.regime?.replace(/_/g,' ') || ''}</span>
                                    ${blocked ? html`<span style="font-size:7px;color:${COLORS.red};font-weight:bold;">🚫</span>` : html`<span style="font-size:7px;color:#555;">${r.position_pct}%</span>`}
                                </div>
                            `;
                        })}
                        </div>
                        <div style="display:flex;align-items:center;gap:4px;">
                            ${['H1','M15','M5'].map(tf => html`
                                <button onClick=${()=>setRadarTF(tf)}
                                    style="background:${radarTF===tf?COLORS.cyan+'22':'transparent'};border:1px solid ${radarTF===tf?COLORS.cyan+'66':'#1a1a1a'};
                                    color:${radarTF===tf?COLORS.cyan:'#333'};padding:2px 7px;border-radius:2px;cursor:pointer;font-size:8px;font-family:monospace;">
                                    ${tf}
                                </button>
                            `)}
                            <button onClick=${fetchRadarMap}
                                style="background:transparent;border:1px solid #1a1a1a;color:#222;padding:2px 7px;border-radius:2px;cursor:pointer;font-size:8px;"
                                title="Refresh radar">↻</button>
                        </div>
                    </div>
                ` : null}

                <div class="scanline-bg" style="background-color:${COLORS.panelBg};border:1px solid ${COLORS.border};position:relative;min-height:220px;flex-shrink:0;display:flex;flex-direction:column;">
                    <canvas ref=${radarCanvasRef} style="width:100%;flex:1;display:block;min-height:180px;"></canvas>
                    <!-- Summary strip -->
                    <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 12px;border-top:1px solid #111;background:#030507;flex-shrink:0;">
                        <div style="display:flex;gap:14px;">
                            <span style="font-size:8px;color:#334;">P̂ <span style="color:${finalZColor};font-weight:900;">${(finalZPressure*100).toFixed(1)}%</span></span>
                            <span style="font-size:8px;color:#334;">Ê <span style="color:${COLORS.purple};font-weight:900;">${frePct.toFixed(1)}%</span></span>
                            <span style="font-size:8px;color:#334;">B̂ <span style="color:${COLORS.cyan};font-weight:900;">${dbuPct.toFixed(1)}%</span></span>
                        </div>
                        <div style="display:flex;gap:12px;font-size:8px;font-family:monospace;">
                            <span style="color:#2a2a2a;">BAL: <span style="color:#666;">$${balance.toFixed(2)}</span></span>
                            <span style="color:#2a2a2a;">EQ: <span style="color:${currentEquity>=balance?COLORS.green:COLORS.red};">$${currentEquity.toFixed(2)}</span></span>
                            <span style="color:#2a2a2a;">TRADES: <span style="color:${activeTrades.length>0?COLORS.cyan:'#444'};">${activeTrades.length}</span></span>
                        </div>
                    </div>
                </div>

                <div style="background:${COLORS.panelBg};border:1px solid ${COLORS.border};display:flex;flex-direction:column;flex:1;min-height:200px;flex-shrink:0;">

                    <div style="padding:6px 12px;border-bottom:1px solid #0f0f0f;display:flex;justify-content:space-between;align-items:center;background:#05070b;flex-shrink:0;">
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="font-size:10px;color:${COLORS.cyan};font-weight:bold;letter-spacing:1.5px;white-space:nowrap;">⚖ POSITION MONITOR</span>
                            <div style="width:1px;height:14px;background:#1a1a1a;flex-shrink:0;"></div>
                            <span style="font-size:8px;color:${disciplineColor};border:1px solid ${disciplineColor}44;padding:2px 8px;border-radius:2px;background:${disciplineColor}0c;white-space:nowrap;">
                                ${disciplineStatus}
                            </span>
                            ${activeTrades.length > 0 ? html`
                                <span style="font-size:7px;color:#2a2a2a;letter-spacing:1px;white-space:nowrap;">${activeTrades.length} OPEN</span>
                            ` : null}
                        </div>
                        <div style="display:flex;gap:10px;align-items:center;">
                            ${activeTrades.length > 0 ? html`
                                <div style="text-align:right;">
                                    <div style="font-size:6px;color:#333;letter-spacing:1px;">TOTAL FLOAT</div>
                                    <div style="font-size:12px;font-weight:900;font-family:monospace;color:${activeTrades.reduce((s,t)=>s+parseFloat(t.profit||t.pnl||0),0)>=0?COLORS.green:COLORS.red};">
                                        ${(()=>{ const t=activeTrades.reduce((s,t)=>s+parseFloat(t.profit||t.pnl||0),0); return (t>=0?'+':'')+t.toFixed(2)+' $'; })()}
                                    </div>
                                </div>
                            ` : null}
                            ${isHibernating ? html`<button onClick=${handleReboot} style="background:${COLORS.green}18;border:1px solid ${COLORS.green}88;color:${COLORS.green};font-weight:900;font-size:9px;padding:4px 12px;cursor:pointer;border-radius:2px;animation:blinker 1.5s infinite;">⚡ REBOOT</button>` : null}
                            <button onClick=${handlePanicKill}
                                style="background:linear-gradient(135deg,#6b0000,#420000);border:1px solid #ff000044;color:#cc4444;font-weight:900;font-size:9px;padding:4px 14px;cursor:pointer;border-radius:2px;letter-spacing:1px;transition:.2s;"
                                onMouseEnter=${e=>{e.target.style.background='linear-gradient(135deg,#aa0000,#770000)';e.target.style.color='#fff';}}
                                onMouseLeave=${e=>{e.target.style.background='linear-gradient(135deg,#6b0000,#420000)';e.target.style.color='#cc4444';}}>
                                ☢ SCRAM
                            </button>
                        </div>
                    </div>

                    <div class="financial-stats">
                        <!-- Col 1: Target -->
                        <div style="text-align:center;display:flex;flex-direction:column;justify-content:center;align-items:center;">
                            <div style="font-size:7px;color:#555;letter-spacing:1px;margin-bottom:2px;">🎯 MỤC TIÊU</div>
                            <div style="font-size:12px;color:${COLORS.cyan};font-weight:bold;">$${configuredTarget.toFixed(2)}</div>
                            <div style="font-size:8px;color:${saturationPct>=100?COLORS.green:'#555'};">${saturationPct.toFixed(1)}%</div>
                            <div style="width:75%;height:3px;background:#111;margin-top:3px;border-radius:2px;overflow:hidden;">
                                <div style="width:${saturationPct}%;height:100%;background:${saturationPct>=100?COLORS.green:COLORS.cyan};transition:0.5s;"></div>
                            </div>
                        </div>
                        <!-- Col 2: Floating Risk -->
                        <div style="text-align:center;display:flex;flex-direction:column;justify-content:center;">
                            <div style="font-size:7px;color:${COLORS.red};letter-spacing:1px;">FLOATING RISK</div>
                            <div style="font-size:13px;color:${COLORS.red};font-weight:bold;">${formatMoney(sumFloatingRisk)}</div>
                            <div style="font-size:7px;color:#334;">${activeTrades.length} lệnh</div>
                        </div>
                        <!-- Col 3: Projected Yield -->
                        <div style="text-align:center;display:flex;flex-direction:column;justify-content:center;">
                            <div style="font-size:7px;color:#b565ff;letter-spacing:1px;">PROJECTED YIELD</div>
                            <div style="font-size:13px;color:#b565ff;font-weight:bold;">${formatMoney(sumProjectedYield)}</div>
                            <div style="font-size:7px;color:#334;">nếu TP hit</div>
                        </div>
                        <!-- Col 4: Live Edge -->
                        <div style="text-align:center;display:flex;flex-direction:column;justify-content:center;">
                            <div style="font-size:7px;color:${disciplineColor};letter-spacing:1px;">LIVE EDGE</div>
                            <div style="font-size:13px;color:${disciplineColor};font-weight:bold;">1:${kineticRatio.toFixed(2)}</div>
                            <div style="font-size:7px;color:#334;">R:R thực tế</div>
                        </div>
                        <!-- Col 5: Daily PnL -->
                        <div style="text-align:center;display:flex;flex-direction:column;justify-content:center;">
                            <div style="font-size:7px;color:${netDailyPnL>=0?COLORS.green:COLORS.red};letter-spacing:1px;">DAILY P&L</div>
                            <div style="font-size:13px;font-weight:bold;color:${netDailyPnL>=0?COLORS.green:COLORS.red};">${netDailyPnL>=0?'+':''}${netDailyPnL.toFixed(2)}$</div>
                            <div style="font-size:7px;color:#334;">EQ $${currentEquity.toFixed(2)}</div>
                        </div>
                    </div>

                    <div style="padding:4px 12px;background:#040608;border-bottom:1px solid #0a0a0a;display:flex;align-items:center;gap:8px;" title="Risk Bar — Đỏ: Floating SL Risk | Tím: Projected TP Yield">
                        <span style="font-size:7px;font-weight:bold;color:${disciplineColor};letter-spacing:1.5px;white-space:nowrap;min-width:46px;">⚡ EDGE</span>
                        <div style="flex:1;height:4px;background:#080808;border-radius:2px;overflow:hidden;border:1px solid #0f0f0f;position:relative;">
                            <div style="position:absolute;left:0;top:0;width:${riskBarPct}%;height:100%;background:${COLORS.red};opacity:0.8;transition:width .5s;"></div>
                            <div style="position:absolute;left:${riskBarPct}%;top:0;width:${rewardBarPct}%;height:100%;background:${COLORS.purple};opacity:0.8;transition:left .5s,width .5s;"></div>
                        </div>
                        <div style="font-size:8px;font-family:monospace;display:flex;gap:8px;align-items:center;white-space:nowrap;flex-shrink:0;">
                            <span style="color:${COLORS.red}88;">-${sumFloatingRisk.toFixed(0)}$</span>
                            <span style="color:#181818;">|</span>
                            <span style="color:#b565ff88;">+${sumProjectedYield.toFixed(0)}$</span>
                            <span style="color:#1e1e1e;border-left:1px solid #111;padding-left:8px;font-size:7px;">1:${kineticRatio.toFixed(2)}</span>
                        </div>
                    </div>

                    <div class="trade-table-container scanline-bg">
                        <${ComplianceAlertBanner} alerts=${complianceAlerts} onDismiss=${() => setComplianceAlerts([])} COLORS=${COLORS} />
                        ${(() => {
                            const blocked = Object.entries(radarMap).filter(([,r]) => !r.allow_trade);
                            if (blocked.length === 0) return '';
                            return html`<div style="background:#1a0005;border:1px solid ${COLORS.red}44;padding:6px 14px;display:flex;align-items:center;gap:10px;">
                                <span style="font-size:9px;color:${COLORS.red};font-weight:bold;white-space:nowrap;">🚫 RADAR BLOCK</span>
                                <span style="font-size:9px;color:#cc3355;flex:1;">${blocked.map(([k,r])=>`${k.split('/')[0]} (${r.score?.toFixed(0) ?? '--'} — ${r.regime || ''})`).join(' · ')} — Score < 30, không nên vào lệnh</span>
                                <button onClick=${fetchRadarMap} style="background:transparent;border:1px solid #cc3355;color:#cc3355;padding:2px 8px;border-radius:2px;cursor:pointer;font-size:8px;">REFRESH</button>
                            </div>`;
                        })()}

                        <div class="trade-row" style="padding:5px 10px;border-bottom:1px solid #0f0f0f;background:#020304;position:sticky;top:0;z-index:5;">
                            <span style="color:#2e2e2e;font-size:8px;letter-spacing:.5px;">TICKET</span>
                            <span style="color:#3a3a3a;font-size:8px;letter-spacing:.5px;">ASSET</span>
                            <span style="color:#2e2e2e;font-size:8px;letter-spacing:.5px;">DIR</span>
                            <span style="color:#3a3a3a;font-size:8px;letter-spacing:.5px;">VOL</span>
                            <span style="color:#2e2e2e;font-size:8px;letter-spacing:.5px;">ENTRY</span>
                            <span style="color:#3a3a3a;font-size:8px;letter-spacing:.5px;">CURRENT</span>
                            <span style="color:${COLORS.red};font-size:8px;letter-spacing:.5px;">SL · RISK$</span>
                            <span style="color:#7a44bb;font-size:8px;letter-spacing:.5px;">TP · YIELD$</span>
                            <span style="color:${COLORS.yellow};font-size:8px;letter-spacing:.5px;">R:R</span>
                            <span style="color:#2e2e2e;font-size:8px;letter-spacing:.5px;">SWAP</span>
                            <span style="color:#444;text-align:right;font-size:8px;letter-spacing:.5px;">FLOAT PNL</span>
                        </div>
                        ${(globalStatus.open_trades || []).length === 0 ? html`
                            <div style="text-align:center;padding:30px 0;display:flex;flex-direction:column;align-items:center;gap:5px;">
                                <div style="font-size:20px;opacity:0.08;">◎</div>
                                <div style="font-size:8px;letter-spacing:3px;color:#181818;font-weight:bold;">NO OPEN POSITIONS</div>
                                <div style="font-size:7px;color:#111;letter-spacing:1px;">Polling live · 1s interval</div>
                            </div>
                        ` : null}
                        ${(globalStatus.open_trades || []).map(t => {
                            const rRisk = Math.abs(parseFloat(t.stl_money) || 0);
                            const rReward = parseFloat(t.tp_money) || 0;
                            let tradeRR = 0;
                            let edgeDisplay = "0.0";
                            let edgeColor = COLORS.red;

                            if (rRisk === 0 && rReward === 0) {
                                edgeDisplay = "NO SL/TP";
                                edgeColor = COLORS.red;
                            } else if (rRisk === 0) {
                                edgeDisplay = "NO SL !";
                                edgeColor = "#ff0000"; 
                            } else {
                                tradeRR = rReward / rRisk;
                                edgeDisplay = `1 : ${tradeRR.toFixed(1)}`;
                                if (tradeRR >= targetRR) edgeColor = COLORS.green; 
                                else if (tradeRR >= 1.0) edgeColor = COLORS.yellow; 
                            }

                            const bgStyle = rRisk === 0 ? `repeating-linear-gradient(45deg, #330000, #330000 10px, rgba(0,0,0,0.8) 10px, rgba(0,0,0,0.8) 20px)` : `rgba(0,0,0,0.4)`;

                            // ── Field normalisation ─────────────────────────────────────
                                // Backend (dashboard_service.py) gửi: lots, entry_price, side(str), profit, swap, sl, tp, stl_money, tp_money, current_price
                                // Fallback sang các tên cũ cho backward-compat
                                const vol   = parseFloat(t.lots   || t.volume     || 0);
                                const opx   = parseFloat(t.entry_price || t.open_price || t.price || 0);
                                const curPx = parseFloat(t.current_price || t.price_current || 0);
                                const swap  = parseFloat(t.swap   || 0);
                                const pnl   = parseFloat(t.profit || t.pnl        || 0);
                                const slRaw = parseFloat(t.sl     || 0);
                                const tpRaw = parseFloat(t.tp     || 0);
                                const slMny = parseFloat(t.stl_money || 0);   // âm = risk$
                                const tpMny = parseFloat(t.tp_money  || 0);   // dương = yield$

                                // Direction: backend gửi side='BUY'/'SELL' (string), hoặc type=0/1 (int)
                                const dir   = t.side
                                    ? String(t.side).toUpperCase().replace('ORDER_TYPE_','').replace(/_/g,' ')
                                    : (t.type === 0 ? 'BUY' : t.type === 1 ? 'SELL'
                                       : String(t.type || '').replace('ORDER_TYPE_','').replace(/_/g,' ').toUpperCase());
                                const isBuy = dir === 'BUY' || dir.startsWith('BUY');
                                const fmtPx = v => v >= 100 ? v.toFixed(2) : v.toFixed(5);

                                // Current price delta vs entry
                                const hasCur    = curPx > 0 && opx > 0;
                                const rawDelta  = hasCur ? curPx - opx : null;
                                const pipDelta  = rawDelta !== null ? (isBuy ? rawDelta : -rawDelta) : null;
                                const deltaCol  = pipDelta === null ? '#333' : pipDelta > 0 ? COLORS.green : COLORS.red;

                                // SL / TP display strings
                                const slStr = slRaw > 0 ? fmtPx(slRaw) : slMny < 0 ? '—' : '—';
                                const tpStr = tpRaw > 0 ? fmtPx(tpRaw) : '—';

                                // PnL colour + class
                                const pnlCol   = pnl > 0 ? COLORS.green : pnl < 0 ? COLORS.red : '#555';
                                const pnlClass = pnl > 0 ? 'pnl-pos' : pnl < 0 ? 'pnl-neg' : '';
                                const pnlFmt   = (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + ' $';

                                // Regime fit badge (backend provides)
                                const fitScore = parseFloat(t.regime_fit_score ?? 100);
                                const fitBadge = fitScore <= 30 ? html`<span style="font-size:6px;color:${COLORS.red};letter-spacing:.3px;">MISMATCH</span>`
                                               : fitScore <= 70 ? html`<span style="font-size:6px;color:${COLORS.yellow};letter-spacing:.3px;">ELEVATED</span>`
                                               : null;

                                const radarInfo    = getRadarForSymbol(t.symbol);
                                const radarBlocked = radarInfo && !radarInfo.allow_trade;
                                const radarScore   = radarInfo?.score;
                                const radarSc      = radarScoreColor(radarScore);
                                const tradeBg      = radarBlocked
                                    ? 'repeating-linear-gradient(45deg,#180004,#180004 10px,rgba(0,0,0,0.95) 10px,rgba(0,0,0,0.95) 20px)'
                                    : rRisk === 0
                                        ? 'repeating-linear-gradient(45deg,#180000,#180000 8px,rgba(0,0,0,0.92) 8px,rgba(0,0,0,0.92) 16px)'
                                        : 'transparent';

                                const borderCol = radarBlocked ? COLORS.red
                                    : pnl > 0 ? COLORS.green + '77'
                                    : pnl < 0 ? COLORS.red   + '55'
                                    : radarScore >= 70 ? COLORS.green + '33'
                                    : radarScore >= 50 ? COLORS.cyan  + '33'
                                    : '#151515';

                                return html`
                                <div class="trade-row" style="padding:5px 10px;border-bottom:1px solid #0a0a0a;background:${tradeBg};border-left:2px solid ${borderCol};transition:background .15s;"
                                     title="#${t.ticket} ${t.symbol} ${dir} | Vol:${vol.toFixed(2)} | Entry:${opx>0?fmtPx(opx):'—'} | Current:${curPx>0?fmtPx(curPx):'live'} | SL:${slRaw||'—'} TP:${tpRaw||'—'} | Risk:${slMny.toFixed(2)}$ Yield:${tpMny.toFixed(2)}$ | Swap:${swap.toFixed(2)} | PnL:${pnlFmt}">

                                    <!-- TICKET + radar score + fit badge -->
                                    <span style="display:flex;flex-direction:column;gap:1px;">
                                        <span style="color:#3a3a3a;font-family:monospace;font-size:9px;">#${t.ticket}</span>
                                        ${radarScore != null ? html`<span style="font-size:6.5px;color:${radarSc};font-family:monospace;">${radarScore.toFixed(0)}</span>` : null}
                                        ${fitBadge}
                                    </span>

                                    <!-- SYMBOL -->
                                    <span style="color:${COLORS.cyan};font-weight:bold;font-size:10px;">${t.symbol || '—'}</span>

                                    <!-- DIR -->
                                    <span style="color:${isBuy?COLORS.green:COLORS.red};font-weight:900;font-size:10px;">${dir || '—'}</span>

                                    <!-- VOL -->
                                    <span style="color:#666;font-family:monospace;">${vol > 0 ? vol.toFixed(2) : '—'}</span>

                                    <!-- ENTRY -->
                                    <span style="color:#383838;font-family:monospace;font-size:9px;">${opx > 0 ? fmtPx(opx) : '—'}</span>

                                    <!-- CURRENT PRICE (live) -->
                                    <span style="display:flex;flex-direction:column;gap:1px;">
                                        <span style="color:${curPx > 0 ? '#666' : '#1e1e1e'};font-family:monospace;font-size:9px;">${curPx > 0 ? fmtPx(curPx) : '—'}</span>
                                        ${pipDelta !== null ? html`
                                            <span style="font-size:6.5px;color:${deltaCol};font-family:monospace;">
                                                ${pipDelta >= 0 ? '▲' : '▼'} ${Math.abs(rawDelta).toFixed(rawDelta < 0.1 ? 5 : 2)}
                                            </span>
                                        ` : null}
                                    </span>

                                    <!-- SL + risk$ -->
                                    <span style="display:flex;flex-direction:column;gap:1px;">
                                        ${rRisk === 0
                                            ? html`<span style="color:#ff3333;font-weight:bold;font-size:9px;">⚠ NO SL</span>`
                                            : html`<span style="color:#554444;font-family:monospace;font-size:9px;">${slStr}</span>`}
                                        ${slMny < 0 ? html`<span style="font-size:6.5px;color:${COLORS.red}99;font-family:monospace;">${slMny.toFixed(2)}$</span>` : null}
                                    </span>

                                    <!-- TP + yield$ -->
                                    <span style="display:flex;flex-direction:column;gap:1px;">
                                        <span style="color:${tpRaw > 0 ? '#664488' : '#1e1e1e'};font-family:monospace;font-size:9px;">${tpStr}</span>
                                        ${tpMny > 0 ? html`<span style="font-size:6.5px;color:#b565ff88;font-family:monospace;">+${tpMny.toFixed(2)}$</span>` : null}
                                    </span>

                                    <!-- R:R EDGE -->
                                    <span style="color:${edgeColor};font-weight:bold;background:${edgeColor}12;padding:2px 5px;border-radius:2px;font-size:9px;text-align:center;">${edgeDisplay}</span>

                                    <!-- SWAP -->
                                    <span style="color:${swap < 0 ? '#773333' : swap > 0 ? '#337755' : '#222'};font-family:monospace;font-size:9px;">${swap !== 0 ? (swap > 0 ? '+' : '') + swap.toFixed(2) : '—'}</span>

                                    <!-- FLOAT PNL (live, always visible) -->
                                    <span class="${pnlClass}" style="text-align:right;font-weight:900;color:${pnlCol};font-size:10px;font-family:monospace;background:${pnlCol}0f;padding:2px 5px;border-radius:2px;">${pnlFmt}</span>
                                </div>
                            `;
                        })}
                    </div>
                </div>
            </main>

            <aside style="display: flex; flex-direction: column; overflow: hidden; height: 100%;">
                <${RightColumn} 
                    globalStatus=${globalStatus} 
                    unitsConfig=${unitsConfig}
                    activeTrades=${globalStatus.open_trades} 
                    onOpenSetup=${() => setActiveSetup(currentAccountId)} 
                    onOpenAiBudget=${() => setShowAiBudget(true)} 
                    COLORS=${COLORS} 
                />
            </aside>

            ${activeSetup ? html`<${SetupModal} activeSetup=${activeSetup} isLocked=${isLocked} unitsConfig=${unitsConfig} globalStatus=${globalStatus} fetchData=${fetchData} onClose=${() => setActiveSetup(null)} COLORS=${COLORS} />` : null}
            ${showMacro ? html`<${MacroModal} activeSetup=${currentAccountId} globalStatus=${globalStatus} unitsConfig=${unitsConfig} myUnitConfig=${myUnitConfig} COLORS=${COLORS} fetchData=${fetchData} onClose=${() => setShowMacro(false)} />` : null}
            ${showAiBudget ? html`<${AiGuardCenter} activeSetup=${currentAccountId} isLocked=${isLocked} unitsConfig=${unitsConfig} globalStatus=${globalStatus} fetchData=${fetchData} onClose=${() => setShowAiBudget(false)} COLORS=${COLORS} />` : null}
            
            <${DebriefingPanel} session=${showDebrief} onClose=${() => setShowDebrief(null)} COLORS=${COLORS} />
        </div>
    `;
}