/**
 * COCKPIT_PATCHES.js
 * ─────────────────────────────────────────────────────────────
 * Đây là bộ patch tích hợp vào Cockpit.js hiện tại.
 * KHÔNG thay thế Cockpit.js — chỉ là hướng dẫn tích hợp có code sẵn.
 *
 * Cách dùng: Copy từng section vào vị trí tương ứng trong Cockpit.js
 */

import { logTrade, updateTradeResult, checkCompliance, closeSession, generateDebrief } from './aiAgentEngine.js';
import { h } from 'preact';
import htm from 'htm';
const html = htm.bind(h);

// ═══════════════════════════════════════════════════════════════
// SECTION 1: THÊM VÀO IMPORTS / CONSTANTS (đầu file)
// ═══════════════════════════════════════════════════════════════

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8000'
    : `http://${window.location.hostname}:8000`;

// Ghi audit log vào localStorage và fire custom event để RightColumn cập nhật ngay
function writeAuditLog(accountId, action, message, extra = {}) {
    try {
        const key = `zarmor_audit_${accountId}`;
        const logs = JSON.parse(localStorage.getItem(key) || '[]');
        logs.push({
            date: new Date().toLocaleString('vi-VN'),
            action,
            message,
            timestamp: Date.now(),
            ...extra
        });
        // Giữ tối đa 200 log gần nhất
        if (logs.length > 200) logs.splice(0, logs.length - 200);
        localStorage.setItem(key, JSON.stringify(logs));
        // Fire custom event để RightColumn cập nhật không cần polling
        window.dispatchEvent(new CustomEvent('zarmor_log_updated'));
    } catch {}
}

// ═══════════════════════════════════════════════════════════════
// SECTION 2: THÊM VÀO STATE DECLARATIONS (trong component)
// ═══════════════════════════════════════════════════════════════

// Thêm vào trong component Cockpit, sau các useState hiện có:
/*
const prevTradesRef = useRef([]);
const [complianceAlerts, setComplianceAlerts] = useState([]);
const [showDebrief, setShowDebrief] = useState(null); // null | closedSession object
*/

// ═══════════════════════════════════════════════════════════════
// SECTION 3: TRADE LOGGER useEffect (thêm vào component)
// ═══════════════════════════════════════════════════════════════

// Thêm useEffect này vào trong component Cockpit:
function useTradeLogger(activeTrades, accountId, neural, dailyUsed, currentDdPct) {
    const prevTradesRef = useRef([]);

    useEffect(() => {
        if (!activeTrades || !accountId) return;

        const prev = prevTradesRef.current;
        const prevTickets = new Set(prev.map(t => String(t.ticket)));
        const currTickets = new Set(activeTrades.map(t => String(t.ticket)));

        // ── Lệnh MỚI XUẤT HIỆN ─────────────────────────────
        const newTrades = activeTrades.filter(t => !prevTickets.has(String(t.ticket)));
        newTrades.forEach(t => {
            const plannedRR = neural?.historical_rr || 2.0;
            // Ước tính risk nếu không có field rõ ràng
            const riskAmount = parseFloat(t.risk_amount)
                || Math.abs(parseFloat(t.open_price || 0) - parseFloat(t.sl || 0)) * parseFloat(t.volume || 0.01) * 10
                || 0;

            // Ghi vào AI Agent Memory
            const entry = logTrade(accountId, {
                symbol: t.symbol,
                direction: t.side || t.type,
                risk_amount: riskAmount,
                planned_rr: plannedRR,
                hour_of_day: new Date().getHours(),
                day_of_week: new Date().getDay(),
                ticket: t.ticket
            });
            // Lưu agent_id lại trên trade object để update sau khi đóng
            t._agent_id = entry?.id;

            // Compliance check
            const check = checkCompliance(accountId,
                { risk_amount: riskAmount, planned_rr: plannedRR },
                { daily_used: dailyUsed, current_dd_pct: currentDdPct }
            );

            if (check.violations.length > 0) {
                check.violations.forEach(v => {
                    writeAuditLog(accountId, 'COMPLIANCE_VIOL', v.detail, { severity: v.severity });
                });
                // setComplianceAlerts(check.violations) — gọi từ component
            }

            // Ghi audit log lệnh mở
            writeAuditLog(accountId, 'TRADE_OPEN', `[${t.ticket}] ${t.symbol} ${t.side} | Risk $${riskAmount.toFixed(0)} | Planned R:R 1:${plannedRR}`);
        });

        // ── Lệnh VỪA ĐÓNG ──────────────────────────────────
        const closedTrades = prev.filter(t => !currTickets.has(String(t.ticket)));
        closedTrades.forEach(t => {
            const profit = parseFloat(t.profit || t.pnl || 0);
            const result = profit > 0 ? 'WIN' : profit < 0 ? 'LOSS' : 'BE';
            const riskAmt = parseFloat(t.risk_amount || 1);
            const actualRR = riskAmt > 0 ? Math.abs(profit) / riskAmt : 0;

            // Cập nhật kết quả vào AI Agent Memory
            updateTradeResult(accountId, t._agent_id, result, actualRR);

            // Ghi audit log
            const resultIcon = result === 'WIN' ? '✅' : result === 'LOSS' ? '❌' : '⚡';
            writeAuditLog(accountId,
                result === 'WIN' ? 'TRADE_WIN' : result === 'LOSS' ? 'TRADE_LOSS' : 'INFO',
                `${resultIcon} [${t.ticket}] ${t.symbol} ĐÓNG | ${result} | P&L: ${profit >= 0 ? '+' : ''}$${profit.toFixed(2)} | R:R thực: ${actualRR.toFixed(2)}`,
                { profit, actualRR }
            );
        });

        prevTradesRef.current = activeTrades;
    }, [activeTrades, accountId]);
}

