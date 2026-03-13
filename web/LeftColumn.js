import { h } from 'preact';
import { useState } from 'preact/hooks'; 
import htm from 'htm';

const html = htm.bind(h);

export default function LeftColumn({ global_status, units_config, COLORS, onOpenMacro }) {
    const [showRaw, setShowRaw] = useState(false);

    const physics = global_status.physics || {};
    
    // ĐỒNG BỘ TOÁN HỌC: Lấy thẳng Equity và Balance từ MT5 Backend (Bao gồm cả Swap/Com)
    const balance = global_status.balance || 0;
    const currentEquity = global_status.equity || balance;
    const trueFloatingPnL = currentEquity - balance; 

    const formatMoney = (val) => parseFloat(val || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    
    const startBalance = global_status.start_balance || balance;
    const peakEquity = physics.peak_equity || Math.max(currentEquity, startBalance);
    
    const accountId = localStorage.getItem('zarmor_id') || localStorage.getItem('zarmor_account_id') || 'MainUnit';
    const myUnitConfig = units_config[accountId] || units_config["MainUnit"] || {};
    const riskParams = myUnitConfig.risk_params || {};
    const neural = myUnitConfig.neural_profile || {};
    
    // FIX: Ưu tiên riskParams.daily_limit_money (nguồn thật từ MacroModal/SetupModal)
    // physics.budget_capacity chỉ update khi EA gửi heartbeat → có thể stale
    const rawDailyLoss = parseFloat(riskParams.daily_limit_money)
                      || parseFloat(physics.budget_capacity)
                      || 150;
    // remCapacity tính lại từ rawDailyLoss mới — không dùng physics.rem_capacity (stale)
    const _dailyFloor = startBalance - rawDailyLoss;
    const remCapacity = Math.max(0, currentEquity - _dailyFloor);
    
    // 💡 LOGIC MỚI: Tính toán Ngân sách Đã Triển Khai (Closed Loss + Active Risk)
    const closedLoss = Math.max(0, startBalance - balance);
    const activeRisk = Math.abs(global_status.total_stl || 0);
    const deployedBudget = closedLoss + activeRisk;
    const dbuPct = rawDailyLoss > 0 ? (deployedBudget / rawDailyLoss) * 100 : 0;

    const frePct = physics.fre_pct || 0; 

    const rrRatio = Number(neural.historical_rr || 1.5);
    const optimalTarget = rawDailyLoss * rrRatio * 0.85;
    let saturationPct = optimalTarget > 0 ? (Math.max(0, trueFloatingPnL) / optimalTarget) * 100 : 0;
    saturationPct = Math.min(100, saturationPct);

    const profitLockPct = parseFloat(riskParams.profit_lock_pct) || 40;
    const baseFloor = startBalance - rawDailyLoss;
    const maxProfit = peakEquity - startBalance;
    let trailingFloor = 0;
    let trailingStatus = "CHƯA KÍCH HOẠT";
    if (maxProfit > 0) {
        trailingFloor = peakEquity - (maxProfit * (profitLockPct / 100));
        trailingStatus = `$${formatMoney(trailingFloor)}`;
    }
    
    const getAiGuardMessage = (state) => {
        if (!state) return "Đang đồng bộ dữ liệu với Mạng lưới Đám mây...";
        if (state === "DISCONNECTED" || state.includes("DISCONNECT")) return "🔌 MẤT KẾT NỐI EA: Không nhận được nhịp tim (Heartbeat) từ MT5.";
        if (state.includes("FATAL") || state.includes("LOCKED")) return "💀 HỆ THỐNG KHÓA CỨNG: Đã chạm Đáy quỹ ngày. Đã phát lệnh SCRAM!";
        if (state.includes("PROFIT LOCKED") || state.includes("SHIELD")) return "🏆 KHIÊN KHÓA LÃI KÍCH HOẠT: Đã chạm ngưỡng Trailing Drawdown. Bảo vệ thành quả!";
        if (state.includes("CRITICAL") || state.includes("OVERLOAD")) return "🚨 BÁO ĐỘNG ĐỎ: Áp suất sinh tồn cực thấp. Lệnh sẽ bị bắn hạ!";
        if (state.includes("ELEVATED")) return "⚠️ CẢNH BÁO RỦI RO: Tiêu hao ngân sách nhanh. Khuyến nghị giảm Volume.";
        if (state.includes("HIBERNATING")) return "⏸️ NGỦ ĐÔNG CHIẾN THUẬT: Hệ thống tạm dừng.";
        return "Trường năng lượng ổn định. Chỉ số tuân thủ định luật Nhiệt động lực học.";
    };

    const renderProgressBar = (rawValue, max, color, label) => {
        const value = parseFloat(rawValue) || 0;
        const pct = Math.min((value / max) * 100, 100);
        const blocks = 20;
        const filledBlocks = Math.round((pct / 100) * blocks);
        
        return html`
            <div style="margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; font-size: 10px; margin-bottom: 4px; font-weight: bold; letter-spacing: 1px;">
                    <span style="color: #aaa;">${label}</span>
                    <span style="color: ${color};">${value.toFixed(2)}${label.includes('(P̂)') || label.includes('Ê') ? '' : '%'}</span>
                </div>
                <div style="display: flex; gap: 2px; width: 100%; flex-wrap: wrap;">
                    ${Array(blocks).fill(0).map((_, i) => html`
                        <div style="flex: 1; min-width: 5px; height: 8px; background: ${i < filledBlocks ? color : '#111'}; border-radius: 1px; transition: 0.3s;"></div>
                    `)}
                </div>
            </div>
        `;
    };

    const velocityValue = parseFloat(physics.velocity) || 0;
    const velocityColor = velocityValue > 0 ? COLORS.green : (velocityValue < 0 ? COLORS.red : COLORS.cyan);
    const aiGuardState = physics.state || "DISCONNECTED";
    
    let guardBadgeColor = COLORS.green;
    if (aiGuardState.includes("DISCONNECT")) guardBadgeColor = "#555";
    else if (aiGuardState.includes("ELEVATED")) guardBadgeColor = COLORS.yellow;
    else if (aiGuardState.includes("CRITICAL")) guardBadgeColor = COLORS.orange;
    else if (aiGuardState.includes("LOCKED") || aiGuardState.includes("FATAL") || aiGuardState.includes("PROFIT")) guardBadgeColor = COLORS.red;
    else if (aiGuardState.includes("HIBERNATING")) guardBadgeColor = COLORS.cyan;

    const zPct = Math.min((parseFloat(physics.z_pressure) || 0) * 100, 150); 

    return html`
        <div style="display: flex; flex-direction: column; gap: 10px; height: 100%; overflow-y: auto; overflow-x: hidden; padding-right: 2px;">
            
            <div style="background: #080a0f; border: 1px solid ${guardBadgeColor}55; border-left: 3px solid ${guardBadgeColor}; padding: 15px; border-radius: 2px; animation: slideDown 0.5s ease-out;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div style="font-size: 11px; font-weight: bold; color: ${COLORS.yellow}; letter-spacing: 1px;">⚠️ CLOUD AI GUARD</div>
                    <div style="font-size: 9px; font-weight: bold; color: #000; background: ${guardBadgeColor}; padding: 2px 6px; border-radius: 2px; text-transform: uppercase;">
                        ${aiGuardState.includes("PROFIT") ? 'SHIELD ACTIVATED' : aiGuardState}
                    </div>
                </div>
                <div style="font-size: 11px; color: #888; font-style: italic; margin-top: 10px; line-height: 1.5;">
                    "${getAiGuardMessage(aiGuardState)}"
                </div>
            </div>

            <div style="background: ${COLORS.panelBg}; border: 1px solid ${COLORS.border}; padding: 15px; border-radius: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="color: #fff; font-size: 14px;">🛡️</span>
                        <span style="color: #888; font-size: 10px; font-weight: bold; letter-spacing: 1px;">CAPITAL CORE</span>
                    </div>
                    <div style="font-size: 9px; color: ${COLORS.green}; border: 1px solid ${COLORS.green}44; padding: 2px 6px; border-radius: 2px; background: ${COLORS.green}11;">ONLINE</div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: flex-end;">
                    <div style="color: #aaa; font-size: 11px;">Core Balance</div>
                    <div style="color: #fff; font-size: 16px; font-weight: bold;">$${formatMoney(balance)}</div>
                </div>
                
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px; gap: 10px;">
                    <button onClick=${onOpenMacro} style="flex: 1; font-size: 12px; font-weight: 900; color: #000; background: linear-gradient(90deg, ${COLORS.cyan} 0%, #00aaff 100%); border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; transition: 0.3s; box-shadow: 0 0 15px ${COLORS.cyan}66; display: flex; align-items: center; justify-content: center; gap: 6px;">
                        <span>🚀</span> MACRO EQ: $${formatMoney(currentEquity)}
                    </button>
                    <div style="font-size: 15px; font-weight: bold; color: ${trueFloatingPnL >= 0 ? COLORS.green : COLORS.red}; text-align: right; min-width: 80px;">
                        ${trueFloatingPnL >= 0 ? '+' : ''}$${formatMoney(trueFloatingPnL)}
                    </div>
                </div>
                
                <div style="margin-top: 12px; border-top: 1px dashed #222; padding-top: 10px; display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-size: 9px; color: ${COLORS.yellow}; font-weight: bold;">🏆 PEAK EQUITY</div>
                    <div style="font-size: 12px; color: ${COLORS.yellow}; font-family: monospace;">$${formatMoney(peakEquity)}</div>
                </div>
            </div>

            <div style="background: ${COLORS.panelBg}; border: 1px solid ${COLORS.border}; padding: 15px; border-radius: 4px; display: flex; flex-direction: column; gap: 15px;">
                
                <div>
                    ${renderProgressBar(saturationPct, 100, saturationPct >= 100 ? COLORS.green : '#00bfff', '[1] KINETIC SATURATION (🎯)')}
                    <div style="display: flex; justify-content: space-between; font-size: 9px; color: #666;">
                        <span style="color: ${saturationPct >= 100 ? COLORS.green : '#888'}; font-weight: bold;">Đích đến: $${formatMoney(optimalTarget)}</span>
                    </div>
                </div>

                <div>
                    ${renderProgressBar(dbuPct, 100, dbuPct >= 80 ? COLORS.red : COLORS.yellow, '[2] DAILY BUDGET USED (B̂)')}
                    <div style="display: flex; justify-content: space-between; font-size: 9px; color: #666;">
                        <span style="color: ${remCapacity > 0 ? COLORS.green : COLORS.red}; font-weight: bold;">Máu khả dụng: $${formatMoney(remCapacity)}</span>
                        <span title="Kích thước Dot trên Radar">● Radar Dot Size</span>
                    </div>
                </div>

                <div>
                    ${renderProgressBar(frePct, 5.0, COLORS.purple || '#b565ff', '[3] RISK EXPOSURE (Ê)')}
                    <div style="display: flex; justify-content: space-between; font-size: 9px; color: #666;">
                        <span style="color: ${frePct > 2.0 ? COLORS.yellow : '#888'};">Volume Market</span>
                        <span>Radar Y-Axis</span>
                    </div>
                </div>

                <div>
                    ${renderProgressBar(zPct, 100, zPct >= 100 ? COLORS.red : (zPct >= 85 ? COLORS.red : (zPct >= 60 ? COLORS.yellow : (zPct >= 15 ? COLORS.green : '#00bfff'))), '[4] QUANTUM Z-LOAD (P̂)')}
                    <div style="display: flex; justify-content: space-between; font-size: 9px; color: #666;">
                        <span><span style="color: ${zPct >= 100 ? COLORS.red : COLORS.green};">💥 ${zPct >= 100 ? 'VỠ ÁP SUẤT' : 'CHỊU TẢI'}</span></span>
                        <span>Radar X-Axis</span>
                    </div>
                </div>

            </div>

            <div style="background: #080a0f; border: 1px solid #1a1a1a; padding: 12px 15px; border-radius: 4px; border-left: 3px solid ${COLORS.cyan};">
                <div style="font-size: 9px; color: #888; font-weight: bold; margin-bottom: 10px; letter-spacing: 1px;">HỆ THỐNG SÀN BẢO VỆ (FLOORS)</div>
                <div style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: baseline;">
                    <span style="font-size: 10px; color: #ff4400;">SÀN TỬ THỦ (Base)</span>
                    <span style="font-size: 13px; color: #ff4400; font-family: monospace; font-weight: bold;">$${formatMoney(baseFloor)}</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: baseline;">
                    <span style="font-size: 10px; color: ${maxProfit > 0 ? COLORS.green : '#666'};">SÀN KHÓA LÃI (Trail)</span>
                    <span style="font-size: 13px; color: ${maxProfit > 0 ? COLORS.green : '#666'}; font-family: monospace; font-weight: bold;">${trailingStatus}</span>
                </div>
            </div>

            <div style="background: ${COLORS.panelBg}; border: 1px solid ${COLORS.cyan}55; padding: 15px; border-radius: 4px; box-shadow: 0 0 15px ${COLORS.cyan}11;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <div style="font-size: 11px; font-weight: bold; color: ${COLORS.cyan}; letter-spacing: 1px;">⚡ CLOUD RISK FLUX</div>
                    <div style="text-align: right;">
                        <div style="font-size: 9px; color: #888;">Equity Velocity</div>
                        <div style="font-size: 13px; font-weight: bold; color: ${velocityColor};">${velocityValue > 0 ? '+' : ''}${velocityValue.toFixed(2)} $/s</div>
                    </div>
                </div>
                <div style="border-top: 1px dashed #333; margin: 10px 0;"></div>
                <div style="display: flex; justify-content: space-between; font-size: 10px;">
                    <span style="color: #888;">Risk Penalty: <span style="color: ${COLORS.yellow}; font-weight:bold;">${((parseFloat(physics.entropy_tax_rate) || 0) * 100).toFixed(0)}%</span></span>
                    <span style="color: #888;">Damping Output: <span style="color: ${COLORS.cyan}; font-weight:bold;">${(parseFloat(physics.damping_factor) || 0).toFixed(2)}x</span></span>
                </div>
            </div>

            <div>
                <button 
                    onClick=${() => setShowRaw(!showRaw)} 
                    style="width: 100%; background: ${showRaw ? COLORS.cyan + '22' : '#111'}; border: 1px dashed ${showRaw ? COLORS.cyan : '#333'}; color: ${showRaw ? COLORS.cyan : '#888'}; padding: 10px; font-size: 10px; cursor: pointer; letter-spacing: 2px; transition: 0.2s; font-weight: bold;"
                >
                    ${showRaw ? '▲ ENCRYPT METRICS' : '▼ DECRYPT RAW METRICS'}
                </button>

                ${showRaw ? html`

                    <div style="background: #020305; border: 1px solid ${COLORS.cyan}55; border-top: none; padding: 12px; font-family: 'Courier New', monospace; font-size: 9px; color: ${COLORS.cyan}; overflow: hidden; box-shadow: inset 0 0 15px rgba(0,229,255,0.05); animation: slideDown 0.3s ease-out;">
                        <style>@keyframes slideDown { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }</style>
                        <div style="color: ${COLORS.green}; margin-bottom: 8px; border-bottom: 1px dashed #333; padding-bottom: 4px;">> root@z-armor:~/cloud_metrics# cat physics_engine.dump</div>
                        
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; color: #aaa;">
                            <div style="display: flex; justify-content: space-between; border-right: 1px dashed #333; padding-right: 5px;"><span>sys_state</span> <span style="color:${COLORS.yellow};">${physics.state || 'N/A'}</span></div>
                            <div style="display: flex; justify-content: space-between; padding-left: 5px;"><span>z_pressure</span> <span style="color:#fff;">${(parseFloat(physics.z_pressure)||0).toFixed(6)}</span></div>
                            <div style="display: flex; justify-content: space-between; border-right: 1px dashed #333; padding-right: 5px;"><span>base_pres</span> <span style="color:#fff;">${(parseFloat(physics.base_pressure)||0).toFixed(4)}</span></div>
                            <div style="display: flex; justify-content: space-between; padding-left: 5px;"><span>trail_pres</span> <span style="color:#fff;">${(parseFloat(physics.trailing_pressure)||0).toFixed(4)}</span></div>
                            <div style="display: flex; justify-content: space-between; border-right: 1px dashed #333; padding-right: 5px;"><span>damping_out</span> <span style="color:#fff;">${(parseFloat(physics.damping_factor)||0).toFixed(6)}</span></div>
                            <div style="display: flex; justify-content: space-between; padding-left: 5px;"><span>entropy_tax</span> <span style="color:#fff;">${(parseFloat(physics.entropy_tax_rate)||0).toFixed(6)}</span></div>
                            <div style="display: flex; justify-content: space-between; border-right: 1px dashed #333; padding-right: 5px;"><span>budget_usd</span> <span style="color:#fff;">${(parseFloat(physics.dbu_pct)||0).toFixed(4)}%</span></div>
                            <div style="display: flex; justify-content: space-between; padding-left: 5px;"><span>risk_fre</span> <span style="color:#fff;">${(parseFloat(physics.fre_pct)||0).toFixed(4)}%</span></div>
                            <div style="display: flex; justify-content: space-between; border-right: 1px dashed #333; padding-right: 5px;"><span>capacity_cbr</span> <span style="color:#fff;">${(parseFloat(physics.cbr_pct)||0).toFixed(4)}%</span></div>
                            <div style="display: flex; justify-content: space-between; padding-left: 5px;"><span>active_thrd</span> <span style="color:#fff;">${global_status.open_trades?.length || 0}</span></div>
                        </div>
                        
                        <div style="margin-top: 8px; color: #555; border-top: 1px dashed #333; padding-top: 4px; display: flex; justify-content: space-between;">
                            <span>> EOF. Listening...</span>
                            <span class="blink-text" style="color: ${COLORS.cyan}">_</span>
                        </div>
                    </div>
                ` : null}

            </div>
            
        </div>
    `;
}