import React from 'react';
import { FiArrowRight } from 'react-icons/fi';

const DCFModelTab = ({ data }) => {
  if (!data || !data.dcf_result) return null;

  const { company: comp, dcf_result: dcf, wacc: waccObj } = data;
  const isFinancial = Boolean(comp?.is_financial || data.diagnostics?.is_financial || dcf?.is_financial);
  const symbol = comp?.symbol || '$';
  const market = comp?.market || 'US';

  const formatNum = (val, curSymbol = symbol, curMarket = market) => {
    if (val === undefined || val === null || isNaN(val)) return '-';
    
    let formattedVal = '';
    
    if (curMarket === 'IN') {
      if (Math.abs(val) >= 1e7) {
        formattedVal = (val / 1e7).toFixed(2) + 'Cr';
      } else if (Math.abs(val) >= 1e5) {
        formattedVal = (val / 1e5).toFixed(2) + 'L';
      } else {
        formattedVal = new Intl.NumberFormat('en-IN').format(val);
      }
    } else {
      if (Math.abs(val) >= 1e9) {
        formattedVal = (val / 1e9).toFixed(2) + 'B';
      } else if (Math.abs(val) >= 1e6) {
        formattedVal = (val / 1e6).toFixed(2) + 'M';
      } else if (Math.abs(val) >= 1e3) {
        formattedVal = (val / 1e3).toFixed(2) + 'K';
      } else {
        formattedVal = new Intl.NumberFormat('en-US').format(val);
      }
    }
    
    return `${curSymbol}${formattedVal}`;
  };

  const formatPct = (val) => {
    if (val === undefined || val === null || isNaN(val)) return '-';
    return (val * 100).toFixed(1) + '%';
  };

  const projectionYears = dcf.projected_revenue?.length || 0;
  const cash = waccObj?.total_cash ?? comp?.total_cash ?? comp?.cash;
  
  return (
    <div className="space-y-6">
      {/* Projected Financials Table */}
      <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800">
        <div className="mb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h2 className="text-xl font-semibold text-slate-100">
              {isFinancial ? 'Projected Financials (Regulatory Capital FCFE Model)' : 'Projected Financials'}
            </h2>
            <p className="text-sm text-slate-400">
              {projectionYears}-Year Forecast Horizon {isFinancial ? '— Tier-1 Regulatory Capital Retention' : ''}
            </p>
          </div>
          {isFinancial && (
            <span className="px-3 py-1 rounded-full bg-emerald-900/30 border border-emerald-500/30 text-emerald-300 font-mono text-xs w-fit">
              Damodaran Bank Valuation Framework
            </span>
          )}
        </div>
        
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-zinc-900 text-slate-400 uppercase text-xs tracking-wider">
              <tr>
                <th className="px-4 py-3 font-medium rounded-tl-lg sticky left-0 bg-zinc-900 z-10">Metric</th>
                {Array.from({ length: projectionYears }).map((_, i) => (
                  <th key={i} className="px-4 py-3 font-medium text-right min-w-[100px]">
                    Year {i + 1}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800 border-b border-zinc-800">
              {/* Revenue / Net Income */}
              <tr className="bg-zinc-800/80 hover:bg-zinc-800/50 transition-colors">
                <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-zinc-800/80 z-10 border-r border-zinc-800/30">
                  {isFinancial ? 'Projected Net Income' : 'Revenue'}
                </td>
                {dcf.projected_revenue?.map((val, i) => (
                  <td key={i} className="px-4 py-3 text-right font-mono tabular-nums text-slate-300">
                    {formatNum(val)}
                  </td>
                ))}
              </tr>
              {/* Growth Rate */}
              <tr className="bg-zinc-900/50 hover:bg-zinc-800/80 transition-colors">
                <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-zinc-900/50 z-10 border-r border-zinc-800/30">
                  {isFinancial ? 'Net Income Growth Rate (g)' : 'Growth Rate'}
                </td>
                {dcf.growth_schedule?.map((val, i) => (
                  <td key={i} className="px-4 py-3 text-right font-mono tabular-nums text-slate-300">
                    {formatPct(val)}
                  </td>
                ))}
              </tr>
              {/* Margin / ROE */}
              {dcf.margin_schedule && (
                <tr className="bg-zinc-900/30 hover:bg-zinc-800/80 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-zinc-900/30 z-10 border-r border-zinc-800/30">
                    {isFinancial ? 'Target Return on Equity (ROE)' : 'EBIT Margin'}
                  </td>
                  {dcf.margin_schedule.map((val, i) => (
                    <td key={i} className="px-4 py-3 text-right font-mono tabular-nums text-slate-400">
                      {formatPct(val)}
                    </td>
                  ))}
                </tr>
              )}
              {/* NOPAT / Reported Net Income */}
              {dcf.projected_nopat && !isFinancial && (
                <tr className="bg-zinc-800/40 hover:bg-zinc-800/80 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-zinc-800/40 z-10 border-r border-zinc-800/30">
                    NOPAT
                  </td>
                  {dcf.projected_nopat.map((val, i) => (
                    <td key={i} className="px-4 py-3 text-right font-mono tabular-nums text-slate-400">
                      {formatNum(val)}
                    </td>
                  ))}
                </tr>
              )}
              {/* D&A / Regulatory Capital Retained */}
              {dcf.projected_dna && (
                <tr className="bg-zinc-900/30 hover:bg-zinc-800/80 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-zinc-900/30 z-10 border-r border-zinc-800/30">
                    {isFinancial ? '(−) Tier-1 Regulatory Capital Retained' : '(+) D&A'}
                  </td>
                  {dcf.projected_dna.map((val, i) => (
                    <td key={i} className="px-4 py-3 text-right font-mono tabular-nums text-slate-400">
                      {isFinancial ? `- ${formatNum(val)}` : formatNum(val)}
                    </td>
                  ))}
                </tr>
              )}
              {/* CapEx (Non-financial only) */}
              {dcf.projected_capex && !isFinancial && (
                <tr className="bg-zinc-800/40 hover:bg-zinc-800/80 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-zinc-800/40 z-10 border-r border-zinc-800/30">
                    (-) CapEx
                  </td>
                  {dcf.projected_capex.map((val, i) => (
                    <td key={i} className="px-4 py-3 text-right font-mono tabular-nums text-slate-400">
                      {formatNum(val)}
                    </td>
                  ))}
                </tr>
              )}
              {/* ΔNWC (Non-financial only) */}
              {dcf.projected_dnwc && !isFinancial && (
                <tr className="bg-zinc-900/30 hover:bg-zinc-800/80 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-zinc-900/30 z-10 border-r border-zinc-800/30">
                    (-) ΔNWC
                  </td>
                  {dcf.projected_dnwc.map((val, i) => (
                    <td key={i} className="px-4 py-3 text-right font-mono tabular-nums text-slate-400">
                      {formatNum(val)}
                    </td>
                  ))}
                </tr>
              )}
              {/* UFCF / FCFE */}
              <tr className="bg-zinc-800/90 hover:bg-zinc-800 transition-colors border-t border-zinc-700">
                <td className="px-4 py-3 font-semibold text-slate-100 sticky left-0 bg-zinc-800/90 z-10 border-r border-zinc-800/30">
                  {isFinancial ? 'Free Cash Flow to Equity (FCFE)' : 'Unlevered FCF (UFCF)'}
                </td>
                {dcf.projected_ufcf?.map((val, i) => (
                  <td key={i} className="px-4 py-3 text-right font-bold font-mono tabular-nums text-emerald-400">
                    {formatNum(val)}
                  </td>
                ))}
              </tr>
              {/* Mid-Year Period (t) */}
              {dcf.discount_periods && (
                <tr className="bg-zinc-900/40 hover:bg-zinc-800/60 transition-colors text-xs">
                  <td className="px-4 py-2.5 font-medium text-slate-400 sticky left-0 bg-zinc-900/40 z-10 border-r border-zinc-800/30">
                    Mid-Year Period (t)
                  </td>
                  {dcf.discount_periods.map((t, i) => (
                    <td key={i} className="px-4 py-2.5 text-right font-mono tabular-nums text-slate-400">
                      {t.toFixed(1)}
                    </td>
                  ))}
                </tr>
              )}
              {/* Discount Factor */}
              {dcf.discount_factors && (
                <tr className="bg-zinc-900/30 hover:bg-zinc-800/60 transition-colors text-xs">
                  <td className="px-4 py-2.5 font-medium text-slate-400 sticky left-0 bg-zinc-900/30 z-10 border-r border-zinc-800/30">
                    {isFinancial ? 'Discount Factor [1/(1+Ke)^t]' : 'Discount Factor [1/(1+WACC)^t]'}
                  </td>
                  {dcf.discount_factors.map((df, i) => (
                    <td key={i} className="px-4 py-2.5 text-right font-mono tabular-nums text-blue-400">
                      {df.toFixed(4)}
                    </td>
                  ))}
                </tr>
              )}
              {/* PV of UFCF / FCFE */}
              {dcf.pv_ufcf_list && (
                <tr className="bg-emerald-950/20 hover:bg-emerald-950/30 transition-colors border-t border-emerald-900/40">
                  <td className="px-4 py-3 font-semibold text-emerald-300 sticky left-0 bg-zinc-800/90 z-10 border-r border-zinc-800/30">
                    {isFinancial ? 'Present Value of FCFE' : 'Present Value of UFCF'}
                  </td>
                  {dcf.pv_ufcf_list.map((pv, i) => (
                    <td key={i} className="px-4 py-3 text-right font-bold font-mono tabular-nums text-emerald-300">
                      {formatNum(pv)}
                    </td>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Terminal Value / Valuation Breakdown Section */}
      <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800 mt-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
          <h2 className="text-xl font-semibold text-slate-100">
            {isFinancial ? 'Equity Value & Terminal Value Breakdown' : 'Enterprise Value Breakdown'}
          </h2>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="px-2.5 py-1 rounded bg-blue-900/30 border border-blue-500/30 text-blue-300 font-mono">
              Mid-Year Convention Active
            </span>
            <span className="px-2.5 py-1 rounded bg-zinc-700/50 border border-zinc-600/30 text-zinc-300 font-mono">
              {isFinancial ? 'Discount: Ke (CAPM)' : `Tax Rate: ${formatPct(dcf.tax_rate ?? (market === 'IN' ? 0.2517 : 0.21))}`}
            </span>
            <span className="px-2.5 py-1 rounded bg-zinc-700/50 border border-zinc-600/30 text-zinc-300 font-mono">
              Terminal g: {formatPct(dcf.terminal_growth ?? (market === 'IN' ? 0.055 : 0.025))}
            </span>
          </div>
        </div>
        
        {!data.diagnostics?.terminal_value_valid && data.diagnostics?.terminal_value_note && (
          <div className="mb-4 bg-amber-900/20 border border-amber-500/30 p-3 rounded-lg text-amber-200/90 text-sm">
            {data.diagnostics.terminal_value_note}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800/50">
            <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">
              {isFinancial ? 'PV of 5-Yr FCFEs' : 'PV of 5-Yr Cash Flows'}
            </p>
            <p className="text-xl font-semibold text-emerald-400 font-mono tabular-nums">
              {formatNum(dcf.pv_ufcf)}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              {isFinancial ? 'Sum of discounted FCFE' : 'Sum of discounted UFCF'}
            </p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800/50">
            <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">
              {isFinancial ? 'Terminal Equity Value (Nominal)' : 'Terminal Value (Nominal)'}
            </p>
            {dcf.terminal_value === null || !data.diagnostics?.terminal_value_valid ? (
              <p className="text-xl font-semibold text-zinc-500 font-mono tabular-nums">N/A</p>
            ) : (
              <p className="text-xl font-semibold text-slate-100 font-mono tabular-nums">
                {formatNum(dcf.terminal_value)}
              </p>
            )}
            <p className="text-xs text-slate-500 mt-1">Gordon Growth formula</p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800/50">
            <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">PV of Terminal Value</p>
            <p className="text-xl font-semibold text-blue-400 font-mono tabular-nums">
              {formatNum(dcf.pv_terminal_value)}
            </p>
            <p className="text-xs text-slate-500 mt-1">Discounted using Year 5 factor</p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800/50">
            <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">
              {isFinancial ? 'Total Implied Equity Value' : 'Enterprise Value'}
            </p>
            <p className="text-xl font-semibold text-white font-mono tabular-nums">
              {formatNum(isFinancial ? dcf.equity_value : dcf.enterprise_value)}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              {isFinancial ? 'PV(FCFE) + PV(Terminal Equity)' : 'PV(UFCF) + PV(Terminal)'}
            </p>
          </div>
        </div>
      </div>

      {/* Equity Valuation Bridge Section */}
      <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800 mt-4">
        <h2 className="text-xl font-semibold text-slate-100 mb-4">
          {isFinancial ? 'Bank Equity Valuation Bridge' : 'Equity Bridge'}
        </h2>
        
        {isFinancial ? (
          <div className="space-y-4">
            <div className="flex flex-col md:flex-row items-center justify-between gap-4 overflow-x-auto pb-2">
              {/* PV of 5-Yr FCFE */}
              <div className="flex-1 min-w-[140px] bg-zinc-900 rounded-lg p-4 text-center border border-zinc-800/50">
                <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">PV of 5-Yr FCFE</p>
                <p className="text-lg font-semibold text-emerald-400 font-mono tabular-nums">
                  {formatNum(dcf.pv_ufcf)}
                </p>
              </div>

              <div className="text-slate-500 hidden md:block">+</div>
              <div className="text-slate-500 md:hidden">+</div>

              {/* PV of Terminal Value */}
              <div className="flex-1 min-w-[140px] bg-zinc-900 rounded-lg p-4 text-center border border-zinc-800/50">
                <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">PV of Terminal Value</p>
                <p className="text-lg font-semibold text-blue-400 font-mono tabular-nums">
                  {formatNum(dcf.pv_terminal_value)}
                </p>
              </div>

              <div className="text-slate-500 hidden md:block">=</div>
              <div className="text-slate-500 md:hidden">=</div>

              {/* Total Equity Value */}
              <div className="flex-1 min-w-[140px] bg-zinc-900 rounded-lg p-4 text-center border border-zinc-800/50">
                <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Total Equity Value</p>
                <p className="text-lg font-semibold text-slate-100 font-mono tabular-nums">
                  {formatNum(dcf.equity_value)}
                </p>
              </div>

              <div className="text-slate-500 hidden md:block"><FiArrowRight size={20} /></div>
              <div className="text-slate-500 md:hidden rotate-90"><FiArrowRight size={20} /></div>

              {/* Implied Price per Share */}
              <div className="flex-1 min-w-[140px] bg-accent-blue/10 rounded-lg p-4 text-center border border-accent-blue/30 shadow-[0_0_15px_rgba(59,130,246,0.15)]">
                <p className="text-accent-blue/80 text-xs uppercase tracking-wider mb-1 font-semibold">FCFE Fair Value</p>
                <p className="text-2xl font-bold text-white font-mono tabular-nums">
                  {formatNum(dcf.implied_price)}
                </p>
              </div>
            </div>

            {/* Justified Price-to-Book (P/B) Cross-Check Banner */}
            {(data.diagnostics?.justified_pb || dcf.justified_pb) && (
              <div className="bg-zinc-900/80 rounded-lg p-4 border border-zinc-700/50 flex flex-col sm:flex-row items-center justify-between gap-4">
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wider text-amber-400">
                    Valuation Sanity Check: Justified Price-to-Book Model
                  </span>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Justified P/B = (ROE − g) / (Ke − g) applied to Book Value per Share (BVPS)
                  </p>
                </div>
                <div className="flex items-center gap-4 text-sm font-mono">
                  <div className="text-right">
                    <span className="text-xs text-slate-400 block">BVPS</span>
                    <span className="text-slate-200 font-bold">{formatNum(data.diagnostics?.bvps ?? dcf.bvps)}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-xs text-slate-400 block">Justified P/B</span>
                    <span className="text-amber-300 font-bold">{(data.diagnostics?.justified_pb ?? dcf.justified_pb).toFixed(2)}x</span>
                  </div>
                  <div className="text-right pl-3 border-l border-zinc-700">
                    <span className="text-xs text-slate-400 block">Justified Fair Value</span>
                    <span className="text-emerald-300 font-bold text-base">{formatNum(data.diagnostics?.justified_price ?? dcf.justified_price)}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col md:flex-row items-center justify-between gap-4 overflow-x-auto pb-2">
            {/* Enterprise Value */}
            <div className="flex-1 min-w-[140px] bg-zinc-900 rounded-lg p-4 text-center border border-zinc-800/50">
              <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Enterprise Value</p>
              <p className="text-lg font-semibold text-slate-100 font-mono tabular-nums">
                {formatNum(dcf.enterprise_value)}
              </p>
            </div>
            
            <div className="text-slate-500 hidden md:block"><FiArrowRight size={20} /></div>
            <div className="text-slate-500 md:hidden rotate-90"><FiArrowRight size={20} /></div>
            
            {/* Less Debt */}
            <div className="flex-1 min-w-[140px] bg-zinc-900 rounded-lg p-4 text-center border border-zinc-800/50">
              <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Total Debt</p>
              <p className="text-lg font-semibold text-accent-red font-mono tabular-nums">
                - {formatNum(waccObj?.total_debt)}
              </p>
            </div>
            
            {cash !== undefined && (
              <>
                <div className="text-slate-500 hidden md:block"><FiArrowRight size={20} /></div>
                <div className="text-slate-500 md:hidden rotate-90"><FiArrowRight size={20} /></div>
                
                {/* Plus Cash */}
                <div className="flex-1 min-w-[140px] bg-zinc-900 rounded-lg p-4 text-center border border-zinc-800/50">
                  <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Cash</p>
                  <p className="text-lg font-semibold text-accent-green font-mono tabular-nums">
                    + {formatNum(cash)}
                  </p>
                </div>
              </>
            )}

            <div className="text-slate-500 hidden md:block"><FiArrowRight size={20} /></div>
            <div className="text-slate-500 md:hidden rotate-90"><FiArrowRight size={20} /></div>
            
            {/* Equity Value */}
            <div className="flex-1 min-w-[140px] bg-zinc-900 rounded-lg p-4 text-center border border-zinc-800/50">
              <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Equity Value</p>
              <p className="text-lg font-semibold text-slate-100 font-mono tabular-nums">
                {formatNum(dcf.equity_value)}
              </p>
            </div>

            <div className="text-slate-500 hidden md:block"><FiArrowRight size={20} /></div>
            <div className="text-slate-500 md:hidden rotate-90"><FiArrowRight size={20} /></div>
            
            {/* Implied Price */}
            <div className="flex-1 min-w-[140px] bg-accent-blue/10 rounded-lg p-4 text-center border border-accent-blue/30 shadow-[0_0_15px_rgba(59,130,246,0.15)]">
              <p className="text-accent-blue/80 text-xs uppercase tracking-wider mb-1 font-semibold">Implied Price</p>
              <p className="text-2xl font-bold text-white font-mono tabular-nums">
                {formatNum(dcf.implied_price)}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DCFModelTab;
