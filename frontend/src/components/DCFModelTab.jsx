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
        formattedVal = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(val / 1e7) + ' Cr';
      } else if (Math.abs(val) >= 1e5) {
        formattedVal = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(val / 1e5) + ' L';
      } else {
        formattedVal = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(val);
      }
    } else {
      if (Math.abs(val) >= 1e9) {
        formattedVal = (val / 1e9).toFixed(2) + 'B';
      } else if (Math.abs(val) >= 1e6) {
        formattedVal = (val / 1e6).toFixed(2) + 'M';
      } else if (Math.abs(val) >= 1e3) {
        formattedVal = (val / 1e3).toFixed(2) + 'K';
      } else {
        formattedVal = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(val);
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
  const shares = data.market_data?.shares_outstanding || 0;
  
  return (
    <div className="space-y-4 text-[#f4eedf]">
      {/* 1. Projected Financials Table */}
      <div className="bg-[#141b26] rounded-2xl p-5 shadow-lg border border-[#f4eedf]/10">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-lg sm:text-xl font-bold text-[#f4eedf] tracking-tight">
            {isFinancial ? '5-Year Regulatory Capital FCFE Schedule' : '5-Year Unlevered Free Cash Flow (FCFF) Schedule'}
          </h2>
          <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
            <span className="px-2.5 py-1 rounded-lg bg-[#5b8fd9]/15 border border-[#5b8fd9]/30 text-[#8ab4f8]">
              Mid-Year Convention
            </span>
            <span className="px-2.5 py-1 rounded-lg bg-[#0d121a] border border-[#f4eedf]/10 text-[#a6b0c3] tabular-nums">
              {isFinancial ? 'Discount: Ke (CAPM)' : `Tax Rate: ${formatPct(dcf.tax_rate ?? (market === 'IN' ? 0.2517 : 0.21))}`}
            </span>
            <span className="px-2.5 py-1 rounded-lg bg-[#0d121a] border border-[#f4eedf]/10 text-[#e3b23c] tabular-nums">
              Terminal g: {formatPct(dcf.terminal_growth ?? (market === 'IN' ? 0.055 : 0.025))}
            </span>
          </div>
        </div>
        
        <div className="overflow-x-auto rounded-xl border border-[#f4eedf]/10">
          <table className="w-full text-sm text-left">
            <thead className="bg-[#0d121a] text-[#a6b0c3] uppercase text-xs tracking-wider border-b border-[#f4eedf]/10">
              <tr>
                <th className="px-4 py-3 font-bold sticky left-0 bg-[#0d121a] z-10 border-r border-[#f4eedf]/10">Line Item</th>
                {Array.from({ length: projectionYears }).map((_, i) => (
                  <th key={i} className="px-4 py-3 font-bold text-right min-w-[115px]">
                    Year {i + 1}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#f4eedf]/8">
              <tr className="bg-[#141b26] hover:bg-[#1a2332] transition-colors">
                <td className="px-4 py-3 font-semibold text-[#f4eedf] sticky left-0 bg-[#141b26] z-10 border-r border-[#f4eedf]/10">
                  {isFinancial ? 'Projected Net Income' : 'Projected Revenue'}
                </td>
                {dcf.projected_revenue?.map((val, i) => (
                  <td key={i} className="px-4 py-3 text-right font-display font-bold tabular-nums text-[#f4eedf]">
                    {formatNum(val)}
                  </td>
                ))}
              </tr>
              <tr className="bg-[#0d121a]/60 hover:bg-[#1a2332] transition-colors">
                <td className="px-4 py-2.5 font-medium text-[#a6b0c3] sticky left-0 bg-[#111721] z-10 border-r border-[#f4eedf]/10">
                  {isFinancial ? 'Net Income Growth (g)' : 'Revenue Growth (%)'}
                </td>
                {dcf.growth_schedule?.map((val, i) => (
                  <td key={i} className="px-4 py-2.5 text-right font-display font-bold tabular-nums text-[#e3b23c]">
                    {formatPct(val)}
                  </td>
                ))}
              </tr>
              {dcf.margin_schedule && (
                <tr className="bg-[#141b26] hover:bg-[#1a2332] transition-colors">
                  <td className="px-4 py-2.5 font-medium text-[#a6b0c3] sticky left-0 bg-[#141b26] z-10 border-r border-[#f4eedf]/10">
                    {isFinancial ? 'Target ROE (%)' : 'EBIT Margin (%)'}
                  </td>
                  {dcf.margin_schedule.map((val, i) => (
                    <td key={i} className="px-4 py-2.5 text-right font-display font-semibold tabular-nums text-[#a6b0c3]">
                      {formatPct(val)}
                    </td>
                  ))}
                </tr>
              )}
              {dcf.projected_nopat && !isFinancial && (
                <tr className="bg-[#0d121a]/60 hover:bg-[#1a2332] transition-colors">
                  <td className="px-4 py-2.5 font-medium text-[#f4eedf] sticky left-0 bg-[#111721] z-10 border-r border-[#f4eedf]/10">
                    NOPAT (After-Tax EBIT)
                  </td>
                  {dcf.projected_nopat.map((val, i) => (
                    <td key={i} className="px-4 py-2.5 text-right font-display font-semibold tabular-nums text-[#f4eedf]">
                      {formatNum(val)}
                    </td>
                  ))}
                </tr>
              )}
              {dcf.projected_dna && (
                <tr className="bg-[#141b26] hover:bg-[#1a2332] transition-colors">
                  <td className="px-4 py-2.5 font-medium text-[#a6b0c3] sticky left-0 bg-[#141b26] z-10 border-r border-[#f4eedf]/10">
                    {isFinancial ? '(−) Regulatory Capital Retained' : '(+) Depreciation & Amortization'}
                  </td>
                  {dcf.projected_dna.map((val, i) => (
                    <td key={i} className="px-4 py-2.5 text-right font-display tabular-nums text-[#a6b0c3]">
                      {isFinancial ? `- ${formatNum(val)}` : formatNum(val)}
                    </td>
                  ))}
                </tr>
              )}
              {dcf.projected_capex && !isFinancial && (
                <tr className="bg-[#0d121a]/60 hover:bg-[#1a2332] transition-colors">
                  <td className="px-4 py-2.5 font-medium text-[#a6b0c3] sticky left-0 bg-[#111721] z-10 border-r border-[#f4eedf]/10">
                    (−) Capital Expenditures (CapEx)
                  </td>
                  {dcf.projected_capex.map((val, i) => (
                    <td key={i} className="px-4 py-2.5 text-right font-display tabular-nums text-[#a6b0c3]">
                      {formatNum(val)}
                    </td>
                  ))}
                </tr>
              )}
              {dcf.projected_dnwc && !isFinancial && (
                <tr className="bg-[#141b26] hover:bg-[#1a2332] transition-colors">
                  <td className="px-4 py-2.5 font-medium text-[#a6b0c3] sticky left-0 bg-[#141b26] z-10 border-r border-[#f4eedf]/10">
                    (−) Change in Working Capital (ΔNWC)
                  </td>
                  {dcf.projected_dnwc.map((val, i) => (
                    <td key={i} className="px-4 py-2.5 text-right font-display tabular-nums text-[#a6b0c3]">
                      {formatNum(val)}
                    </td>
                  ))}
                </tr>
              )}
              <tr className="bg-[#182232] border-t border-[#f4eedf]/20">
                <td className="px-4 py-3 font-bold text-[#f4eedf] sticky left-0 bg-[#182232] z-10 border-r border-[#f4eedf]/10">
                  {isFinancial ? 'Free Cash Flow to Equity (FCFE)' : 'Unlevered Free Cash Flow (FCFF)'}
                </td>
                {dcf.projected_ufcf?.map((val, i) => (
                  <td key={i} className="px-4 py-3 text-right font-display font-bold tabular-nums text-[#34b38a]">
                    {formatNum(val)}
                  </td>
                ))}
              </tr>
              {dcf.discount_periods && (
                <tr className="bg-[#0d121a]/60 text-xs">
                  <td className="px-4 py-2 font-medium text-[#a6b0c3] sticky left-0 bg-[#111721] z-10 border-r border-[#f4eedf]/10">
                    Mid-Year Period (t)
                  </td>
                  {dcf.discount_periods.map((t, i) => (
                    <td key={i} className="px-4 py-2 text-right font-display tabular-nums text-[#a6b0c3]">
                      {t.toFixed(1)}
                    </td>
                  ))}
                </tr>
              )}
              {dcf.discount_factors && (
                <tr className="bg-[#141b26] text-xs">
                  <td className="px-4 py-2 font-medium text-[#a6b0c3] sticky left-0 bg-[#141b26] z-10 border-r border-[#f4eedf]/10">
                    {isFinancial ? 'Discount Factor [1/(1+Ke)^t]' : 'Discount Factor [1/(1+WACC)^t]'}
                  </td>
                  {dcf.discount_factors.map((df, i) => (
                    <td key={i} className="px-4 py-2 text-right font-display tabular-nums text-[#8ab4f8]">
                      {df.toFixed(4)}
                    </td>
                  ))}
                </tr>
              )}
              {dcf.pv_ufcf_list && (
                <tr className="bg-[#34b38a]/10 border-t border-[#34b38a]/30">
                  <td className="px-4 py-3 font-bold text-[#34b38a] sticky left-0 bg-[#132225] z-10 border-r border-[#f4eedf]/10">
                    {isFinancial ? 'Present Value of FCFE' : 'Present Value of FCFF'}
                  </td>
                  {dcf.pv_ufcf_list.map((pv, i) => (
                    <td key={i} className="px-4 py-3 text-right font-display font-bold tabular-nums text-[#34b38a]">
                      {formatNum(pv)}
                    </td>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 2. Terminal Value & Equity Bridge Summary Strip */}
      <div className="bg-[#141b26] rounded-2xl p-5 shadow-lg border border-[#f4eedf]/10">
        <h3 className="font-display text-base sm:text-lg font-bold text-[#f4eedf] mb-3.5 tracking-tight">
          {isFinancial ? 'Terminal Value & Bank Equity Bridge' : 'Terminal Value & Enterprise-to-Equity Bridge'}
        </h3>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div className="bg-[#0d121a] rounded-xl p-3.5 border border-[#f4eedf]/8">
            <div className="text-[11px] uppercase tracking-wider text-[#a6b0c3] font-semibold">
              {isFinancial ? 'PV of 5-Yr FCFEs' : 'PV of 5-Yr Cash Flows'}
            </div>
            <div className="font-display text-lg sm:text-xl font-bold text-[#34b38a] tabular-nums mt-1">
              {formatNum(dcf.pv_ufcf)}
            </div>
          </div>
          <div className="bg-[#0d121a] rounded-xl p-3.5 border border-[#f4eedf]/8">
            <div className="text-[11px] uppercase tracking-wider text-[#a6b0c3] font-semibold">
              Terminal Value (Yr 5)
            </div>
            <div className="font-display text-lg sm:text-xl font-bold text-[#f4eedf] tabular-nums mt-1">
              {dcf.terminal_value === null || !data.diagnostics?.terminal_value_valid ? 'N/A' : formatNum(dcf.terminal_value)}
            </div>
          </div>
          <div className="bg-[#0d121a] rounded-xl p-3.5 border border-[#f4eedf]/8">
            <div className="text-[11px] uppercase tracking-wider text-[#a6b0c3] font-semibold">
              PV of Terminal Value
            </div>
            <div className="font-display text-lg sm:text-xl font-bold text-[#8ab4f8] tabular-nums mt-1">
              {formatNum(dcf.pv_terminal_value)}
            </div>
          </div>
          <div className="bg-[#0d121a] rounded-xl p-3.5 border border-[#f4eedf]/10">
            <div className="text-[11px] uppercase tracking-wider text-[#e3b23c] font-semibold">
              {isFinancial ? 'Total Equity Value' : 'Enterprise Value (EV)'}
            </div>
            <div className="font-display text-lg sm:text-xl font-bold text-[#f4eedf] tabular-nums mt-1">
              {formatNum(isFinancial ? dcf.equity_value : dcf.enterprise_value)}
            </div>
          </div>
        </div>

        {isFinancial ? (
          /* Bank Equity Valuation Bridge with Arithmetic Operators */
          <div className="pt-3 border-t border-[#f4eedf]/10 space-y-2">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 items-center">
              <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/8">
                <div className="text-[10px] text-[#34b38a] font-bold uppercase">(+) PV of 5-Yr FCFE</div>
                <div className="font-display font-bold text-sm sm:text-base text-[#34b38a] tabular-nums mt-0.5">+{formatNum(dcf.pv_ufcf)}</div>
              </div>
              <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/8">
                <div className="text-[10px] text-[#8ab4f8] font-bold uppercase">(+) PV of Terminal Equity</div>
                <div className="font-display font-bold text-sm sm:text-base text-[#8ab4f8] tabular-nums mt-0.5">+{formatNum(dcf.pv_terminal_value)}</div>
              </div>
              <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/10">
                <div className="text-[10px] text-[#e3b23c] font-bold uppercase">(=) Total Equity Value</div>
                <div className="font-display font-bold text-sm sm:text-base text-[#e3b23c] tabular-nums mt-0.5">={formatNum(dcf.equity_value)}</div>
              </div>
              <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/10">
                <div className="text-[10px] text-[#e3b23c] font-bold uppercase">(=) Implied Fair Value</div>
                <div className="font-display font-bold text-base sm:text-lg text-[#e3b23c] tabular-nums mt-0.5">={formatNum(dcf.implied_price)}</div>
              </div>
            </div>
            <div className="text-[11px] text-[#a6b0c3] bg-[#0d121a] p-2.5 rounded-xl border border-[#f4eedf]/8 flex items-center justify-between">
              <span>🏦 <strong className="text-[#f4eedf]">Bank Tier-1 Model:</strong> Customer deposits &amp; borrowings are operational funding rather than debt. Valuation flows directly to Equity via FCFE.</span>
              <span className="font-display font-bold text-[#f4eedf] tabular-nums shrink-0 ml-2">Diluted Shares: {shares ? (shares > 1e7 ? `${(shares/1e7).toFixed(2)} Cr` : shares.toLocaleString()) : 'N/A'}</span>
            </div>
          </div>
        ) : (
          /* Corporate / Industrial Enterprise-to-Equity Bridge with Arithmetic Operators */
          <div className="grid grid-cols-2 sm:grid-cols-6 gap-2.5 pt-3 border-t border-[#f4eedf]/10 items-center">
            <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/8">
              <div className="text-[10px] text-[#a6b0c3] font-bold uppercase">Enterprise Value</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-0.5">{formatNum(dcf.enterprise_value)}</div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/8">
              <div className="text-[10px] text-[#e07a5f] font-bold uppercase">(−) Less Debt</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#e07a5f] tabular-nums mt-0.5">−{formatNum(waccObj?.total_debt)}</div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/8">
              <div className="text-[10px] text-[#34b38a] font-bold uppercase">(+) Plus Cash</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#34b38a] tabular-nums mt-0.5">+{formatNum(cash)}</div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/10">
              <div className="text-[10px] text-[#e3b23c] font-bold uppercase">(=) Equity Value</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#e3b23c] tabular-nums mt-0.5">={formatNum(dcf.equity_value)}</div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/8">
              <div className="text-[10px] text-[#a6b0c3] font-bold uppercase">(÷) Diluted Shares</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-0.5">÷{shares ? (shares > 1e7 ? `${(shares/1e7).toFixed(2)} Cr` : shares.toLocaleString()) : 'N/A'}</div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/10">
              <div className="text-[10px] text-[#e3b23c] font-bold uppercase">(=) DCF Fair Value</div>
              <div className="font-display font-bold text-base sm:text-lg text-[#e3b23c] tabular-nums mt-0.5">={formatNum(dcf.implied_price)}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DCFModelTab;
