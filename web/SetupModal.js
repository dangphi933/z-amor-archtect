import { h } from 'preact';
import { useState, useEffect, useRef } from 'preact/hooks';
import htm from 'htm';
const html = htm.bind(h);

// F-06: Auth token helper for SetupModal
const _smGetToken = () => localStorage.getItem('za_access_token') || '';


const API_BASE = window.location.hostname === 'localhost'
    || window.location.hostname === '127.0.0.1'
    || window.location.protocol === 'file:'
    ? 'http://127.0.0.1:8000'
    : `http://${window.location.hostname}:8000`;

// ─── SESSION HELPERS ─────────────────────────────────────────
function getSessionHistory(id) {
    try { return JSON.parse(localStorage.getItem(`zarmor_sessions_${id}`) || '[]'); } catch { return []; }
}
function getTodaySession(id) {
    try { return JSON.parse(localStorage.getItem(`zarmor_current_session_${id}`) || 'null'); } catch { return null; }
}
function calcHealth(sessions) {
    if (!sessions.length) return null;
    const last5     = sessions.slice(-5);
    const avg       = last5.reduce((s, x) => s + (x.compliance_score || 80), 0) / last5.length;
    const winStreak = last5.filter(s => s.pnl > 0).length;
    const trend     = sessions.length >= 2
        ? (sessions[sessions.length - 1].compliance_score || 80) - (sessions[sessions.length - 2].compliance_score || 80)
        : 0;
    return { compliance: Math.round(avg), winStreak, total: sessions.length, trend };
}

// ─── RISK DEFAULTS ───────────────────────────────────────────
const RISK_DEF = { max_daily_dd_pct: 5.0, max_dd: 10.0, dd_type: 'STATIC', consistency: 97, rollover_hour: 0, broker_timezone: 2 };

function buildForm(cfg) {
    const risk = cfg.risk_params     || {};
    const tg   = cfg.telegram_config || {};
    return {
        alias:            cfg.alias           || '',
        mt5_login:        cfg.mt5_login        || '',
        telegram_chat_id: tg.chat_id           || '',
        telegram_active:  tg.is_active !== undefined ? tg.is_active : true,
        max_daily_dd_pct: risk.max_daily_dd_pct !== undefined ? Number(risk.max_daily_dd_pct) : RISK_DEF.max_daily_dd_pct,
        max_dd:           risk.max_dd           !== undefined ? Number(risk.max_dd)           : RISK_DEF.max_dd,
        dd_type:          risk.dd_type           || RISK_DEF.dd_type,
        consistency:      risk.consistency       !== undefined ? Number(risk.consistency)     : RISK_DEF.consistency,
        rollover_hour:    risk.rollover_hour     !== undefined ? risk.rollover_hour            : RISK_DEF.rollover_hour,
        broker_timezone:  risk.broker_timezone   !== undefined ? risk.broker_timezone          : RISK_DEF.broker_timezone,
    };
}

