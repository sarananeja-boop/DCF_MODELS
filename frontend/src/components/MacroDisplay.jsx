import React from 'react';

export default function MacroDisplay({ data }) {
  if (!data) return null;

  const { macro, company, market_data, wacc } = data;
  const erp = (macro?.market_return || 0.12) - (macro?.risk_free_rate || 0.04);

  return (
    <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-xl">
      <div className="flex items-center justify-between mb-3.5 pb-2.5 border-b border-[#f4eedf]/10">
        <h3 className="font-display font-bold text-[#f4eedf] text-base tracking-tight">
          Market &amp; Macro Config
        </h3>
        <span className="text-[11px] font-semibold px-2 py-0.5 rounded bg-[#0d121a] text-[#e3b23c] border border-[#f4eedf]/10">
          {company?.market === 'US' ? '🇺🇸 US' : '🇮🇳 INDIA'}
        </span>
      </div>
      
      <div className="space-y-2.5 text-xs">
        <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/8">
          <span className="text-[#a6b0c3]">Reporting Currency</span>
          <span className="font-display font-bold text-[#f4eedf]">{company?.currency} ({company?.symbol})</span>
        </div>

        <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/8">
          <span className="text-[#a6b0c3]">10Y Risk-Free Rate (Rf)</span>
          <div className="text-right">
            <span className="font-display font-bold tabular-nums text-[#34b38a]">{((macro?.risk_free_rate || 0) * 100).toFixed(2)}%</span>
            {macro?.risk_free_source && (
              <div className="text-[10px] text-[#a6b0c3]">{macro.risk_free_source}</div>
            )}
          </div>
        </div>

        <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/8">
          <span className="text-[#a6b0c3]">Expected Market Return</span>
          <span className="font-display font-bold tabular-nums text-[#f4eedf]">{((macro?.market_return || 0) * 100).toFixed(1)}%</span>
        </div>

        <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/8">
          <span className="text-[#a6b0c3]">Equity Risk Premium (ERP)</span>
          <span className="font-display font-bold tabular-nums text-[#f4eedf]">{(erp * 100).toFixed(2)}%</span>
        </div>

        <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/8">
          <span className="text-[#a6b0c3]">Effective Tax Rate</span>
          <span className="font-display font-bold tabular-nums text-[#f4eedf]">{((macro?.tax_rate || 0) * 100).toFixed(2)}%</span>
        </div>

        <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/8">
          <span className="text-[#a6b0c3]">Nominal GDP Growth Cap</span>
          <span className="font-display font-bold tabular-nums text-[#f4eedf]">{((macro?.gdp_growth || 0.065) * 100).toFixed(1)}%</span>
        </div>

        <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/8">
          <span className="text-[#a6b0c3]">Adjusted Beta (Raw)</span>
          <span className="font-display font-bold tabular-nums text-[#f4eedf]">
            {market_data?.beta ? market_data.beta.toFixed(2) : '1.00'}
            {market_data?.raw_beta != null && (
              <span className="text-[#a6b0c3] font-normal ml-1">({market_data.raw_beta.toFixed(2)})</span>
            )}
          </span>
        </div>

        <div className="flex justify-between items-center pt-1">
          <span className="text-[#a6b0c3]">Synthetic Credit Rating</span>
          <span className="font-display font-bold text-[#e3b23c]">
            {wacc?.synthetic_rating || 'N/A'}
            {wacc?.default_spread != null && (
              <span className="text-[#a6b0c3] font-normal ml-1">(+{(wacc.default_spread * 100).toFixed(2)}%)</span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