// ═══════════════════════════════════════════════════════════════
// SECTION 4: DD WARNING CHECK useEffect
// ═══════════════════════════════════════════════════════════════

function useDDWarning(currentDdPct, maxDdPct, accountId) {
    const lastWarnLevel = useRef(0);

    useEffect(() => {
        const pct = (currentDdPct / maxDdPct) * 100;

        // Cảnh báo ở 75% và 90% — chỉ cảnh báo 1 lần mỗi mức
        if (pct >= 90 && lastWarnLevel.current < 90) {
            writeAuditLog(accountId, 'DD_WARNING',
                `☢️ CRITICAL: Drawdown ${currentDdPct.toFixed(1)}% đã chạm ${pct.toFixed(0)}% capacity (Max ${maxDdPct}%). Xem xét đóng lệnh!`,
                { severity: 'CRITICAL' }
            );
            lastWarnLevel.current = 90;
        } else if (pct >= 75 && pct < 90 && lastWarnLevel.current < 75) {
            writeAuditLog(accountId, 'DD_WARNING',
                `⚠️ WARNING: Drawdown ${currentDdPct.toFixed(1)}% đang tiến đến Max DD ${maxDdPct}%`,
                { severity: 'HIGH' }
            );
            lastWarnLevel.current = 75;
        } else if (pct < 50) {
            lastWarnLevel.current = 0; // Reset để cảnh báo lại nếu DD tăng trở lại
        }
    }, [currentDdPct, maxDdPct, accountId]);
}

// ═══════════════════════════════════════════════════════════════
// SECTION 5: ROLLOVER & SESSION CLOSE useEffect
// ═══════════════════════════════════════════════════════════════

function useRolloverDetect(riskParams, accountId, globalStatus, currentDdPct, telegramChatId) {
    const rolloverFiredRef = useRef(false);

    useEffect(() => {
        const rolloverHour = Number(riskParams?.rollover_hour) || 0;

        const check = () => {
            const now = new Date();
            if (now.getHours() === rolloverHour && now.getMinutes() === 0) {
                if (rolloverFiredRef.current) return; // Chỉ fire 1 lần mỗi ngày
                rolloverFiredRef.current = true;

                const session = (() => {
                    try { return JSON.parse(localStorage.getItem(`zarmor_current_session_${accountId}`) || 'null'); } catch { return null; }
                })();

                if (session?.status === 'ACTIVE') {
                    const finalPnL = globalStatus?.total_pnl || 0;
                    const closed = closeSession(accountId, finalPnL, currentDdPct);

                    if (closed) {
                        writeAuditLog(accountId, 'SESSION_CLOSE',
                            `📊 SESSION CLOSED | PnL: ${finalPnL >= 0 ? '+' : ''}$${finalPnL.toFixed(2)} | Compliance: ${closed.compliance_score}% | DD hit: ${currentDdPct.toFixed(1)}%`,
                            { pnl: finalPnL, compliance: closed.compliance_score }
                        );

                        // Gửi Telegram debrief
                        if (telegramChatId) {
                            const debrief = generateDebrief(closed);
                            fetch(`${API_BASE}/api/send-telegram`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ chat_id: telegramChatId, message: debrief })
                            }).catch(() => {});
                        }

                        // Trigger debriefing panel
                        // setShowDebrief(closed) — gọi từ component
                        window.dispatchEvent(new CustomEvent('zarmor_session_closed', { detail: closed }));

                        // Lock mở lại sau 1 phút (cho phép giao dịch phiên mới)
                        setTimeout(() => { rolloverFiredRef.current = false; }, 60000);
                    }
                }
            }
        };

        const intv = setInterval(check, 30000); // check mỗi 30s
        return () => clearInterval(intv);
    }, [riskParams?.rollover_hour, accountId, globalStatus, currentDdPct, telegramChatId]);
}

