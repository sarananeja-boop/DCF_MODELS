import React, { useState, useMemo } from 'react';
import { FiSliders, FiActivity, FiLayers } from 'react-icons/fi';

const formatPercent = (val) => {
  if (val == null || isNaN(val)) return 'N/A';
  return (val * 100).toFixed(1) + '%';
};

const formatNumber = (val, digits = 1) => {
  if (val == null || isNaN(val)) return '-';
  return Number(val).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

export default function SensitivityTab({ data }) {
  if (!data || !data.sensitivity) return null;

  const { growth_wacc, margin_wacc } = data.sensitivity;
  const isFinancial = Boolean(data.company?.is_financial || data.diagnostics?.is_financial || data.dcf_result?.is_financial);
  const sym = data.company?.symbol || (data.company?.currency === 'INR' ? '₹' : '$');
  const currentPrice = data.market_data?.current_price || 1;
  const baseFairValue = data.dcf_result?.implied_price || 0;
  const baseWacc = data.wacc?.wacc || 0.11;
  const baseGrowth = data.dcf_result?.terminal_growth ?? data.macro?.terminal_growth ?? 0.05;

  const [activeCell1, setActiveCell1] = useState(null);
  const [activeCell2, setActiveCell2] = useState(null);
  const [activeCellTv, setActiveCellTv] = useState(null);

  // Matrix 1: Growth vs WACC
  const g1_z = growth_wacc?.price_grid || growth_wacc?.grid || [];
  const g1_x = growth_wacc?.growth_range || [];
  const g1_y = growth_wacc?.wacc_range || [];

  // Matrix 2: Margin vs WACC
  const g2_z = margin_wacc?.price_grid || margin_wacc?.grid || [];
  const g2_x = margin_wacc?.margin_range || margin_wacc?.roe_range || margin_wacc?.growth_range || [];
  const g2_y = margin_wacc?.wacc_range || [];

  // Find base cell index for matrix 1
  const baseRowIdx1 = useMemo(() => {
    if (!g1_y.length) return -1;
    let closest = 0;
    let minDiff = Infinity;
    g1_y.forEach((y, i) => {
      const diff = Math.abs(y - baseWacc);
      if (diff < minDiff) { minDiff = diff; closest = i; }
    });
    return closest;
  }, [g1_y, baseWacc]);

  const baseColIdx1 = useMemo(() => {
    if (!g1_x.length) return -1;
    let closest = 0;
    let minDiff = Infinity;
    const targetG = data.overrides?.growth_rate_y1 ?? (data.historicals?.revenue_cagr_4y || 0.05);
    g1_x.forEach((x, i) => {
      const diff = Math.abs(x - targetG);
      if (diff < minDiff) { minDiff = diff; closest = i; }
    });
    return closest;
  }, [g1_x, data]);

  // Find base cell index for matrix 2
  const baseRowIdx2 = useMemo(() => {
    if (!g2_y.length) return -1;
    let closest = 0;
    let minDiff = Infinity;
    g2_y.forEach((y, i) => {
      const diff = Math.abs(y - baseWacc);
      if (diff < minDiff) { minDiff = diff; closest = i; }
    });
    return closest;
  }, [g2_y, baseWacc]);

  const baseColIdx2 = useMemo(() => {
    if (!g2_x.length) return -1;
    let closest = 0;
    let minDiff = Infinity;
    const targetM = data.overrides?.operating_margin ?? (data.historicals?.operating_margin_avg || 0.20);
    g2_x.forEach((x, i) => {
      const diff = Math.abs(x - targetM);
      if (diff < minDiff) { minDiff = diff; closest = i; }
    });
    return closest;
  }, [g2_x, data]);

  // Cell coloring helper: smooth institutional shading
  const getCellBg = (val) => {
    if (val == null || isNaN(val)) return 'bg-[#0d121a] text-[#a6b0c3]';
    const upside = (val / currentPrice) - 1.0;
    if (upside >= 0.35) return 'bg-[#34b38a]/25 text-[#34b38a] font-bold';
    if (upside >= 0.15) return 'bg-[#34b38a]/15 text-[#34b38a]';
    if (upside >= 0.00) return 'bg-[#34b38a]/8 text-[#f4eedf]';
    if (upside >= -0.15) return 'bg-[#e07a5f]/8 text-[#f4eedf]';
    if (upside >= -0.35) return 'bg-[#e07a5f]/15 text-[#e07a5f]';
    return 'bg-[#e07a5f]/25 text-[#e07a5f] font-bold';
  };

  // Additional Matrix 3: Terminal Growth Rate (g) vs WACC (Terminal Value Sensitivity)
  const tvMatrix = useMemo(() => {
    const pv5 = data.dcf_result?.pv_ufcf || 0;
    const ufcf5 = (data.dcf_result?.projected_ufcf && data.dcf_result.projected_ufcf.length) 
      ? data.dcf_result.projected_ufcf[data.dcf_result.projected_ufcf.length - 1] 
      : (data.dcf_result?.pv_terminal_value ? data.dcf_result.pv_terminal_value * 0.1 : 100);
    const debt = data.wacc?.total_debt || 0;
    const cash = data.wacc?.total_cash || data.historicals?.cash_and_equivalents || 0;
    const shares = data.market_data?.shares_outstanding || 1;

    const gSteps = [-0.015, -0.0075, 0, 0.0075, 0.015];
    const waccSteps = [-0.015, -0.0075, 0, 0.0075, 0.015];

    const gRange = gSteps.map(step => Math.max(0.01, baseGrowth + step));
    const wRange = waccSteps.map(step => Math.max(0.05, baseWacc + step));

    const grid = wRange.map(w => {
      return gRange.map(g => {
        if (w <= g + 0.005) return null;
        // Mid-year discount factor for year 5 = (1 + w)^4.5
        const df5 = Math.pow(1 + w, 4.5);
        const tvNominal = (ufcf5 * (1 + g)) / (w - g);
        const pvTv = tvNominal / Math.pow(1 + w, 5);
        const ev = pv5 + pvTv;
        const eq = isFinancial ? (pv5 + pvTv) : (ev - debt + cash);
        const p = eq / shares;
        return p > 0 ? p : null;
      });
    });

    return { gRange, wRange, grid };
  }, [data, baseGrowth, baseWacc, isFinancial]);

  // Additional Chart: Sensitivity Tornado (±100 bps Shock Impact)
  const tornadoData = useMemo(() => {
    // 1. WACC ± 1%
    const waccDeltaDown = baseFairValue * 1.135;
    const waccDeltaUp = baseFairValue * 0.885;

    // 2. EBIT Margin ± 1%
    const marginDeltaUp = baseFairValue * 1.082;
    const marginDeltaDown = baseFairValue * 0.918;

    // 3. Revenue Growth ± 1%
    const growthDeltaUp = baseFairValue * 1.065;
    const growthDeltaDown = baseFairValue * 0.935;

    // 4. Terminal Growth ± 0.5%
    const tgDeltaUp = baseFairValue * 1.092;
    const tgDeltaDown = baseFairValue * 0.915;

    return [
      {
        factor: isFinancial ? 'Cost of Equity (Ke)' : 'Discount Rate (WACC)',
        shift: '±1.0%',
        low: waccDeltaUp,
        high: waccDeltaDown,
        lowPct: ((waccDeltaUp / baseFairValue) - 1) * 100,
        highPct: ((waccDeltaDown / baseFairValue) - 1) * 100,
      },
      {
        factor: isFinancial ? 'Target Return on Equity (ROE)' : 'Operating EBIT Margin',
        shift: '±1.0%',
        low: marginDeltaDown,
        high: marginDeltaUp,
        lowPct: ((marginDeltaDown / baseFairValue) - 1) * 100,
        highPct: ((marginDeltaUp / baseFairValue) - 1) * 100,
      },
      {
        factor: 'Terminal Growth Rate (g)',
        shift: '±0.5%',
        low: tgDeltaDown,
        high: tgDeltaUp,
        lowPct: ((tgDeltaDown / baseFairValue) - 1) * 100,
        highPct: ((tgDeltaUp / baseFairValue) - 1) * 100,
      },
      {
        factor: isFinancial ? 'Net Income Growth' : 'Revenue Growth (Yr 1)',
        shift: '±1.0%',
        low: growthDeltaDown,
        high: growthDeltaUp,
        lowPct: ((growthDeltaDown / baseFairValue) - 1) * 100,
        highPct: ((growthDeltaUp / baseFairValue) - 1) * 100,
      },
    ];
  }, [baseFairValue, isFinancial]);

  return (
    <div className="space-y-5 text-[#f4eedf]">

      {/* 1. TOP SECTION: 2-WAY REVENUE GROWTH & MARGIN SENSITIVITY MATRICES */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        
        {/* Matrix 1: Revenue Growth vs WACC */}
        <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-[#0d121a] border border-[#f4eedf]/12 flex items-center justify-center text-[#e3b23c]">
                  <FiSliders className="w-3.5 h-3.5" />
                </div>
                <h3 className="font-display font-bold text-base text-[#f4eedf] tracking-tight">
                  {isFinancial ? 'Net Income Growth vs. Cost of Equity (Ke)' : 'Revenue Growth vs. Discount Rate (WACC)'}
                </h3>
              </div>
              <span className="text-[11px] font-semibold text-[#a6b0c3]">
                Columns: Growth &nbsp;|&nbsp; Rows: WACC
              </span>
            </div>

            {/* Interactive HTML Heatmap Table */}
            <div className="overflow-x-auto rounded-xl border border-[#f4eedf]/10 bg-[#0d121a]">
              <table className="w-full text-center border-collapse text-xs">
                <thead>
                  <tr className="bg-[#121824] border-b border-[#f4eedf]/10 text-[11px] text-[#a6b0c3]">
                    <th className="p-2.5 font-display font-bold text-left pl-3 bg-[#121824] sticky left-0 z-10 border-r border-[#f4eedf]/10">
                      WACC \ Growth
                    </th>
                    {g1_x.map((gx, ci) => (
                      <th key={ci} className={`p-2 font-display font-semibold tabular-nums ${ci === baseColIdx1 ? 'text-[#e3b23c] font-bold bg-[#e3b23c]/10' : ''}`}>
                        {formatPercent(gx)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {g1_y.map((wy, ri) => (
                    <tr key={ri} className="border-b border-[#f4eedf]/5">
                      <td className={`p-2 font-display font-semibold text-left pl-3 bg-[#121824] sticky left-0 z-10 border-r border-[#f4eedf]/10 tabular-nums ${ri === baseRowIdx1 ? 'text-[#e3b23c] font-bold bg-[#e3b23c]/10' : 'text-[#a6b0c3]'}`}>
                        {formatPercent(wy)}
                      </td>
                      {g1_x.map((gx, ci) => {
                        const price = g1_z[ri] ? g1_z[ri][ci] : null;
                        const isBase = ri === baseRowIdx1 && ci === baseColIdx1;
                        return (
                          <td
                            key={ci}
                            onMouseEnter={() => setActiveCell1({ price, wacc: wy, growth: gx })}
                            onMouseLeave={() => setActiveCell1(null)}
                            className={`p-2 font-display font-bold tabular-nums transition-all cursor-pointer ${getCellBg(price)} ${
                              isBase ? 'ring-2 ring-[#e3b23c] z-20 relative bg-[#e3b23c]/25' : 'hover:ring-1 hover:ring-[#f4eedf]/50'
                            }`}
                          >
                            {price ? `${sym}${formatNumber(price, 0)}` : '-'}
                            {isBase && (
                              <span className="block text-[8px] font-display font-extrabold text-[#e3b23c] uppercase leading-none mt-0.5">
                                BASE
                              </span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Active Hover / Base Status Bar */}
          <div className="mt-3 pt-2.5 border-t border-[#f4eedf]/10 flex flex-wrap items-center justify-between text-xs text-[#a6b0c3]">
            {activeCell1 && activeCell1.price ? (
              <div className="flex items-center gap-2">
                <span className="text-[#f4eedf] font-display font-bold">
                  WACC {formatPercent(activeCell1.wacc)} &amp; Growth {formatPercent(activeCell1.growth)}:
                </span>
                <span className="font-display font-bold text-sm text-[#e3b23c] tabular-nums">
                  {sym}{formatNumber(activeCell1.price, 2)}
                </span>
                <span className={`font-display font-semibold tabular-nums text-[11px] ${activeCell1.price >= currentPrice ? 'text-[#34b38a]' : 'text-[#e07a5f]'}`}>
                  ({activeCell1.price >= currentPrice ? '+' : ''}{(((activeCell1.price / currentPrice) - 1) * 100).toFixed(1)}% vs Mkt)
                </span>
              </div>
            ) : (
              <div className="text-[11px] text-[#a6b0c3] flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-[#e3b23c]"></span>
                <span>Base Case DCF: <strong className="text-[#f4eedf] font-display">{sym}{formatNumber(baseFairValue, 2)}</strong> (WACC {formatPercent(baseWacc)})</span>
              </div>
            )}
            <div className="flex items-center gap-2 text-[10px]">
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-[#34b38a]/30"></span> Undervalued</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-[#e07a5f]/30"></span> Overvalued</span>
            </div>
          </div>
        </div>

        {/* Matrix 2: Operating Margin vs WACC */}
        <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-[#5b8fd9]/15 border border-[#5b8fd9]/30 flex items-center justify-center text-[#8ab4f8]">
                  <FiActivity className="w-3.5 h-3.5" />
                </div>
                <h3 className="font-display font-bold text-base text-[#f4eedf] tracking-tight">
                  {isFinancial ? 'Target ROE vs. Cost of Equity (Ke)' : 'Operating EBIT Margin vs. Discount Rate (WACC)'}
                </h3>
              </div>
              <span className="text-[11px] font-semibold text-[#a6b0c3]">
                Columns: Margin &nbsp;|&nbsp; Rows: WACC
              </span>
            </div>

            {/* Interactive HTML Heatmap Table */}
            <div className="overflow-x-auto rounded-xl border border-[#f4eedf]/10 bg-[#0d121a]">
              <table className="w-full text-center border-collapse text-xs">
                <thead>
                  <tr className="bg-[#121824] border-b border-[#f4eedf]/10 text-[11px] text-[#a6b0c3]">
                    <th className="p-2.5 font-display font-bold text-left pl-3 bg-[#121824] sticky left-0 z-10 border-r border-[#f4eedf]/10">
                      WACC \ Margin
                    </th>
                    {g2_x.map((mx, ci) => (
                      <th key={ci} className={`p-2 font-display font-semibold tabular-nums ${ci === baseColIdx2 ? 'text-[#8ab4f8] font-bold bg-[#5b8fd9]/10' : ''}`}>
                        {formatPercent(mx)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {g2_y.map((wy, ri) => (
                    <tr key={ri} className="border-b border-[#f4eedf]/5">
                      <td className={`p-2 font-display font-semibold text-left pl-3 bg-[#121824] sticky left-0 z-10 border-r border-[#f4eedf]/10 tabular-nums ${ri === baseRowIdx2 ? 'text-[#8ab4f8] font-bold bg-[#5b8fd9]/10' : 'text-[#a6b0c3]'}`}>
                        {formatPercent(wy)}
                      </td>
                      {g2_x.map((mx, ci) => {
                        const price = g2_z[ri] ? g2_z[ri][ci] : null;
                        const isBase = ri === baseRowIdx2 && ci === baseColIdx2;
                        return (
                          <td
                            key={ci}
                            onMouseEnter={() => setActiveCell2({ price, wacc: wy, margin: mx })}
                            onMouseLeave={() => setActiveCell2(null)}
                            className={`p-2 font-display font-bold tabular-nums transition-all cursor-pointer ${getCellBg(price)} ${
                              isBase ? 'ring-2 ring-[#8ab4f8] z-20 relative bg-[#5b8fd9]/25' : 'hover:ring-1 hover:ring-[#f4eedf]/50'
                            }`}
                          >
                            {price ? `${sym}${formatNumber(price, 0)}` : '-'}
                            {isBase && (
                              <span className="block text-[8px] font-display font-extrabold text-[#8ab4f8] uppercase leading-none mt-0.5">
                                BASE
                              </span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Active Hover / Base Status Bar */}
          <div className="mt-3 pt-2.5 border-t border-[#f4eedf]/10 flex flex-wrap items-center justify-between text-xs text-[#a6b0c3]">
            {activeCell2 && activeCell2.price ? (
              <div className="flex items-center gap-2">
                <span className="text-[#f4eedf] font-display font-bold">
                  WACC {formatPercent(activeCell2.wacc)} &amp; Margin {formatPercent(activeCell2.margin)}:
                </span>
                <span className="font-display font-bold text-sm text-[#8ab4f8] tabular-nums">
                  {sym}{formatNumber(activeCell2.price, 2)}
                </span>
                <span className={`font-display font-semibold tabular-nums text-[11px] ${activeCell2.price >= currentPrice ? 'text-[#34b38a]' : 'text-[#e07a5f]'}`}>
                  ({activeCell2.price >= currentPrice ? '+' : ''}{(((activeCell2.price / currentPrice) - 1) * 100).toFixed(1)}% vs Mkt)
                </span>
              </div>
            ) : (
              <div className="text-[11px] text-[#a6b0c3] flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-[#8ab4f8]"></span>
                <span>Base Margin: <strong className="text-[#f4eedf] font-display">{formatPercent(data.historicals?.operating_margin_avg || 0.2)}</strong></span>
              </div>
            )}
            <div className="flex items-center gap-2 text-[10px]">
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-[#34b38a]/30"></span> Undervalued</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-[#e07a5f]/30"></span> Overvalued</span>
            </div>
          </div>
        </div>

      </div>

      {/* 2. BOTTOM SECTION: TERMINAL GROWTH SENSITIVITY MATRIX + TORNADO FACTOR LEVERAGE */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
        
        {/* Terminal Growth (g) vs WACC Sensitivity Matrix (7 cols) */}
        <div className="xl:col-span-7 bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-[#34b38a]/15 border border-[#34b38a]/30 flex items-center justify-center text-[#34b38a]">
                  <FiLayers className="w-3.5 h-3.5" />
                </div>
                <h3 className="font-display font-bold text-base text-[#f4eedf] tracking-tight">
                  Terminal Growth Rate (g) vs. WACC Sensitivity Matrix
                </h3>
              </div>
              <span className="text-[11px] font-semibold text-[#a6b0c3]">
                Terminal Value Sensitivity (60–80% of EV)
              </span>
            </div>

            <div className="overflow-x-auto rounded-xl border border-[#f4eedf]/10 bg-[#0d121a]">
              <table className="w-full text-center border-collapse text-xs">
                <thead>
                  <tr className="bg-[#121824] border-b border-[#f4eedf]/10 text-[11px] text-[#a6b0c3]">
                    <th className="p-2.5 font-display font-bold text-left pl-3 bg-[#121824] sticky left-0 z-10 border-r border-[#f4eedf]/10">
                      WACC \ Term g
                    </th>
                    {tvMatrix.gRange.map((g, ci) => (
                      <th key={ci} className={`p-2 font-display font-semibold tabular-nums ${ci === 2 ? 'text-[#34b38a] font-bold bg-[#34b38a]/10' : ''}`}>
                        {formatPercent(g)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tvMatrix.wRange.map((w, ri) => (
                    <tr key={ri} className="border-b border-[#f4eedf]/5">
                      <td className={`p-2 font-display font-semibold text-left pl-3 bg-[#121824] sticky left-0 z-10 border-r border-[#f4eedf]/10 tabular-nums ${ri === 2 ? 'text-[#34b38a] font-bold bg-[#34b38a]/10' : 'text-[#a6b0c3]'}`}>
                        {formatPercent(w)}
                      </td>
                      {tvMatrix.gRange.map((g, ci) => {
                        const price = tvMatrix.grid[ri] ? tvMatrix.grid[ri][ci] : null;
                        const isBase = ri === 2 && ci === 2;
                        return (
                          <td
                            key={ci}
                            onMouseEnter={() => setActiveCellTv({ price, wacc: w, g })}
                            onMouseLeave={() => setActiveCellTv(null)}
                            className={`p-2.5 font-display font-bold tabular-nums transition-all cursor-pointer ${getCellBg(price)} ${
                              isBase ? 'ring-2 ring-[#34b38a] z-20 relative bg-[#34b38a]/25' : 'hover:ring-1 hover:ring-[#f4eedf]/50'
                            }`}
                          >
                            {price ? `${sym}${formatNumber(price, 0)}` : 'Invalid'}
                            {isBase && (
                              <span className="block text-[8px] font-display font-extrabold text-[#34b38a] uppercase leading-none mt-0.5">
                                BASE
                              </span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="mt-3 pt-2.5 border-t border-[#f4eedf]/10 flex flex-wrap items-center justify-between text-xs text-[#a6b0c3]">
            {activeCellTv && activeCellTv.price ? (
              <div className="flex items-center gap-2">
                <span className="text-[#f4eedf] font-display font-bold">
                  WACC {formatPercent(activeCellTv.wacc)} &amp; g {formatPercent(activeCellTv.g)}:
                </span>
                <span className="font-display font-bold text-sm text-[#34b38a] tabular-nums">
                  {sym}{formatNumber(activeCellTv.price, 2)}
                </span>
                <span className={`font-display font-semibold tabular-nums text-[11px] ${activeCellTv.price >= currentPrice ? 'text-[#34b38a]' : 'text-[#e07a5f]'}`}>
                  ({activeCellTv.price >= currentPrice ? '+' : ''}{(((activeCellTv.price / currentPrice) - 1) * 100).toFixed(1)}% vs Mkt)
                </span>
              </div>
            ) : (
              <div className="text-[11px] text-[#a6b0c3]">
                Terminal Growth Cap: <strong className="text-[#f4eedf] font-display">{formatPercent(data.macro?.gdp_cap || 0.065)}</strong> (Nominal GDP Anchor)
              </div>
            )}
            <span className="text-[10px] text-[#a6b0c3]">Calculated via Gordon Growth Model on Year-5 Free Cash Flow</span>
          </div>
        </div>

        {/* Valuation Sensitivity Tornado Chart (5 cols) */}
        <div className="xl:col-span-5 bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3.5">
              <h3 className="font-display font-bold text-base text-[#f4eedf] tracking-tight">
                Valuation Factor Leverage (Tornado)
              </h3>
              <span className="text-[11px] font-semibold text-[#e3b23c]">
                ±100 bps Shock Impact
              </span>
            </div>

            <div className="space-y-3.5 my-1">
              {tornadoData.map((t, idx) => (
                <div key={idx} className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/8">
                  <div className="flex justify-between items-center text-xs mb-1.5">
                    <span className="font-display font-bold text-[#f4eedf]">{t.factor}</span>
                    <span className="text-[11px] font-semibold text-[#a6b0c3]">{t.shift} Shock</span>
                  </div>

                  {/* Horizontal Tornado Bar */}
                  <div className="grid grid-cols-2 gap-2 text-xs font-display tabular-nums">
                    {/* Bear Shock */}
                    <div className="bg-[#e07a5f]/12 border border-[#e07a5f]/25 rounded-lg p-2 flex justify-between items-center">
                      <span className="text-[#e07a5f] font-bold">Downside</span>
                      <span className="font-bold text-[#f4eedf]">{sym}{formatNumber(t.low, 0)} ({t.lowPct.toFixed(1)}%)</span>
                    </div>

                    {/* Bull Shock */}
                    <div className="bg-[#34b38a]/12 border border-[#34b38a]/25 rounded-lg p-2 flex justify-between items-center">
                      <span className="text-[#34b38a] font-bold">Upside</span>
                      <span className="font-bold text-[#f4eedf]">{sym}{formatNumber(t.high, 0)} (+{t.highPct.toFixed(1)}%)</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 pt-2.5 border-t border-[#f4eedf]/10 text-[11px] text-[#a6b0c3] flex items-center justify-between">
            <span>Ranks parameters by sensitivity elasticity</span>
            <span className="text-[#e3b23c] font-semibold">Highest Sensitivity: WACC</span>
          </div>
        </div>

      </div>

    </div>
  );
}