// ═══════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════
export default function SetupModal({ activeSetup, isLocked, unitsConfig, globalStatus, onClose, COLORS, fetchData }) {
    // __NEW__ mode = mở form trắng để thêm tài khoản mới
    const isNewMode   = activeSetup === '__NEW__';

    // targetId = tài khoản đang được cấu hình trong modal này
    const targetId    = isNewMode ? null : (activeSetup || localStorage.getItem('zarmor_id') || 'MainUnit');
    const resolvedKey = useRef(targetId).current;

    const [form,          setForm]          = useState(() => {
        if (isNewMode) return buildForm({});
        const cfg = (unitsConfig && targetId) ? (unitsConfig[targetId] || {}) : {};
        return buildForm(cfg);
    });
    // Tự điền key từ URL ?key=ZARMOR-T-xxx
    const _urlKey = new URLSearchParams(window.location.search).get('key') || '';
    const [licInput,      setLicInput]      = useState(_urlKey);
    const [isVerified,    setIsVerified]    = useState(false);
    const [isSaving,      setIsSaving]      = useState(false);
    const [saveStatus,    setSaveStatus]    = useState(null);   // null | 'ok' | 'err'
    const [localLocked,   setLocalLocked]   = useState(isNewMode ? false : isLocked);
    const [isHardLocked,  setIsHardLocked]  = useState(false);
    const [strictMsg,     setStrictMsg]     = useState(null);
    const [disarmTimer,   setDisarmTimer]   = useState(0);
    const [liveConn,      setLiveConn]      = useState(false);
    const [isTesting,     setIsTesting]     = useState(false);
    const [testResult,    setTestResult]    = useState(null);   // null | 'ok' | 'err'
    const timerRef = useRef(null);

    const history      = targetId ? getSessionHistory(targetId) : [];
    const todaySession = targetId ? getTodaySession(targetId)   : null;
    const health       = calcHealth(history);

    // ── Dirty tracking: field nào user đã tự tay chỉnh → KHÔNG BAO GIỜ bị sync ghi đè ──
    // Set khi user onInput/onChange, cleared khi saveSetup thành công
    const dirtyFields = useRef(new Set());
    const markDirty   = (field) => dirtyFields.current.add(field);

    // Helper: merge server config vào form, bỏ qua field đã dirty
    const mergeCfg = (built) => setForm(prev => {
        const next = { ...prev };
        for (const [k, v] of Object.entries(built)) {
            if (!dirtyFields.current.has(k)) next[k] = v;
        }
        return next;
    });

    // ── Sync CHỈ 1 LẦN lúc mount (trước khi user chạm vào gì) ──
    const hasSyncedOnMount = useRef(false);
    useEffect(() => {
        if (hasSyncedOnMount.current) return;
        if (isNewMode || !targetId || !unitsConfig) return;
        const cfg = unitsConfig[targetId] || null;
        if (!cfg) return;
        mergeCfg(buildForm(cfg));
        hasSyncedOnMount.current = true;
    }, [unitsConfig, targetId, isNewMode]);

    // ── Sync khi MT5 vừa bật (offline→online transition) ──
    // KHÔNG sync nếu dirtyFields không rỗng (user đang chỉnh dở)
    const prevLiveConn = useRef(false);
    useEffect(() => {
        const justCameOnline = liveConn && !prevLiveConn.current;
        prevLiveConn.current = liveConn;
        if (!justCameOnline) return;
        if (isNewMode || !targetId || !unitsConfig) return;
        if (dirtyFields.current.size > 0) return;   // user đang chỉnh → không đụng
        const cfg = unitsConfig[targetId] || null;
        if (!cfg) return;
        mergeCfg(buildForm(cfg));
    }, [liveConn]);

    useEffect(() => {
        if (!isHardLocked) setLocalLocked(isLocked);
    }, [isLocked, isHardLocked]);

    // ── HardLock timer ──────────────────────────────────────
    useEffect(() => {
        const check = () => {
            const login = form.mt5_login || localStorage.getItem('zarmor_id');
            if (!login) return;
            const raw   = localStorage.getItem(`zarmor_hardlock_${login}`);
            if (raw) {
                const rem = parseInt(raw) - Date.now();
                if (rem > 0) {
                    setIsHardLocked(true); setLocalLocked(true);
                    const h = Math.floor(rem / 3600000), m = Math.floor((rem % 3600000) / 60000);
                    setStrictMsg(`MO KHOA SAU: ${h}h ${m}m`);
                } else {
                    setIsHardLocked(false); setStrictMsg(null);
                    localStorage.removeItem(`zarmor_hardlock_${login}`);
                }
            } else { setIsHardLocked(false); setStrictMsg(null); }
        };
        check();
        const iv = setInterval(check, 1000);
        return () => clearInterval(iv);
    }, [form.mt5_login, isSaving]);

    // ── MT5 live ping + No-MT5 auto-launch logic ───────────────
    // mt5Offline: true ngay khi modal mở nếu chưa thấy MT5 live
    const [mt5Offline, setMt5Offline]           = useState(true);
    const [autoLaunch, setAutoLaunch]            = useState(false);
    const [launchCountdown, setLaunchCountdown]  = useState(60);
    const [isSyncingMT5, setIsSyncingMT5]        = useState(false); // trạng thái nút Sync
    const [syncMT5Msg, setSyncMT5Msg]            = useState(null);  // null | 'ok' | 'err'
    const autoLaunchRef = useRef(null);

    // Cleanup khi unmount
    useEffect(() => () => { if (autoLaunchRef.current) clearInterval(autoLaunchRef.current); }, []);

    // Thử gọi server mở MT5
    const tryOpenMT5 = async () => {
        try {
            await fetch(`${API_BASE}/api/launch-mt5`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ account_id: form.mt5_login }),
                signal: AbortSignal.timeout(5000),
            });
        } catch { console.warn('[MT5] Cannot auto-launch — open MT5 manually'); }
    };

    // Đếm ngược 60s → gọi tryOpenMT5
    const startAutoLaunch = () => {
        if (autoLaunchRef.current) return;
        setAutoLaunch(true);
        setLaunchCountdown(60);
        let cd = 60;
        autoLaunchRef.current = setInterval(() => {
            cd -= 1;
            setLaunchCountdown(cd);
            if (cd <= 0) {
                clearInterval(autoLaunchRef.current);
                autoLaunchRef.current = null;
                setAutoLaunch(false);
                tryOpenMT5();
            }
        }, 1000);
    };

    const cancelAutoLaunch = () => {
        if (autoLaunchRef.current) { clearInterval(autoLaunchRef.current); autoLaunchRef.current = null; }
        setAutoLaunch(false);
        setLaunchCountdown(60);
    };

    // Nút SYNC THỦ CÔNG — kéo config từ server vào form ngay lập tức
    const syncFromMT5 = async () => {
        const id = activePingId || form.mt5_login;
        if (!id) return;
        setIsSyncingMT5(true); setSyncMT5Msg(null);
        try {
            const res  = await fetch(`${API_BASE}/api/init-data?account_id=${id}`,
                { signal: AbortSignal.timeout(5000) });
            const data = await res.json();
            const ok   = data?.physics?.state !== 'DISCONNECTED';
            if (!ok) { setSyncMT5Msg('err'); setTimeout(() => setSyncMT5Msg(null), 3000); return; }

            // Lấy config từ server nếu có
            const cfg = data?.units_config?.[id] || null;
            if (cfg) {
                const built = buildForm(cfg);
                setForm(built);                   // ghi đè toàn bộ bằng data từ server
                setSyncMT5Msg('ok');
            } else {
                setSyncMT5Msg('ok');              // connected nhưng chưa có config → vẫn OK
            }
        } catch { setSyncMT5Msg('err'); }
        finally { setIsSyncingMT5(false); setTimeout(() => setSyncMT5Msg(null), 3000); }
    };

    // activePingId = login ID đã được debounce confirm (≥6 ký tự, ngừng gõ 800ms)
    // Tách khỏi form.mt5_login để tránh ping mỗi lần gõ
    const [activePingId, setActivePingId] = useState('');

    // Debounce: chờ 800ms sau khi ngừng gõ + phải đủ 6 ký tự
    useEffect(() => {
        const raw = (form.mt5_login || '').trim();
        if (raw.length < 6) {
            // Chưa đủ → reset hết, không ping, không banner
            setActivePingId('');
            setLiveConn(false);
            setMt5Offline(false);
            cancelAutoLaunch();
            return;
        }
        // Đủ ký tự → debounce 800ms
        const t = setTimeout(() => setActivePingId(raw), 800);
        return () => clearTimeout(t);
    }, [form.mt5_login]);

    // Ping loop — chỉ chạy khi activePingId thay đổi (đã qua debounce)
    useEffect(() => {
        if (!activePingId) return;

        // Bắt đầu coi như offline, hiện banner, chạy countdown
        setMt5Offline(true);
        setLiveConn(false);
        if (!autoLaunchRef.current) startAutoLaunch();

        if (unitsConfig?.[activePingId]) {
            setIsVerified(true);
            setLicInput('✅ ACTIVE SECURE KEY');
        }

        const ping = async () => {
            try {
                const res  = await fetch(`${API_BASE}/api/init-data?account_id=${activePingId}`,
                    { signal: AbortSignal.timeout(3000) });
                const data = await res.json();
                const ok   = data?.physics?.state !== 'DISCONNECTED';
                setLiveConn(ok);
                if (ok) {
                    setMt5Offline(false);
                    cancelAutoLaunch();
                    setIsVerified(true);
                    setLicInput('✅ ACTIVE SECURE KEY');
                }
            } catch {
                setLiveConn(false);
            }
        };

        ping();
        const iv = setInterval(ping, 2000);
        return () => { clearInterval(iv); cancelAutoLaunch(); };
    }, [activePingId]);

    // ── ACTIONS ─────────────────────────────────────────────
    const executeUnlock = async () => {
        const id = form.mt5_login || resolvedKey;
        localStorage.removeItem(`zarmor_hardlock_${id}`);
        setIsHardLocked(false); setLocalLocked(false);
        try {
            const res = await fetch(`${API_BASE}/api/unlock-unit`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${_smGetToken()}` }, // F-06
                body: JSON.stringify({ account_id: id }), signal: AbortSignal.timeout(5000),
            });
            if (res.ok) fetchData();
        } catch (e) { console.warn('[UNLOCK] Server offline (local-only):', e.message); }
    };

    const handleMouseDown = () => {
        if (strictMsg) { alert(`KHOA CUNG — KHONG THE SUA\n\n${strictMsg}`); return; }
        setDisarmTimer(5);
        timerRef.current = setInterval(() => {
            setDisarmTimer(prev => { if (prev <= 1) { clearInterval(timerRef.current); executeUnlock(); return 0; } return prev - 1; });
        }, 1000);
    };
    const handleMouseUp = () => { clearInterval(timerRef.current); setDisarmTimer(0); };

    const bindLicense = async () => {
        if (!licInput || !form.mt5_login) return alert('Vui long nhap ID MT5 va License Key!');
        if (isVerified) return;
        try {
            const res  = await fetch(`${API_BASE}/api/bind-license`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ license_key: licInput, account_id: form.mt5_login }),
            });
            const data = await res.json();
            if (data.status === 'success' || data.message?.includes('da duoc lien ket')) {
                setIsVerified(true); setLicInput('✅ ACTIVE SECURE KEY');
                localStorage.setItem('zarmor_id', form.mt5_login);
                localStorage.setItem('mt5_login',  form.mt5_login);
                // Đăng ký vào fleet list
                try {
                    const fleet = JSON.parse(localStorage.getItem('zarmor_accounts') || '[]');
                    if (!fleet.includes(form.mt5_login)) {
                        fleet.push(form.mt5_login);
                        localStorage.setItem('zarmor_accounts', JSON.stringify(fleet));
                    }
                } catch {}
                await fetch(`${API_BASE}/api/panic-kill`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${_smGetToken()}` }, // F-06
                    body: JSON.stringify({ account_id: form.mt5_login }),
                });
                fetchData(); alert('KICH HOAT THANH CONG!');
            } else { alert(`TU CHOI:\n${data.message}`); }
        } catch (e) { alert(`Loi ket noi may chu xac thuc!\n${e.message}`); }
    };

    const handleMT5Change = (e) => {
        setForm({ ...form, mt5_login: e.target.value });
        if (isVerified && !liveConn) { setIsVerified(false); setLicInput(''); }
    };

    const testTelegram = async () => {
        if (!form.telegram_chat_id) return alert('Nhap Chat ID truoc khi Test!');
        setIsTesting(true); setTestResult(null);
        try {
            const res = await fetch(`${API_BASE}/api/test-telegram`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chat_id: form.telegram_chat_id }),
            });
            setTestResult(res.ok ? 'ok' : 'err');
        } catch { setTestResult('err'); }
        finally { setIsTesting(false); setTimeout(() => setTestResult(null), 4000); }
    };

    const saveSetup = async () => {
        if (localLocked || isSaving) return;
        if (!form.mt5_login) return alert('Nhap MT5 Login ID!');
        if (!window.confirm('CANH BAO: Sau khi luu, thong so rui ro se KHOA CUNG den ky Rollover. Xac nhan?')) return;
        if (!window.confirm('XAC NHAN LAN CUOI: He thong tu choi moi Disarm den het phien. Nhan OK de truyen tai.')) return;

        setIsSaving(true); setSaveStatus(null);
        try {
            const payload = {
                unit_key:         form.mt5_login,
                alias:            form.alias || `Trader ${form.mt5_login}`,
                mt5_login:        form.mt5_login,
                telegram_config:  { chat_id: form.telegram_chat_id, is_active: form.telegram_active },
                risk_params: {
                    max_daily_dd_pct: Math.max(0.5, Math.min(10,  Number(form.max_daily_dd_pct) || 5.0)),
                    max_dd:           Math.max(0.5, Math.min(20,  Number(form.max_dd)           || 10.0)),
                    dd_type:          form.dd_type       || 'STATIC',
                    consistency:      Number(form.consistency)    || 97,
                    rollover_hour:    Number(form.rollover_hour)   || 0,
                    broker_timezone:  Number(form.broker_timezone) || 2,
                },
            };
            const res = await fetch(`${API_BASE}/api/update-unit-config`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (res.ok) {
                await fetch(`${API_BASE}/api/panic-kill`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${_smGetToken()}` }, // F-06
                    body: JSON.stringify({ account_id: form.mt5_login }),
                });
                const next = new Date();
                next.setHours(Number(form.rollover_hour) || 0, 0, 0, 0);
                if (Date.now() >= next.getTime()) next.setDate(next.getDate() + 1);
                localStorage.setItem('zarmor_id', form.mt5_login);
                localStorage.setItem(`zarmor_hardlock_${form.mt5_login}`, btoa(next.getTime().toString()).replace(/=/g,'')); // F-20: obfuscated
                // Đăng ký vào fleet list nếu chưa có
                try {
                    const fleet = JSON.parse(localStorage.getItem('zarmor_accounts') || '[]');
                    if (!fleet.includes(form.mt5_login)) {
                        fleet.push(form.mt5_login);
                        localStorage.setItem('zarmor_accounts', JSON.stringify(fleet));
                    }
                } catch {}
                setIsHardLocked(true); setLocalLocked(true);
                setSaveStatus('ok');
                dirtyFields.current.clear();   // reset dirty tracking sau khi save
                fetchData();
            } else {
                setSaveStatus('err'); alert('Loi tu may chu khi luu cau hinh!');
            }
        } catch (e) {
            setSaveStatus('err');
            alert('Lỗi kết nối: Không thể lưu cấu hình. Vui lòng thử lại.') // F-22;
        } finally {
            setIsSaving(false);
            setTimeout(() => setSaveStatus(null), 3000);
        }
    };

    const changeAccount = () => {
        if (window.confirm('Ngat ket noi tai khoan hien tai va nhap License moi?')) {
            ['za_access_token','za_refresh_token','za_user','zarmor_id','zarmor_license_key','zarmor_accounts'].forEach(k => localStorage.removeItem(k)); alert('Da ngat ket noi an toan!'); window.location.reload();
        }
    };

    // ── STYLES ──────────────────────────────────────────────
    const C_    = `background:${localLocked ? '#0f0505' : '#0a0c10'}; border:1px solid ${localLocked ? COLORS.red + '44' : '#222'}; color:${localLocked ? COLORS.red + 'aa' : COLORS.cyan};`;
    const inpS  = `width:100%; ${C_} padding:9px 11px; outline:none; font-family:monospace; font-size:12px; box-sizing:border-box; transition:0.3s; border-radius:3px; opacity:${localLocked ? 0.85 : 1};`;
    const selS  = `${inpS} cursor:${localLocked ? 'not-allowed' : 'pointer'}; appearance:none;`;
    const mt5S  = `width:100%; background:${liveConn ? '#002211' : (localLocked ? '#0f0505' : '#0a0c10')}; border:1px solid ${liveConn ? '#00ff9d' : (localLocked ? COLORS.red + '44' : '#222')}; color:${liveConn ? '#00ff9d' : (localLocked ? COLORS.red : COLORS.cyan)}; padding:9px 11px; outline:none; font-family:monospace; font-size:12px; box-sizing:border-box; transition:0.3s; border-radius:3px; font-weight:${liveConn ? 'bold' : 'normal'}; box-shadow:${liveConn ? '0 0 8px rgba(0,255,157,0.15)' : 'none'};`;
    const licS  = `width:100%; background:${isVerified ? '#002211' : '#0a0c10'}; border:1px solid ${isVerified ? '#00ff9d' : '#222'}; color:${isVerified ? '#00ff9d' : COLORS.cyan}; padding:9px 11px; outline:none; font-family:monospace; font-size:12px; box-sizing:border-box; transition:0.3s; border-radius:3px; font-weight:${isVerified ? 'bold' : 'normal'}; text-align:${isVerified ? 'center' : 'left'};`;
    const lblS  = `font-size:9px; color:#555; display:block; margin-bottom:4px; font-weight:bold; letter-spacing:0.5px;`;
    const boxS  = `background:#0a0c10; border:1px solid ${localLocked ? COLORS.red + '22' : '#1a1a1a'}; padding:12px; border-radius:3px; transition:0.3s;`;
    const borderC = localLocked ? COLORS.red : COLORS.cyan;

    const dailyPct = Number(form.max_daily_dd_pct) || 5;
    const totalPct = Number(form.max_dd)            || 10;
    const warnHier = dailyPct >= totalPct * 0.7;

    return html`
    <div style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.92);display:flex;align-items:center;justify-content:center;z-index:9999;backdrop-filter:blur(6px);">
    <div style="background:#05070a;border:1px solid ${borderC}33;width:600px;max-height:96vh;overflow-y:auto;border-radius:4px;box-shadow:0 0 60px ${borderC}18;transition:0.3s;">

        <!-- HEADER -->
        <div style="padding:16px 22px;background:#020305;border-bottom:1px solid #1a1a1a;position:sticky;top:0;z-index:10;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:${health ? '12px' : '0'};">
                <div>
                    <div style="font-size:11px;color:${borderC};font-weight:900;letter-spacing:2px;">[ QUANTUM SECURE CALIBRATION V8.1 ]${isNewMode ? html`<span style="margin-left:10px;font-size:9px;color:${COLORS.yellow};background:${COLORS.yellow}18;border:1px solid ${COLORS.yellow}44;padding:2px 8px;border-radius:2px;font-weight:normal;letter-spacing:0;">＋ TÀI KHOẢN MỚI</span>` : null}</div>
                    <div style="font-size:9px;color:#333;margin-top:3px;">${isNewMode ? 'Nhập thông tin để đăng ký tài khoản mới vào Fleet' : 'IDENTITY LAYER — Tang Nhan Dang He Thong'}</div>
                </div>
                <button onClick=${onClose} style="background:none;border:none;color:#444;font-size:24px;cursor:pointer;line-height:1;">×</button>
            </div>

            <!-- SESSION HEALTH BAR -->
            ${health ? html`
                <div style="background:#080a0f;border:1px solid #1a1a1a;border-radius:3px;padding:10px 14px;display:flex;align-items:center;gap:16px;">
                    <div style="flex:1;">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
                            <span style="font-size:9px;color:#444;font-weight:bold;">SESSION HEALTH (5 phien gan nhat)</span>
                            <span style="font-size:9px;color:${health.compliance>=85?COLORS.green:health.compliance>=60?COLORS.yellow:COLORS.red};font-weight:bold;">
                                ${health.compliance>=85?'🏆 XUAT SAC':health.compliance>=60?'⚠️ TRUNG BINH':'🚨 CAN CAI THIEN'}
                                ${health.trend>0?` ▲+${health.trend.toFixed(0)}`:health.trend<0?` ▼${health.trend.toFixed(0)}`:''}
                            </span>
                        </div>
                        <div style="width:100%;height:5px;background:#111;border-radius:3px;overflow:hidden;">
                            <div style="width:${health.compliance}%;height:100%;background:${health.compliance>=85?COLORS.green:health.compliance>=60?COLORS.yellow:COLORS.red};border-radius:3px;transition:width 0.8s;"></div>
                        </div>
                    </div>
                    <div style="display:flex;gap:14px;flex-shrink:0;">
                        <div style="text-align:center;">
                            <div style="font-size:14px;color:#fff;font-weight:900;font-family:monospace;">${health.compliance}%</div>
                            <div style="font-size:8px;color:#444;">Compliance</div>
                        </div>
                        <div style="text-align:center;">
                            <div style="font-size:14px;color:${COLORS.cyan};font-weight:900;font-family:monospace;">#${health.total}</div>
                            <div style="font-size:8px;color:#444;">Sessions</div>
                        </div>
                        <div style="text-align:center;">
                            <div style="font-size:14px;color:${COLORS.green};font-weight:900;font-family:monospace;">${health.winStreak}/5</div>
                            <div style="font-size:8px;color:#444;">Win Phien</div>
                        </div>
                    </div>
                </div>
            ` : html`
                <div style="background:#080a0f;border:1px dashed #111;border-radius:3px;padding:8px 14px;font-size:9px;color:#222;font-style:italic;text-align:center;">
                    🌱 Phien dau tien — AI se bat dau hoc sau khi ban ARM he thong
                </div>
            `}
        </div>

        <!-- BODY -->
        <div style="padding:18px 22px;display:flex;flex-direction:column;gap:14px;">

            <!-- ── MT5 OFFLINE BANNER ──────────────────────────── -->
            ${mt5Offline && !liveConn && activePingId ? html`
                <div style="background:#0d0500;border:1px solid ${COLORS.red}55;border-left:3px solid ${COLORS.red};border-radius:3px;padding:14px 16px;animation:blinker 2s linear infinite;">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
                        <div style="display:flex;align-items:center;gap:10px;">
                            <div style="font-size:20px;">⚠️</div>
                            <div>
                                <div style="font-size:10px;color:${COLORS.red};font-weight:900;letter-spacing:1px;margin-bottom:3px;">
                                    KHÔNG TÌM THẤY MT5 ĐANG CHẠY
                                </div>
                                <div style="font-size:9px;color:#555;line-height:1.6;">
                                    EA chưa kết nối. Vui lòng mở MetaTrader 5 và khởi động EA trên tài khoản <span style="color:${COLORS.cyan};font-family:monospace;">${form.mt5_login||'?'}</span>
                                </div>
                            </div>
                        </div>
                        <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
                            ${autoLaunch ? html`
                                <!-- Đang đếm ngược -->
                                <div style="text-align:center;">
                                    <div style="font-size:22px;color:${COLORS.yellow};font-weight:900;font-family:monospace;line-height:1;">${launchCountdown}</div>
                                    <div style="font-size:8px;color:#444;margin-top:2px;">giay</div>
                                </div>
                                <div style="text-align:left;">
                                    <div style="font-size:9px;color:${COLORS.yellow};font-weight:bold;">Auto-launch MT5</div>
                                    <div style="font-size:8px;color:#444;">sau ${launchCountdown}s</div>
                                </div>
                                <button
                                    onClick=${cancelAutoLaunch}
                                    style="background:#1a0a00;border:1px dashed #555;color:#555;padding:5px 10px;font-size:9px;font-weight:bold;cursor:pointer;border-radius:2px;white-space:nowrap;transition:0.2s;">
                                    ✕ HUỶ
                                </button>
                            ` : html`
                                <!-- Đã huỷ hoặc vừa launch -->
                                <div style="font-size:9px;color:#333;font-style:italic;">
                                    Mở MT5 thủ công hoặc...
                                </div>
                                <button
                                    onClick=${startAutoLaunch}
                                    style="background:${COLORS.red}18;border:1px solid ${COLORS.red}55;color:${COLORS.red};padding:6px 12px;font-size:9px;font-weight:bold;cursor:pointer;border-radius:2px;white-space:nowrap;transition:0.2s;">
                                    🚀 TỰ ĐỘNG MỞ MT5
                                </button>
                            `}
                        </div>
                    </div>

                    <!-- Progress bar đếm ngược -->
                    ${autoLaunch ? html`
                        <div style="margin-top:10px;height:3px;background:#111;border-radius:2px;overflow:hidden;">
                            <div style="height:100%;background:${COLORS.yellow};border-radius:2px;transition:width 1s linear;width:${(launchCountdown/60)*100}%;"></div>
                        </div>
                        <div style="margin-top:5px;font-size:8px;color:#333;text-align:center;">
                            MT5 sẽ được tự động khởi động sau ${launchCountdown} giây — hoặc tự mở thủ công để bỏ qua
                        </div>
                    ` : null}
                </div>
            ` : null}

            <!-- LOCK OVERLAY -->
            ${localLocked ? html`
                <div style="background:${strictMsg?COLORS.red+'0a':COLORS.yellow+'0a'};border:1px solid ${strictMsg?COLORS.red+'44':COLORS.yellow+'33'};padding:14px 18px;border-radius:3px;text-align:center;transition:0.3s;">
                    <div style="font-size:22px;margin-bottom:6px;">${strictMsg?'⏳':'🔒'}</div>
                    <div style="color:${strictMsg?COLORS.red:COLORS.yellow};font-weight:900;font-size:13px;letter-spacing:1px;margin-bottom:6px;">
                        ${strictMsg?'KHOA CUNG — KHONG THE SUA':'HE THONG DA DUOC ARMED'}
                    </div>
                    ${todaySession?html`
                        <div style="font-size:9px;color:#555;margin-bottom:8px;">
                            Phien #${history.length+1} · Max DD ${todaySession.contract?.max_daily_dd_pct??todaySession.contract?.daily_budget??'—'}%/ngay · Total ${todaySession.contract?.max_dd||0}%
                        </div>
                    ` : null}

                    <button onMouseDown=${handleMouseDown} onMouseUp=${handleMouseUp} onMouseLeave=${handleMouseUp}
                        onTouchStart=${handleMouseDown} onTouchEnd=${handleMouseUp}
                        style="background:${disarmTimer>0?COLORS.yellow:(strictMsg?'#1a0505':'transparent')};border:1px dashed ${strictMsg?COLORS.red:COLORS.yellow};color:${disarmTimer>0?'#000':(strictMsg?COLORS.red:COLORS.yellow)};padding:7px 20px;font-weight:900;cursor:${strictMsg?'not-allowed':'pointer'};font-size:10px;border-radius:2px;transition:0.2s;margin-top:8px;width:100%;">
                        ${strictMsg?`KHONG THE SUA | ${strictMsg}`:(disarmTimer>0?`GIU CHUOT: MO KHOA SAU ${disarmTimer}s`:'🔓 DISARM & EDIT (NHAN & GIU 5s)')}
                    </button>
                </div>
            ` : null}


            <!-- IDENTITY -->
            <div style="${boxS}">
                <div style="font-size:9px;color:${COLORS.cyan};font-weight:bold;margin-bottom:10px;letter-spacing:1px;">IDENTITY & CONNECTION</div>
                <div style="display:flex;gap:10px;">
                    <div style="flex:2;">
                        <label style="${lblS}">OPERATIONAL ALIAS (TEN HIEN THI)</label>
                        <input style="${inpS}" placeholder="VD: Dang Phi — Quy 100k" value=${form.alias}
                            onInput=${e=>{markDirty('alias');setForm({...form,alias:e.target.value})}} disabled=${localLocked} />
                    </div>
                    <div style="flex:1;">
                        <label style="font-size:9px;display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                            <span style="color:${liveConn?COLORS.green:'#555'};font-weight:bold;">MT5 LOGIN ID ${isVerified?'✅':''}</span>
                            <div style="display:flex;align-items:center;gap:6px;">
                                ${liveConn ? html`
                                    <button
                                        type="button"
                                        onClick=${syncFromMT5}
                                        disabled=${isSyncingMT5||localLocked}
                                        title="Kéo cấu hình hiện tại từ MT5 vào form"
                                        style="display:flex;align-items:center;gap:3px;background:${syncMT5Msg==='ok'?COLORS.green+'22':syncMT5Msg==='err'?COLORS.red+'22':COLORS.cyan+'15'};border:1px solid ${syncMT5Msg==='ok'?COLORS.green:syncMT5Msg==='err'?COLORS.red:COLORS.cyan+'44'};color:${syncMT5Msg==='ok'?COLORS.green:syncMT5Msg==='err'?COLORS.red:COLORS.cyan};padding:2px 7px;font-size:8px;font-weight:bold;cursor:pointer;border-radius:2px;transition:0.2s;white-space:nowrap;">
                                        ${isSyncingMT5?'⏳':syncMT5Msg==='ok'?'✅ ĐÃ SYNC':syncMT5Msg==='err'?'❌ THẤT BẠI':'↻ SYNC TỪ MT5'}
                                    </button>
                                ` : null}
                                <span style="color:${liveConn?COLORS.green:(mt5Offline&&form.mt5_login?COLORS.red:COLORS.yellow)};font-weight:bold;font-size:8px;">
                                    ${liveConn?'🟢 LIVE':(mt5Offline&&form.mt5_login?'⚠️ OFFLINE':'🟡 CHỜ')}
                                </span>
                            </div>
                        </label>
                        <input style="${mt5S}" placeholder="VD: 1085205" value=${form.mt5_login}
                            onInput=${handleMT5Change} disabled=${localLocked||isVerified} />
                        ${!liveConn&&mt5Offline&&activePingId?html`
                            <div style="font-size:8px;color:${COLORS.red}77;margin-top:4px;line-height:1.5;">
                                Mở MT5 với tài khoản này để kích hoạt sync tự động
                            </div>
                        ` : null}

                    </div>
                </div>
            </div>

            <!-- LICENSE -->
            <div style="background:linear-gradient(135deg,#0a0c10,#05070a);border:1px solid ${isVerified?'#00ff9d44':COLORS.yellow+'33'};border-left:3px solid ${isVerified?'#00ff9d':COLORS.yellow};padding:14px;border-radius:3px;transition:0.3s;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                    <span style="font-size:9px;color:${isVerified?'#00ff9d':COLORS.yellow};font-weight:bold;">${isVerified?'🛡️ SYSTEM FULLY PROTECTED':'🔑 LICENSE BINDING'}</span>
                    ${isVerified?html`<button type="button" onClick=${changeAccount} style="background:#1a0505;border:1px dashed ${COLORS.red};color:${COLORS.red};padding:4px 12px;font-size:9px;cursor:pointer;border-radius:2px;font-weight:bold;transition:0.2s;">⏏ EJECT / DOI TK</button>` : null}
                </div>
                <div style="display:flex;gap:8px;">
                    <input style="${licS}" placeholder="Dan ma ZARMOR-XXXXXX..." value=${licInput}
                        onInput=${e=>setLicInput(e.target.value)} disabled=${localLocked||isVerified} />
                    <button onClick=${bindLicense} disabled=${localLocked||isVerified}
                        style="background:${isVerified?'#00ff9d':COLORS.yellow}22;border:1px solid ${isVerified?'#00ff9d':COLORS.yellow};color:${isVerified?'#00ff9d':COLORS.yellow};padding:0 14px;font-size:9px;font-weight:bold;cursor:${isVerified?'default':'pointer'};transition:0.2s;white-space:nowrap;border-radius:3px;">
                        ${isVerified?'VERIFIED ✓':'VERIFY & BIND'}
                    </button>
                </div>
            </div>

            <!-- TELEGRAM -->
            <div style="${boxS}">
                <div style="font-size:9px;color:${COLORS.cyan};font-weight:bold;margin-bottom:10px;letter-spacing:1px;">📱 TELEGRAM NOTIFICATION</div>
                <div style="display:flex;gap:8px;align-items:flex-end;">
                    <div style="flex:1;">
                        <label style="${lblS}">CHAT ID (lay tu @userinfobot)</label>
                        <input style="${inpS}" placeholder="VD: 7976137362" value=${form.telegram_chat_id}
                            onInput=${e=>{markDirty('telegram_chat_id');setForm({...form,telegram_chat_id:e.target.value})}} disabled=${localLocked} />
                    </div>
                    <button onClick=${testTelegram} disabled=${localLocked||isTesting}
                        style="background:${testResult==='ok'?COLORS.green+'22':testResult==='err'?COLORS.red+'22':COLORS.cyan+'18'};border:1px solid ${testResult==='ok'?COLORS.green:testResult==='err'?COLORS.red:COLORS.cyan+'55'};color:${testResult==='ok'?COLORS.green:testResult==='err'?COLORS.red:COLORS.cyan};padding:9px 14px;font-size:9px;font-weight:bold;cursor:pointer;white-space:nowrap;border-radius:3px;transition:0.2s;height:36px;">
                        ${isTesting?'⏳':testResult==='ok'?'✅ OK':testResult==='err'?'❌ LOI':'TEST'}
                    </button>
                </div>
                <div style="margin-top:8px;padding:7px 10px;background:#080a0f;border:1px dashed #1a1a1a;border-radius:3px;font-size:8px;color:#333;line-height:1.8;">
                    Alert co chuong 🔔: ⚡ Order mo/dong · 🟠 DD > 50% · 🔴 Sat SCRAM · ☢️ SCRAM Lock · 🚨 Compliance · 🛡️ AI Override · 📊 Debrief
                </div>
            </div>

            <!-- SESSION TIMING -->
            <div style="${boxS}">
                <div style="font-size:9px;color:${COLORS.yellow};font-weight:bold;margin-bottom:10px;letter-spacing:1px;">⏱ SESSION TIMING</div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div>
                        <label style="${lblS}">ROLLOVER HOUR (RESET NGAY MOI)</label>
                        <select style="${selS}" value=${form.rollover_hour} onChange=${e=>{markDirty('rollover_hour');setForm({...form,rollover_hour:Number(e.target.value)})}} disabled=${localLocked}>
                            ${Array.from({length:24}).map((_,i)=>html`<option value=${i}>${i.toString().padStart(2,'0')}:00 ${i===0?'(Midnight)':i===17?'(NY Close)':''}</option>`)}
                        </select>
                    </div>
                    <div>
                        <label style="${lblS}">BROKER TIMEZONE (MUI GIO SAN)</label>
                        <select style="${selS}" value=${form.broker_timezone} onChange=${e=>{markDirty('broker_timezone');setForm({...form,broker_timezone:Number(e.target.value)})}} disabled=${localLocked}>
                            <option value="-5">UTC -05:00 (NY EST)</option>
                            <option value="-4">UTC -04:00 (NY EDT)</option>
                            <option value="0">UTC +00:00 (London GMT)</option>
                            <option value="1">UTC +01:00 (London BST)</option>
                            <option value="2">UTC +02:00 (Forex Winter)</option>
                            <option value="3">UTC +03:00 (Forex Summer)</option>
                            <option value="7">UTC +07:00 (Vietnam ICT)</option>
                            <option value="8">UTC +08:00 (Singapore SGT)</option>
                            <option value="9">UTC +09:00 (Tokyo JST)</option>
                        </select>
                    </div>
                </div>
            </div>

            <!-- RISK CONSTITUTION -->
            <div style="background:#0a0c10;border:1px solid ${localLocked?COLORS.red+'22':'#222'};border-left:3px solid ${COLORS.red};padding:14px;border-radius:3px;transition:0.3s;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <div style="font-size:9px;color:${COLORS.red};font-weight:bold;letter-spacing:1px;">⚔️ RISK CONSTITUTION — GIOI HAN VAT LY</div>
                    <div style="font-size:8px;color:#333;font-style:italic;">Daily Budget ($) → MacroModal</div>
                </div>
                <div style="font-size:8px;color:#2a2a2a;font-style:italic;margin-bottom:12px;line-height:1.5;">
                    Rao can cung bat bien — tinh theo % nen khong bi anh huong boi size tai khoan. AI Guard se hoc tu day.
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;">
                    <div>
                        <label style="font-size:9px;color:${COLORS.red};display:block;margin-bottom:4px;font-weight:bold;">MAX DAILY DD (%)</label>
                        <div style="position:relative;">
                            <input type="number" style="${inpS}" value=${form.max_daily_dd_pct}
                                onInput=${e=>{markDirty('max_daily_dd_pct');setForm({...form,max_daily_dd_pct:e.target.value})}}
                                min="0.5" max="10" step="0.5" disabled=${localLocked} />
                            <div style="position:absolute;right:8px;top:50%;transform:translateY(-50%);font-size:9px;color:${COLORS.red}88;pointer-events:none;">%/ngay</div>
                        </div>
                        <div style="font-size:8px;color:#222;margin-top:3px;">Prop: 4–5% · Ca nhan: 5–10%</div>
                    </div>
                    <div>
                        <label style="font-size:9px;color:#e05050;display:block;margin-bottom:4px;font-weight:bold;">MAX CAPACITY DD (%)</label>
                        <div style="position:relative;">
                            <input type="number" style="${inpS}" value=${form.max_dd}
                                onInput=${e=>{markDirty('max_dd');setForm({...form,max_dd:e.target.value})}}
                                min="0.5" max="20" disabled=${localLocked} />
                            <div style="position:absolute;right:8px;top:50%;transform:translateY(-50%);font-size:9px;color:#e0505088;pointer-events:none;">%</div>
                        </div>
                        <div style="font-size:8px;color:#222;margin-top:3px;">Tong tu dinh equity</div>
                    </div>
                    <div>
                        <label style="font-size:9px;color:${COLORS.green};display:block;margin-bottom:4px;font-weight:bold;">GIBBS RETENTION (%)</label>
                        <div style="position:relative;">
                            <input type="number" style="${inpS}" value=${form.consistency}
                                onInput=${e=>{markDirty('consistency');setForm({...form,consistency:e.target.value})}}
                                disabled=${localLocked} />
                            <div style="position:absolute;right:8px;top:50%;transform:translateY(-50%);font-size:9px;color:${COLORS.green}88;pointer-events:none;">%</div>
                        </div>
                        <div style="font-size:8px;color:#222;margin-top:3px;">San bao ve balance</div>
                    </div>
                    <div>
                        <label style="font-size:9px;color:#aaa;display:block;margin-bottom:4px;font-weight:bold;">CAPACITY MODE</label>
                        <select style="${selS}" value=${form.dd_type}
                            onChange=${e=>{markDirty('dd_type');setForm({...form,dd_type:e.target.value})}} disabled=${localLocked}>
                            <option value="STATIC">STATIC</option>
                            <option value="TRAILING">TRAILING</option>
                        </select>
                        <div style="font-size:8px;color:#222;margin-top:3px;">${form.dd_type==='TRAILING'?'Tinh tu dinh equity dong':'Tinh tu balance co dinh'}</div>
                    </div>
                </div>

                <!-- DD Hierarchy -->
                <div style="margin-top:12px;padding:8px 10px;background:#080a0f;border:1px dashed #1a1a1a;border-radius:3px;display:flex;align-items:center;gap:8px;">
                    <div style="font-size:8px;color:#333;white-space:nowrap;">DD Hierarchy:</div>
                    <div style="flex:1;display:flex;align-items:center;gap:4px;font-size:9px;font-family:monospace;">
                        <span style="color:${COLORS.red};font-weight:bold;">Daily ${dailyPct}%</span>
                        <span style="color:#222;">→ dung ngay</span>
                        <span style="color:#333;margin:0 4px;">|</span>
                        <span style="color:#e05050;font-weight:bold;">Total ${totalPct}%</span>
                        <span style="color:#222;">→ SCRAM</span>
                        <span style="color:#333;margin:0 4px;">|</span>
                        <span style="color:${COLORS.green};font-weight:bold;">Floor ${form.consistency||97}%</span>
                        <span style="color:#222;">→ hard floor</span>
                    </div>
                </div>

                ${warnHier?html`
                    <div style="margin-top:8px;padding:6px 10px;background:${COLORS.yellow}0a;border:1px dashed ${COLORS.yellow}44;border-radius:3px;font-size:8px;color:${COLORS.yellow}88;">
                        ⚠️ Daily DD (${dailyPct}%) ≥ 70% Total DD (${totalPct}%). Khuyen nghi Daily ≤ 50% Total.
                    </div>
                ` : null}

            </div>

            <!-- SESSION CONTRACT -->
            ${todaySession&&localLocked?html`
                <div style="background:#05070a;border:1px dashed ${COLORS.green}44;border-radius:3px;padding:12px;font-family:monospace;font-size:10px;color:#555;line-height:2;">
                    <div style="font-size:9px;color:${COLORS.green}66;font-weight:bold;margin-bottom:6px;letter-spacing:1px;">📋 SESSION CONTRACT ACTIVE</div>
                    <div style="display:flex;justify-content:space-between;"><span>Phien mo luc:</span><span style="color:#888;">${new Date(todaySession.opened_at||Date.now()).toLocaleTimeString('vi-VN')}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>Max Daily DD:</span><span style="color:${COLORS.red};">${todaySession.contract?.max_daily_dd_pct??todaySession.contract?.daily_budget??'—'}%/ngay</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>Daily Budget:</span><span style="color:${COLORS.yellow};">${todaySession.contract?.daily_budget?'$'+todaySession.contract.daily_budget:'→ MacroModal'}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>Max DD Total:</span><span style="color:${COLORS.red};">${todaySession.contract?.max_dd}%</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>WR Ke hoach:</span><span style="color:${COLORS.yellow};">${todaySession.contract?.planned_wr}%</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>R:R Ke hoach:</span><span style="color:${COLORS.yellow};">1:${todaySession.contract?.planned_rr}</span></div>
                    <div style="display:flex;justify-content:space-between;border-top:1px dashed #1a1a1a;margin-top:6px;padding-top:6px;">
                        <span>Compliance Score:</span>
                        <span style="color:${todaySession.compliance_score>=80?COLORS.green:COLORS.yellow};">${todaySession.compliance_score}/100</span>
                    </div>
                </div>
            ` : null}


        </div>

        <!-- FOOTER -->
        <div style="padding:14px 22px 20px;display:flex;gap:10px;border-top:1px solid #111;">
            <button disabled=${localLocked||isSaving} onClick=${saveSetup}
                style="flex:1;padding:13px;background:${localLocked?'#111':saveStatus==='ok'?COLORS.green:COLORS.cyan};color:${localLocked?'#333':'#000'};font-weight:900;letter-spacing:1px;cursor:${localLocked?'not-allowed':'pointer'};border:none;transition:0.2s;border-radius:3px;font-size:11px;box-shadow:${localLocked?'none':'0 0 15px '+(saveStatus==='ok'?COLORS.green:COLORS.cyan)+'33'};">
                ${isSaving?'⏳ TRANSMITTING...':saveStatus==='ok'?'✅ SAVED & ARMED':(localLocked?'🔒 SYSTEM LOCKED':'✔ SAVE TO CLOUD & LOCK')}
            </button>
            <button onClick=${onClose} style="flex:0.35;padding:13px;background:#0a0c10;color:#666;border:1px solid #222;cursor:pointer;font-weight:bold;transition:0.2s;border-radius:3px;font-size:11px;">CLOSE</button>
        </div>

    </div>
    </div>
    `;
}