// ═══════════════════════════════════════════════════════════════
// SECTION 6: COMPLIANCE ALERT BANNER COMPONENT
// ═══════════════════════════════════════════════════════════════

// Dán trực tiếp vào render của Cockpit.js, phía TRÊN bảng lệnh:
export function ComplianceAlertBanner({ alerts, onDismiss, COLORS }) {
    if (!alerts || alerts.length === 0) return null;
    return html`
        <div style="background:${COLORS.red}0a;border:1px solid ${COLORS.red}44;border-radius:3px;padding:10px 14px;display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;animation:slideIn 0.3s ease;">
            <style>@keyframes slideIn { from { opacity:0; transform:translateY(-8px); } to { opacity:1; transform:translateY(0); } }</style>
            <div>
                <div style="font-size:10px;color:${COLORS.red};font-weight:900;margin-bottom:4px;">⚠️ COMPLIANCE VIOLATION</div>
                ${alerts.map(v => html`
                    <div style="font-size:9px;color:#cc4444;line-height:1.5;">${v.detail || v.type}</div>
                `)}
            </div>
            <button onClick=${onDismiss}
                style="background:none;border:none;color:#555;cursor:pointer;font-size:16px;padding:0;flex-shrink:0;margin-left:10px;">×</button>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════
// SECTION 7: END-OF-DAY DEBRIEFING PANEL
// ═══════════════════════════════════════════════════════════════

// Modal toàn màn hình hiện khi Rollover:
export function DebriefingPanel({ session, onClose, COLORS }) {
    if (!session) return null;

    const pnlColor = session.pnl >= 0 ? COLORS.green : COLORS.red;
    const compColor = session.compliance_score >= 85 ? COLORS.green : session.compliance_score >= 60 ? COLORS.yellow : COLORS.red;

    return html`
        <div style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.92);display:flex;align-items:center;justify-content:center;z-index:20000;backdrop-filter:blur(8px);">
            <div style="background:#08090e;border:1px solid ${pnlColor}44;width:500px;border-radius:4px;box-shadow:0 0 60px ${pnlColor}18;overflow:hidden;">

                <!-- Header -->
                <div style="padding:16px 20px;background:#020305;border-bottom:1px solid #1a1a1a;">
                    <div style="font-size:16px;color:${pnlColor};font-weight:900;letter-spacing:2px;">📊 SESSION DEBRIEFING</div>
                    <div style="font-size:9px;color:#444;margin-top:3px;">${session.date} · Phiên #${session.session_id?.slice(-4) || '—'}</div>
                </div>

                <!-- PnL big -->
                <div style="padding:20px;text-align:center;border-bottom:1px solid #111;">
                    <div style="font-size:10px;color:#444;margin-bottom:6px;">KẾT QUẢ PHIÊN</div>
                    <div style="font-size:48px;color:${pnlColor};font-weight:900;font-family:monospace;">${session.pnl >= 0 ? '+' : ''}$${(session.pnl || 0).toFixed(2)}</div>
                </div>

                <!-- Stats grid -->
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0;border-bottom:1px solid #111;">
                    ${[
                        { label: 'WIN RATE', val: `${(session.actual_wr || 0).toFixed(0)}%`, sub: `KH: ${session.contract?.planned_wr || 55}%`, color: (session.actual_wr || 0) >= (session.contract?.planned_wr || 55) ? COLORS.green : COLORS.red },
                        { label: 'R:R TB', val: (session.actual_rr_avg || 0).toFixed(2), sub: `KH: ${session.contract?.planned_rr || 2.0}`, color: (session.actual_rr_avg || 0) >= (session.contract?.planned_rr || 2) * 0.85 ? COLORS.green : COLORS.red },
                        { label: 'MAX DD HIT', val: `${(session.actual_max_dd_hit || 0).toFixed(1)}%`, sub: `/ ${session.contract?.max_dd || 10}%`, color: (session.actual_max_dd_hit || 0) < (session.contract?.max_dd || 10) * 0.8 ? COLORS.green : COLORS.yellow },
                        { label: 'TRADES', val: session.trades_count || 0, sub: `${session.wins || 0}W ${session.losses || 0}L`, color: '#fff' },
                        { label: 'COMPLIANCE', val: `${session.compliance_score || 0}%`, sub: session.violations?.length ? `${session.violations.length} vi phạm` : 'Sạch', color: compColor },
                        { label: 'VIOLATIONS', val: session.violations?.length || 0, sub: session.violations?.length ? session.violations[0]?.type : '—', color: session.violations?.length ? COLORS.red : COLORS.green },
                    ].map(s => html`
                        <div style="padding:12px 14px;border-right:1px solid #111;border-bottom:1px solid #111;">
                            <div style="font-size:8px;color:#444;margin-bottom:4px;font-weight:bold;">${s.label}</div>
                            <div style="font-size:18px;color:${s.color};font-weight:900;font-family:monospace;">${s.val}</div>
                            <div style="font-size:8px;color:#333;margin-top:2px;">${s.sub}</div>
                        </div>
                    `)}
                </div>

                <!-- AI Learning note -->
                <div style="padding:12px 20px;background:#030507;border-bottom:1px solid #111;">
                    <div style="font-size:8px;color:#333;line-height:1.6;">
                        🧠 Dữ liệu phiên này đã được AI Agent lưu vào Memory Bank. AiGuardCenter sẽ cập nhật DNA Score và Recommendations dựa trên phiên vừa rồi.
                    </div>
                </div>

                <!-- Action -->
                <div style="padding:14px 20px;display:flex;gap:10px;">
                    <button onClick=${onClose}
                        style="flex:1;padding:12px;background:${COLORS.cyan};color:#000;font-weight:900;border:none;cursor:pointer;border-radius:3px;font-size:11px;letter-spacing:1px;">
                        ✔ ĐÃ HIỂU — BẮT ĐẦU PHIÊN MỚI
                    </button>
                </div>
            </div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════
