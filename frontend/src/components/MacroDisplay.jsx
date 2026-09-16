import React from 'react';

export default function MacroDisplay({ data }) {
  if (!data) return null;

  const { macro, company } = data;

  return (
    <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800 shadow-lg">
      <h3 className="font-semibold text-white mb-3">Market Config</h3>
      
      <div className="space-y-3">
        <div className="flex justify-between items-center pb-2 border-b border-zinc-800/80">
          <span className="text-sm text-text-secondary">Market</span>
          <span className="text-sm font-medium flex items-center gap-1">
            {company.market === 'US' ? '🇺🇸' : '🇮🇳'} {company.market}
          </span>
        </div>
        
        <div className="flex justify-between items-center pb-2 border-b border-zinc-800/80">
          <span className="text-sm text-text-secondary">Currency</span>
          <span className="text-sm font-medium">{company.currency} ({company.symbol})</span>
        </div>

        <div className="flex justify-between items-center pb-2 border-b border-zinc-800/80">
          <span className="text-sm text-text-secondary">Risk-Free Rate</span>
          <div className="text-right">
            <span className="text-sm font-mono tabular-nums text-white">{(macro.risk_free_rate * 100).toFixed(2)}%</span>
            <div className="text-[10px] text-accent-green flex items-center gap-1 justify-end mt-0.5">
              <span className="w-1.5 h-1.5 bg-accent-green rounded-full inline-block"></span>
              {macro.risk_free_source}
            </div>
          </div>
        </div>

        <div className="flex justify-between items-center pb-2 border-b border-zinc-800/80">
          <span className="text-sm text-text-secondary">Market Return</span>
          <span className="text-sm font-mono tabular-nums text-white">{(macro.market_return * 100).toFixed(1)}%</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-sm text-text-secondary">Tax Rate</span>
          <span className="text-sm font-mono tabular-nums text-white">{(macro.tax_rate * 100).toFixed(2)}%</span>
        </div>
      </div>
    </div>
  );
}