// SECTION 8: HƯỚNG DẪN TÍCH HỢP VÀO Cockpit.js
// ═══════════════════════════════════════════════════════════════

/*
BƯỚC 1: Thêm imports ở đầu Cockpit.js:
─────────────────────────────────────────
import { logTrade, updateTradeResult, checkCompliance, closeSession, generateDebrief } from './aiAgentEngine.js';
import { ComplianceAlertBanner, DebriefingPanel } from './CockpitPatches.js';

BƯỚC 2: Thêm state declarations trong component:
─────────────────────────────────────────────────
const prevTradesRef = useRef([]);
const lastWarnLevelRef = useRef(0);
const rolloverFiredRef = useRef(false);
const [complianceAlerts, setComplianceAlerts] = useState([]);
const [showDebrief, setShowDebrief] = useState(null);

BƯỚC 3: Thêm useEffects (copy từ Section 3, 4, 5 ở trên)

BƯỚC 4: Thêm vào JSX render:
─────────────────────────────
// Ngay trước bảng lệnh:
<ComplianceAlertBanner alerts={complianceAlerts} onDismiss={() => setComplianceAlerts([])} COLORS={COLORS} />

// Cuối component, trước closing tag:
<DebriefingPanel session={showDebrief} onClose={() => setShowDebrief(null)} COLORS={COLORS} />

BƯỚC 5: Listen session close event:
────────────────────────────────────
useEffect(() => {
    const handler = (e) => setShowDebrief(e.detail);
    window.addEventListener('zarmor_session_closed', handler);
    return () => window.removeEventListener('zarmor_session_closed', handler);
}, []);
*/

export { writeAuditLog };